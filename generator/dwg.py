#!/usr/bin/env python3
"""Obsługa plików DWG: wczytywanie (DWG -> DXF) i eksport wyników (DXF -> DWG).

Format DWG jest zamknięty, więc program nie czyta go sam - korzysta z zewnętrznego,
darmowego konwertera:
  - ODA File Converter (Open Design Alliance; zalecany, Windows/Linux/macOS),
  - LibreDWG (programy „dwg2dxf” / „dxf2dwg”) - zapasowo.

Ścieżkę konwertera można wskazać zmienną środowiskową GENERATOR_ODA (plik ODAFileConverter)
albo GENERATOR_LIBREDWG (katalog z dwg2dxf/dxf2dwg). Bez nich program szuka w typowych
miejscach instalacji i w PATH.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile

# wersja zapisywanego DWG (ODA: ACAD2018 = format AutoCAD 2018-2024+)
WERSJA_DWG = "ACAD2018"
LINK_ODA = "https://www.opendesign.com/guestfiles/oda_file_converter"


class BrakKonwertera(RuntimeError):
    """Nie znaleziono programu do konwersji DWG."""


def jest_dwg(sciezka) -> bool:
    return bool(sciezka) and str(sciezka).lower().endswith(".dwg")


# ---------------------------------------------------------------------------
def _znajdz_oda():
    env = os.environ.get("GENERATOR_ODA")
    if env and os.path.isfile(env):
        return env
    for nazwa in ("ODAFileConverter", "ODAFileConverter.exe"):
        p = shutil.which(nazwa)
        if p:
            return p
    wzorce = []
    if sys.platform.startswith("win"):
        for baza in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            wzorce.append(os.path.join(baza, "ODA", "ODAFileConverter*", "ODAFileConverter.exe"))
    elif sys.platform == "darwin":
        wzorce.append("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter")
    else:
        wzorce += ["/usr/bin/ODAFileConverter", "/opt/ODAFileConverter*/ODAFileConverter"]
    for w in wzorce:
        trafienia = sorted(glob.glob(w))
        if trafienia:
            return trafienia[-1]                        # najnowsza wersja (sortowanie po nazwie)
    return None


def _znajdz_libredwg(program):
    env = os.environ.get("GENERATOR_LIBREDWG")
    if env:
        for nazwa in (program, program + ".exe"):
            p = os.path.join(env, nazwa)
            if os.path.isfile(p):
                return p
    return shutil.which(program)


def konwerter() -> str | None:
    """Opis dostępnego konwertera (do logu) albo None."""
    oda = _znajdz_oda()
    if oda:
        return f"ODA File Converter ({oda})"
    if _znajdz_libredwg("dwg2dxf"):
        return "LibreDWG"
    return None


def _brak():
    return BrakKonwertera(
        "Do obsługi plików DWG potrzebny jest darmowy program ODA File Converter "
        f"({LINK_ODA}) albo LibreDWG. Zainstaluj go (lub wskaż ścieżkę w zmiennej "
        "GENERATOR_ODA) i uruchom ponownie. Możesz też zapisać plik jako DXF w programie CAD.")


def _uruchom(argv, opis):
    kw = {}
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000                # CREATE_NO_WINDOW - bez migającej konsoli
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=600, **kw)
    except subprocess.TimeoutExpired as ex:
        raise RuntimeError(f"{opis}: konwerter nie odpowiada (przekroczony czas).") from ex
    except OSError as ex:
        raise RuntimeError(f"{opis}: nie udało się uruchomić konwertera ({ex}).") from ex
    return p


def _konwertuj_oda(oda, wejscie, wyjscie, typ):
    """ODA konwertuje całe katalogi - plik kopiujemy do osobnego katalogu tymczasowego."""
    opis = f"Konwersja {os.path.basename(wejscie)} -> {typ}"
    with tempfile.TemporaryDirectory(prefix="dwg_we_") as we, \
            tempfile.TemporaryDirectory(prefix="dwg_wy_") as wy:
        nazwa = os.path.basename(wejscie)
        shutil.copy2(wejscie, os.path.join(we, nazwa))
        # argumenty: katalog_we katalog_wy wersja typ rekurencja audyt [filtr]
        p = _uruchom([oda, we, wy, WERSJA_DWG, typ, "0", "1", nazwa], opis)
        wynik = os.path.join(wy, os.path.splitext(nazwa)[0] + "." + typ.lower())
        if not os.path.isfile(wynik):
            bledy = glob.glob(os.path.join(wy, "*.err"))
            szczegoly = ""
            if bledy:
                with open(bledy[0], encoding="utf-8", errors="replace") as f:
                    szczegoly = f.read().strip()
            szczegoly = szczegoly or (p.stderr or p.stdout or "").strip()
            raise RuntimeError(f"{opis} nie powiodła się." + (f" {szczegoly}" if szczegoly else ""))
        os.makedirs(os.path.dirname(os.path.abspath(wyjscie)), exist_ok=True)
        shutil.move(wynik, wyjscie)
    return wyjscie


def _konwertuj_libredwg(program, wejscie, wyjscie):
    opis = f"Konwersja {os.path.basename(wejscie)} ({os.path.basename(program)})"
    if os.path.exists(wyjscie):
        os.remove(wyjscie)                              # LibreDWG nie nadpisuje istniejącego pliku
    p = _uruchom([program, "-y", "-o", wyjscie, wejscie], opis)
    if not os.path.isfile(wyjscie):
        raise RuntimeError(f"{opis} nie powiodła się. {(p.stderr or p.stdout or '').strip()}")
    return wyjscie


# ---------------------------------------------------------------------------
def dwg_na_dxf(dwg: str, dxf: str) -> str:
    """Zamienia plik DWG na DXF (zapisany pod ścieżką `dxf`)."""
    oda = _znajdz_oda()
    if oda:
        return _konwertuj_oda(oda, dwg, dxf, "DXF")
    prog = _znajdz_libredwg("dwg2dxf")
    if prog:
        return _konwertuj_libredwg(prog, dwg, dxf)
    raise _brak()


def dxf_na_dwg(dxf: str, dwg: str | None = None) -> str:
    """Zapisuje kopię pliku DXF w formacie DWG (domyślnie obok, z rozszerzeniem .dwg)."""
    dwg = dwg or os.path.splitext(dxf)[0] + ".dwg"
    oda = _znajdz_oda()
    if oda:
        return _konwertuj_oda(oda, dxf, dwg, "DWG")
    prog = _znajdz_libredwg("dxf2dwg")
    if prog:
        return _konwertuj_libredwg(prog, dxf, dwg)
    raise _brak()


class Wejscia:
    """Zamienia wskazane pliki DWG na tymczasowe DXF (o tej samej nazwie bazowej, więc nazwy
    wyników się nie zmieniają). Ten sam plik DWG jest konwertowany tylko raz."""

    def __init__(self, log=print):
        self.log = log
        self._katalog = None
        self._mapa: dict[str, str] = {}

    def dxf(self, sciezka):
        if not jest_dwg(sciezka) or not os.path.isfile(sciezka):
            return sciezka
        klucz = os.path.normcase(os.path.abspath(sciezka))
        if klucz not in self._mapa:
            if self._katalog is None:
                self._katalog = tempfile.mkdtemp(prefix="generator_dwg_")
            # osobny podkatalog na każdy plik - dwa DWG o tej samej nazwie się nie nadpiszą
            kat = os.path.join(self._katalog, str(len(self._mapa)))
            os.makedirs(kat)
            cel = os.path.join(kat, os.path.splitext(os.path.basename(sciezka))[0] + ".dxf")
            self.log(f"Wczytuję DWG: {os.path.basename(sciezka)} (konwersja do DXF)…")
            self._mapa[klucz] = dwg_na_dxf(sciezka, cel)
        return self._mapa[klucz]

    def sprzatnij(self):
        if self._katalog:
            shutil.rmtree(self._katalog, ignore_errors=True)
            self._katalog = None
            self._mapa.clear()


if __name__ == "__main__":
    # python -m generator.dwg plik.dwg|plik.dxf  - szybka konwersja w obie strony
    for plik in sys.argv[1:]:
        if jest_dwg(plik):
            print(dwg_na_dxf(plik, os.path.splitext(plik)[0] + ".dxf"))
        else:
            print(dxf_na_dwg(plik))
