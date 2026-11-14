"""FINAŁ - kompletny PDF projektu dla stacji trafo.

Dla każdej stacji jeden PDF (albo jeden wspólny dla wybranych stacji), w kolejności:
  1. opis techniczny          <opisy>\\<nr>.docx (Word zapisuje go do PDF)
  2. plan orientacyjny        arkusz „1” rysunku stałego stacji <rysunki stałe>\\<nr>.dwg/.dxf
  3. arkusze PZT stacji       arkusze „<nr>-1”, „<nr>-2”… pliku PZT
  4. rysunki 3.1-3.4          arkusze „3.1”…„3.4” rysunku stałego stacji
  5. przewieszenia stacji     arkusze rysunku przewieszeń przypisane do stacji (plik „….stacje.json”,
                              zapisywany przez moduł Przewieszenia)

Brakująca część jest pomijana z uwagą w raporcie (np. stacja bez przewieszeń). Rysunki DWG są
zamieniane na DXF w folderze tymczasowym (ODA File Converter).
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field

from . import dwg as mod_dwg
from . import dxf2pdf
from . import nazwy as mod_nazwy

CZESCI = ("opis", "plan orientacyjny", "PZT", "rysunki 3.1-3.4", "przewieszenia")
ARKUSZ_ORIENTACJI = "1"
RE_RYSUNKI_3 = re.compile(r"^3\.\d+$")
RE_ARKUSZ_PZT = re.compile(r"^(\d+)-(\d+)$")


@dataclass
class Zrodla:
    opisy: str | None = None             # folder z opisami <nr>.docx
    rysunki_stale: str | None = None     # folder z rysunkami stałymi <nr>.dwg/.dxf
    pzt: str | None = None               # plik PZT (arkusze <nr>-<k>)
    przewieszenia: str | None = None     # rysunek przewieszeń (+ „….stacje.json”)


@dataclass
class Wynik:
    pliki: list = field(default_factory=list)
    uwagi: list = field(default_factory=list)


# ---------------------------------------------------------------- pliki źródłowe
def _rysunek_stacji(folder: str | None, nr: int) -> str | None:
    if not folder or not os.path.isdir(folder):
        return None
    for n in sorted(os.listdir(folder)):
        baza, roz = os.path.splitext(n)
        if roz.lower() in (".dwg", ".dxf") and mod_nazwy.nr_stacji(baza) == nr and baza.strip().isdigit():
            dwg = os.path.join(folder, baza + ".dwg")
            return dwg if os.path.isfile(dwg) else os.path.join(folder, n)
    return None


def _opis_stacji(folder: str | None, nr: int) -> str | None:
    if not folder or not os.path.isdir(folder):
        return None
    for n in sorted(os.listdir(folder)):
        baza, roz = os.path.splitext(n)
        if roz.lower() == ".docx" and baza.strip().isdigit() and int(baza) == nr:
            return os.path.join(folder, n)
    return None


def stacje(zrodla: Zrodla) -> list[int]:
    """Numery stacji, dla których jest coś do złożenia (rysunki stałe, arkusze PZT, opisy)."""
    nr = set()
    for folder, roz in ((zrodla.rysunki_stale, (".dwg", ".dxf")), (zrodla.opisy, (".docx",))):
        if folder and os.path.isdir(folder):
            for n in os.listdir(folder):
                baza, r = os.path.splitext(n)
                if r.lower() in roz and baza.strip().isdigit():
                    nr.add(int(baza))
    return sorted(nr)


# ---------------------------------------------------------------- DOCX -> PDF (Word)
def docx_do_pdf(docx: str, pdf: str) -> None:
    """Zapis dokumentu Word do PDF przez zainstalowany Microsoft Word (pywin32)."""
    bledy = docx_wiele_do_pdf([(docx, pdf)])
    if bledy:
        raise RuntimeError(bledy[docx])


def docx_wiele_do_pdf(pary) -> dict:
    """[(docx, pdf)] -> {docx: błąd} - wszystkie dokumenty w JEDNYM uruchomieniu Worda."""
    pary = list(pary)
    if not pary:
        return {}
    try:
        import pythoncom
        import win32com.client
    except ImportError as ex:
        raise RuntimeError("zapis opisu do PDF wymaga Microsoft Word i biblioteki pywin32") from ex
    pythoncom.CoInitialize()
    word = None
    bledy = {}
    try:
        word = win32com.client.DispatchEx("Word.Application")        # osobny Word - nie rusza otwartego
        word.Visible = False
        word.DisplayAlerts = 0
        for docx, pdf in pary:
            try:
                dok = word.Documents.Open(os.path.abspath(docx), False, True, False)   # tylko do odczytu
                try:
                    # SaveAs2 zamiast ExportAsFixedFormat - ten zrywał połączenie z Wordem (RPC_E_DISCONNECTED)
                    dok.SaveAs2(os.path.abspath(pdf), FileFormat=17)    # 17 = wdFormatPDF
                finally:
                    dok.Close(False)
            except Exception as ex:  # noqa: BLE001 - jeden zły dokument nie zatrzymuje pozostałych
                bledy[docx] = str(ex)
    except Exception as ex:  # noqa: BLE001 - brak Worda: błąd dla wszystkich
        for docx, _pdf in pary:
            bledy.setdefault(docx, f"Microsoft Word niedostępny ({ex})")
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:  # noqa: BLE001
                pass
        pythoncom.CoUninitialize()
    return bledy


# ---------------------------------------------------------------- składanie
class _Rysunki:
    """Rysunki DXF (DWG zamienione na DXF w folderze tymczasowym) i ich arkusze w PDF - każdy
    rysunek rysowany raz, nawet gdy jego arkusze trafiają do kilku stacji."""

    def __init__(self, tmp: str, log):
        self.tmp, self.log = tmp, log
        self.pdf: dict[str, tuple] = {}

    def strony(self, rysunek: str):
        if rysunek not in self.pdf:
            dxf = rysunek
            if mod_dwg.jest_dwg(rysunek):
                dxf = mod_dwg.dwg_na_dxf(rysunek, os.path.join(self.tmp, f"r{len(self.pdf)}.dxf"))
            self.pdf[rysunek] = dxf2pdf.arkusze_do_pdf(dxf, folder_obrazow=os.path.dirname(rysunek))
        return self.pdf[rysunek]

    def dolacz(self, cel, rysunek: str, wybierz) -> int:
        dok, nazwy = self.strony(rysunek)
        n = 0
        for i, nazwa in enumerate(nazwy):
            if wybierz(nazwa):
                cel.insert_pdf(dok, from_page=i, to_page=i)
                n += 1
        return n


def _stacje_przewieszen(przewieszenia: str | None) -> dict | None:
    if not przewieszenia:
        return None
    try:
        with open(os.path.splitext(przewieszenia)[0] + ".stacje.json", encoding="utf-8") as f:
            arkusze = json.load(f).get("arkusze") or {}
    except (OSError, ValueError):
        return None
    return {ark: {mod_nazwy.nr_stacji(s) for s in st if mod_nazwy.nr_stacji(s) is not None}
            for ark, st in arkusze.items()}


def zloz(zrodla: Zrodla, folder_wyj: str, wybrane=None, jeden_plik: bool = False, nazwa_projektu: str = "",
         log=print) -> Wynik:
    """Składa kompletne PDF-y. wybrane - numery stacji (None = wszystkie); jeden_plik - wszystkie
    wybrane stacje w jednym PDF zamiast osobnego pliku na stację."""
    import pymupdf
    wynik = Wynik()
    numery = [n for n in stacje(zrodla) if wybrane is None or n in set(wybrane)]
    if not numery:
        raise ValueError("Nie znaleziono stacji do złożenia (brak rysunków stałych i opisów <nr>.dwg/.docx).")
    os.makedirs(folder_wyj, exist_ok=True)
    przew_stacje = _stacje_przewieszen(zrodla.przewieszenia)
    if zrodla.przewieszenia and przew_stacje is None:
        wynik.uwagi.append("Rysunek przewieszeń bez przypisania arkuszy do stacji (brak pliku „….stacje.json”) "
                           "- utwórz przewieszenia ponownie, żeby trafiły do kompletu.")
    tmp = tempfile.mkdtemp(prefix="final_")
    rys = _Rysunki(tmp, log)
    calosc = pymupdf.open() if jeden_plik else None
    try:
        # opisy do PDF naraz - jedno uruchomienie Worda
        opisy = {nr: _opis_stacji(zrodla.opisy, nr) for nr in numery}
        pdf_opisow = {nr: os.path.join(tmp, f"opis_{nr}.pdf") for nr, o in opisy.items() if o}
        if pdf_opisow:
            log(f"Opisy do PDF (Microsoft Word): {len(pdf_opisow)}…")
        bledy_opisow = docx_wiele_do_pdf([(opisy[nr], p) for nr, p in pdf_opisow.items()])
        for nr in numery:
            dok = pymupdf.open()
            czesci = []

            def czesc(nazwa, ile):
                czesci.append(f"{nazwa}: {ile}" if ile else f"{nazwa}: brak")
                if not ile:
                    wynik.uwagi.append(f"stacja {nr}: brak - {nazwa}")

            ile = 0
            if nr in pdf_opisow:
                if opisy[nr] in bledy_opisow:
                    wynik.uwagi.append(f"stacja {nr}: opis nie zapisał się do PDF ({bledy_opisow[opisy[nr]]})")
                elif os.path.isfile(pdf_opisow[nr]):
                    with pymupdf.open(pdf_opisow[nr]) as o:
                        dok.insert_pdf(o)
                        ile = o.page_count
            czesc("opis", ile)
            rys_st = _rysunek_stacji(zrodla.rysunki_stale, nr)
            czesc("plan orientacyjny", rys.dolacz(dok, rys_st, lambda n: n == ARKUSZ_ORIENTACJI) if rys_st else 0)
            czesc("PZT", rys.dolacz(dok, zrodla.pzt, lambda n: bool(RE_ARKUSZ_PZT.match(n))
                                    and int(RE_ARKUSZ_PZT.match(n).group(1)) == nr) if zrodla.pzt else 0)
            czesc("rysunki 3.1-3.4", rys.dolacz(dok, rys_st, lambda n: bool(RE_RYSUNKI_3.match(n))) if rys_st else 0)
            ile = 0
            if przew_stacje is not None:
                ile = rys.dolacz(dok, zrodla.przewieszenia, lambda n: nr in przew_stacje.get(n, set()))
            czesc("przewieszenia", ile)
            if dok.page_count == 0:
                wynik.uwagi.append(f"stacja {nr}: nic do złożenia - pominięta")
                continue
            log(f"  ST {nr}: {dok.page_count} stron ({'; '.join(czesci)})")
            if calosc is not None:
                calosc.insert_pdf(dok)
            else:
                plik = os.path.join(folder_wyj, f"FINAŁ ST {nr}.pdf")
                dok.save(plik, garbage=3, deflate=True)
                wynik.pliki.append(plik)
            dok.close()
        if calosc is not None and calosc.page_count:
            plik = os.path.join(folder_wyj, f"FINAŁ {nazwa_projektu}.pdf".replace("  ", " ").replace(" .pdf", ".pdf"))
            calosc.save(plik, garbage=3, deflate=True)
            wynik.pliki.append(plik)
    finally:
        for d, _n in rys.pdf.values():
            d.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return wynik


def parsuj_stacje(tekst: str) -> list[int] | None:
    """„565, 1495” / „05-0565 1495” -> [565, 1495]; puste -> None (wszystkie)."""
    nr = [mod_nazwy.nr_stacji(t) for t in re.split(r"[,;\s]+", tekst or "") if t.strip()]
    nr = [n for n in nr if n is not None]
    return nr or None



def pdf_przewieszen(przewieszenia: str, folder_wyj: str, log=print) -> Wynik:
    """PDF-y rysunku przewieszeń (jak w FINALE): osobny „<nr>p.pdf” dla każdej stacji (skrócony numer,
    np. 856p.pdf; arkusze przypisane w „….stacje.json”). Bez przypisania - jeden PDF z całego rysunku."""
    import pymupdf
    wynik = Wynik()
    os.makedirs(folder_wyj, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="przew_pdf_")
    rys = _Rysunki(tmp, log)
    try:
        dok, nazwy = rys.strony(przewieszenia)
        if not nazwy:
            raise ValueError("W rysunku przewieszeń nie ma arkuszy do wydruku.")
        przew_stacje = _stacje_przewieszen(przewieszenia)
        if przew_stacje is None:
            # bez przypisania do stacji - jeden PDF z całego rysunku
            plik = os.path.join(folder_wyj, os.path.splitext(os.path.basename(przewieszenia))[0] + ".pdf")
            dok.save(plik, garbage=3, deflate=True)
            wynik.pliki.append(plik)
            wynik.uwagi.append("Brak pliku „….stacje.json” - powstał jeden PDF z całego rysunku "
                               "(utwórz przewieszenia ponownie, żeby podzielić je na stacje).")
            return wynik
        for nr in sorted({n for st in przew_stacje.values() for n in st}):
            jedna = pymupdf.open()
            ile = rys.dolacz(jedna, przewieszenia, lambda n, nr=nr: nr in przew_stacje.get(n, set()))
            if ile:
                plik = os.path.join(folder_wyj, f"{nr}p.pdf")       # np. 856p.pdf
                jedna.save(plik, garbage=3, deflate=True)
                wynik.pliki.append(plik)
                log(f"  ST {nr}: {ile} ark.")
            jedna.close()
        bez = [n for n in nazwy if not przew_stacje.get(n)]
        if bez:
            wynik.uwagi.append("Arkusze bez przypisanej stacji (pominięte w PDF): " + ", ".join(bez))
    finally:
        for d, _n in rys.pdf.values():
            d.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return wynik


def _dopisz_stacje(slupy, plan: str, log=print, tol: float = 1.0) -> None:
    """Stacja trafo słupa wg logiki zestawienia (obszary !trafo_<nr>, opisy stacji, drzewo sieci) -
    w pliku PZT nie ma obrysów !trafo, z których korzysta moduł warunków technicznych."""
    from . import zestawienie as mod_zest
    tmp = tempfile.mkdtemp(prefix="tabela_")
    try:
        dxf = mod_dwg.dwg_na_dxf(plan, os.path.join(tmp, "plan.dxf")) if mod_dwg.jest_dwg(plan) else plan
        mapa = mod_zest.mapa_stacji_slupow(dxf)
    except Exception as ex:  # noqa: BLE001
        log(f"Uwaga: nie ustalono stacji trafo ({ex})")
        return
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    n = 0
    for w in slupy:
        m = min(mapa, key=lambda t: (t[0] - w.x) ** 2 + (t[1] - w.y) ** 2, default=None)
        if m and ((m[0] - w.x) ** 2 + (m[1] - w.y) ** 2) ** 0.5 <= tol:
            w.stacja_trafo = m[3]
            n += 1
    log(f"Stacje trafo: przypisano {n} z {len(slupy)} słupów")


def tabela_projektowa(plan: str, wt_plik: str | None, folder_wyj: str | None = None, adresy: bool = True,
                      log=print) -> str:
    """Tabela projektowa z gotowego (ponumerowanego) planu: numeracja i układ współrzędnych jak we
    wcześniejszych warunkach technicznych (wt_plik), niewykorzystane słupy WT - wiersz przekreślony.
    Zwraca ścieżkę zapisanego pliku „<plan>_tabela_projektowa.xlsx”."""
    from pathlib import Path
    from . import wt as mod_wt
    from .warunki.config import Config
    from .warunki.projekt import Projekt
    wt = mod_wt.wczytaj_wt(wt_plik) if wt_plik else None
    if wt:
        log(f"Warunki techniczne: {len(wt)} słupów ({'PL-2000' if wt[0].uklad == 'pl2000' else 'WGS 84'})")
    p = Projekt(Config())
    p.wczytaj(plan)
    log(f"Plan: {len(p.slupy)} słupów")
    if adresy:
        p.geokoduj(lambda i, n: None)
    p.zastosuj_stan()
    p.planuj()
    _dopisz_stacje(p.slupy, plan, log)
    folder = Path(folder_wyj or os.path.dirname(os.path.abspath(plan)))
    folder.mkdir(parents=True, exist_ok=True)
    cel = folder / (Path(plan).stem + "_tabela_projektowa.xlsx")
    p.zapisz_projektowa(cel, wt=wt)
    log(f"Zapisano: {cel}")
    return str(cel)


__all__ = ["Zrodla", "Wynik", "CZESCI", "stacje", "zloz", "tabela_projektowa", "pdf_przewieszen", "parsuj_stacje", "docx_do_pdf", "glob"]
