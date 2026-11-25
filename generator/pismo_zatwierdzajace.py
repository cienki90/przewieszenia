"""Pismo zatwierdzające (uzgodnienie projektów wykonawczych) dla kilku projektów naraz.

Dla każdego wskazanego folderu projektu jeden akapit:
  „- Podwieszenie kabla światłowodowego, na istniejących słupach linii nN 0,4kV własności
  PGE Dystrybucja S.A. Oddział Warszawa, Rejon Energetyczny <rejon> w miejscowościach
  <miejscowości gm. gmina>. Linia napowietrzna nN zasilana ze stacji transformatorowej SN/nN
  nr <stacje> na <N> stanowiskach słupowych. W/w dokumentacje wykonane na podstawie wydanych
  warunków technicznych nr <WT>.”

Skąd dane (wszystko z folderu projektu):
  * stacje i liczba słupów - „zestawienie <plan>.xlsx” (moduł Zestawienie),
  * miejscowości i gminy  - „rysunki stałe/…/zestawienie_stacji.xlsx” (moduł Rysunki stałe),
  * rejon                 - „<plan>.wt.json” (Generator WT), inaczej pole „rejon” podane ręcznie,
  * numer WT              - „projekt GeneratorNN.json”, a gdy go tam nie ma - z opisów/PPW (.docx).
Wszystkie wartości można poprawić w oknie przed utworzeniem pisma.

Szablon (opcjonalny) - dokument .docx z akapitem „*projekty*” (tam trafią akapity projektów) i
ewentualnie „*data*”, „*rejon*”, „*razem*” (suma słupów). Bez szablonu powstaje prosty dokument.
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import re
import zipfile
from dataclasses import dataclass, field

from . import uklad_projektu as uklad

# 65/RE-5/KŚ/2026, 49/RE-8/JZ/2026
RE_WT = re.compile(r"\b\d{1,4}\s*/\s*RE-\s*\d+\s*/\s*[A-ZĄĆĘŁŃÓŚŹŻ]{1,4}\s*/\s*\d{4}\b")
ZN_PROJEKTY, ZN_DATA, ZN_REJON, ZN_RAZEM = "*projekty*", "*data*", "*rejon*", "*razem*"
MIESIACE = ("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
            "września", "października", "listopada", "grudnia")


@dataclass
class Projekt:
    folder: str
    miejscowosci: str = ""          # „Stojadła, Mińsk Mazowiecki gm. Mińsk Mazowiecki; Tyborów gm. Cegłów”
    stacje: list = field(default_factory=list)   # ['05-1570', '05-0068']
    slupy: int = 0
    wt: str = ""
    rejon: str = ""                 # „Mińsk Mazowiecki” (bez „Rejon Energetyczny”)
    uwagi: list = field(default_factory=list)

    @property
    def nazwa(self) -> str:
        return os.path.basename(os.path.normpath(self.folder))


# ------------------------------------------------------------------ odczyt danych z projektu
def _bez_cudzyslowow(s) -> str:
    return re.sub(r'^[\s"„”\']+|[\s"„”\']+$', "", str(s or ""))


def _rozbij(s) -> list[str]:
    return [m.strip() for m in re.split(r"[,;]", str(s or "")) if m.strip()]


def _klucz_stacji(s) -> str:
    tok = re.split(r"[-/ ]", str(s or "").strip())[-1]
    cyfry = re.sub(r"\D", "", tok)
    return str(int(cyfry)) if cyfry else str(s).strip().lower()


def miejscowosci_z_rysunkow(sciezka: str, stacje=None) -> str:
    """„miejsc1, miejsc2 gm. G1; miejsc3 gm. G2” z zestawienia stacji (Rysunki stałe), w kolejności
    stacji; tylko stacje z listy `stacje` (gdy podana)."""
    import openpyxl
    wb = openpyxl.load_workbook(sciezka, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    wiersze = list(ws.iter_rows(values_only=True))
    wb.close()
    if not wiersze:
        return ""
    hdr = [re.sub(r"\s+", " ", str(h or "")).strip().lower() for h in wiersze[0]]

    def kol(*nazwy):
        return next((i for i, h in enumerate(hdr) if h in nazwy), None)
    i_ozn, i_nr = kol("oznaczenie stacji", "oznaczenie"), kol("nr stacji", "numer", "nr")
    i_m, i_g = kol("miejscowość", "miejscowosc"), kol("gmina")
    if i_m is None:
        return ""
    chciane = {_klucz_stacji(s) for s in stacje} if stacje else None
    gminy: dict[str, list[str]] = {}
    for r in wiersze[1:]:
        if not r or i_m >= len(r) or not r[i_m]:
            continue
        nr = next((r[i] for i in (i_ozn, i_nr) if i is not None and i < len(r) and r[i] not in (None, "")), "")
        if chciane is not None and _klucz_stacji(nr) not in chciane:
            continue
        g = _bez_cudzyslowow(r[i_g]) if i_g is not None and i_g < len(r) else ""
        lst = gminy.setdefault(g, [])
        for m in _rozbij(r[i_m]):
            if m.lower() not in (x.lower() for x in lst):
                lst.append(m)
    czesci = [", ".join(m) + (f" gm. {g}" if g else "") for g, m in gminy.items() if m]
    return "; ".join(czesci)


def _tekst_docx(sciezka: str) -> str:
    try:
        with zipfile.ZipFile(sciezka) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    return re.sub(r"<[^>]+>", "", xml)


KLUCZE_WT = ("wt_opisy", "wt_ppw", "wt_zakladki")      # pola numeru WT w pliku projektu (wspólny numer)


def wt_zapisany(folder: str) -> str:
    """Numer WT zapisany w „projekt GeneratorNN.json” (pole wspólne dla opisów/PPW/zakładek)."""
    from . import projekt
    pola = (projekt.wczytaj(folder) or {}).get("pola") or {}
    return next((pola[k].strip() for k in KLUCZE_WT if isinstance(pola.get(k), str) and pola[k].strip()), "")


def zapamietaj_wt(folder: str, wt: str) -> bool:
    """Zapisuje numer WT w pliku projektu (gdy go tam nie ma albo jest inny) - kolejne pismo, opisy
    i PPW wezmą go stamtąd. Plik projektu jest tworzony, gdy go brak."""
    from . import projekt
    wt = (wt or "").strip()
    if not wt or not os.path.isdir(folder) or wt_zapisany(folder) == wt:
        return False
    dane = projekt.wczytaj(folder) or {}
    pola = dict(dane.get("pola") or {})
    pola.update({k: wt for k in KLUCZE_WT})
    projekt.zapisz(folder, pola, [k for k in dane.get("auto") or [] if k not in KLUCZE_WT])
    return True


def wt_z_opisow(folder: str) -> str:
    """Numer WT „NN/RE-5/KŚ/RRRR” z opisów technicznych projektu (najnowsze .docx, bez szablonów)."""
    pliki = [p for p in glob.glob(os.path.join(folder, "**", "*.docx"), recursive=True)
             if not os.path.basename(p).startswith("~$") and "szablon" not in os.path.basename(p).lower()]
    # najpierw opisy (folder „opisy”), potem reszta (PPW); w obrębie - najnowsze
    pliki.sort(key=lambda p: ("opisy" not in os.path.normcase(p).split(os.sep)[-2], -os.path.getmtime(p)))
    for p in pliki[:60]:
        m = RE_WT.search(_tekst_docx(p))
        if m:
            return re.sub(r"\s+", "", m.group(0))
    return ""


def wt_z_projektu(folder: str) -> str:
    """Numer WT projektu: zapisany w pliku projektu, a gdy go brak - z opisów (i od razu zapamiętany)."""
    wt = wt_zapisany(folder)
    if not wt:
        wt = wt_z_opisow(folder)
        if wt:
            try:
                zapamietaj_wt(folder, wt)
            except OSError:
                pass
    return wt


def rejon_z_projektu(folder: str) -> str:
    """„Mińsk Mazowiecki” z ustawień Generatora WT („<plan>.wt.json”)."""
    for p in sorted(glob.glob(os.path.join(folder, "*.wt.json")), key=os.path.getmtime, reverse=True):
        try:
            with open(p, encoding="utf-8") as f:
                r = (json.load(f).get("ustawienia") or {}).get("rejon") or ""
        except (OSError, ValueError):
            continue
        r = re.sub(r"^\s*rejon\s+energetyczny\s*", "", r, flags=re.I).strip()
        if r:
            return r
    return ""


def wczytaj_projekt(folder: str) -> Projekt:
    from . import ppw
    if not os.path.isdir(folder):
        raise NotADirectoryError(f"To nie jest folder projektu: {folder}")
    p = Projekt(folder)
    zest = uklad.znajdz(folder, "ppw_zestawienie")
    if zest:
        ppw._wymagaj_bibliotek()
        pominiete = []
        stacje = ppw.wczytaj_zestawienie_zbiorcze(zest, pominiete)
        p.stacje = [s for s, _n, _d in stacje]
        p.slupy = sum(n for _s, n, _d in stacje)
        if pominiete:
            p.uwagi.append("w zestawieniu są stacje bez nazwy: " + ", ".join(pominiete))
    else:
        p.uwagi.append("brak zestawienia słupów („zestawienie <plan>.xlsx”)")
    zs = uklad.znajdz(folder, "ppw_zestawienie_stacji")
    if zs:
        p.miejscowosci = miejscowosci_z_rysunkow(zs, p.stacje or None)
    if not p.miejscowosci:
        p.uwagi.append("brak miejscowości (zestawienie_stacji.xlsx z Rysunków stałych)")
    p.wt = wt_z_projektu(folder)
    if not p.wt:
        p.uwagi.append("brak numeru WT - wpisz ręcznie")
    p.rejon = rejon_z_projektu(folder)
    return p


# ------------------------------------------------------------------ tabele projektowe
def tabele_dostepne() -> bool:
    """Tabela projektowa wymaga modułu warunków technicznych (wersja „PGE MAKER + WT”)."""
    try:
        from . import final
        from .warunki import projekt as _p  # noqa: F401
    except ImportError:
        return False
    return hasattr(final, "tabela_projektowa")


def _nazwa_wt(wt: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", wt).strip(" -") or "bez numeru WT"


def tabele_projektowe(projekty: list[Projekt], folder_wyj: str, adresy: bool = True, log=print) -> list[str]:
    """Osobna tabela projektowa dla każdego WT (projektu): z pliku PZT projektu, z numeracją jak
    w pliku warunków technicznych projektu („…_uproszczona.xls”). Pliki „Tabela projektowa <WT>.xlsx”
    w folderze_wyj (obok pisma). Zwraca listę utworzonych plików."""
    import shutil
    import tempfile
    from . import final
    os.makedirs(folder_wyj, exist_ok=True)
    wyniki, uzyte = [], set()
    for p in projekty:
        pzt = uklad.znajdz(p.folder, "final_pzt")
        if not pzt:
            log(f"UWAGA - {p.nazwa}: brak pliku PZT - pominięto tabelę projektową.")
            continue
        wt_plik = uklad.znajdz(p.folder, "wt_plik")
        if not wt_plik:
            log(f"UWAGA - {p.nazwa}: brak pliku warunków technicznych - numeracja od 1, WGS 84.")
        nazwa = f"Tabela projektowa {_nazwa_wt(p.wt)}"
        if nazwa.lower() in uzyte:                         # ten sam WT w dwóch projektach
            nazwa += f" - {p.nazwa}"
        uzyte.add(nazwa.lower())
        log(f"\n{p.nazwa} (WT {p.wt or '?'}): {os.path.basename(pzt)}")
        tmp = tempfile.mkdtemp(prefix="tabela_")
        try:
            cel = final.tabela_projektowa(pzt, wt_plik, folder_wyj=tmp, adresy=adresy, log=log)
            wynik = os.path.join(folder_wyj, nazwa + ".xlsx")
            shutil.move(cel, wynik)
            wyniki.append(wynik)
            log(f"  -> {wynik}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return wyniki


# ------------------------------------------------------------------ treść pisma
def data_slownie(d: datetime.date | None = None) -> str:
    d = d or datetime.date.today()
    return f"{d.day} {MIESIACE[d.month - 1]} {d.year} r."


def czesci_akapitu(p: Projekt, rejon: str) -> list[tuple[str, bool]]:
    """Akapit projektu jako [(tekst, pogrubiony)]."""
    rej = (p.rejon or rejon or "").strip()
    stacje = ", ".join(p.stacje)
    sl = "stanowisku słupowym" if p.slupy == 1 else "stanowiskach słupowych"
    return [
        ("- Podwieszenie kabla światłowodowego, na istniejących słupach linii nN 0,4kV własności "
         f"PGE Dystrybucja S.A. Oddział Warszawa, Rejon Energetyczny {rej} w miejscowościach ", False),
        (f"{p.miejscowosci}.", True),
        (f"\nLinia napowietrzna nN zasilana ze stacji transformatorowej SN/nN nr {stacje} na {p.slupy} {sl}. "
         "W/w dokumentacje wykonane na podstawie wydanych warunków technicznych\nnr ", False),
        (f"{p.wt}.", True),
    ]


def _dodaj_akapit(doc, czesci, przed=None):
    """Projekt jako kilka akapitów (podział w miejscach „\\n”) - wyjustowane bez rozciągania linii
    przed podziałem; numery stacji z nierozdzielającym myślnikiem (05‑0244 nie pęka na końcu linii)."""
    akapity = [[]]
    for tekst, bold in czesci:
        linie = re.sub(r"(\d)-(\d)", "\\1\u2011\\2", tekst).split("\n")
        for k, linia in enumerate(linie):
            if k:
                akapity.append([])
            if linia:
                akapity[-1].append((linia, bold))
    for k, runy in enumerate(akapity):
        par = przed.insert_paragraph_before() if przed is not None else doc.add_paragraph()
        for linia, bold in runy:
            par.add_run(linia).bold = bold
        par.paragraph_format.alignment = 3          # do obu krawędzi
        par.paragraph_format.space_after = 0 if k < len(akapity) - 1 else None
    return par


def _podmien_proste(doc, mapa):
    for par in list(doc.paragraphs) + [p for t in doc.tables for row in t.rows for c in row.cells
                                       for p in c.paragraphs]:
        txt = "".join(r.text for r in par.runs)
        if any(z in txt for z in mapa):
            for z, w in mapa.items():
                txt = txt.replace(z, w)
            par.runs[0].text = txt
            for r in par.runs[1:]:
                r.text = ""


def generuj(projekty: list[Projekt], wyjscie: str, szablon: str | None = None, rejon: str = "",
            miejscowosc: str = "", data: datetime.date | None = None, log=print) -> str:
    """Tworzy pismo .docx; zwraca ścieżkę."""
    import docx
    if not projekty:
        raise ValueError("Nie wskazano żadnego projektu.")
    braki = [f"{p.nazwa}: {', '.join(n for n, v in (('stacje', p.stacje), ('miejscowości', p.miejscowosci), ('nr WT', p.wt)) if not v)}"
             for p in projekty if not (p.stacje and p.miejscowosci and p.wt)]
    for b in braki:
        log(f"UWAGA - niekompletne dane: {b}")
    rej = (rejon or next((p.rejon for p in projekty if p.rejon), "")).strip()
    razem = sum(p.slupy for p in projekty)
    mapa = {ZN_DATA: data_slownie(data), ZN_REJON: rej, ZN_RAZEM: str(razem)}
    if szablon:
        doc = docx.Document(szablon)
        znacznik = next((p for p in doc.paragraphs if ZN_PROJEKTY in p.text), None)
        if znacznik is None:
            raise ValueError(f"W szablonie nie ma akapitu ze znacznikiem {ZN_PROJEKTY}: {szablon}")
        for p in projekty:
            _dodaj_akapit(doc, czesci_akapitu(p, rej), przed=znacznik)
        znacznik._element.getparent().remove(znacznik._element)
        _podmien_proste(doc, mapa)
    else:
        doc = docx.Document()
        st = doc.styles["Normal"]
        st.font.name, st.font.size = "Verdana", docx.shared.Pt(10)
        d = doc.add_paragraph(f"{miejscowosc + ', ' if miejscowosc else ''}{mapa[ZN_DATA]}")
        d.paragraph_format.alignment = 2
        doc.add_paragraph()
        doc.add_paragraph("Dotyczy: Uzgodnienie projektu wykonawczego budowy kabla optotelekomunikacyjnego "
                          "wykorzystującego podbudowę słupową PGE.")
        doc.add_paragraph("W odpowiedzi na pismo, które wpłynęło do PGE Dystrybucja S.A. informujemy, iż "
                          "Wydział Majątku Sieciowego nie wnosi uwag do projektu wykonawczego poniżej "
                          "wymienionego:").paragraph_format.alignment = 3
        for p in projekty:
            _dodaj_akapit(doc, czesci_akapitu(p, rej))
        doc.add_paragraph(f"Przed przystąpieniem do prac budowlanych należy poinformować RE {rej} "
                          "o terminie prowadzenia prac budowlanych.").paragraph_format.alignment = 3
        doc.add_paragraph()
        doc.add_paragraph("Z poważaniem")
    os.makedirs(os.path.dirname(os.path.abspath(wyjscie)), exist_ok=True)
    doc.save(wyjscie)
    log(f"Pismo zatwierdzające: {len(projekty)} projekt(ów), {razem} słupów -> {wyjscie}")
    return wyjscie
