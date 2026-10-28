#!/usr/bin/env python3
"""
czytaj_dxf - odczyt rysunku DXF do modelu na potrzeby AUTOMATYCZNEJ numeracji słupów.

Logika odczytu (parser DXF ASCII, rozpoznawanie słupów/stacji/zakresów/obwodów oraz
budowa grafu "ciągu logicznego" !tele) jest WZIĘTA z generatora zestawień
`generator/zestawienie.py` (repo przewieszenia, branch program-polaczony), aby program
numerujący był spójny z istniejącym zestawieniem - te same tolerancje i te same reguły
przynależności słupów do stacji trafo.

RÓŻNICA względem zestawienia: tam numery słupów są odczytywane z rysunku i służą do
podziału na obwody. TUTAJ projektant podaje tylko słup "1" i "2" każdego obwodu
(ręczne TEXT-y na warstwie numerów), a program resztę numeruje sam. Dlatego ten moduł
dodatkowo wyłapuje:
  * starty obwodów = groty opisów "obw. nr X" (pierwsze przęsło),
  * markery "1" i "2" = ręczne numery przy słupie startowym i następnym (kierunek
    magistrali "na wprost").

Zależności: tylko biblioteka standardowa (re, math, collections).
"""
import collections
import math
import re

# ---------------------------------------------------------------- ustawienia (jak w zestawieniu)
WARSTWA_ZAKRESOW = '!trafo'      # zamknięte polilinie = zakres stacji
WARSTWA_SIECI = '!tele'          # polilinie = ciąg logiczny sieci (łączą słupy w gałęzie/obwody)
TOL_SIEC = 8.0                   # [m] maks. odległość wierzchołka polilinii sieci od słupa
TOL_WYMIAR = 3.0                 # [m] maks. odległość końca wymiaru od słupa
TOL_NUMER = 15.0                 # [m] maks. odległość numeru od słupa
TOL_DUPLIKAT = 1.0               # [m] opisy słupów bliżej niż to = ten sam słup
TOL_STACJA = 150.0               # [m] słup nr 1 poza zakresem -> najbliższa stacja
TOL_MUFA = 5.0                   # [m] maks. odległość bloku mufy od słupa
DOMYSLNE_OZNACZENIE = 'P'

RE_SLUP = re.compile(r's[łl]up\s*nN(?:\s*/\s*\w+)?\s*\n\s*([A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ]*)\s*(-.+?)\s*$', re.I | re.S)
RE_STACJA = re.compile(r'STACJA\s+TRAFO\s*\n\s*(\S+)', re.I)
RE_OBWOD = re.compile(r'obw\.?\s*nr\s*(\d+)', re.I)
RE_NUMER = re.compile(r'^\d+(\.\d+)*$')


# ================================================================ parser DXF ASCII
def _kodowanie(raw):
    head = raw[:20000].decode('latin-1')
    m = re.search(r'\$ACADVER\s*\r?\n\s*1\s*\r?\n\s*AC(\d+)', head)
    if m and int(m.group(1)) >= 1021:
        return 'utf-8'
    m = re.search(r'\$DWGCODEPAGE\s*\r?\n\s*3\s*\r?\n\s*ANSI_(\d+)', head)
    return 'cp' + m.group(1) if m else 'cp1250'


def czytaj_grupy(sciezka):
    raw = open(sciezka, 'rb').read()
    if raw.startswith(b'AutoCAD Binary DXF'):
        raise ValueError('Binarny DXF nie jest obsługiwany - zapisz rysunek jako DXF ASCII.')
    linie = raw.decode(_kodowanie(raw), errors='replace').splitlines()
    for i in range(0, len(linie) - 1, 2):
        try:
            kod = int(linie[i].strip())
        except ValueError:
            continue
        yield kod, linie[i + 1].strip()


def encje(sciezka):
    """Zwraca (encje, bloki):
    encje - lista (typ, [(kod, wartość), ...]) z sekcji ENTITIES,
    bloki - słownik nazwa_bloku -> lista encji w definicji bloku."""
    wynik, bloki, sekcja, biez = [], {}, None, None
    blok, naglowek_bloku = None, None
    poprz_section = False
    for kod, wart in czytaj_grupy(sciezka):
        if kod == 0:
            if biez is not None:
                (wynik if sekcja == 'ENTITIES' else bloki.setdefault(blok, [])).append(biez)
                biez = None
            naglowek_bloku = None
            if wart == 'SECTION':
                poprz_section = True
                continue
            if wart == 'ENDSEC':
                sekcja = None
            elif sekcja == 'ENTITIES':
                biez = (wart, [])
            elif sekcja == 'BLOCKS':
                if wart == 'BLOCK':
                    naglowek_bloku = True
                elif wart == 'ENDBLK':
                    blok = None
                elif blok is not None:
                    biez = (wart, [])
        elif kod == 2 and poprz_section:
            sekcja = wart
        elif naglowek_bloku and kod == 2:
            blok = wart
            bloki.setdefault(blok, [])
        elif biez is not None:
            biez[1].append((kod, wart))
        poprz_section = False
    if biez is not None and sekcja == 'ENTITIES':
        wynik.append(biez)
    return wynik, bloki


def fl(d, k, dom=0.0):
    try:
        return float(d[k])
    except (KeyError, ValueError):
        return dom


def opis_multileadera(g):
    """(tekst, grot) z encji MULTILEADER. Grot = pierwszy punkt linii leadera."""
    d = dict(g)
    txt = next((v for k, v in g if k == 304 and not v.endswith('{')), None)
    p = None
    for n, (k, v) in enumerate(g):
        if k == 304 and v == 'LEADER_LINE{':
            try:
                p = (float(g[n + 1][1]), float(g[n + 2][1]))
            except (IndexError, ValueError):
                pass
            break
    if p is None:
        p = (fl(d, 10), fl(d, 20))
    return txt, p


def czysc_mtext(s):
    s = re.sub(r'\\U\+([0-9A-Fa-f]{4})', lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace('\\P', '\n').replace('\\~', ' ')
    s = re.sub(r'\\[ACcFfHhQqTWp][^;\\]*;', '', s)
    s = re.sub(r'\\[LlOoKkNn]', '', s)
    s = s.replace('{', '').replace('}', '')
    return s.strip()


# ================================================================ model rysunku
class Rysunek:
    """Model wczytanego rysunku: słupy, stacje, zakresy, numery, opisy obwodów,
    graf !tele. Konstruktor tylko wczytuje encje DXF; interpretacja (słupy/stacje)
    jest w `zbuduj_model`."""

    def __init__(self, sciezka):
        self.sciezka = sciezka
        self.opisy = []          # (tekst, punkt) - opisy słupów/stacji/obwodów
        self.teksty = []         # (tekst, punkt) - numery (RE_NUMER), w praktyce warstwa _numery
        self.wymiary = []        # (dlugosc, p1, p2, nadpis, text_midpoint|None)
        self.zakresy = []        # [punkty] - polilinie !trafo
        self.nazwy_zakresow = [] # numer stacji z nazwy warstwy (!trafo_05-0181 -> 05-0181) lub None
        self.mufy = []           # punkty wstawienia bloków mufy
        self.sieci = []          # [punkty] - polilinie !tele (ciąg logiczny)
        self.uwagi = []
        self._wczytaj()

    def _wczytaj(self):
        lista, bloki = encje(self.sciezka)
        bloki_slupy, bloki_mufy = {}, set()
        for nazwa, ents in bloki.items():
            if nazwa is None or nazwa.startswith('*'):
                continue
            for typ, g in ents:
                if typ == 'MULTILEADER':
                    txt, p = opis_multileadera(g)
                elif typ in ('MTEXT', 'TEXT'):
                    d = dict(g)
                    txt, p = ''.join(v for k, v in g if k == 3) + d.get(1, ''), (fl(d, 10), fl(d, 20))
                else:
                    continue
                if txt and RE_SLUP.search(czysc_mtext(txt)):
                    bloki_slupy[nazwa] = (czysc_mtext(txt), p)
                    break
            warstwy = {dict(g).get(8, '') for _, g in ents}
            if 'muf' in nazwa.lower() or (warstwy and all('muf' in w.lower() for w in warstwy)):
                bloki_mufy.add(nazwa)

        for typ, g in lista:
            d = dict(g)
            warstwa = d.get(8, '')
            if typ == 'INSERT':
                nazwa = d.get(2, '')
                ip = (fl(d, 10), fl(d, 20))
                if nazwa in bloki_mufy or 'muf' in warstwa.lower():
                    self.mufy.append(ip)
                elif nazwa in bloki_slupy:
                    txt, (bx, by) = bloki_slupy[nazwa]
                    sx, sy = fl(d, 41, 1.0), fl(d, 42, 1.0)
                    a = math.radians(fl(d, 50))
                    x, y = bx * sx, by * sy
                    p = (ip[0] + x * math.cos(a) - y * math.sin(a),
                         ip[1] + x * math.sin(a) + y * math.cos(a))
                    self.opisy.append((txt, p))
            elif typ == 'MULTILEADER':
                txt, p = opis_multileadera(g)
                if txt is None:
                    continue
                self.opisy.append((czysc_mtext(txt), p))
            elif typ in ('TEXT', 'MTEXT'):
                txt = ''.join(v for k, v in g if k == 3) + d.get(1, '')
                txt = czysc_mtext(txt)
                p = (fl(d, 10), fl(d, 20))
                if RE_NUMER.match(txt):
                    self.teksty.append((txt, p))
                elif RE_SLUP.search(txt) or RE_STACJA.search(txt) or RE_OBWOD.search(txt):
                    self.opisy.append((txt, p))
            elif typ == 'DIMENSION':
                if 13 in d and 14 in d:
                    p1, p2 = (fl(d, 13), fl(d, 23)), (fl(d, 14), fl(d, 24))
                    L = fl(d, 42, math.dist(p1, p2))
                    nadpis = None
                    t = czysc_mtext(d.get(1, ''))
                    if t and '<>' not in t:
                        m = re.search(r'\d+(?:[.,]\d+)?', t)
                        if m:
                            nadpis = float(m.group(0).replace(',', '.'))
                    # text_midpoint (kod 11/21) - pozycja tekstu wymiaru; po tej stronie
                    # linii !tele ma znaleźć się numer słupa
                    mid = (fl(d, 11), fl(d, 21)) if 11 in d and 21 in d else None
                    self.wymiary.append((L, p1, p2, nadpis, mid))
            elif typ == 'LWPOLYLINE' and warstwa.lower().startswith(WARSTWA_ZAKRESOW.lower()):
                xs = [float(v) for k, v in g if k == 10]
                ys = [float(v) for k, v in g if k == 20]
                if len(xs) >= 3:
                    self.zakresy.append(list(zip(xs, ys)))
                    reszta = warstwa[len(WARSTWA_ZAKRESOW):].strip(' _-')
                    self.nazwy_zakresow.append(reszta or None)
            elif typ == 'LWPOLYLINE' and warstwa.lower() == WARSTWA_SIECI.lower():
                xs = [float(v) for k, v in g if k == 10]
                ys = [float(v) for k, v in g if k == 20]
                if len(xs) >= 2:
                    self.sieci.append(list(zip(xs, ys)))


# ================================================================ geometria
def w_wielokacie(pt, poly):
    x, y = pt
    w = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            w = not w
    return w


def graf_sieci(sieci, slupy, num):
    """Graf sąsiedztwa słupów z polilinii warstwy !tele (ciąg logiczny sieci).
    Kolejne wierzchołki polilinii pokrywające się ze słupami tworzą krawędź słup-słup."""
    sas = collections.defaultdict(set)
    if not num:
        return sas

    def slup_przy(pt):
        d, j = min((math.dist(pt, slupy[i]['p']), i) for i in num)
        return j if d <= TOL_SIEC else None

    for pts in sieci:
        seq = []
        for pt in pts:
            j = slup_przy(pt)
            if j is not None and (not seq or seq[-1] != j):
                seq.append(j)
        for a, b in zip(seq, seq[1:]):
            if a != b:
                sas[a].add(b)
                sas[b].add(a)
    return sas


def graf_wymiarow(wymiary, slupy, num):
    """Graf sąsiedztwa z wymiarów (DIMENSION) - uzupełnia luki w sieci !tele."""
    sas = collections.defaultdict(set)
    for L, a, b, _nadpis, _mid in wymiary:
        if not num:
            break
        da, ja = min((math.dist(a, slupy[j]['p']), j) for j in num)
        db, jb = min((math.dist(b, slupy[j]['p']), j) for j in num)
        if da > TOL_WYMIAR or db > TOL_WYMIAR or ja == jb:
            continue
        sas[ja].add(jb)
        sas[jb].add(ja)
    return sas
