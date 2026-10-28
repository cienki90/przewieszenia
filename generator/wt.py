#!/usr/bin/env python3
"""Odczyt pliku Warunków Technicznych (WT) i ustalanie miejscowości stacji z WT.

Plik WT (załącznik do umowy) to tabela słupów energetycznych wykorzystywanych do
podwieszenia światłowodu. Dla każdego słupa zawiera m.in.:

    Nr słupa | Rejon Energetyczny | Gmina | Miejscowość | Lokalizacja, ulica | współrzędne

Współrzędne mogą być podane w układzie PUWG 2000 (PL-2000) albo w WGS84 (stopnie) -
program rozpoznaje układ po zakresie wartości i w razie potrzeby przelicza WGS84 -> PL-2000.
Plik WT NIE zawiera numeru stacji trafo - przypisanie słup WT -> stacja robimy przestrzennie
na podstawie rysunku DXF (patrz miejscowosci_stacji_z_wt).

Odczyt .xls/.xlsx bez bibliotek zewnętrznych - przez czytniki z modułu obliczenia.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

try:
    from . import obliczenia as _obl
    from . import orientacje as _ori
except ImportError:  # bezpośrednie uruchomienie
    import obliczenia as _obl
    import orientacje as _ori


# nagłówki rozpoznawane dla pól WT (po normalizacji do ascii/małych liter)
_H_MIEJSCOWOSC = ("miejscowosc", "miejscowość")
_H_ULICA = ("lokalizacja, ulica", "lokalizacja ulica", "ulica", "lokalizacja")
_H_NR = ("nr slupa", "nr słupa", "lp", "lp.", "numer")


def _ascii(s) -> str:
    tr = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    return str(s or "").translate(tr).strip().lower()


@dataclass
class SlupWT:
    x: float            # easting PL-2000 (jak w DXF: X ~ 7.5 mln dla strefy 7)
    y: float            # northing PL-2000 (Y ~ 5.8 mln)
    miejscowosc: str
    ulica: str = ""
    nr: str = ""


# ---------------------------------------------------------------------------
# Rozpoznanie kolumn współrzędnych i układu (PL-2000 vs WGS84)
# ---------------------------------------------------------------------------
def _czy_pl2000_easting(v) -> bool:
    """Easting PL-2000: strefa 5-8 w milionach, reszta blisko false easting 500 000."""
    if not isinstance(v, (int, float)) or v <= 0:
        return False
    zone = int(v // 1_000_000)
    if zone not in (5, 6, 7, 8):
        return False
    # po odjęciu prefiksu strefy i false easting (500 km) odległość od południka osiowego
    # mieści się w ~±170 km (strefa PL-2000 jest szeroka na 3°)
    reszta = v - zone * 1_000_000 - 500_000
    return -170_000 <= reszta <= 170_000


def _czy_pl2000_northing(v) -> bool:
    """Northing PL-2000 (GRS80): ~1 500 000 .. 9 000 000, ale NIE wpada w okno eastingu."""
    return isinstance(v, (int, float)) and 1_000_000 <= v <= 9_000_000 and not _czy_pl2000_easting(v)


def _czy_wgs_lat(v) -> bool:
    return isinstance(v, (int, float)) and 49.0 <= v <= 55.0


def _czy_wgs_lon(v) -> bool:
    return isinstance(v, (int, float)) and 14.0 <= v <= 24.5


def _wykryj_kolumny_wsp(rows, kol_startowe):
    """Zwraca (idx_x, idx_y, uklad) gdzie uklad in {'pl2000','wgs84'} albo None.

    rows - lista wierszy (lista komórek). kol_startowe - kolumny-kandydaci na współrzędne.
    Rozpoznajemy po zawartości (zakresy wartości), bo nagłówek bywa scalony/pusty."""
    # zbierz wartości liczbowe per kolumna
    kolumny = {}
    for r in rows:
        for c in kol_startowe:
            if c < len(r) and isinstance(r[c], (int, float)):
                kolumny.setdefault(c, []).append(r[c])
    kolumny = {c: v for c, v in kolumny.items() if len(v) >= 3}
    if len(kolumny) < 2:
        return None

    def ocena(vals, test):
        return sum(1 for v in vals for t in [test(v)] if t) / len(vals)

    east = [c for c, v in kolumny.items() if ocena(v, _czy_pl2000_easting) > 0.8]
    north = [c for c, v in kolumny.items() if ocena(v, _czy_pl2000_northing) > 0.8]
    if east and north:
        return east[0], north[0], "pl2000"
    lat = [c for c, v in kolumny.items() if ocena(v, _czy_wgs_lat) > 0.8]
    lon = [c for c, v in kolumny.items() if ocena(v, _czy_wgs_lon) > 0.8]
    if lat and lon:
        # x = lon, y = lat (przeliczymy niżej)
        return lon[0], lat[0], "wgs84"
    return None


# ---------------------------------------------------------------------------
# Odczyt pliku WT
# ---------------------------------------------------------------------------
def _wiersze_z_arkusza(cells):
    """Zamienia słownik {(r,c): v} (z czytaj_xls) na listę wierszy (lista komórek)."""
    if not cells:
        return []
    maxr = max(r for r, _ in cells)
    maxc = max(c for _, c in cells)
    return [[cells.get((r, c)) for c in range(maxc + 1)] for r in range(maxr + 1)]


def _wczytaj_arkusze(sciezka):
    """Lista (nazwa, wiersze) z pliku .xls/.xlsx - przez czytniki modułu obliczenia."""
    with open(sciezka, "rb") as f:
        head = f.read(8)
    if head[:2] == b"PK":                       # .xlsx (ZIP/OOXML)
        arkusze = _obl.czytaj_xlsx(sciezka)
    else:                                        # .xls (OLE2/BIFF8)
        arkusze = _obl.czytaj_xls(sciezka)
    out = []
    for nazwa, cells in arkusze:
        out.append((nazwa, _wiersze_z_arkusza(cells)))
    return out


def wczytaj_wt(sciezka):
    """Czyta plik WT. Zwraca listę SlupWT (współrzędne w PL-2000, jak w DXF).

    Rozpoznaje kolumny po nagłówkach (Miejscowość / ulica) i współrzędne po zawartości;
    gdy współrzędne są w WGS84 - przelicza na PL-2000."""
    arkusze = _wczytaj_arkusze(sciezka)
    for _nazwa, rows in arkusze:
        slupy = _slupy_z_wierszy(rows)
        if slupy:
            return slupy
    raise ValueError(f"W pliku WT „{sciezka}” nie znaleziono słupów ze współrzędnymi "
                     "(kolumny Miejscowość + współrzędne PUWG 2000 lub WGS84).")


def _znajdz_wiersz_naglowka(rows):
    """Indeks wiersza nagłówka = pierwszy wiersz zawierający 'Miejscowość'."""
    for i, r in enumerate(rows[:20]):
        if any(_ascii(v) in _H_MIEJSCOWOSC for v in r):
            return i
    return None


def _slupy_z_wierszy(rows):
    i_hdr = _znajdz_wiersz_naglowka(rows)
    if i_hdr is None:
        return []
    naglowek = [_ascii(v) for v in rows[i_hdr]]
    i_miejsc = next((j for j, h in enumerate(naglowek) if h in _H_MIEJSCOWOSC), None)
    i_ulica = next((j for j, h in enumerate(naglowek) if h in _H_ULICA), None)
    i_nr = next((j for j, h in enumerate(naglowek) if h in _H_NR), None)
    if i_miejsc is None:
        return []
    dane = rows[i_hdr + 1:]
    # kolumny-kandydaci na współrzędne: wszystkie na prawo od miejscowości (oraz ulicy)
    start = max(x for x in (i_miejsc, i_ulica or 0) if x is not None) + 1
    maxc = max((len(r) for r in dane), default=0)
    kol_kand = list(range(start, maxc))
    wykr = _wykryj_kolumny_wsp(dane, kol_kand)
    if wykr is None:
        return []
    ix, iy, uklad = wykr
    slupy = []
    for r in dane:
        if ix >= len(r) or iy >= len(r):
            continue
        vx, vy = r[ix], r[iy]
        if not isinstance(vx, (int, float)) or not isinstance(vy, (int, float)):
            continue
        miejsc = str(r[i_miejsc]).strip() if i_miejsc < len(r) and r[i_miejsc] else ""
        if not miejsc or miejsc == "-":
            continue
        if uklad == "wgs84":
            lon, lat = vx, vy
            zone = _strefa_z_lon(lon)
            x, y = _ori.wgs84_to_pl2000(lat, lon, zone)   # (easting, northing)
        else:
            x, y = _os_easting_northing(vx, vy)
        ulica = ""
        if i_ulica is not None and i_ulica < len(r) and r[i_ulica] and str(r[i_ulica]).strip() != "-":
            ulica = str(r[i_ulica]).strip()
        nr = ""
        if i_nr is not None and i_nr < len(r) and r[i_nr] is not None:
            nr = str(r[i_nr]).strip()
        slupy.append(SlupWT(x=x, y=y, miejscowosc=miejsc, ulica=ulica, nr=nr))
    return slupy


def _os_easting_northing(a, b):
    """Zwraca (easting, northing) PL-2000 z pary (a, b) niezależnie od kolejności kolumn."""
    if _czy_pl2000_easting(a) and _czy_pl2000_northing(b):
        return a, b
    if _czy_pl2000_easting(b) and _czy_pl2000_northing(a):
        return b, a
    # awaryjnie: większa z wartości ~7-8 mln bywa eastingiem (strefa 7/8), mniejsza northingiem
    return (a, b) if a >= b else (b, a)


def _strefa_z_lon(lon):
    """Strefa PL-2000 z długości geograficznej (południki osiowe 15/18/21/24)."""
    poludniki = {15: 5, 18: 6, 21: 7, 24: 8}
    najbl = min(poludniki, key=lambda m: abs(m - lon))
    return poludniki[najbl]


# ---------------------------------------------------------------------------
# Miejscowości stacji z WT (przypisanie przez !tele w zasięgu !trafo)
# ---------------------------------------------------------------------------
def miejscowosci_stacji_z_wt(dxf_path, wt_path, tol=3.0, log=print):
    """Zwraca ({nr_stacji: [miejscowości...]}, ostrzeżenia[]) ustalone z pliku WT.

    Dla każdej stacji: bierzemy WIERZCHOŁKI polilinii !tele leżące w jej poligonie !trafo
    (odporne na poszerzony poligon), dopasowujemy do nich najbliższe słupy z WT (tol = `tol` m)
    i zbieramy ich miejscowości. Lista posortowana malejąco wg liczby trafień.

    Gdy dla stacji nie uda się dopasować ŻADNEGO słupa WT - zgłaszamy to głośno w ostrzeżeniach
    (fallback na geokodowanie wykonuje warstwa wyżej)."""
    slupy_wt = wczytaj_wt(wt_path)
    if not slupy_wt:
        raise ValueError(f"Plik WT „{wt_path}” nie zawiera słupów ze współrzędnymi.")

    # poligony !trafo i trasy !tele z DXF (ten sam parser co PZT)
    try:
        from . import pzt as _pzt
    except ImportError:
        import pzt as _pzt
    we = _pzt.wczytaj(dxf_path)
    oznaczenia = {_pzt._norm_nr(nr): nr for nr, _ in we.stacje}

    # indeks słupów WT w siatce ~tol do szybkiego szukania najbliższego
    from collections import defaultdict
    siatka = defaultdict(list)
    bok = max(tol, 1.0)
    for s in slupy_wt:
        siatka[(round(s.x / bok), round(s.y / bok))].append(s)

    def najblizszy_slup(pt):
        gx, gy = round(pt[0] / bok), round(pt[1] / bok)
        best, bd = None, tol
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for s in siatka.get((gx + dx, gy + dy), ()):
                    d = math.hypot(s.x - pt[0], s.y - pt[1])
                    if d <= bd:
                        best, bd = s, d
        return best

    # poligony per stacja (po numerze z nazwy warstwy !trafo_<nr> albo z opisu STACJA TRAFO)
    ostrzezenia = []
    poligony_stacji = defaultdict(list)
    for nazwa_warstwy, pts, _uchwyt in we.poligony:
        nr = _pzt._norm_nr(nazwa_warstwy) if nazwa_warstwy else None
        if not nr:
            nr = _pzt._numer_poligonu(pts, we.stacje, oznaczenia, ostrzezenia)
            nr = _pzt._norm_nr(nr) if nr else None
        if nr:
            poligony_stacji[nr].append(pts)

    wynik = {}
    for nr, polys in poligony_stacji.items():
        liczby = {}
        trafien = 0
        for poly in polys:
            for pts in we.trasy:
                for wx, wy in pts:                       # WIERZCHOŁKI !tele
                    if not _pzt.w_poligonie((wx, wy), poly):
                        continue
                    s = najblizszy_slup((wx, wy))
                    if s is not None:
                        liczby[s.miejscowosc] = liczby.get(s.miejscowosc, 0) + 1
                        trafien += 1
        if liczby:
            wynik[nr] = [m for m, _c in sorted(liczby.items(), key=lambda kv: (-kv[1], kv[0]))]
        else:
            ozn = oznaczenia.get(nr, nr)
            ostrzezenia.append(
                f"Stacja {ozn}: NIE dopasowano żadnego słupa z WT do wierzchołków !tele w jej zasięgu "
                f"(tolerancja {tol:.0f} m) - sprawdź układ współrzędnych w WT i zasięg !trafo.")
    return wynik, ostrzezenia
