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

Dodatkowo moduł zawiera RENUMERACJĘ numerów rysunku w tabelkach arkuszy DXF
(odpowiednik polecenia PPW z PPW_RENUMER.lsp dla GstarCAD) - patrz renumeruj_rysunki().
Ta część działa na czystym Pythonie (tagi DXF), bez bibliotek zewnętrznych.
"""
from __future__ import annotations

import os
import re

try:
    from . import dxfio as _dxf
except ImportError:  # bezpośrednie uruchomienie
    import dxfio as _dxf

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


# ===========================================================================
# RENUMERACJA numerów rysunku w tabelkach arkuszy DXF (odpowiednik PPW_RENUMER.lsp)
# ===========================================================================
# Dla arkuszy (layoutów) o nazwie STACJA-ARKUSZ (np. 112-1) wylicza nowy numer rysunku:
#   * stacje numerowane kolejno rosnąco po numerze stacji: 112->1, 115->2, 181->3, ...
#   * arkusze w ramach stacji: <nr>.<podnr> (1.1, 1.2, ...); stacja z JEDNYM arkuszem -> bez kropki.
# Numer wpisywany do tabelki (MTEXT numeru). Dodatkowo „Projekt wykonawczy” -> „Projekt powykonawczy”.
# Nazwy zakładek (layoutów) NIE są zmieniane. Wynik to nowy plik (nieniszcząco).

RE_LAYOUT_SA = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")   # "112-1" -> (stacja, arkusz)
WYS_NUMERU = 2.0                                          # wysokość MTEXT numeru rysunku [j.]
TOL_WYS = 0.05                                            # tolerancja wysokości
STYL_PREFEROWANY = "LEGENDA"                              # styl preferowany (nie wymagany)


def _is_num_rysunku(txt: str) -> bool:
    """Czy treść wygląda na numer rysunku: 'N' lub 'N.N' (same cyfry, maks. jedna kropka)."""
    s = (txt or "").strip()
    return bool(s) and re.fullmatch(r"\d+(?:\.\d+)?", s) is not None


def _mapa_numerow(nazwy_layoutow):
    """Buduje {nazwa_layoutu: nowy_numer_rysunku} wg reguły PPW (jak w LISP build-map).

    nazwy_layoutow - iterowalne nazw; brane są tylko pasujące do STACJA-ARKUSZ."""
    arkusze = []                       # (nazwa, stacja_int, arkusz_int)
    for nm in nazwy_layoutow:
        m = RE_LAYOUT_SA.match(nm or "")
        if m:
            arkusze.append((nm, int(m.group(1)), int(m.group(2))))
    # sort po stacji, potem po numerze arkusza
    arkusze.sort(key=lambda a: (a[1], a[2]))
    # liczba arkuszy na stację + indeks stacji (kolejno od 1 wg rosnącego numeru stacji)
    liczba = {}
    for _nm, st, _ar in arkusze:
        liczba[st] = liczba.get(st, 0) + 1
    indeks_stacji = {st: i for i, st in enumerate(sorted(liczba), start=1)}
    mapa = {}
    order = {}
    for nm, st, _ar in arkusze:
        order[st] = order.get(st, 0) + 1
        n = indeks_stacji[st]
        mapa[nm] = str(n) if liczba[st] == 1 else f"{n}.{order[st]}"
    return mapa


def _nazwy_layoutow(secs):
    """Zwraca listę (nazwa_layoutu, handle_block_record) z sekcji OBJECTS."""
    out = []
    for t, d in _dxf.split_entities(secs.get("OBJECTS", [])):
        if t == "LAYOUT":
            nazwy = [v for c, v in d if c == 1]
            br = [v for c, v in d if c == 330]
            if nazwy and br:
                out.append((nazwy[-1], br[-1].upper()))
    return out


def _mapa_br_na_blok(secs):
    """{handle_block_record (UPPER): nazwa_bloku} z tabeli BLOCK_RECORD."""
    out = {}
    for t, d in _dxf.split_entities(secs.get("TABLES", [])):
        if t == "BLOCK_RECORD":
            h = _dxf.get(d, 5)
            if h:
                out[h.upper()] = _dxf.get(d, 2) or ""
    return out


def _ustaw_numer_w_encjach(ents, nalezy, nowy):
    """Podmienia treść (kod 1) pierwszego MTEXT będącego numerem rysunku (wys. ~2.0, treść N/N.N)
    wśród encji, dla których predykat `nalezy(indeks)` jest prawdziwy. Preferuje styl LEGENDA,
    ale go nie wymaga. Zwraca True, gdy podmieniono."""
    for wymagaj_stylu in (True, False):
        for i, (t, d) in enumerate(ents):
            if t != "MTEXT" or not nalezy(i):
                continue
            h = _dxf.getf(d, 40)
            txt = _dxf.mtext_plain(_dxf.get(d, 1, "") or "")
            sty = (_dxf.get(d, 7) or "").strip().upper()
            if h is None or abs(h - WYS_NUMERU) > TOL_WYS:
                continue
            if not _is_num_rysunku(txt):
                continue
            if wymagaj_stylu and sty != STYL_PREFEROWANY:
                continue
            ents[i] = (t, [(c, (nowy if c == 1 else v)) for c, v in d])
            return True
    return False


def _zamien_powykonawczy(secs):
    """W całym rysunku zamienia 'Projekt wykonawczy'->'Projekt powykonawczy'
    (fallback 'wykonawczy'->'powykonawczy'), w TEXT i MTEXT. Zwraca liczbę zmian."""
    zmian = 0
    for sekcja in ("ENTITIES", "BLOCKS"):
        ents = _dxf.split_entities(secs.get(sekcja, []))
        zmieniono = False
        for i, (t, d) in enumerate(ents):
            if t not in ("TEXT", "MTEXT"):
                continue
            d2 = []
            lok = False
            for c, v in d:
                if c == 1 and v and "wykonawczy" in v.lower() and "powykonawczy" not in v.lower():
                    nowy = re.sub(r"(?i)projekt\s+wykonawczy", "Projekt powykonawczy", v)
                    if nowy == v:
                        nowy = re.sub(r"(?i)wykonawczy", "powykonawczy", v)
                    if nowy != v:
                        v = nowy
                        lok = True
                d2.append((c, v))
            if lok:
                ents[i] = (t, d2)
                zmian += 1
                zmieniono = True
        if zmieniono:
            secs[sekcja] = _dxf.join_entities(ents)
    return zmian


def renumeruj_rysunki(dxf, wyjscie=None, log=None):
    """Renumeruje numery rysunku w tabelkach arkuszy STACJA-ARKUSZ i zamienia
    „Projekt wykonawczy” -> „Projekt powykonawczy”. Tworzy NOWY plik DXF (oryginał nietknięty).

    Zwraca (ścieżka_wyniku, liczba_ustawionych_numerow, liczba_zamian_tekstu)."""
    log = log or print
    if not os.path.isfile(dxf):
        raise FileNotFoundError(f"Nie znaleziono pliku DXF: {dxf}")
    secs_list = _dxf.split_sections(_dxf.read_tags(dxf))
    secs = dict(secs_list)
    kolejnosc = [n for n, _ in secs_list]

    layouty = _nazwy_layoutow(secs)
    mapa = _mapa_numerow(nm for nm, _br in layouty)
    if not mapa:
        raise ValueError("Nie znaleziono arkuszy w formacie STACJA-ARKUSZ (np. „112-1”).")

    log("--- Mapowanie (arkusz -> numer rysunku) ---")
    for nm in sorted(mapa, key=_klucz_sa):
        log(f"  {nm}  ->  {mapa[nm]}")

    # podmiana numeru w tabelce każdego arkusza. Encje papieru arkusza są:
    #  * w BLOCKS - w bloku *Paper_SpaceN (zwykłe arkusze), albo
    #  * w ENTITIES - gdy to AKTYWNY arkusz (owner 330 = handle jego block record).
    br2blk = _mapa_br_na_blok(secs)
    ents_blocks = _dxf.split_entities(secs.get("BLOCKS", []))
    ents_model = _dxf.split_entities(secs.get("ENTITIES", []))

    # indeksy encji BLOCKS wg aktualnego bloku (do predykatu „należy do bloku”)
    blok_encji = [None] * len(ents_blocks)
    cur = None
    for i, (t, d) in enumerate(ents_blocks):
        if t == "BLOCK":
            cur = _dxf.get(d, 2) or ""
        blok_encji[i] = cur

    ustawione, braki = 0, []
    for nazwa, br in layouty:
        if nazwa not in mapa:
            continue
        blok = br2blk.get(br, "")
        nowy = mapa[nazwa]
        # 1) spróbuj w BLOCKS (po nazwie bloku papieru)
        if _ustaw_numer_w_encjach(ents_blocks, lambda i, b=blok: blok_encji[i] == b, nowy):
            ustawione += 1
            continue
        # 2) aktywny arkusz: encje w ENTITIES z ownerem (330) = handle block record layoutu
        if _ustaw_numer_w_encjach(ents_model, lambda i, h=br: (_dxf.get(ents_model[i][1], 330) or "").upper() == h, nowy):
            ustawione += 1
            continue
        braki.append(nazwa)
    secs["BLOCKS"] = _dxf.join_entities(ents_blocks)
    secs["ENTITIES"] = _dxf.join_entities(ents_model)

    # „Projekt wykonawczy” -> „Projekt powykonawczy” (po podmianie numerów, bo też rusza BLOCKS)
    zmian_txt = _zamien_powykonawczy(secs)

    if not wyjscie:
        baza, _ext = os.path.splitext(dxf)
        wyjscie = baza + " - powykonawczy.dxf"
    tags = []
    for name in kolejnosc:
        tags += [(0, "SECTION"), (2, name)] + secs[name] + [(0, "ENDSEC")]
    tags.append((0, "EOF"))
    _dxf.write_tags(wyjscie, tags)

    log(f"Numerów rysunku ustawionych: {ustawione}/{len(mapa)}")
    if braki:
        log("UWAGA - nie znaleziono pola numeru na arkuszach: " + ", ".join(braki))
    log(f"Tekstów „wykonawczy”->„powykonawczy”: {zmian_txt}")
    log(f"-> {os.path.basename(wyjscie)}")
    return wyjscie, ustawione, zmian_txt


def _klucz_sa(nazwa):
    """Klucz sortowania nazwy STACJA-ARKUSZ po (stacja, arkusz)."""
    m = RE_LAYOUT_SA.match(nazwa or "")
    return (int(m.group(1)), int(m.group(2))) if m else (10**9, nazwa)


# ---------------------------------------------------------------------------
def main(argv=None):
    import argparse
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="PPW - zbiorczy opis techniczny .docx + renumeracja rysunków DXF.")
    ap.add_argument("zestawienie", nargs="?", help="plik .xls/.xlsx z modułu „zestawienie” (tryb opisu zbiorczego)")
    ap.add_argument("--szablon", default=None, help="szablon .docx (domyślnie dołączony „PPW miński szablon.docx”)")
    ap.add_argument("--nazwy", default=None, help="„zestawienie_stacji.xlsx” z Rysunków stałych (miejscowości)")
    ap.add_argument("--wt", default="", help="numer warunków technicznych (WT)")
    ap.add_argument("-o", "--wyjscie", default=None, help="plik wynikowy")
    ap.add_argument("--renumeruj", default=None, metavar="DXF",
                    help="TRYB renumeracji: wskaż plik DXF - przenumeruj numery rysunku w tabelkach "
                         "arkuszy STACJA-ARKUSZ i zamień „Projekt wykonawczy”->„Projekt powykonawczy”")
    a = ap.parse_args(argv)
    import sys as _sys
    # tryb renumeracji rysunków (DXF) - nie wymaga bibliotek ani szablonu
    if a.renumeruj:
        try:
            renumeruj_rysunki(a.renumeruj, a.wyjscie)
            return 0
        except Exception as ex:  # noqa: BLE001
            print(f"BŁĄD: {ex}", file=_sys.stderr)
            return 1
    if not a.zestawienie:
        ap.error("podaj plik zestawienia (tryb opisu) albo --renumeruj DXF (tryb renumeracji).")
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
        print("Brak szablonu PPW - wskaż --szablon.", file=_sys.stderr)
        return 1
    try:
        generuj(szablon, a.zestawienie, zestawienie_stacji=a.nazwy, wt=a.wt, wyjscie=a.wyjscie)
        return 0
    except Exception as ex:  # noqa: BLE001
        print(f"BŁĄD: {ex}", file=_sys.stderr)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
