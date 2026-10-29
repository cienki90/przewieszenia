#!/usr/bin/env python3
"""Arkusze PZT - automatyczne arkusze A3 1:1000 dla zakresów stacji trafo.

Odpowiednik programu AutoLISP PZT_ARKUSZE, przeniesiony na Pythona (bez CAD-a).
Z jednego pliku DXF:

  * trasa      - polilinie na warstwie !tele,
  * zakresy    - zamknięte polilinie (poligony) na warstwie !trafo (zasięg stacji),
  * stacje     - multileadery "STACJA TRAFO <nr>" na warstwie _mm trafo,
  * wzorzec    - layout papieru o nazwie "a" (ramka A3, tabelka, legenda, rzutnia 1:1000),

tworzy dla każdej stacji komplet arkuszy pokrywających całą jej trasę przy minimalnej
liczbie arkuszy (ten sam algorytm rozmieszczania co generator_wt/arkusze.py). Wynik to
kopia pliku wejściowego z dopisanymi layoutami (model i reszta pliku bez zmian).

Algorytm rozmieszczania (osie N-S, bez obrotu):
  1. trasa stacji próbkowana co ``GESTOSC`` m,
  2. obszar użytkowy arkusza = ramka minus margines, minus róg z tabelką/legendą,
  3. zakładka wzdłuż trasy (domyślnie 50 m) - sąsiednie arkusze mają wspólny odcinek,
  4. kandydaci na siatce co ``KROK`` m, minimalna liczba arkuszy (zachłannie + dokładne
     dopracowanie), potem centrowanie odcinka trasy na arkuszu i kolejność wzdłuż trasy.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

try:
    from .dxfio import get, getf, mtext_plain, read_tags, split_entities, split_sections
except ImportError:  # bezpośrednie uruchomienie: python generator/pzt.py
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from dxfio import get, getf, mtext_plain, read_tags, split_entities, split_sections

# ------------------------------------------------------------------ ustawienia
WARSTWA_ZAKRES = "!trafo"           # poligony zasięgu stacji
WARSTWA_TRASA = "!tele"             # trasa (wzorzec dopasowania wielu warstw: !tele*)
WARSTWA_STACJA = "_mm trafo"        # multileadery "STACJA TRAFO <nr>"
WARSTWA_RAMEK = "Defpoints"         # obrysy arkuszy w modelu
KOLOR_RAMEK = 4
NAZWA_WZORCA = "a"                  # layout-wzorzec w pliku
BLOKI_TABELKI = ("tabelka", "legenda")   # bloki tabelki/legendy w layoucie (strefa "zakazana")
PREFIKS_RYS = "2."                  # numer rysunku = 2.n

ZAKLAD = 50.0                       # wspólny odcinek trasy sąsiednich arkuszy [m]
MARGINES_MM = 10.0                  # odstęp trasy od ramki i tabelki [mm papieru = m terenu w 1:1000]
GESTOSC = 5.0                       # próbkowanie trasy [m]
KROK = 15.0                         # siatka kandydatów na arkusze [m]
BB_LIMIT = 20000                    # limit dokładnego przeszukiwania

RE_STACJA = re.compile(r"(\d{2,3}-\d{3,4}|\d{3,4})")   # "03-0494" lub "0494"/"494"
RE_NAZWA_PZT = re.compile(r"^\d+-\d+$")                # nazwa layoutu PZT, np. "244-1" / "2-3"


# ============================================================ geometria (stdlib)
def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dlugosc(pts):
    return sum(_dist(p, q) for p, q in zip(pts, pts[1:]))


def _interp(pts, dlugosci, skum, t):
    """Punkt na łamanej `pts` w odległości `t` wzdłuż trasy (skum = skumulowane długości)."""
    if t <= 0:
        return pts[0]
    if t >= skum[-1]:
        return pts[-1]
    for i in range(1, len(skum)):
        if skum[i] >= t:
            d = skum[i] - skum[i - 1]
            u = 0.0 if d == 0 else (t - skum[i - 1]) / d
            (x1, y1), (x2, y2) = pts[i - 1], pts[i]
            return (x1 + u * (x2 - x1), y1 + u * (y2 - y1))
    return pts[-1]


def w_poligonie(pt, poly):
    """Czy punkt leży w (zamkniętym) poligonie - metoda promienia."""
    x, y = pt
    wew = False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xprzec = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xprzec:
                wew = not wew
    return wew


def _odc_x_poligon(p, a, b):
    """Odległość punktu p od odcinka ab."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return _dist(p, (ax + t * dx, ay + t * dy))


def dist_pt_poligon(pt, poly):
    return min(_odc_x_poligon(pt, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def _przeciecie(a, b, c, d):
    """Punkt przecięcia odcinków ab i cd albo None."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


# ============================================================ rozmieszczanie arkuszy
@dataclass
class Arkusz:
    x0: float               # lewy dolny narożnik okna arkusza w modelu
    y0: float
    szer: float             # szerokość okna [m terenu]
    wys: float
    stacja: str = ""        # oznaczenie stacji (np. "03-0494")
    nr_stacji: str = ""     # znormalizowany numer stacji (np. "494") - do warstw/zamrażania
    nazwa: str = ""         # nazwa layoutu, np. "494-1"
    nr_rys: str = ""        # numer rysunku, np. "2.1"
    miejscowosci: list = field(default_factory=list)

    @property
    def srodek(self):
        return (self.x0 + self.szer / 2, self.y0 + self.wys / 2)


def _probkuj(linie, gestosc):
    """Zwraca listę próbek trasy: (x, y, nr_lancucha, kilometraz_w_lancuchu)."""
    P = []
    for i, pts in enumerate(linie):
        skum = [0.0]
        for a, b in zip(pts, pts[1:]):
            skum.append(skum[-1] + _dist(a, b))
        dl = skum[-1]
        n = max(2, int(math.ceil(dl / gestosc)) + 1)
        for k in range(n):
            t = dl * k / (n - 1)
            x, y = _interp(pts, None, skum, t)
            P.append((x, y, i, t))
    return P


def _w_uzyt(px, py, W, H, m, zx0, zy1):
    """Czy punkt (względem narożnika arkusza) leży w obszarze użytkowym:
    ramka pomniejszona o margines m, bez prawego dolnego rogu (tabelka/legenda)."""
    return (m < px < W - m and m < py < H - m and not (px > zx0 and py < zy1))


def _pokrycie(x0, y0, P, W, H, m, zx0, zy1, zaklad):
    """Maska: które próbki trasy pokrywa arkusz o narożniku (x0,y0).

    Próbka jest pokryta, gdy leży w obszarze użytkowym i jest dalej niż `zaklad`
    (wzdłuż trasy) od miejsca, w którym trasa wychodzi z arkusza - dzięki temu
    sąsiednie arkusze mają wspólny odcinek trasy ~zaklad."""
    wew = [_w_uzyt(x - x0, y - y0, W, H, m, zx0, zy1) for (x, y, _c, _t) in P]
    if zaklad <= 0 or not any(wew):
        return wew
    wyn = list(wew)
    for k in range(len(P) - 1):
        if wew[k] != wew[k + 1] and P[k][2] == P[k + 1][2]:   # ten sam łańcuch, zmiana strony granicy
            tg = (P[k][3] + P[k + 1][3]) / 2
            ch = P[k][2]
            for j, (_x, _y, c, t) in enumerate(P):
                if c == ch and abs(t - tg) < zaklad:
                    wyn[j] = False
    return wyn


def _wybierz_zachlannie(maski, n_prob):
    """Pokrycie zbioru zachłannie + usunięcie zbędnych arkuszy (minimalizacja liczby)."""
    pokryte = [False] * n_prob
    wybrane = []
    while not all(pokryte):
        najlepszy, zysk_najl = -1, 0
        for j, m in enumerate(maski):
            if j in wybrane:
                continue
            zysk = sum(1 for i in range(n_prob) if m[i] and not pokryte[i])
            if zysk > zysk_najl:
                najlepszy, zysk_najl = j, zysk
        if najlepszy < 0:
            break
        wybrane.append(najlepszy)
        for i in range(n_prob):
            if maski[najlepszy][i]:
                pokryte[i] = True
    # usuń arkusze zbędne (gdy reszta i tak pokrywa wszystko)
    zmiana = True
    while zmiana and len(wybrane) > 1:
        zmiana = False
        for j in sorted(wybrane, key=lambda j: sum(maski[j])):
            inne = [k for k in wybrane if k != j]
            if all(any(maski[k][i] for k in inne) for i in range(n_prob)):
                wybrane = inne
                zmiana = True
                break
    return wybrane


def _rozmiesc_skupisko(linie, W, H, zakazane, m, zaklad, krok, gestosc):
    """Lewe dolne narożniki arkuszy pokrywających `linie` (odpowiednik _rozmiesc_skupisko z WT)."""
    zx0 = zakazane[0] - m
    zy1 = zakazane[3] + m
    sx = (m + (W - m)) / 2 - ((W - zx0) if False else 0)   # środek obszaru użytkowego (przybliżony)
    # środek obszaru użytkowego: prostokąt [m, W-m]x[m, H-m] bez rogu -> użyj środka ramki
    sx = W / 2
    sy = H / 2
    P = _probkuj(linie, gestosc)
    if not P:
        return []
    xs = [p[0] for p in P]
    ys = [p[1] for p in P]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)

    # --- 1. kandydaci na siatce
    XY, maski = [], []
    x0 = xmin - W + m
    while x0 <= xmax - m + krok:
        y0 = ymin - H + m
        while y0 <= ymax - m + krok:
            msk = _pokrycie(x0, y0, P, W, H, m, zx0, zy1, zaklad)
            if any(msk):
                XY.append((x0, y0))
                maski.append(msk)
            y0 += krok
        x0 += krok

    n = len(P)
    # próbki, których nie da się pokryć z zakładem - dodaj arkusz wyśrodkowany na próbce (bez zakładu)
    pokryte_kand = [any(maski[j][i] for j in range(len(maski))) for i in range(n)]
    for i in range(n):
        if not pokryte_kand[i]:
            x0, y0 = P[i][0] - sx, P[i][1] - sy
            msk = [_w_uzyt(x - x0, y - y0, W, H, m, zx0, zy1) for (x, y, _c, _t) in P]
            msk[i] = True
            XY.append((x0, y0))
            maski.append(msk)
            for k in range(n):
                if msk[k]:
                    pokryte_kand[k] = True

    # kandydaci o identycznym pokryciu są równoważni - zostaw po jednym
    uniq = {}
    for j, msk in enumerate(maski):
        uniq.setdefault(tuple(msk), j)
    idx = sorted(uniq.values())
    XY = [XY[j] for j in idx]
    maski = [maski[j] for j in idx]

    # --- 2. wybór arkuszy (minimalna liczba)
    wybrane = _wybierz_zachlannie(maski, n)
    ark = [XY[j] for j in wybrane]
    pk = [maski[j] for j in wybrane]

    # --- 3. centrowanie (2 przebiegi): środek odcinka trasy arkusza -> środek obszaru użytkowego
    for _ in range(2):
        # właściciel próbki = arkusz, w którym leży najgłębiej (najdalej od krawędzi użytkowej)
        wlasc = [-1] * n
        gleb = [-1.0] * n
        for a, ((x0, y0), msk) in enumerate(zip(ark, pk)):
            for i in range(n):
                if not msk[i]:
                    continue
                px, py = P[i][0] - x0, P[i][1] - y0
                g = min(px - m, (W - m) - px, py - m, (H - m) - py)   # odległość od krawędzi ramki
                if g > gleb[i]:
                    gleb[i] = g
                    wlasc[i] = a
        for a in range(len(ark)):
            moje = [i for i in range(n) if wlasc[i] == a]
            if not moje:
                continue
            cx = (min(P[i][0] for i in moje) + max(P[i][0] for i in moje)) / 2
            cy = (min(P[i][1] for i in moje) + max(P[i][1] for i in moje)) / 2
            celx, cely = cx - sx, cy - sy
            x0, y0 = ark[a]
            kc = max(5.0, W / 80)
            dy = -H / 2
            kandydaci = []
            while dy <= H / 2 + 1e-9:
                dx = -W / 2
                while dx <= W / 2 + 1e-9:
                    nx, ny = x0 + dx, y0 + dy
                    if all(_w_uzyt(P[i][0] - nx, P[i][1] - ny, W, H, m, zx0, zy1) for i in moje):
                        kandydaci.append((nx, ny))
                    dx += kc
                dy += kc
            kandydaci.sort(key=lambda nxy: math.hypot(nxy[0] - celx, nxy[1] - cely))
            for nx, ny in kandydaci[:60]:
                r = _pokrycie(nx, ny, P, W, H, m, zx0, zy1, zaklad)
                if all(r[i] for i in moje):
                    ark[a], pk[a] = (nx, ny), r
                    break

    # --- 4. kolejność wzdłuż trasy (wg pierwszej pokrytej próbki)
    def pierwsza(msk):
        for i in range(n):
            if msk[i]:
                return i
        return 0
    kolej = sorted(range(len(ark)), key=lambda a: pierwsza(pk[a]))
    return [ark[a] for a in kolej]


def rozmiesc(linie, W, H, zakazane, m=MARGINES_MM, zaklad=ZAKLAD, krok=KROK, gestosc=GESTOSC):
    """Dzieli trasę na skupiska (dalej niż przekątna arkusza od siebie) i rozmieszcza osobno."""
    if not linie:
        return []
    r = math.hypot(W, H) / 2

    def blisko(a_pts, b_pts):
        # szybki test: czy jakiś punkt a jest w promieniu 'r' od jakiegokolwiek odcinka b (lub odwrotnie)
        for p in a_pts:
            if dist_pt_poligon(p, b_pts) <= 2 * r:
                return True
        return False

    grupy = []
    for i, pts in enumerate(linie):
        laczy = [g for g in grupy if any(blisko(pts, linie[j]) for j in g)]
        nowa = sorted(set([i] + [j for g in laczy for j in g]))
        grupy = [g for g in grupy if g not in laczy] + [nowa]
    grupy.sort(key=min)
    wynik = []
    for g in grupy:
        for (x0, y0) in _rozmiesc_skupisko([linie[j] for j in g], W, H, zakazane, m, zaklad, krok, gestosc):
            wynik.append((x0, y0))
    return wynik


# ============================================================ odczyt DXF
def _mleader_tekst_grot(d):
    """(tekst, grot) z MULTILEADER: pierwszy wierzchołek LEADER_LINE jako grot."""
    txt = mtext_plain(get(d, 304, "") or "")
    grot = None
    for i, (k, v) in enumerate(d):
        if k == 304 and v == "LEADER_LINE{":
            try:
                grot = (float(d[i + 1][1]), float(d[i + 2][1]))
            except (IndexError, ValueError):
                pass
            break
    if grot is None:
        grot = (getf(d, 10, 0.0), getf(d, 20, 0.0))
    return txt, grot


def _lwpoly_punkty(d):
    xs = [float(v) for k, v in d if k == 10]
    ys = [float(v) for k, v in d if k == 20]
    return list(zip(xs, ys)), (int(get(d, 70, "0")) & 1)   # (punkty, zamknięta?)


def _dopasuj(nazwa_warstwy, wzor):
    """Czy warstwa pasuje do wzorca (wzor = 'tele' -> !tele, !tele*, _tele itp.)."""
    n = (nazwa_warstwy or "").lower()
    return wzor.lower() in n


@dataclass
class Wejscie:
    trasy: list                       # [[(x,y), ...], ...] polilinie !tele
    poligony: list                    # [(numer_stacji|None, [punkty]), ...] zakresy !trafo
    stacje: list                      # [(numer, (x,y)), ...] z multileaderów STACJA TRAFO
    wzor_okno: tuple                  # (W, H) rozmiar okna arkusza [m] z rzutni wzorca
    wzor_zakazane: tuple              # (x0,y0,x1,y1) tabelka+legenda wzgl. lewego dolnego rogu rzutni


def wczytaj(sciezka, wzorzec_sciezka=None):
    """Czyta trasę, poligony i stacje z `sciezka`, a wzorzec (okno + strefa tabelki)
    z `wzorzec_sciezka` (gdy None - z tego samego pliku)."""
    secs = dict(split_sections(read_tags(sciezka)))
    ents = split_entities(secs.get("ENTITIES", []))

    trasy, poligony, stacje = [], [], []
    for t, d in ents:
        warstwa = get(d, 8, "")
        if t == "LWPOLYLINE" and _dopasuj(warstwa, WARSTWA_TRASA):
            pts, _zamkn = _lwpoly_punkty(d)
            if len(pts) >= 2:
                trasy.append(pts)
        elif t == "LWPOLYLINE" and warstwa.lower().startswith(WARSTWA_ZAKRES.lower()):
            pts, _zamkn = _lwpoly_punkty(d)
            if len(pts) >= 3:
                # numer stacji z nazwy warstwy "!trafo_<nr>" (z poprzedniego uruchomienia) - opcjonalnie
                reszta = warstwa[len(WARSTWA_ZAKRES):].strip(" _-")
                poligony.append([reszta or None, pts, get(d, 5)])   # [nr|None, punkty, uchwyt]
        elif t == "MULTILEADER" and _dopasuj(warstwa, "trafo"):
            txt, grot = _mleader_tekst_grot(d)
            if "STACJA" in txt.upper():
                m = RE_STACJA.search(txt)
                if m:
                    # zachowaj PEŁNE oznaczenie (np. '05-0244') - potrzebne do tabelki
                    stacje.append((m.group(1).strip(), grot))

    W, H, zak = _wczytaj_wzorzec(sciezka if wzorzec_sciezka is None else wzorzec_sciezka)
    return Wejscie(trasy, poligony, stacje, (W, H), zak)


def _norm_nr(s):
    """'03-0494'/'0494'/'494' -> '494' (do porównań i nazw)."""
    s = str(s or "").strip()
    tok = re.split(r"[-/ ]", s)[-1]
    cyfry = re.sub(r"\D", "", tok)
    return str(int(cyfry)) if cyfry else s


def oznaczenie_stacji(numer, stacje_oznaczenia):
    """Pełne oznaczenie stacji (np. '03-0494') dla znormalizowanego numeru, gdy znane."""
    return stacje_oznaczenia.get(_norm_nr(numer), numer)


def _wczytaj_wzorzec(sciezka):
    """Z layoutu-wzorca `a`: rozmiar okna rzutni modelu [m] i strefa tabelki/legendy.

    Zwraca (W, H, (zx0, zy0, zx1, zy1)) - strefa względem lewego dolnego rogu rzutni."""
    secs = dict(split_sections(read_tags(sciezka)))
    objsy = split_entities(secs.get("OBJECTS", []))
    bloki = split_entities(secs.get("BLOCKS", []))
    ents = split_entities(secs.get("ENTITIES", []))

    # layout "a" -> jego block record
    br_wzorca = None
    for t, d in objsy:
        if t == "LAYOUT":
            nazwy = [v for c, v in d if c == 1]
            if nazwy and nazwy[-1].strip().lower() == NAZWA_WZORCA.lower():
                br330 = [v for c, v in d if c == 330]
                br_wzorca = br330[-1] if br330 else None
                break
    if br_wzorca is None:
        raise ValueError(f"W pliku nie ma layoutu-wzorca „{NAZWA_WZORCA}”. "
                         "Przygotuj arkusz-wzorzec PZT (ramka A3, tabelka, legenda, rzutnia 1:1000).")

    # encje tego layoutu: w BLOCKS (owner == br_wzorca) albo w ENTITIES (aktywny arkusz)
    encje_layoutu = [(t, d) for t, d in (bloki + ents)
                     if get(d, 330) == br_wzorca and t not in ("BLOCK", "ENDBLK")]
    rzutnie = [d for t, d in encje_layoutu if t == "VIEWPORT" and (get(d, 69) or "").strip() != "1"]
    if not rzutnie:
        raise ValueError(f"Layout-wzorzec „{NAZWA_WZORCA}” nie ma rzutni modelu.")
    vp = max(rzutnie, key=lambda d: getf(d, 40, 0) * getf(d, 41, 0))
    H = getf(vp, 45) or getf(vp, 41)                     # wysokość widoku [m]
    W = H * getf(vp, 40, 1.0) / getf(vp, 41, 1.0)        # szerokość widoku [m]

    # Strefa "zakazana" (tabelka + legenda) = prawy dolny róg arkusza. Bierzemy TYLKO bloki
    # tabelki/legendy (INSERT o nazwach z BLOKI_TABELKI) i wyznaczamy prostokąt od ich lewej
    # krawędzi do prawego dolnego rogu rzutni. Współrzędne papieru rzutni są 1:1 do metrów okna
    # (A3: viewport mm == metry terenu w 1:1000), więc wystarczy przeliczyć względem narożnika.
    pw, ph = getf(vp, 40, W), getf(vp, 41, H)
    pcx, pcy = getf(vp, 10, W / 2), getf(vp, 20, H / 2)        # środek rzutni na papierze
    px0, py0 = pcx - pw / 2, pcy - ph / 2                       # lewy dolny róg rzutni (papier)
    sx = W / pw if pw else 1.0
    sy = H / ph if ph else 1.0

    def pap_do_model(x, y):
        return ((x - px0) * sx, (y - py0) * sy)

    nazwy_tab = {s.strip().lower() for s in BLOKI_TABELKI}
    tab_pts = []
    for t, d in encje_layoutu:
        if t == "INSERT" and (get(d, 2) or "").strip().lower() in nazwy_tab:
            tab_pts.append((getf(d, 10, 0.0), getf(d, 20, 0.0)))
    if tab_pts:
        # lewa krawędź najdalej wysuniętego w lewo bloku tabelki/legendy -> prawy dolny róg
        lewa = min(x for x, _ in tab_pts)
        mx0, _my0 = pap_do_model(lewa, py0)
        mx1, my1 = pap_do_model(px0 + pw, py0 + 0.0)
        # wysokość strefy: ~1/4 arkusza (tabelka+legenda zwykle w dolnym pasie) lub do najwyższego bloku
        gora = max((y for _x, y in tab_pts), default=py0)
        _mg, zy1 = pap_do_model(lewa, max(gora, py0 + ph * 0.22))
        zak = (mx0, 0.0, W, zy1)
    else:
        zak = (W, 0.0, W, 0.0)   # brak tabelki -> brak strefy zakazanej
    return W, H, zak


def _punkty_encji(d):
    """Punkty do obwiedni encji layoutu (LWPOLYLINE / INSERT / TEXT / MTEXT)."""
    t_pts = []
    xs = [float(v) for k, v in d if k == 10]
    ys = [float(v) for k, v in d if k == 20]
    for x, y in zip(xs, ys):
        t_pts.append((x, y))
    return t_pts


# ============================================================ przęsła trasy w poligonie
def _trasa_w_poligonie(trasy, poly, gestosc=GESTOSC):
    """Fragmenty tras (!tele) leżące wewnątrz poligonu, jako lista łamanych.

    Odcinek trasy jest przycinany do granicy poligonu (po punktach próbkowania)."""
    frag = []
    for pts in trasy:
        biez = []
        # próbkuj gęsto i zbieraj spójne odcinki wewnątrz poligonu
        skum = [0.0]
        for a, b in zip(pts, pts[1:]):
            skum.append(skum[-1] + _dist(a, b))
        dl = skum[-1]
        if dl == 0:
            continue
        n = max(2, int(math.ceil(dl / gestosc)) + 1)
        for k in range(n):
            q = _interp(pts, None, skum, dl * k / (n - 1))
            if w_poligonie(q, poly):
                biez.append(q)
            else:
                if len(biez) >= 2:
                    frag.append(biez)
                biez = []
        if len(biez) >= 2:
            frag.append(biez)
    return frag


def _numer_poligonu(poly, stacje, oznaczenia, ostrzezenia):
    """Numer stacji dla poligonu: z nazwy warstwy, z opisu STACJA TRAFO w poligonie,
    a gdy brak - najbliższa stacja (z ostrzeżeniem)."""
    # 1) stacja, której grot leży w poligonie
    w_srodku = [(nr, p) for nr, p in stacje if w_poligonie(p, poly)]
    if len(w_srodku) == 1:
        return w_srodku[0][0]
    if len(w_srodku) > 1:
        ostrzezenia.append(f"W jednym poligonie !trafo leży kilka opisów STACJA TRAFO "
                           f"({', '.join(oznaczenia.get(nr, nr) for nr, _ in w_srodku)}) - "
                           f"przyjęto {oznaczenia.get(w_srodku[0][0], w_srodku[0][0])}.")
        return w_srodku[0][0]
    # 2) najbliższa stacja do poligonu
    if stacje:
        nr, dmin = None, None
        for n, p in stacje:
            d = dist_pt_poligon(p, poly)
            if dmin is None or d < dmin:
                nr, dmin = n, d
        ostrzezenia.append(f"Poligon !trafo bez opisu STACJA TRAFO w środku - przypisano "
                           f"najbliższą stację {oznaczenia.get(nr, nr)} ({dmin:.0f} m).")
        return nr
    return None


@dataclass
class DaneStacji:
    """Wszystko, co potrzebne do rozmieszczenia arkuszy jednej stacji (też dla podglądu)."""
    nr: str                 # znormalizowany numer, np. "565"
    oznaczenie: str         # pełne oznaczenie, np. "05-0565"
    poligony: list          # [[(x, y), ...], ...] zasięg stacji
    linie: list             # [[(x, y), ...], ...] trasa !tele w zasięgu


def dane_stacji(we: Wejscie, ostrzezenia=None):
    """Lista DaneStacji (w kolejności numerów) i {nr: [uchwyty poligonów]} - wspólne dla
    generowania arkuszy i podglądu ich układu."""
    ostrzezenia = [] if ostrzezenia is None else ostrzezenia
    oznaczenia = {_norm_nr(nr): nr for nr, _ in we.stacje}      # 494 -> 03-0494
    poligony = []
    poligony_stacji = {}          # nr -> [uchwyty poligonów tej stacji]
    for nazwa_warstwy, pts, uchwyt in we.poligony:
        nr = _norm_nr(nazwa_warstwy) if nazwa_warstwy else None
        if not nr:
            nr = _numer_poligonu(pts, we.stacje, oznaczenia, ostrzezenia)
            nr = _norm_nr(nr) if nr else None
        if nr:
            poligony.append((nr, pts))
            if uchwyt:
                poligony_stacji.setdefault(nr, []).append(uchwyt)
    wynik = []
    for nr in sorted({n for n, _ in poligony}, key=lambda s: (len(s), s)):
        polys = [pts for n, pts in poligony if n == nr]
        linie = []
        for poly in polys:
            linie += _trasa_w_poligonie(we.trasy, poly)
        wynik.append(DaneStacji(nr, oznaczenia.get(nr, nr), polys, linie))
    return wynik, poligony_stacji


# ============================================================ ręczny układ arkuszy (podgląd)
# Układ przesunięty ręcznie w oknie podglądu zapisywany jest obok planu jako
# „<plan> - arkusze PZT.json”: {"okno": [W, H], "stacje": {"565": [[x0, y0], ...]}}.
# Generowanie PZT używa go zamiast rozkładu automatycznego (tylko dla zapisanych stacji).
UKLAD_WERSJA = 1


def sciezka_ukladu(dxf: str) -> str:
    import os
    return os.path.splitext(os.path.abspath(dxf))[0] + " - arkusze PZT.json"


def wczytaj_uklad(sciezka: str, okno=None, log=print) -> dict:
    """{nr stacji: [(x0, y0), ...]} z pliku układu albo {} (brak pliku / inny rozmiar arkusza)."""
    import json
    try:
        with open(sciezka, encoding="utf-8") as f:
            dane = json.load(f)
    except (OSError, ValueError):
        return {}
    if okno and dane.get("okno") and any(abs(a - b) > 0.01 for a, b in zip(dane["okno"], okno)):
        log(f"Uwaga: zapisany układ arkuszy dotyczy innego rozmiaru arkusza {dane['okno']} - pominięto.")
        return {}
    return {str(nr): [tuple(map(float, p)) for p in pts] for nr, pts in (dane.get("stacje") or {}).items()}


def zapisz_uklad(sciezka: str, okno, stacje: dict) -> None:
    """Zapisuje ręczny układ arkuszy ({nr: [(x0, y0), ...]}); pusty słownik usuwa plik."""
    import json
    import os
    if not stacje:
        if os.path.exists(sciezka):
            os.remove(sciezka)
        return
    dane = {"wersja": UKLAD_WERSJA, "okno": [round(okno[0], 4), round(okno[1], 4)],
            "stacje": {nr: [[round(x, 3), round(y, 3)] for x, y in pts] for nr, pts in sorted(stacje.items())}}
    tmp = sciezka + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dane, f, ensure_ascii=False, indent=1)
    os.replace(tmp, sciezka)


def niepokryte(linie, narozniki, W, H, zakazane, m=MARGINES_MM, gestosc=GESTOSC):
    """Próbki trasy (x, y), które nie leżą w obszarze użytkowym żadnego arkusza
    (ramka minus margines, minus róg tabelki) - dziury po ręcznym przesunięciu."""
    zx0, zy1 = zakazane[0] - m, zakazane[3] + m
    return [(x, y) for x, y, _c, _t in _probkuj(linie, gestosc)
            if not any(_w_uzyt(x - x0, y - y0, W, H, m, zx0, zy1) for x0, y0 in narozniki)]


def zaplanuj(we: Wejscie, miejscowosci_stacji=None, tylko=None, zaklad=ZAKLAD, uklad=None, log=print):
    """Zwraca listę arkuszy (Arkusz) dla wszystkich stacji oraz listę ostrzeżeń.

    miejscowosci_stacji - {znormalizowany_nr_stacji: [miejscowości...]} do wpisania w tabelce
                          (po zasięgu stacji trafo); każdy arkusz danej stacji dostaje tę samą listę.
    tylko               - zbiór znormalizowanych numerów stacji do wygenerowania (None = wszystkie).
    uklad               - {nr: [(x0, y0), ...]} ręczny układ arkuszy (z okna podglądu) - zastępuje
                          rozkład automatyczny dla tych stacji."""
    ostrzezenia = []
    W, H = we.wzor_okno
    miejscowosci_stacji = miejscowosci_stacji or {}
    uklad = uklad or {}
    stacje, poligony_stacji = dane_stacji(we, ostrzezenia)

    arkusze = []
    for st in stacje:
        nr = st.nr
        if tylko and nr not in tylko:
            continue
        if not st.linie:
            ostrzezenia.append(f"Stacja {st.oznaczenie}: brak trasy !tele w zakresie - pominięto.")
            continue
        miejsc = list(miejscowosci_stacji.get(nr, []))
        if uklad.get(nr):
            narozniki = list(uklad[nr])
            luki = niepokryte(st.linie, narozniki, W, H, we.wzor_zakazane)
            zrodlo = " (układ ręczny)"
            if luki:
                ostrzezenia.append(f"Stacja {st.oznaczenie}: ręczny układ arkuszy nie pokrywa ok. "
                                   f"{len(luki) * GESTOSC:.0f} m trasy - sprawdź w podglądzie.")
        else:
            narozniki = rozmiesc(st.linie, W, H, we.wzor_zakazane, zaklad=zaklad)
            zrodlo = ""
        for i, (x0, y0) in enumerate(narozniki, 1):
            a = Arkusz(x0, y0, W, H, stacja=st.oznaczenie, nr_stacji=nr,
                       nazwa=f"{nr}-{i}", nr_rys=f"{PREFIKS_RYS}{i}")
            a.miejscowosci = miejsc
            arkusze.append(a)
        opis_m = (" - " + ", ".join(miejsc)) if miejsc else ""
        log(f"   stacja {st.oznaczenie:<10} arkuszy: {len(narozniki)}{zrodlo}{opis_m}")
    return arkusze, ostrzezenia, poligony_stacji


# ============================================================ zapis layoutów (nieniszczący)
def _max_handle(secs):
    mx = 0
    for nazwa, tags in secs.items():
        if nazwa == "HEADER":
            continue
        for c, v in tags:
            if c in (5, 105):
                try:
                    mx = max(mx, int(v, 16))
                except ValueError:
                    pass
    return mx


def _owner(d):
    """Właściciel (pierwszy kod 330 poza grupami 102 {...})."""
    depth = 0
    for c, v in d:
        if c == 102:
            depth += 1 if str(v).startswith("{") else -1
        elif c == 330 and depth == 0:
            return v
    return None


def _tekst_tabelki(encje_tagi, podmianki):
    """Zwraca kopię encji layoutu z podmienionymi polami tabelki.

    Podmiana prostą heurystyką: w MTEXT/TEXT, których treść pasuje do znacznika
    (np. '2.x', '03-xx', nazwa miejscowości wzorca), wstaw wartość docelową.
    `podmianki` = lista (wzorzec_regex, nowa_wartosc)."""
    out = []
    for t, d in encje_tagi:
        if t in ("MTEXT", "TEXT"):
            nd = []
            for c, v in d:
                if c in (1, 3):
                    for wzor, nowa in podmianki:
                        if wzor.search(v):
                            # nowa=None -> wzorzec sam wie, czym podmienić (np. miejscowość,
                            # z zachowaniem frazy/formatowania); inaczej zwykłe regex.sub
                            v = wzor.sub(v) if nowa is None else wzor.sub(nowa, v)
                nd.append((c, v))
            out.append((t, nd))
        else:
            out.append((t, d))
    return out


def zapisz_arkusze(wejscie_sciezka, wyjscie_sciezka, arkusze, wzorzec_sciezka=None,
                   poligony_stacji=None, log=print):
    """Dopisuje do kopii pliku wejściowego po jednym layoucie na każdy arkusz PZT.

    Model pozostaje praktycznie bez zmian - jedyną ingerencją jest przeniesienie poligonów
    zakresu stacji na warstwy „!trafo_<nr>” (po jednej na stację), żeby w rzutni każdego
    arkusza można było ZAMROZIĆ warstwy pozostałych stacji - wtedy na arkuszu danej stacji
    nie widać zasięgów innych stacji (jak w programie LISP). Gdy wzorzec jest w innym pliku,
    jego layout „a” jest importowany."""
    poligony_stacji = poligony_stacji or {}
    secs_list = split_sections(read_tags(wejscie_sciezka))
    secs = dict(secs_list)
    kolejnosc = [n for n, _ in secs_list]

    # regeneracja: usuń istniejące layouty PZT (gdy wejście już było wynikiem PZT) - bez tego
    # ponowne uruchomienie DUBLOWAŁO layouty o tych samych nazwach ('244-1' itd.)
    _usun_layouty_pzt(secs, log=log)

    # --- wzorzec: layout "a" + jego block record + encje papieru + rzutnia modelu ---
    zrodlo = secs if wzorzec_sciezka is None else dict(split_sections(read_tags(wzorzec_sciezka)))
    lay_wzor, br_wzor = _znajdz_wzorzec_layout(zrodlo)
    if lay_wzor is None:
        raise ValueError(f"Nie znaleziono layoutu-wzorca „{NAZWA_WZORCA}”.")
    encje_wzor = [(t, d) for t, d in (split_entities(zrodlo.get("BLOCKS", []))
                                      + split_entities(zrodlo.get("ENTITIES", [])))
                  if get(d, 330) == br_wzor and t not in ("BLOCK", "ENDBLK")]
    wlasc_dict = _owner(lay_wzor)   # słownik ACAD_LAYOUT (do rejestracji nowych layoutów)

    nast = _max_handle(secs) + 1

    def nh():
        nonlocal nast
        h = format(nast, "X")
        nast += 1
        return h

    # numeracja *Paper_SpaceN
    nr_ps = 0
    for t, d in split_entities(secs.get("TABLES", [])):
        nm = (get(d, 2) or "")
        if t == "BLOCK_RECORD" and nm.upper().startswith("*PAPER_SPACE") and nm[12:].isdigit():
            nr_ps = max(nr_ps, int(nm[12:]))

    nowe_br = []        # tagi BLOCK_RECORD do dodania do TABLES
    nowe_bloki = []     # tagi BLOCKS (BLOCK ... encje ... ENDBLK)
    nowe_layouty = []   # tagi LAYOUT do OBJECTS
    wpisy_slownika = [] # (nazwa, lay_h) do słownika ACAD_LAYOUT
    br_table = _handle_tabeli(secs, "BLOCK_RECORD")

    # tab order startuje po istniejących layoutach
    tab0 = _max_tab_order(secs) + 1

    # --- warstwy zakresów stacji "!trafo_<nr>" + przeniesienie poligonów + uchwyty do zamrażania ---
    # dla każdej stacji tworzymy (jeśli brak) warstwę !trafo_<nr>, przenosimy jej poligony na tę
    # warstwę i zapamiętujemy uchwyt rekordu warstwy (do kodu 341 w rzutniach).
    warstwa_stacji_handle = {}            # nr -> uchwyt rekordu warstwy
    uchwyt_poligonu_warstwa = {}          # uchwyt poligonu -> nazwa warstwy docelowej
    stacje_z_poligonami = sorted(poligony_stacji, key=_klucz_nr)
    if stacje_z_poligonami:
        props_trafo = _props_warstwy(secs, WARSTWA_ZAKRES)
        istnieje = {(_warstwa_nazwa(d) or "").lower(): get(d, 5)
                    for t, d in split_entities(secs.get("TABLES", [])) if t == "LAYER"}
        nowe_warstwy = []
        for nr in stacje_z_poligonami:
            lname = f"{WARSTWA_ZAKRES}_{_oznaczenie_dla_warstwy(nr, arkusze)}"
            klucz = lname.lower()
            if klucz in istnieje:
                warstwa_stacji_handle[nr] = istnieje[klucz]
            else:
                lh = nh()
                nowe_warstwy.append(_rekord_warstwy(lh, lname, props_trafo))
                istnieje[klucz] = lh
                warstwa_stacji_handle[nr] = lh
            for uchwyt in poligony_stacji[nr]:
                uchwyt_poligonu_warstwa[uchwyt] = lname
        if nowe_warstwy:
            secs["TABLES"] = _wstaw_warstwy(secs["TABLES"], nowe_warstwy)
        # przenieś poligony na warstwy stacji (zmiana kodu 8 w encjach modelu)
        secs["ENTITIES"] = _przenies_poligony(secs["ENTITIES"], uchwyt_poligonu_warstwa)

    for i, ark in enumerate(arkusze):
        br = nh()
        lay_h = nh()
        nr_ps += 1
        blok = f"*Paper_Space{nr_ps}"
        cx, cy = ark.srodek

        # encje papieru: nowe uchwyty, nowy właściciel (br), rzutnia -> okno arkusza
        enc_tagi, vp_glowna = [], None
        for t, d in encje_wzor:
            nd, skip = [], False
            h = nh()
            for c, v in d:
                if c == 102 and v in ("{ACAD_XDICTIONARY", "{ACAD_REACTORS"):
                    skip = True
                    continue
                if skip:
                    if c == 102 and v == "}":
                        skip = False
                    continue
                if c in (360, 361):
                    continue
                if c == 5:
                    v = h
                elif c == 330:
                    v = br
                nd.append((c, v))
            if t == "VIEWPORT" and (get(d, 69) or "").strip() != "1":
                nd = _ustaw_rzutnie(nd, cx, cy, ark.wys)
                # zamroź w rzutni warstwy zakresu WSZYSTKICH INNYCH stacji (kod 341 = uchwyt warstwy)
                frozen = [hh for n, hh in warstwa_stacji_handle.items() if n != ark.nr_stacji]
                nd = _dodaj_zamrozone(nd, frozen)
                vp_glowna = h
            enc_tagi.append((t, nd))

        # podmiana pól tabelki: numer rysunku, numer stacji, miejscowości
        podmianki = _podmianki_tabelki(ark)
        enc_tagi = _tekst_tabelki(enc_tagi, podmianki)

        # BLOCK ... ENDBLK dla tego layoutu (encje papieru z flagą 67=1)
        nowe_bloki.append((0, "BLOCK"))
        nowe_bloki += [(5, nh()), (330, br), (100, "AcDbEntity"), (67, "     1"), (8, "0"),
                       (100, "AcDbBlockBegin"), (2, blok), (70, "     0"), (10, "0.0"), (20, "0.0"),
                       (30, "0.0"), (3, blok), (1, "")]
        for t, d in enc_tagi:
            nowe_bloki.append((0, t))
            # wstaw 67=1 tuż po pierwszym 100
            d2 = list(d)
            for j, (c, _v) in enumerate(d2):
                if c == 100:
                    d2.insert(j + 1, (67, "     1"))
                    break
            nowe_bloki += d2
        nowe_bloki += [(0, "ENDBLK"), (5, nh()), (330, br), (100, "AcDbEntity"), (67, "     1"),
                       (8, "0"), (100, "AcDbBlockEnd")]

        # BLOCK_RECORD
        nowe_br.append([(5, br), (330, br_table), (100, "AcDbSymbolTableRecord"),
                        (100, "AcDbBlockTableRecord"), (2, blok), (340, lay_h),
                        (70, "     0"), (280, "     1"), (281, "     0")])

        # LAYOUT - klon wzorca z nową nazwą, uchwytem, br, tab order, aktywną rzutnią
        nowe_layouty.append(_klon_layout(lay_wzor, lay_h, br, ark.nazwa, tab0 + i, vp_glowna, wlasc_dict))
        wpisy_slownika.append((ark.nazwa, lay_h))

    # --- wstaw wszystko do odpowiednich sekcji ---
    secs["TABLES"] = _wstaw_block_recordy(secs["TABLES"], nowe_br)
    secs["BLOCKS"] = secs.get("BLOCKS", []) + nowe_bloki
    secs["OBJECTS"] = _wstaw_layouty_i_slownik(secs["OBJECTS"], nowe_layouty, wpisy_slownika, wlasc_dict)

    # obrysy arkuszy w modelu (Defpoints)
    secs["ENTITIES"] = secs.get("ENTITIES", []) + _obrysy_modelu(arkusze, nh)

    # $HANDSEED
    hdr = list(secs["HEADER"])
    for i, (c, v) in enumerate(hdr):
        if c == 9 and v == "$HANDSEED":
            hdr[i + 1] = (5, format(nast, "X"))
            break
    secs["HEADER"] = hdr

    tags = []
    for name in kolejnosc:
        tags += [(0, "SECTION"), (2, name)] + secs[name] + [(0, "ENDSEC")]
    tags.append((0, "EOF"))
    _write_tags(wyjscie_sciezka, tags)
    log(f"Dopisano {len(arkusze)} layoutów -> {wyjscie_sciezka}")


# --- pomocnicze do zapisu ---
def _write_tags(path, tags):
    out = []
    for c, v in tags:
        out.append(f"{c:>3}\n{v}\n")
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("".join(out))


def _nazwa_layoutu(d):
    """Nazwa layoutu z tagów LAYOUT (ostatni kod 1)."""
    nazwy = [v for c, v in d if c == 1]
    return nazwy[-1].strip() if nazwy else ""


def _usun_layouty_pzt(secs, log=print):
    """Usuwa z pliku ISTNIEJĄCE layouty PZT (nazwa '<nr>-<n>', np. '244-1') wraz z ich
    block record, blokiem papieru i wpisem w słowniku ACAD_LAYOUT.

    Dzięki temu ponowne uruchomienie PZT na pliku, który już ma arkusze PZT (np. z poprzedniego
    uruchomienia), REGENERUJE je zamiast dublować. Layouty inne niż PZT (Model, wzorzec 'a',
    arkusze przewieszeń itp.) zostają nietknięte. Zwraca liczbę usuniętych layoutów."""
    objs = split_entities(secs.get("OBJECTS", []))
    # handle layoutów PZT i ich block_record (330), + nazwy do czyszczenia słownika
    lay_handle, br_handle, nazwy_pzt = set(), set(), set()
    for t, d in objs:
        if t == "LAYOUT" and RE_NAZWA_PZT.match(_nazwa_layoutu(d)):
            h = get(d, 5)
            if h:
                lay_handle.add(h)
            br330 = [v for c, v in d if c == 330]
            if br330:
                br_handle.add(br330[-1])
            nazwy_pzt.add(_nazwa_layoutu(d))
    if not lay_handle:
        return 0

    # OBJECTS: wyrzuć te LAYOUT-y i wyczyść pary (3,nazwa)(350,handle) w słownikach ACAD_LAYOUT
    nowe_objs = []
    for t, d in objs:
        if t == "LAYOUT" and get(d, 5) in lay_handle:
            continue
        if t == "DICTIONARY":
            nd, i = [], 0
            while i < len(d):
                c, v = d[i]
                if c == 3 and i + 1 < len(d) and d[i + 1][0] == 350 and d[i + 1][1] in lay_handle:
                    i += 2
                    continue
                nd.append((c, v))
                i += 1
            d = nd
        nowe_objs.append((t, d))
    secs["OBJECTS"] = _join(nowe_objs)

    # TABLES: usuń BLOCK_RECORD-y usuwanych layoutów i popraw licznik 70 tabeli
    tabs = split_entities(secs.get("TABLES", []))
    nowe_tabs, cur = [], None
    for t, d in tabs:
        if t == "TABLE":
            cur = get(d, 2)
            if cur == "BLOCK_RECORD":
                usun = sum(1 for tt, dd in tabs if tt == "BLOCK_RECORD" and get(dd, 5) in br_handle)
                stare = sum(1 for tt, dd in tabs if tt == "BLOCK_RECORD")
                d = [(c, (f"{stare - usun:>6}" if c == 70 else v)) for c, v in d]
        if t == "BLOCK_RECORD" and get(d, 5) in br_handle:
            continue
        nowe_tabs.append((t, d))
    secs["TABLES"] = _join(nowe_tabs)

    # BLOCKS: usuń całe BLOCK...ENDBLK, których właściciel (330) to usuwany block_record
    blks = split_entities(secs.get("BLOCKS", []))
    nowe_blks, pomijaj = [], False
    for t, d in blks:
        if t == "BLOCK":
            pomijaj = _owner(d) in br_handle or get(d, 330) in br_handle
            if pomijaj:
                continue
        if t == "ENDBLK" and pomijaj:
            pomijaj = False
            continue
        if pomijaj:
            continue
        nowe_blks.append((t, d))
    secs["BLOCKS"] = _join(nowe_blks)

    log(f"Zastępuję istniejące arkusze PZT: usunięto {len(lay_handle)} layoutów "
        f"({', '.join(sorted(nazwy_pzt))}).")
    return len(lay_handle)


def _znajdz_wzorzec_layout(secs):
    """Zwraca (tagi_layoutu_a, handle_block_recordu) albo (None, None)."""
    for t, d in split_entities(secs.get("OBJECTS", [])):
        if t == "LAYOUT":
            nazwy = [v for c, v in d if c == 1]
            if nazwy and nazwy[-1].strip().lower() == NAZWA_WZORCA.lower():
                br330 = [v for c, v in d if c == 330]
                return d, (br330[-1] if br330 else None)
    return None, None


def _handle_tabeli(secs, nazwa_tabeli):
    for t, d in split_entities(secs.get("TABLES", [])):
        if t == "TABLE" and get(d, 2) == nazwa_tabeli:
            return get(d, 5)
    return "2"


def _max_tab_order(secs):
    mx = 0
    for t, d in split_entities(secs.get("OBJECTS", [])):
        if t == "LAYOUT":
            try:
                mx = max(mx, int(get(d, 71, "0")))
            except ValueError:
                pass
    return mx


def _ustaw_rzutnie(nd, cx, cy, view_h):
    """Ustawia w tagach rzutni: środek widoku (12/22) i wysokość widoku (45)."""
    out = []
    seen = set()
    for c, v in nd:
        if c == 12:
            v = _fmt(cx); seen.add(12)
        elif c == 22:
            v = _fmt(cy); seen.add(22)
        elif c == 45:
            v = _fmt(view_h); seen.add(45)
        out.append((c, v))
    return out


def _dodaj_zamrozone(nd, frozen_handles):
    """Dodaje do tagów rzutni kody 341 (po jednym na warstwę zamrożoną w tej rzutni).

    Kod 341 musi stać w części AcDbViewport (po kodzie 90 flag). Wstawiamy je tuż przed
    końcem encji, co GstarCAD/AutoCAD akceptują (należą do rekordu AcDbViewport)."""
    if not frozen_handles:
        return nd
    # nie duplikuj, gdy już są
    maja = {v for c, v in nd if c == 341}
    dodatki = [(341, h) for h in frozen_handles if h not in maja]
    return list(nd) + dodatki


def _fmt(x):
    if abs(x) < 1e-12:
        x = 0.0
    return repr(float(x))


def _klucz_nr(nr):
    """Sortowanie numerów stacji numerycznie."""
    try:
        return (0, int(re.sub(r"\D", "", nr)))
    except (ValueError, TypeError):
        return (1, str(nr))


def _oznaczenie_dla_warstwy(nr, arkusze):
    """Pełne oznaczenie stacji (np. '03-0494') dla numeru - do nazwy warstwy !trafo_<ozn>."""
    for a in arkusze:
        if a.nr_stacji == nr and a.stacja:
            return a.stacja
    return nr


def _warstwa_nazwa(d):
    return get(d, 2)


def _props_warstwy(secs, nazwa):
    """Właściwości warstwy wzorcowej (kolor 62, linia 6, waga 370) - do klonowania."""
    for t, d in split_entities(secs.get("TABLES", [])):
        if t == "LAYER" and (get(d, 2) or "").lower() == nazwa.lower():
            return [(c, v) for c, v in d if c in (62, 6, 370, 290, 420, 430)]
    return [(62, "     6"), (6, "Continuous")]


def _rekord_warstwy(handle, nazwa, props):
    tagi = [(5, handle), (330, "2"), (100, "AcDbSymbolTableRecord"), (100, "AcDbLayerTableRecord"),
            (2, nazwa), (70, "     0")]
    # dołóż właściwości (kolor/linia/waga), unikając duplikatów kodów
    kolor_jest = False
    for c, v in props:
        if c == 62:
            kolor_jest = True
        tagi.append((c, v))
    if not kolor_jest:
        tagi.append((62, "     6"))
    if not any(c == 6 for c, _ in props):
        tagi.append((6, "Continuous"))
    return tagi


def _wstaw_warstwy(tables_tagi, nowe_warstwy):
    """Wstawia nowe rekordy LAYER przed ENDTAB tabeli LAYER i aktualizuje licznik 70."""
    ents = split_entities(tables_tagi)
    out, cur = [], None
    for t, d in ents:
        if t == "TABLE":
            cur = get(d, 2)
            if cur == "LAYER":
                n = sum(1 for tt, _ in ents if tt == "LAYER") + len(nowe_warstwy)
                d = [(c, (f"{n:>6}" if c == 70 else v)) for c, v in d]
        if t == "ENDTAB" and cur == "LAYER":
            for w in nowe_warstwy:
                out.append(("LAYER", w))
            cur = None
        out.append((t, d))
    return _join(out)


def _przenies_poligony(entities_tagi, uchwyt_warstwa):
    """Zmienia kod 8 (warstwę) encji o danych uchwytach na warstwę docelową."""
    if not uchwyt_warstwa:
        return entities_tagi
    ents = split_entities(entities_tagi)
    out = []
    for t, d in ents:
        h = get(d, 5)
        if h in uchwyt_warstwa:
            cel = uchwyt_warstwa[h]
            d = [(c, (cel if c == 8 else v)) for c, v in d]
        out.append((t, d))
    return _join(out)


def _klon_layout(lay_wzor, lay_h, br, nazwa, tab, vp_glowna, wlasc_dict):
    ost330 = max(i for i, (c, v) in enumerate(lay_wzor) if c == 330)
    ost1 = max(i for i, (c, v) in enumerate(lay_wzor) if c == 1)
    out = []
    for i, (c, v) in enumerate(lay_wzor):
        if c == 5:
            v = lay_h
        elif i == ost330:
            v = br
        elif i == ost1:
            v = nazwa
        elif c == 71:
            v = f"{tab:>6}"
        elif c == 331:
            if vp_glowna is None:
                continue
            v = vp_glowna
        out.append((c, v))
    return out


def _wstaw_block_recordy(tables_tagi, nowe_br):
    """Wstawia nowe BLOCK_RECORD przed ENDTAB tabeli BLOCK_RECORD i aktualizuje licznik 70."""
    ents = split_entities(tables_tagi)
    out, cur = [], None
    for t, d in ents:
        if t == "TABLE":
            cur = get(d, 2)
            if cur == "BLOCK_RECORD":
                n = sum(1 for tt, _ in ents if tt == "BLOCK_RECORD") + len(nowe_br)
                d = [(c, (f"{n:>6}" if c == 70 else v)) for c, v in d]
        if t == "ENDTAB" and cur == "BLOCK_RECORD":
            for br in nowe_br:
                out.append(("BLOCK_RECORD", br))
            cur = None
        out.append((t, d))
    return _join(out)


def _wstaw_layouty_i_slownik(objects_tagi, nowe_layouty, wpisy, wlasc_dict):
    ents = split_entities(objects_tagi)
    out = []
    idx_last_layout = max((i for i, (t, d) in enumerate(ents) if t == "LAYOUT"), default=len(ents) - 1)
    for i, (t, d) in enumerate(ents):
        if t == "DICTIONARY" and get(d, 5) == wlasc_dict:
            d = list(d) + [tag for (nazwa, lay_h) in wpisy for tag in ((3, nazwa), (350, lay_h))]
        out.append((t, d))
    # wstaw nowe LAYOUT-y tuż po ostatnim istniejącym LAYOUT
    for off, lay in enumerate(nowe_layouty, 1):
        out.insert(idx_last_layout + off, ("LAYOUT", lay))
    return _join(out)


def _obrysy_modelu(arkusze, nh, model_owner="1F"):
    """Prostokąty zasięgu arkuszy w modelu na warstwie Defpoints (kolor 4) + nazwa arkusza."""
    tagi = []
    for a in arkusze:
        tagi += [(0, "LWPOLYLINE"), (5, nh()), (330, model_owner), (100, "AcDbEntity"),
                 (8, WARSTWA_RAMEK), (62, f"{KOLOR_RAMEK:>6}"), (100, "AcDbPolyline"),
                 (90, "     4"), (70, "     1")]
        for (px, py) in ((a.x0, a.y0), (a.x0 + a.szer, a.y0),
                         (a.x0 + a.szer, a.y0 + a.wys), (a.x0, a.y0 + a.wys)):
            tagi += [(10, _fmt(px)), (20, _fmt(py))]
        cx, cy = a.srodek
        tagi += [(0, "TEXT"), (5, nh()), (330, model_owner), (100, "AcDbEntity"),
                 (8, WARSTWA_RAMEK), (62, f"{KOLOR_RAMEK:>6}"), (100, "AcDbText"),
                 (10, _fmt(cx)), (20, _fmt(cy)), (30, "0.0"), (40, _fmt(a.wys / 25)),
                 (1, a.nazwa), (72, "     1"), (73, "     2"),
                 (11, _fmt(cx)), (21, _fmt(cy)), (31, "0.0"), (100, "AcDbText")]
    return tagi


def _podmianki_tabelki(ark):
    """Reguły podmiany pól tabelki: numer rysunku (2.x), numer stacji, miejscowość.

    Każda reguła to (funkcja_dopasowania, nowa_wartość) - działa na treści MTEXT/TEXT.
    Podmiany trafiają zarówno w PLACEHOLDER wzorca (np. '03-xx', 'w miejscowości ___'),
    jak i w KONKRETNĄ wartość pozostawioną we wzorcu (np. '05-0614', nazwę miejscowości),
    więc arkusze różnych stacji dostają własny numer i miejscowość, a nie wartość z wzorca."""
    reguly = []
    # numer rysunku: "2.x" / "2." + cyfra -> np. "2.3"
    reguly.append((re.compile(r"2\.(?:x+|\d+)"), ark.nr_rys))
    # numer stacji: placeholder (03-xx) ORAZ realny numer (05-0614) -> oznaczenie stacji arkusza
    if ark.stacja:
        reguly.append((re.compile(r"\b\d{2,3}-(?:x+|\d{3,4})\b", re.I), ark.stacja))
    # miejscowość: fraza "w miejscowości <...>" -> "w miejscowości <miejscowości arkusza>"
    # (działa też, gdy po frazie jest już wpisana nazwa z wzorca - zostaje zastąpiona)
    if ark.miejscowosci:
        nazwa = ", ".join(ark.miejscowosci)
        reguly.append((_PodmianaMiejscowosci(nazwa), None))
    return reguly


# fraza w tabelce, po której stoi nazwa miejscowości (bez znaczenia wielkości liter)
FRAZA_MIEJSCOWOSCI = "w miejscowości"
_RE_MIEJSCOWOSC = re.compile(
    r"(?P<fraza>w\s+miejscowości\s+)(?P<nazwa>[^{}\\;]*)", re.IGNORECASE)


class _PodmianaMiejscowosci:
    """Zamienia nazwę po frazie 'w miejscowości ...' na podaną, zachowując formatowanie MTEXT.

    Udaje interfejs skompilowanego wyrażenia (search/sub), bo _tekst_tabelki tak go używa."""

    def __init__(self, nazwa: str):
        self.nazwa = nazwa

    def search(self, s):
        return _RE_MIEJSCOWOSC.search(s or "")

    def sub(self, s):
        def repl(m):
            # zachowaj pojedynczą spację po frazie; podmień tylko samą nazwę
            return m.group("fraza") + self.nazwa
        return _RE_MIEJSCOWOSC.sub(repl, s or "")


def _join(ents):
    tags = []
    for t, d in ents:
        tags.append((0, t))
        tags.extend(d)
    return tags


# ============================================================ miejscowości wg zasięgu stacji
def miejscowosci_wg_stacji(dxf_path, adresy="uug,osm", cache_dir=None, log=print):
    """Zwraca {znormalizowany_nr_stacji: [miejscowości...]} ustalone z GEOKODOWANIA SŁUPÓW
    leżących w zasięgu danej stacji trafo.

    Przynależność słup->stacja bierzemy z zestawienia (obszary !trafo_<nr> + drzewo sieci) -
    to samo źródło, które decyduje o numerze stacji na arkuszu. Dla każdej stacji geokodujemy
    jej słupy (grupując je przestrzennie w siatkę, żeby ograniczyć liczbę zapytań) i zwracamy
    listę miejscowości tej stacji, posortowaną malejąco wg liczby słupów. Dzięki temu w tabelce
    arkuszy PZT jest ta sama miejscowość, jaką obejmują słupy w zasięgu stacji.

    Przy wyłączonym/niedostępnym geokodowaniu (adresy='brak' albo brak internetu) zwraca
    pusty słownik - wtedy tabelka zachowuje nazwę z wzorca (zmieniany jest tylko numer stacji).
    """
    if (adresy or "").strip().lower() in ("", "brak", "nie", "0"):
        return {}
    try:
        from . import orientacje as _ori
        from . import zestawienie as _zest
    except ImportError:
        import orientacje as _ori
        import zestawienie as _zest

    # 1) słupy przypisane do stacji (po zasięgu !trafo + drzewie sieci)
    try:
        mapa = _zest.mapa_stacji_slupow(dxf_path)
    except Exception as ex:  # noqa: BLE001 - geokodowanie to dodatek, nie przerywaj PZT
        log(f"Uwaga: nie udało się ustalić słupów stacji z zestawienia ({ex}); "
            "miejscowości w tabelce zostaną z wzorca.")
        return {}
    slupy_stacji = {}
    for x, y, _nr, st in mapa:
        slupy_stacji.setdefault(_norm_nr(st), []).append((x, y))
    if not slupy_stacji:
        return {}

    # 2) geokoder (ta sama infrastruktura co „Rysunki stałe” - spójne nazwy, cache, rate-limit)
    from pathlib import Path
    if cache_dir is None:
        cache_dir = _ori.default_cache_dir(_ori.program_dir())
    try:
        geokoder = _ori.PlaceResolver(Path(cache_dir), verify=False, log=log)
    except Exception as ex:  # noqa: BLE001
        log(f"Uwaga: nie udało się uruchomić geokodera ({ex}); miejscowości z wzorca.")
        return {}

    # 3) dla każdej stacji: grupuj słupy w siatkę i geokoduj jeden punkt na komórkę
    komorka = _ori.GESTOSC_MIEJSC
    wynik = {}
    for nr, pts in slupy_stacji.items():
        liczby = {}
        grupy = {}
        for (x, y) in pts:
            grupy.setdefault((round(x / komorka), round(y / komorka)), []).append((x, y))
        for lista in grupy.values():
            x, y = lista[0]
            try:
                zone = _ori.pl2000_zone_from_easting(x)
                lat, lon = _ori.pl2000_to_wgs84(x, y, zone)
                r = geokoder.resolve(lat, lon, x, y, zone)
            except Exception:  # noqa: BLE001 - pojedyncza grupa nie wywraca całości
                continue
            nazwa = (r.get("miejscowosc") or "").strip()
            if nazwa:
                liczby[nazwa] = liczby.get(nazwa, 0) + len(lista)
        if liczby:
            wynik[nr] = [n for n, _c in sorted(liczby.items(), key=lambda kv: (-kv[1], kv[0]))]
    return wynik


# ============================================================ program główny


def _ustal_miejscowosci(dxf, wt_plik, adresy, cache_dir, log):
    """Mapa {nr_stacji: [miejscowości]} wg zasięgu stacji - z WT (gdy podany) lub geokodowania.

    Gdy podano plik WT: miejscowości z WT; dla stacji bez dopasowania WT „krzyczymy” w logu
    (jak uzgodniono) i próbujemy uzupełnić je geokodowaniem, jeśli internet jest włączony."""
    if wt_plik:
        try:
            from . import wt as _wt
        except ImportError:
            import wt as _wt
        log(f"Ustalanie miejscowości stacji z Warunków Technicznych: {wt_plik}")
        mapa, ostrz = _wt.miejscowosci_stacji_z_wt(dxf, wt_plik, log=log)
        for o in ostrz:
            log("UWAGA: " + o)
        # uzupełnij stacje bez trafienia WT geokodowaniem (gdy internet włączony)
        if ostrz and (adresy or "").strip().lower() not in ("", "brak", "nie", "0"):
            log("Uzupełniam brakujące miejscowości geokodowaniem słupów...")
            geo = miejscowosci_wg_stacji(dxf, adresy=adresy, cache_dir=cache_dir, log=log)
            for nr, miejsc in geo.items():
                mapa.setdefault(nr, miejsc)
        return mapa
    log("Ustalanie miejscowości stacji z geokodowania słupów w zasięgu...")
    return miejscowosci_wg_stacji(dxf, adresy=adresy, cache_dir=cache_dir, log=log)


def przetworz(dxf, wyjscie=None, wzorzec=None, tylko=None, miejscowosci_stacji=None,
              adresy="uug,osm", cache_dir=None, wt_plik=None, zaklad=ZAKLAD, uklad=None, log=print):
    """Tworzy arkusze PZT z pliku DXF. Zwraca (ścieżka_wyniku, liczba_arkuszy, ostrzeżenia).

    Miejscowość w tabelce każdego arkusza ustalana jest wg zasięgu stacji trafo:
      * gdy podano `wt_plik` - z pliku Warunków Technicznych (słupy WT dopasowane do
        wierzchołków !tele w zasięgu !trafo; patrz wt.miejscowosci_stacji_z_wt),
      * inaczej - z GEOKODOWANIA słupów stacji (miejscowosci_wg_stacji).
    Można też podać gotową mapę w `miejscowosci_stacji` ({nr: [miejscowości]});
    `adresy='brak'` wyłącza geokodowanie - wtedy nazwa zostaje z wzorca.

    `uklad` - plik ręcznego układu arkuszy (z okna podglądu); None = „<plan> - arkusze PZT.json”
    obok planu, jeśli istnieje; False = zawsze rozkład automatyczny."""
    we = wczytaj(dxf, wzorzec)
    if not we.poligony:
        raise ValueError(f"W pliku nie ma poligonów zasięgu stacji na warstwie {WARSTWA_ZAKRES}.")
    if not we.trasy:
        raise ValueError(f"W pliku nie ma trasy na warstwie {WARSTWA_TRASA}.")
    norm_tylko = {_norm_nr(s) for s in tylko} if tylko else None
    if miejscowosci_stacji is None:
        miejscowosci_stacji = _ustal_miejscowosci(dxf, wt_plik, adresy, cache_dir, log)
    reczny = {}
    if uklad is not False:
        plik_ukladu = uklad or sciezka_ukladu(dxf)
        reczny = wczytaj_uklad(plik_ukladu, we.wzor_okno, log=log)
        if reczny:
            import os
            log(f"Ręczny układ arkuszy z pliku {os.path.basename(plik_ukladu)} "
                f"(stacje: {', '.join(sorted(reczny))}).")
    arkusze, ostrzezenia, poligony_stacji = zaplanuj(we, miejscowosci_stacji=miejscowosci_stacji,
                                                     tylko=norm_tylko, zaklad=zaklad, uklad=reczny, log=log)
    if not arkusze:
        raise ValueError("Nie powstał żaden arkusz (brak trasy w zakresach stacji?).")
    if not wyjscie:
        import os
        baza = os.path.splitext(os.path.basename(dxf))[0]
        wyjscie = os.path.join(os.path.dirname(os.path.abspath(dxf)), f"{baza} - PZT.dxf")
    zapisz_arkusze(dxf, wyjscie, arkusze, wzorzec_sciezka=wzorzec,
                   poligony_stacji=poligony_stacji, log=log)
    for o in ostrzezenia:
        log("Uwaga: " + o)
    return wyjscie, len(arkusze), ostrzezenia


def main(argv=None):
    import argparse
    import sys
    for strumien in (sys.stdout, sys.stderr):
        try:
            strumien.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="Arkusze PZT (A3 1:1000) dla zakresów stacji trafo z pliku DXF.")
    ap.add_argument("dxf", help="plik DXF z trasą !tele, poligonami !trafo i layoutem-wzorcem „a”")
    ap.add_argument("-o", "--wyjscie", default=None, help="plik wynikowy DXF (domyślnie '<plik> - PZT.dxf')")
    ap.add_argument("--wzorzec", default=None, help="osobny plik DXF z layoutem-wzorcem „a”")
    ap.add_argument("--stacje", default=None, help="tylko wybrane stacje, po przecinku (np. 494,541)")
    ap.add_argument("--zaklad", type=float, default=ZAKLAD, help="wspólny odcinek trasy sąsiednich arkuszy [m]")
    ap.add_argument("--adresy", default="uug,osm",
                    help="źródła nazw miejscowości do tabelki: uug,osm lub 'brak' (bez internetu)")
    ap.add_argument("--wt", default=None,
                    help="plik Warunków Technicznych (.xls/.xlsx) - miejscowości słupów wg zasięgu stacji "
                         "(zamiast geokodowania; współrzędne PUWG2000 lub WGS84)")
    a = ap.parse_args(argv)
    zaklad = max(0.0, min(500.0, a.zaklad))
    tylko = [s.strip() for s in a.stacje.replace(";", ",").split(",")] if a.stacje else None
    try:
        wy, n, _ = przetworz(a.dxf, a.wyjscie, a.wzorzec, tylko, adresy=a.adresy,
                             wt_plik=a.wt, zaklad=zaklad, log=print)
        print(f"Gotowe: {n} arkuszy -> {wy}")
        return 0
    except Exception as ex:  # noqa: BLE001
        print(f"BŁĄD: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
