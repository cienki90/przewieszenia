"""Odczyt i zapis rysunków DWG przez ODA File Converter (Open Design Alliance).

ezdxf czyta i zapisuje tylko DXF, dlatego DWG jest przeliczany zewnętrznym programem
ODA File Converter (darmowy, instaluje go użytkownik - nie wolno go dołączać do paczki
programu bez licencji ODA). Pliki DXF obsługujemy jak dotąd, bez konwertera.

    doc = wczytaj("projekt.dwg")          # albo .dxf
    zapisz(doc, "projekt_numeracja.dwg")  # albo .dxf
"""
from __future__ import annotations

import contextlib
import glob
import os
import shutil
import threading
from pathlib import Path

import ezdxf
from ezdxf.addons import odafc
from ezdxf.document import Drawing

ADRES_ODA = "https://www.opendesign.com/guestfiles/oda_file_converter"
KOMUNIKAT_BRAK_ODA = (
    "Do odczytu i zapisu plików DWG potrzebny jest darmowy program ODA File Converter. "
    f"Pobierz go ze strony {ADRES_ODA}, zainstaluj i uruchom analizę ponownie. "
    "Bez niego możesz pracować na plikach DXF.")

EXE = "ODAFileConverter.exe"
# typowe miejsca instalacji (folder ma w nazwie numer wersji, np. "ODAFileConverter 26.4.0")
_WZORCE = [r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
           r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe"]
# foldery systemowe pomijane przy przeszukiwaniu dysków
_POMIJANE = {"windows", "users", "programdata", "$recycle.bin", "system volume information",
             "recovery", "perflogs", "$windows.~ws", "$windows.~bt", "msocache"}
_znaleziony: list[str | None] = []  # wynik przeszukania dysków (raz na uruchomienie)
_BLOKADA_SRODOWISKA = threading.Lock()


class BladDWG(Exception):
    """Błąd obsługi DWG z komunikatem dla użytkownika."""


def jest_dwg(plik: str | os.PathLike) -> bool:
    return Path(plik).suffix.lower() == ".dwg"


def znajdz_oda(wskazana: str | None = None, odswiez: bool = False) -> str | None:
    """Ścieżka do ODAFileConverter.exe: wskazana przez użytkownika, ustawiona w ezdxf,
    znaleziona w typowym miejscu instalacji (najnowsza wersja), w PATH albo w folderze
    z "oda" w nazwie na dyskach lokalnych (np. D:\\programy\\oda). Wynik przeszukania
    dysków jest zapamiętywany; odswiez=True szuka ponownie."""
    for p in (wskazana, odafc.get_win_exec_path().strip('"')):
        if p and Path(p).is_file():
            return str(p)
    znalezione = sorted((p for w in _WZORCE for p in glob.glob(w)), key=_wersja_z_nazwy)
    if znalezione:
        return znalezione[-1]
    w_path = shutil.which(EXE)
    if w_path:
        return w_path
    if odswiez or not _znaleziony or (_znaleziony[0] and not Path(_znaleziony[0]).is_file()):
        _znaleziony[:] = [_przeszukaj_dyski()]
    return _znaleziony[0]


def _dyski() -> list[str]:
    """Dyski lokalne (bez sieciowych i wymiennych - przeszukiwanie byłoby wolne)."""
    if os.name != "nt":
        return []
    import ctypes
    import string
    maska = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{z}:\\" for i, z in enumerate(string.ascii_uppercase)
            if maska >> i & 1 and ctypes.windll.kernel32.GetDriveTypeW(f"{z}:\\") == 3]


def _podfoldery(katalog: str) -> list[str]:
    try:
        with os.scandir(katalog) as it:
            return [e.path for e in it if e.is_dir(follow_symlinks=False)]
    except OSError:
        return []


def _przeszukaj_dyski(dyski: list[str] | None = None) -> str | None:
    """Szuka konwertera w folderach z "oda" w nazwie na 1. i 2. poziomie dysku
    (D:\\ODA, D:\\programy\\oda, E:\\Program Files\\ODA\\ODAFileConverter 26.4.0)."""
    kandydaci = []
    for dysk in (_dyski() if dyski is None else dyski):
        for k1 in _podfoldery(dysk):
            if Path(k1).name.lower() in _POMIJANE:
                continue
            for k in [k1] + _podfoldery(k1):
                if "oda" not in Path(k).name.lower():
                    continue
                kandydaci += [os.path.join(x, EXE) for x in [k] + _podfoldery(k)]
    znalezione = sorted((p for p in kandydaci if os.path.isfile(p)), key=_wersja_z_nazwy)
    return znalezione[-1] if znalezione else None


def _wersja_z_nazwy(sciezka: str) -> tuple:
    nazwa = Path(sciezka).parent.name
    return tuple(int(c) for c in "".join(z if z.isdigit() else " " for z in nazwa).split())


def ustaw_oda(wskazana: str | None = None) -> str | None:
    """Ustawia ścieżkę konwertera dla ezdxf; zwraca ją albo None, gdy go nie ma."""
    p = znajdz_oda(wskazana)
    if p:
        ezdxf.options.set("odafc-addon", "win_exec_path", f'"{p}"')
    return p


def dostepny(wskazana: str | None = None) -> bool:
    return ustaw_oda(wskazana) is not None


@contextlib.contextmanager
def _bez_zmiennych_qt():
    """ODA File Converter to program Qt, a uruchamiamy go z naszym środowiskiem. Zmienne
    Qt naszego procesu (QT_PLUGIN_PATH w paczce .exe, QT_QPA_PLATFORM w testach) kazałyby
    mu ładować obce wtyczki - kończy się wtedy błędem. Na czas konwersji je usuwamy."""
    with _BLOKADA_SRODOWISKA:
        zapis = {k: os.environ.pop(k) for k in list(os.environ)
                 if k.upper().startswith(("QT_", "QML"))}
        try:
            yield
        finally:
            os.environ.update(zapis)


def wczytaj(plik: str | os.PathLike, oda: str | None = None) -> Drawing:
    if not jest_dwg(plik):
        return ezdxf.readfile(str(plik))
    if not dostepny(oda):
        raise BladDWG(KOMUNIKAT_BRAK_ODA)
    try:
        with _bez_zmiennych_qt():
            return odafc.readfile(str(plik))
    except odafc.ODAFCError as e:
        raise BladDWG(f"Nie udało się odczytać pliku DWG {Path(plik).name}: {e}") from e


def zapisz(doc: Drawing, plik: str | os.PathLike, oda: str | None = None) -> None:
    """Zapis do DWG (wersja jak rysunek źródłowy) albo DXF - wg rozszerzenia pliku."""
    if not jest_dwg(plik):
        doc.saveas(str(plik))
        return
    if not dostepny(oda):
        raise BladDWG(KOMUNIKAT_BRAK_ODA)
    try:
        with _bez_zmiennych_qt():
            odafc.export_dwg(doc, str(plik), replace=True)
    except odafc.ODAFCError as e:
        raise BladDWG(f"Nie udało się zapisać pliku DWG {Path(plik).name}: {e}") from e
