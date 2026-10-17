#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Moduł PPW - zbiorczy opis techniczny (.docx) dla CAŁEGO projektu (wszystkie stacje w jednym pliku).

W odróżnieniu od modułu „Opisy” (osobny plik na stację) PPW tworzy JEDEN dokument podsumowujący
wszystkie stacje trafo projektu, na podstawie szablonu Word (domyślnie „PPW miński szablon.docx”).

Źródła danych:
  * ZESTAWIENIE (moduł „zestawienie”, .xls/.xlsx) - arkusz „zestawienie”: stacja | ilość | długość;
    z niego powstaje tabela „Zestawienie zbiorcze słupów” (wiersz na stację + SUMA, numer arkusza
    nadawany kolejno 1, 2, 3…) oraz lista numerów stacji do nagłówka,
  * ZESTAWIENIE_STACJI (moduł „Rysunki stałe”, .xlsx) - mapowanie stacja -> miejscowość (nazwy),
  * WT - numer warunków technicznych, wpisywany ręcznie.

W szablonie podstawiane są znaczniki tekstowe:
  *mmmm*  -> miejscowości projektu (wszystkie, po przecinku, bez powtórzeń),
  *xxxxx* -> numery stacji trafo (wszystkie, po przecinku),
  *wwww*  -> numer WT.

Wymaga bibliotek python-docx i openpyxl (importowane leniwie - brak nie wywraca całego programu).
"""
from __future__ import annotations

import os
import re

# openpyxl / python-docx - opcjonalne, ładowane leniwie (jak w module opisy)
openpyxl = None
docx = None
_copy = None


def _wymagaj_bibliotek():
    global openpyxl, docx, _copy
    if openpyxl is None:
        try:
            import openpyxl as _o
        except ImportError as ex:
            raise ImportError("Moduł PPW wymaga biblioteki openpyxl (pip install openpyxl)") from ex
        openpyxl = _o
    if docx is None:
        try:
            import copy as _c
            import docx as _d
        except ImportError as ex:
            raise ImportError("Moduł PPW wymaga biblioteki python-docx (pip install python-docx)") from ex
        docx, _copy = _d, _c


NAGLOWEK_TABELI = "Nr stacji"            # po tym rozpoznajemy tabelę „Zestawienie zbiorcze słupów”
ZNACZNIKI = ("*mmmm*", "*xxxxx*", "*wwww*")


# ---------------------------------------------------------------------------
# Odczyt źródeł (.xls/.xlsx)
# ---------------------------------------------------------------------------
def _ascii(s):
    tr = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    return str(s or "").translate(tr).strip().lower()


def _wiersze_xlsx(sciezka, arkusz=None):
    wb = openpyxl.load_workbook(sciezka, data_only=True)
    ws = wb[arkusz] if (arkusz and arkusz in wb.sheetnames) else wb[wb.sheetnames[0]]
    return [[("" if c is None else c) for c in r] for r in ws.iter_rows(values_only=True)], wb


def wczytaj_zestawienie_zbiorcze(sciezka):
    """Z pliku modułu „zestawienie” (arkusz „zestawienie”) zwraca listę (stacja, ilosc, dlugosc)
    dla kolejnych stacji - pomijając wiersz zbiorczy RAZEM i stacje bez rozpoznanej nazwy."""
    wb = openpyxl.load_workbook(sciezka, data_only=True)
    nazwa = "zestawienie" if "zestawienie" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[nazwa]
    rows = [[("" if c is None else c) for c in r] for r in ws.iter_rows(values_only=True)]
    out = []
    for r in rows[1:]:                               # pomiń nagłówek (stacja|ilość|długość|kontrola)
        stacja = str(r[0]).strip() if r and r[0] not in (None, "") else ""
        if not stacja or stacja.upper() in ("RAZEM", "SUMA"):
            continue
        if _ascii(stacja).startswith("obszar_") or "?" in stacja:
            continue                                 # stacja bez rozpoznanej nazwy
        ilosc = _int(r[1]) if len(r) > 1 else 0
        dlugosc = _int(r[2]) if len(r) > 2 else 0
        out.append((stacja, ilosc, dlugosc))
    return out


def wczytaj_miejscowosci(sciezka):
    """Z pliku „zestawienie_stacji.xlsx” (Rysunki stałe) zwraca {znormalizowany_nr_stacji: miejscowość}
    oraz listę miejscowości w kolejności występowania (bez powtórzeń)."""
    rows, _wb = _wiersze_xlsx(sciezka)
    if not rows:
        return {}, []
    hdr = [_ascii(v) for v in rows[0]]
    i_ozn = next((j for j, h in enumerate(hdr) if h in ("oznaczenie stacji", "oznaczenie")), None)
    i_nr = next((j for j, h in enumerate(hdr) if h in ("nr stacji", "numer", "nr")), None)
    i_m = next((j for j, h in enumerate(hdr) if h in ("miejscowosc", "miejscowość")), None)
    mapa, kolejnosc = {}, []
    if i_m is None:
        return mapa, kolejnosc
    for r in rows[1:]:
        if not any(r):
            continue
        miejsc = str(r[i_m]).strip() if i_m < len(r) and r[i_m] else ""
        if not miejsc:
            continue
        klucz = ""
        for i in (i_ozn, i_nr):
            if i is not None and i < len(r) and r[i] not in (None, ""):
                klucz = _norm_nr(r[i])
                break
        if klucz:
            mapa[klucz] = miejsc
        if miejsc not in kolejnosc:
            kolejnosc.append(miejsc)
    return mapa, kolejnosc


def _int(v):
    try:
        return int(round(float(str(v).replace(",", ".").split()[0])))
    except (ValueError, TypeError, IndexError):
        return 0


def _norm_nr(s):
    s = str(s or "").strip()
    tok = re.split(r"[-/ ]", s)[-1]
    cyfry = re.sub(r"\D", "", tok)
    return str(int(cyfry)) if cyfry else s.lower()


# ---------------------------------------------------------------------------
# Podmiana znaczników *...* w dokumencie (zwykły tekst, znacznik rozbity na runy)
# ---------------------------------------------------------------------------
def _podmien_w_akapicie(par, mapowanie):
    """Podmienia znaczniki *mmmm*/*xxxxx*/*wwww* w akapicie, nawet gdy są rozbite na kilka runów.
    Zachowuje formatowanie: całość tekstu akapitu wrzucamy do pierwszego runu, resztę czyścimy."""
    pelny = "".join(r.text for r in par.runs)
    if not any(z in pelny for z in mapowanie):
        return 0
    n = sum(pelny.count(z) for z in mapowanie)
    for z, w in mapowanie.items():
        pelny = pelny.replace(z, w)
    if par.runs:
        par.runs[0].text = pelny
        for r in par.runs[1:]:
            r.text = ""
    return n


def _podmien_wszedzie(doc, mapowanie):
    n = 0
    for par in doc.paragraphs:
        n += _podmien_w_akapicie(par, mapowanie)
    for tb in doc.tables:
        for row in tb.rows:
            for cell in row.cells:
                for par in cell.paragraphs:
                    n += _podmien_w_akapicie(par, mapowanie)
    return n


# ---------------------------------------------------------------------------
# Tabela „Zestawienie zbiorcze słupów”
# ---------------------------------------------------------------------------
def _znajdz_tabele_zbiorcza(doc):
    """Tabela, której nagłówek (1. wiersz) zaczyna się od „Nr stacji”."""
    for tb in doc.tables:
        if tb.rows and NAGLOWEK_TABELI.lower() in tb.rows[0].cells[0].text.strip().lower():
            return tb
    return None


def _ustaw_tekst_komorki(cell, tekst):
    """Wstawia `tekst` do komórki, zachowując formatowanie pierwszego runu pierwszego akapitu."""
    par = cell.paragraphs[0]
    if par.runs:
        par.runs[0].text = tekst
        for r in par.runs[1:]:
            r.text = ""
    else:
        par.add_run(tekst)
    # usuń ewentualne dodatkowe akapity w komórce
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)


def wypelnij_tabele(doc, stacje):
    """Wypełnia tabelę „Zestawienie zbiorcze słupów” wierszami per stacja + SUMA.

    stacje - lista (stacja, ilosc, dlugosc). Numer arkusza nadawany kolejno 1, 2, 3…
    Wiersz danych klonowany z wzorca (2. wiersz tabeli), wiersz SUMA - z ostatniego."""
    tb = _znajdz_tabele_zbiorcza(doc)
    if tb is None:
        raise ValueError("W szablonie PPW nie znaleziono tabeli „Zestawienie zbiorcze słupów” "
                         "(pierwsza kolumna nagłówka: „Nr stacji…”).")
    if len(tb.rows) < 2:
        raise ValueError("Tabela zbiorcza w szablonie nie ma wiersza-wzorca danych.")

    wzor_tr = tb.rows[1]._tr                                  # wzorzec wiersza danych
    suma_tr = tb.rows[-1]._tr if len(tb.rows) >= 3 else None  # wzorzec wiersza SUMA (jeśli jest)
    tbl = tb._tbl

    # usuń wszystkie wiersze poza nagłówkiem (wiersz 0)
    for tr in list(tb.rows)[1:]:
        tbl.remove(tr._tr)

    suma_il = suma_dl = 0
    for k, (stacja, ilosc, dlugosc) in enumerate(stacje, start=1):
        nowy = _copy.deepcopy(wzor_tr)
        tbl.append(nowy)
        wiersz = tb.rows[-1]
        _ustaw_tekst_komorki(wiersz.cells[0], str(stacja))
        _ustaw_tekst_komorki(wiersz.cells[1], str(ilosc))
        _ustaw_tekst_komorki(wiersz.cells[2], str(dlugosc))
        _ustaw_tekst_komorki(wiersz.cells[3], str(k))         # numer arkusza po kolei
        suma_il += ilosc
        suma_dl += dlugosc

    # wiersz SUMA
    nowa_suma = _copy.deepcopy(suma_tr if suma_tr is not None else wzor_tr)
    tbl.append(nowa_suma)
    wiersz = tb.rows[-1]
    _ustaw_tekst_komorki(wiersz.cells[0], "SUMA")
    _ustaw_tekst_komorki(wiersz.cells[1], str(suma_il))
    _ustaw_tekst_komorki(wiersz.cells[2], str(suma_dl))
    _ustaw_tekst_komorki(wiersz.cells[3], "")
    return len(stacje)


# ---------------------------------------------------------------------------
# Generowanie
# ---------------------------------------------------------------------------
def generuj(szablon, zestawienie, zestawienie_stacji=None, wt="", wyjscie=None, log=None):
    """Tworzy ZBIORCZY opis PPW (.docx) dla wszystkich stacji projektu.

    szablon            - .docx ze znacznikami *mmmm*/*xxxxx*/*wwww* i tabelą zbiorczą,
    zestawienie        - .xls/.xlsx z modułu „zestawienie” (tabela + numery stacji),
    zestawienie_stacji - .xlsx z „Rysunków stałych” (miejscowości); opcjonalne,
    wt                 - numer warunków technicznych (ręcznie),
    wyjscie            - ścieżka wynikowa (domyślnie w folderze szablonu: „PPW.docx”).
    Zwraca ścieżkę utworzonego pliku."""
    log = log or print
    _wymagaj_bibliotek()
    if not os.path.isfile(szablon):
        raise FileNotFoundError(f"Nie znaleziono szablonu PPW: {szablon}")
    if not os.path.isfile(zestawienie):
        raise FileNotFoundError(f"Nie znaleziono zestawienia: {zestawienie}")

    stacje = wczytaj_zestawienie_zbiorcze(zestawienie)
    if not stacje:
        raise ValueError("Zestawienie nie zawiera stacji (arkusz „zestawienie”: stacja|ilość|długość).")

    mapa_miejsc, kolejnosc_miejsc = ({}, [])
    if zestawienie_stacji and os.path.isfile(zestawienie_stacji):
        mapa_miejsc, kolejnosc_miejsc = wczytaj_miejscowosci(zestawienie_stacji)
    elif zestawienie_stacji:
        log(f"Uwaga: nie znaleziono pliku miejscowości: {zestawienie_stacji} - pominięto nazwy.")

    # miejscowości: najpierw wg stacji z zestawienia (kolejność i bez powtórzeń), potem reszta z pliku nazw
    miejsc = []
    for stacja, _il, _dl in stacje:
        m = mapa_miejsc.get(_norm_nr(stacja))
        if m and m not in miejsc:
            miejsc.append(m)
    for m in kolejnosc_miejsc:
        if m not in miejsc:
            miejsc.append(m)

    numery_stacji = [str(s).strip() for s, _il, _dl in stacje]

    mapowanie = {
        "*mmmm*": ", ".join(miejsc),
        "*xxxxx*": ", ".join(numery_stacji),
        "*wwww*": wt or "",
    }

    doc = docx.Document(szablon)
    n_zn = _podmien_wszedzie(doc, mapowanie)
    n_wier = wypelnij_tabele(doc, stacje)

    if not wyjscie:
        wyjscie = os.path.join(os.path.dirname(os.path.abspath(szablon)), "PPW.docx")
    os.makedirs(os.path.dirname(os.path.abspath(wyjscie)), exist_ok=True)
    doc.save(wyjscie)
    log(f"PPW: {len(stacje)} stacji, {n_wier} wierszy tabeli, podmieniono {n_zn} znaczników -> "
        f"{os.path.basename(wyjscie)}")
    if not miejsc:
        log("Uwaga: nie ustalono żadnej miejscowości (sprawdź plik „zestawienie_stacji.xlsx”).")
    if not (wt or "").strip():
        log("Uwaga: pusty numer WT - wpisz go ręcznie (pole „Numer warunków (WT)”).")
    return wyjscie


# ---------------------------------------------------------------------------
def main(argv=None):
    import argparse
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="PPW - zbiorczy opis techniczny .docx dla całego projektu.")
    ap.add_argument("zestawienie", help="plik .xls/.xlsx z modułu „zestawienie”")
    ap.add_argument("--szablon", default=None, help="szablon .docx (domyślnie dołączony „PPW miński szablon.docx”)")
    ap.add_argument("--nazwy", default=None, help="„zestawienie_stacji.xlsx” z Rysunków stałych (miejscowości)")
    ap.add_argument("--wt", default="", help="numer warunków technicznych (WT)")
    ap.add_argument("-o", "--wyjscie", default=None, help="plik wynikowy (domyślnie „PPW.docx” w folderze szablonu)")
    a = ap.parse_args(argv)
    try:
        _wymagaj_bibliotek()
        from . import zasoby
    except ImportError:
        try:
            import zasoby
        except ImportError:
            zasoby = None
    szablon = a.szablon or (zasoby.szablon_ppw_docx() if zasoby else None)
    if not szablon:
        print("Brak szablonu PPW - wskaż --szablon.", file=__import__("sys").stderr)
        return 1
    try:
        generuj(szablon, a.zestawienie, zestawienie_stacji=a.nazwy, wt=a.wt, wyjscie=a.wyjscie)
        return 0
    except Exception as ex:  # noqa: BLE001
        print(f"BŁĄD: {ex}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
