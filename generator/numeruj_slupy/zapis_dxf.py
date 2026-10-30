#!/usr/bin/env python3
"""
zapis_dxf - zapis wyników numeracji do pliku DXF (biblioteka ezdxf).

Dla każdego obwodu:
  * wpisuje numery słupów jako TEXT na warstwę  _numery_<stacja>_<obwod>
    (osobna warstwa na obwód - ułatwia robienie zestawień),
  * rysuje OBRYS KONTROLNY obwodu polilinią na warstwie  _kontrola_<stacja>_<obwod>
    - inny kolor dla każdego obwodu, grubość linii 0,5 mm, warstwa NIEDRUKOWALNA.

Obrys kontrolny to łamana prowadzona wzdłuż ścieżki numeracji (rodzic->dziecko):
magistrala + odgałęzienia, dzięki czemu wizualnie widać, które słupy program połączył
w jeden obwód i w jakiej kolejności je ponumerował.

Zapis DOPISUJE tylko nowe encje (numery + obrysy) i nowe warstwy do ORYGINALNEGO
pliku DXF - reszta (multileadery z opisami słupów/stacji/obwodów, style, bloki) zostaje
BAJT W BAJT jak w oryginale. Dzięki temu żaden element nie znika w CAD (ezdxf saveas
potrafił psuć render multileaderów przy przepisywaniu całego pliku). Oryginał nie jest
modyfikowany - wynik to nowy plik (domyślnie "!ponumerowany <nazwa>.dxf").
"""
import math
import os
import re

try:
    import ezdxf
except ImportError as _ex:          # ezdxf jest OPCJONALNY - potrzebny tylko do zapisu wyniku
    ezdxf = None
    _EZDXF_BLAD = _ex

# paleta kolorów ACI dla kolejnych obwodów (pomijamy biały/czarny 7 i czerwień 1 zarezerw.)
PALETA_ACI = [1, 3, 5, 6, 2, 4, 30, 150, 190, 210, 40, 90, 230, 8, 250, 170]
WYS_TEKSTU = 2.5                   # [j. rysunku] stała wysokość numeru słupa
ODSTEP_OD_LINII = 2.0              # [j. rysunku] odstęp górnej krawędzi cyfry od linii !tele


def _kolor_obwodu(k):
    return PALETA_ACI[k % len(PALETA_ACI)]


def _nazwa_warstwy(prefix, stacja, obwod):
    st = str(stacja).replace(' ', '_')
    return '%s_%s_%s' % (prefix, st, obwod)


def _kierunek_tele(model, p, tol=3.0):
    """Jednostkowy kierunek linii !tele w punkcie p (albo None).

    Numer ma leżeć RÓWNOLEGLE do linii !tele, przy której stoi słup - dlatego kąt bierzemy
    wprost z odcinka trasy, a NIE z grafu połączeń (ten zawiera też wymiary biegnące w poprzek,
    co ustawiało część numerów pod złym kątem, nawet prostopadle do linii).

    W słupie NAROŻNYM (schodzą się dwa ramiona trasy - jednej polilinii albo dwóch osobnych)
    zwracamy kierunek „średni” obu ramion: prostopadła do niego to dwusieczna narożnika, więc
    numer trafia do środka albo na zewnątrz narożnika, a nie wzdłuż jednego z ramion."""
    odcinki = []                                 # (odległość, kierunek jedn., kierunek OD słupa)
    for pts in getattr(model.rys, "sieci", []):
        for a, b in zip(pts, pts[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            if L2 == 0:
                continue
            t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
            d = math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
            ln = math.sqrt(L2)
            dal = b if math.dist(p, b) >= math.dist(p, a) else a          # koniec dalszy od słupa
            lu = math.dist(p, dal)
            od = ((dal[0] - p[0]) / lu, (dal[1] - p[1]) / lu) if lu > 1e-9 else (dx / ln, dy / ln)
            odcinki.append((d, (dx / ln, dy / ln), od, t))
    if not odcinki:
        return None
    d0, v0, _od0, _t0 = min(odcinki, key=lambda o: o[0])
    if d0 > tol:
        return None
    # ramiona wychodzące ze słupa: odcinki, których KONIEC leży przy słupie (t≈0 albo t≈1),
    # o różnych kierunkach „od słupa” (z tej samej albo z różnych polilinii)
    ramiona = []
    for d, _v, od, t in sorted(odcinki, key=lambda o: o[0]):
        if d > d0 + 0.5 or not (t < 1e-6 or t > 1 - 1e-6):
            continue
        if all(od[0] * r[0] + od[1] * r[1] < math.cos(math.radians(10)) for r in ramiona):
            ramiona.append(od)
    if len(ramiona) == 2:
        (ax, ay), (bx, by) = ramiona
        sx, sy = ax - bx, ay - by                # kierunek „przez słup” (z ramienia b do ramienia a)
        ln = math.hypot(sx, sy)
        if ln > 0.2:                             # nie dla zawrócenia o ~180°
            return (sx / ln, sy / ln)
    return v0


def _kierunek_przesla(model, i):
    """Jednostkowy wektor kierunku linii !tele przy słupie i (kierunek przęsła).

    Priorytet: kierunek najbliższego odcinka !tele (numer równolegle do trasy). Dopiero
    gdy słup nie leży na !tele - fallback na kierunek do najbliższego sąsiada w grafie."""
    p = model.slupy[i]['p']
    kt = _kierunek_tele(model, p)
    if kt is not None:
        return kt
    sas = list(model.polaczenia[i])
    if not sas:
        return (1.0, 0.0)
    j = min(sas, key=lambda j: math.dist(p, model.slupy[j]['p']))
    q = model.slupy[j]['p']
    vx, vy = q[0] - p[0], q[1] - p[1]
    d = math.hypot(vx, vy)
    if d == 0:
        return (1.0, 0.0)
    return (vx / d, vy / d)


def _wymiar_slupa(model, i):
    """NAJBLIŻSZY wymiar przyczepiony do słupa i: (p1, p2, text_midpoint) albo None."""
    p = model.slupy[i]['p']
    najl = None
    for L, p1, p2, nadpis, mid in model.wymiary:
        if mid is None:
            continue
        d_end = min(math.dist(p, p1), math.dist(p, p2))
        if d_end > 8.0:
            continue
        d_mid = math.dist(p, mid)
        if najl is None or d_mid < najl[0]:
            najl = (d_mid, (p1, p2, mid))
    return najl[1] if najl else None


def _cel_wymiaru(model, i):
    """Pozycja tekstu najbliższego wymiaru słupa i (albo None)."""
    w = _wymiar_slupa(model, i)
    return w[2] if w else None


def _strona_wymiaru(model, i):
    """Jednostkowa normalna LINII BAZOWEJ najbliższego wymiaru słupa i, skierowana w stronę jego
    tekstu (albo None). Stronę liczymy względem przęsła, które ten wymiar mierzy - rzut tekstu
    na kierunek INNEGO przęsła (w słupie narożnym) dawał złą stronę."""
    w = _wymiar_slupa(model, i)
    if w is None:
        return None
    (x1, y1), (x2, y2), (mx, my) = w
    dx, dy = x2 - x1, y2 - y1
    ln = math.hypot(dx, dy)
    if ln < 1e-9:
        return None
    nx, ny = -dy / ln, dx / ln
    if (mx - x1) * nx + (my - y1) * ny < 0:
        nx, ny = -nx, -ny
    return nx, ny


def _kierunek_odsuniecia(model, i):
    """Jednostkowy wektor PROSTOPADŁY do linii !tele, wskazujący stronę, w którą ma
    iść numer słupa. Znak dobierany BEZWZGLĘDNIE względem rysunku (nie zależy od tego,
    w którą stronę pokazuje lokalny kierunek przęsła):
      * w stronę najbliższego tekstu wymiaru (po tej samej stronie co wymiarowanie),
      * fallback: strona PRZECIWNA do stacji trafo.
    Zwraca (ux, uy)."""
    p = model.slupy[i]['p']
    kx, ky = _kierunek_przesla(model, i)
    nx, ny = -ky, kx                      # jedna z dwóch normalnych
    sw = _strona_wymiaru(model, i)
    if sw is not None:
        rzut = sw[0] * nx + sw[1] * ny
    else:
        st = model.stacja_slupa.get(i)
        sp = next((s['p'] for s in model.stacje if s['nr'] == st), None)
        if sp is not None:
            # przeciwnie do stacji: ujemny rzut wektora do stacji
            rzut = -((sp[0] - p[0]) * nx + (sp[1] - p[1]) * ny)
        else:
            rzut = 1.0
    znak = 1.0 if rzut >= 0 else -1.0
    return (nx * znak, ny * znak)


def _ma_wymiar(model, i):
    return _cel_wymiaru(model, i) is not None


def _rozmieszczenie(model, i, ref):
    """Zwraca (punkt_srodka, kąt_tekstu_deg) dla numeru słupa i.

    Numer: obrócony zgodnie z kierunkiem linii !tele (czytelny), odsunięty od słupa
    PROSTOPADLE do linii - dzięki temu stoi równo „pod” słupem, a nie przesunięty wzdłuż
    przęsła. Strona: ta sama co wymiar TEGO słupa (najbliższy tekst wymiaru); dla słupa bez
    wymiaru - strona `ref` (uśredniona strona wymiarowania obwodu). Zwracany punkt to ŚRODEK
    cyfry (wyrównanie MIDDLE_CENTER) - leży o (ODSTEP + pół wysokości) od słupa, więc cała
    cyfra jest po właściwej stronie, a jej krawędź bliższa linii ~ODSTEP od linii."""
    p = model.slupy[i]['p']
    kx, ky = _kierunek_przesla(model, i)
    nx, ny = -ky, kx                              # normalna do linii w słupie
    sw = _strona_wymiaru(model, i)                # strona wymiaru względem JEGO przęsła
    if sw is not None:
        rzut = sw[0] * nx + sw[1] * ny
    else:
        rzut = ref[0] * nx + ref[1] * ny
    if abs(rzut) < 1e-9:                          # brak wskazania - strona przeciwna do stacji
        rzut = _kierunek_odsuniecia(model, i)[0] * nx + _kierunek_odsuniecia(model, i)[1] * ny
    ux, uy = (nx, ny) if rzut >= 0 else (-nx, -ny)
    off = ODSTEP_OD_LINII + WYS_TEKSTU / 2.0     # środek cyfry: ODSTEP od linii + pół wys.
    px = p[0] + ux * off
    py = p[1] + uy * off
    kat = math.degrees(math.atan2(ky, kx))
    if kat <= -90 or kat > 90:                   # czytelność: nie "do góry nogami"
        kat += 180.0
    return (px, py), kat


def _sciezka_obwodu(model, ob):
    """Lista krawędzi (i, j) wzdłuż ścieżki numeracji obwodu (rodzic->dziecko).
    Rodzic słupa to słup o numerze bezpośrednio poprzednim, połączony w grafie."""
    numery = ob['slupy']
    nr2idx = {numery[i]: i for i in numery}
    kraw = []
    try:
        from .numeracja import _num_dziecka  # noqa
    except ImportError:
        from numeracja import _num_dziecka  # noqa

    def nr_rodzica(nr):
        cz = nr.split('.')
        if len(cz) > 1 and cz[-1] == '1':
            return '.'.join(cz[:-1])
        n = int(cz[-1]) - 1
        return None if n <= 0 else '.'.join(cz[:-1] + [str(n)])

    for i, nr in numery.items():
        pr = nr_rodzica(nr)
        if pr is not None and pr in nr2idx:
            j = nr2idx[pr]
            if j in model.polaczenia[i]:
                kraw.append((j, i))
    return kraw


def _ref_obwodu(model, ob):
    """Referencyjny kierunek odsunięcia obwodu (strona wymiarowania)."""
    ref = [0.0, 0.0]
    for i in ob['slupy']:
        if _ma_wymiar(model, i):
            ux, uy = _kierunek_odsuniecia(model, i)
            ref[0] += ux
            ref[1] += uy
    if ref == [0.0, 0.0]:
        ref = list(_kierunek_odsuniecia(model, ob['start']))
    return ref


# =============================================================== zapis DXF (dopisywanie)
# Zapis dopisuje TYLKO nowe encje (numery TEXT + obrysy LWPOLYLINE) oraz nowe warstwy do
# ORYGINALNEGO pliku DXF, nie przepisując reszty. Dzięki temu multileadery (opisy słupów,
# stacji, obwodów), style i wszystkie inne encje pozostają BAJT W BAJT jak w oryginale -
# żaden element rysunku nie znika w CAD (ezdxf saveas potrafił psuć render multileaderów).

def _czytaj_tekst_dxf(sciezka):
    raw = open(sciezka, 'rb').read()
    enc = 'utf-8'
    head = raw[:20000].decode('latin-1')
    m = re.search(r'\$ACADVER\s*\r?\n\s*1\s*\r?\n\s*AC(\d+)', head)
    if not (m and int(m.group(1)) >= 1021):
        m2 = re.search(r'\$DWGCODEPAGE\s*\r?\n\s*3\s*\r?\n\s*ANSI_(\d+)', head)
        enc = 'cp' + m2.group(1) if m2 else 'cp1250'
    return raw.decode(enc, errors='replace'), enc


def _max_handle(tekst):
    mx = 0
    linie = tekst.splitlines()
    for i in range(len(linie) - 1):
        k = linie[i].strip()
        if k in ('5', '105'):
            try:
                mx = max(mx, int(linie[i + 1].strip(), 16))
            except ValueError:
                pass
    return mx


class _Handles:
    def __init__(self, start):
        self.n = start

    def nowy(self):
        self.n += 1
        return format(self.n, 'X')


def _grupy(*pary):
    """Składa pary (kod, wartość) w tekst DXF (po dwie linie)."""
    out = []
    for kod, wart in pary:
        out.append('%3d' % kod if isinstance(kod, int) and kod < 100 else str(kod))
        out.append(str(wart))
    return '\n'.join(out)


def _enc_layer(nazwa, kolor, h, hwn, lineweight=None, plot=None):
    """Wpis tabeli LAYER (minimalny, zgodny z R2007)."""
    g = [(0, 'LAYER'), (5, h), (330, hwn), (100, 'AcDbSymbolTableRecord'),
         (100, 'AcDbLayerTableRecord'), (2, nazwa), (70, 0), (62, kolor),
         (6, 'Continuous')]
    if plot is not None:
        g.append((290, plot))                    # 290: plottable (0 = niedrukowalna)
    if lineweight is not None:
        g.append((370, lineweight))              # 370: lineweight (setne mm)
    return _grupy(*g)


def _enc_text(numer, px, py, kat, wys, warstwa, kolor, h):
    """Encja TEXT wyrównana MIDDLE_CENTER (72=1 poziomo center, 73=2 pionowo middle),
    punkt wyrównania = ŚRODEK cyfry w (px,py) - kod 11/21."""
    return _grupy(
        (0, 'TEXT'), (5, h), (330, '1F'), (100, 'AcDbEntity'), (8, warstwa),
        (62, kolor), (100, 'AcDbText'),
        (10, '%.6f' % px), (20, '%.6f' % py), (30, '0.0'),
        (40, '%.6f' % wys), (1, numer), (50, '%.6f' % kat),
        (72, 1), (11, '%.6f' % px), (21, '%.6f' % py), (31, '0.0'),
        (100, 'AcDbText'), (73, 2))


def _enc_lwpolyline(pts, warstwa, kolor, h):
    g = [(0, 'LWPOLYLINE'), (5, h), (330, '1F'), (100, 'AcDbEntity'), (8, warstwa),
         (62, kolor), (100, 'AcDbPolyline'), (90, len(pts)), (70, 0)]
    for x, y in pts:
        g += [(10, '%.6f' % x), (20, '%.6f' % y)]
    return _grupy(*g)


def zapisz(model, obwody, sciezka_wej, sciezka_wyj=None):
    """Zapisuje numery i obrysy kontrolne, DOPISUJĄC je do oryginalnego pliku DXF
    (bez przepisywania reszty). Zwraca ścieżkę wyniku."""
    if ezdxf is None:
        raise ImportError("Moduł numeracji słupów wymaga biblioteki ezdxf "
                          "(zainstaluj: pip install ezdxf).")
    if sciezka_wyj is None:
        folder, nazwa = os.path.split(os.path.splitext(sciezka_wej)[0])
        sciezka_wyj = os.path.join(folder, '!ponumerowany ' + nazwa + '.dxf')

    tekst, enc = _czytaj_tekst_dxf(sciezka_wej)
    H = _Handles(_max_handle(tekst))

    # istniejące nazwy warstw (żeby nie dublować) - czytamy przez ezdxf tylko do odczytu
    doc = ezdxf.readfile(sciezka_wej)
    istniejace = {l.dxf.name for l in doc.layers}
    hwn_layer = '2'                               # owner tabeli LAYER (standard: handle 2)

    klucze = sorted({(o['stacja'], o['nr_obwodu']) for o in obwody})
    kolor_dla = {k: _kolor_obwodu(i) for i, k in enumerate(klucze)}

    nowe_warstwy = []
    nowe_encje = []

    for ob in sorted(obwody, key=lambda o: (o['stacja'], o['nr_obwodu'])):
        st, nr_obw = ob['stacja'], ob['nr_obwodu']
        kolor = kolor_dla[(st, nr_obw)]
        warstwa_num = _nazwa_warstwy('_numery', st, nr_obw)
        warstwa_ctrl = _nazwa_warstwy('_kontrola', st, nr_obw)

        if warstwa_num not in istniejace:
            nowe_warstwy.append(_enc_layer(warstwa_num, 7, H.nowy(), hwn_layer))
            istniejace.add(warstwa_num)
        if warstwa_ctrl not in istniejace:
            nowe_warstwy.append(_enc_layer(warstwa_ctrl, kolor, H.nowy(), hwn_layer,
                                           lineweight=50, plot=0))
            istniejace.add(warstwa_ctrl)

        ref = _ref_obwodu(model, ob)

        for i, numer in ob['slupy'].items():
            (px, py), kat = _rozmieszczenie(model, i, (ref[0], ref[1]))
            nowe_encje.append(_enc_text(numer, px, py, kat, WYS_TEKSTU,
                                        warstwa_num, 7, H.nowy()))

        for a, b in _sciezka_obwodu(model, ob):
            nowe_encje.append(_enc_lwpolyline(
                [model.slupy[a]['p'], model.slupy[b]['p']], warstwa_ctrl, kolor, H.nowy()))

    tekst = _wstrzyknij(tekst, nowe_warstwy, nowe_encje, H.n)
    with open(sciezka_wyj, 'w', encoding=enc, errors='replace', newline='\n') as f:
        f.write(tekst)
    return sciezka_wyj


def _wstrzyknij(tekst, nowe_warstwy, nowe_encje, nowy_handseed):
    """Wstawia nowe wpisy LAYER do tabeli LAYER, nowe encje przed ENDSEC ENTITIES,
    i aktualizuje $HANDSEED. Operuje na surowym tekście DXF (CRLF/LF-agnostycznie)."""
    nl = '\r\n' if '\r\n' in tekst else '\n'
    linie = tekst.split(nl)

    # 1) $HANDSEED
    for i in range(len(linie) - 1):
        if linie[i].strip() == '9' and linie[i + 1].strip() == '$HANDSEED':
            linie[i + 3] = format(nowy_handseed + 10, 'X')
            break

    # 2) wstaw wpisy LAYER przed ENDTAB tabeli LAYER
    #    znajdź "TABLE"->"LAYER" ... potem pierwszy ENDTAB
    i_layer = None
    for i in range(len(linie) - 1):
        if linie[i].strip() == '2' and linie[i + 1].strip() == 'LAYER' \
                and i >= 2 and linie[i - 1].strip() == 'TABLE':
            i_layer = i
            break
    if i_layer is not None and nowe_warstwy:
        for j in range(i_layer, len(linie) - 1):
            if linie[j].strip() == '0' and linie[j + 1].strip() == 'ENDTAB':
                blok = nl.join(nowe_warstwy)
                linie[j:j] = blok.split(nl)
                break

    # 3) wstaw encje przed ENDSEC sekcji ENTITIES
    i_ent = None
    for i in range(len(linie) - 1):
        if linie[i].strip() == '2' and linie[i + 1].strip() == 'ENTITIES':
            i_ent = i
            break
    if i_ent is not None and nowe_encje:
        for j in range(i_ent, len(linie) - 1):
            if linie[j].strip() == '0' and linie[j + 1].strip() == 'ENDSEC':
                blok = nl.join(nowe_encje)
                linie[j:j] = blok.split(nl)
                break

    return nl.join(linie)
