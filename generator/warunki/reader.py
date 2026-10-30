"""Odczyt pliku DXF: słupy (wierzchołki !tele), strefy !trafo, stacje, opisy słupów."""
from __future__ import annotations

import math
import re

from ezdxf.document import Drawing
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from .config import Config
from .model import BlednyKlik, StacjaTrafo, Wierzcholek


def _warstwa(e, nazwa: str) -> bool:
    return e.dxf.layer.casefold() == nazwa.casefold()


def _punkty(e) -> list[tuple[float, float]]:
    typ = e.dxftype()
    if typ == "LINE":
        return [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
    if typ == "LWPOLYLINE":
        pts = [(float(p[0]), float(p[1])) for p in e.get_points("xy")]
        if e.closed and pts:
            pts.append(pts[0])
        return pts
    if typ == "POLYLINE":
        pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
        if e.is_closed and pts:
            pts.append(pts[0])
        return pts
    return []  # bloki, punkty itp. są pomijane


def jest_warstwa_trafo(warstwa: str, cfg: Config) -> bool:
    w = warstwa.casefold()
    return w == cfg.warstwa_trafo.casefold() or w.startswith(cfg.prefiks_warstwy_trafo.casefold())


# ---------------------------------------------------------------- słupy

class _UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def wczytaj_slupy(doc: Drawing, cfg: Config) -> tuple[list[Wierzcholek], list[BlednyKlik]]:
    """Zbiera wierzchołki !tele i scala te, które leżą bliżej niż cfg.tolerancja_slupa.

    Scalanie jest przechodnie (A-B < 5 m i B-C < 5 m => A, B, C to jeden słup).
    Położenie słupa = wierzchołek grupy, który występuje w rysunku najczęściej
    (np. wspólny koniec kilku polilinii), a przy remisie - narysowany najwcześniej.
    """
    surowe: list[tuple[float, float, tuple[int, int]]] = []
    krawedzie: list[tuple[int, int]] = []
    for nr_ob, e in enumerate(doc.modelspace()):
        if not _warstwa(e, cfg.warstwa_tele):
            continue
        poprz = None
        for nr_w, (x, y) in enumerate(_punkty(e)):
            surowe.append((x, y, (nr_ob, nr_w)))
            i = len(surowe) - 1
            if poprz is not None:
                krawedzie.append((poprz, i))
            poprz = i

    tol = cfg.tolerancja_slupa
    uf = _UnionFind(len(surowe))
    siatka: dict[tuple[int, int], list[int]] = {}
    for i, (x, y, _) in enumerate(surowe):
        kx, ky = math.floor(x / tol), math.floor(y / tol)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in siatka.get((kx + dx, ky + dy), []):
                    if math.hypot(surowe[j][0] - x, surowe[j][1] - y) < tol:
                        uf.union(i, j)
        siatka.setdefault((kx, ky), []).append(i)

    grupy: dict[int, list[int]] = {}
    for i in range(len(surowe)):
        grupy.setdefault(uf.find(i), []).append(i)

    slupy: list[Wierzcholek] = []
    bledne: list[BlednyKlik] = []
    mapa: dict[int, int] = {}
    for korzen in sorted(grupy, key=lambda k: surowe[grupy[k][0]][2]):
        czlonkowie = grupy[korzen]
        # liczba wystąpień tego samego położenia (z dokładnością do 1 cm)
        licz: dict[tuple[float, float], int] = {}
        for i in czlonkowie:
            k = (round(surowe[i][0], 2), round(surowe[i][1], 2))
            licz[k] = licz.get(k, 0) + 1
        glowny = min(czlonkowie, key=lambda i: (
            -licz[(round(surowe[i][0], 2), round(surowe[i][1], 2))], surowe[i][2]))
        x, y, kol = surowe[glowny]
        idx = len(slupy)
        w = Wierzcholek(id=idx, x=x, y=y, kolejnosc_rysunku=kol, scalonych=len(czlonkowie))
        slupy.append(w)
        for i in czlonkowie:
            mapa[i] = idx
        if len(licz) > 1:  # różne położenia => błędny klik
            maks = max(math.hypot(surowe[a][0] - surowe[b][0], surowe[a][1] - surowe[b][1])
                       for a in czlonkowie for b in czlonkowie)
            bledne.append(BlednyKlik(x, y, len(licz), round(maks, 2)))
            w.uwagi = f"Scalono {len(licz)} wierzchołki (do {maks:.2f} m)."

    for a, b in krawedzie:
        ia, ib = mapa[a], mapa[b]
        if ia != ib:
            slupy[ia].sasiedzi.add(ib)
            slupy[ib].sasiedzi.add(ia)
    return slupy, bledne


# ---------------------------------------------------------------- stacje trafo

def _czysty_tekst(t: str) -> str:
    t = re.sub(r"\\[A-Za-z][^;\\]*;", "", t)   # kody formatowania MTEXT (\pxql; itp.)
    t = t.replace("\\P", "\n").replace("{", "").replace("}", "")
    return t.strip()


def _nazwa_stacji(tekst: str) -> str:
    m = re.search(r"\d{2}-\d{3,5}", tekst)
    if m:
        return m.group(0)
    return re.sub(r"(?i)stacja\s*trafo\w*", "", tekst).replace("\n", " ").strip() or tekst


def _opisy_trafo(doc: Drawing, cfg: Config) -> list[tuple[Point, str]]:
    """Punkty stacji z opisami: MULTILEADER (grot strzałki), TEXT, MTEXT."""
    frag = cfg.fragment_warstwy_opisu_trafo.casefold()
    wynik = []
    for e in doc.modelspace():
        if frag not in e.dxf.layer.casefold():
            continue
        typ = e.dxftype()
        if typ == "MULTILEADER":
            ctx = e.context
            if not ctx.mtext or not ctx.leaders or not ctx.leaders[0].lines:
                continue
            v = ctx.leaders[0].lines[0].vertices[0]
            wynik.append((Point(v.x, v.y), _nazwa_stacji(_czysty_tekst(ctx.mtext.default_content))))
        elif typ == "TEXT" and e.dxf.text.strip():
            wynik.append((Point(e.dxf.insert.x, e.dxf.insert.y), _nazwa_stacji(e.dxf.text)))
        elif typ == "MTEXT" and e.plain_text().strip():
            wynik.append((Point(e.dxf.insert.x, e.dxf.insert.y), _nazwa_stacji(e.plain_text())))
    return wynik


def wczytaj_stacje_trafo(doc: Drawing, cfg: Config) -> tuple[list[StacjaTrafo], list[str]]:
    """Strefy trafo z polilinii na warstwie !trafo i warstwach '_trafo...'.

    - polilinie niezamknięte są domykane (zgodnie z praktyką rysowania obrysów),
    - nazwa strefy = numer stacji, której opis (grot multileadera / tekst) leży w obrysie,
    - obrysy bez stacji są dołączane do sąsiedniej strefy ze stacją, z którą się stykają.
    Zwraca (strefy, ostrzeżenia).
    """
    ostrz: list[str] = []
    obrysy: list[tuple[int, Polygon, str]] = []
    for nr, e in enumerate(doc.modelspace()):
        if not jest_warstwa_trafo(e.dxf.layer, cfg) or e.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
            continue
        pts = _punkty(e)
        if pts and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.area <= 0:
            continue
        obrysy.append((nr, poly, e.dxf.handle))

    opisy = _opisy_trafo(doc, cfg)
    przypisane: dict[int, tuple[str, Point]] = {}
    for i, (_, poly, uchwyt) in enumerate(obrysy):
        wewn = [(p, n) for p, n in opisy if poly.buffer(0.5).covers(p)]
        if wewn:
            przypisane[i] = (wewn[0][1], wewn[0][0])
            if len({n for _, n in wewn}) > 1:
                ostrz.append(f"Obrys {uchwyt} zawiera kilka stacji: "
                             f"{', '.join(sorted({n for _, n in wewn}))} - użyto {wewn[0][1]}.")

    # obrysy bez stacji -> do stykającej się strefy ze stacją (iteracyjnie)
    zmiana = True
    while zmiana:
        zmiana = False
        for i, (_, poly, uchwyt) in enumerate(obrysy):
            if i in przypisane:
                continue
            sasiad = next((j for j in przypisane
                           if obrysy[j][1].buffer(1.0).intersects(poly)), None)
            if sasiad is not None:
                przypisane[i] = (przypisane[sasiad][0], None)
                zmiana = True

    strefy: dict[str, StacjaTrafo] = {}
    for i, (nr, poly, uchwyt) in enumerate(obrysy):
        if i in przypisane:
            nazwa, punkt = przypisane[i]
        else:
            nazwa, punkt = f"TRAFO ? ({uchwyt})", None
            ostrz.append(f"Obrys !trafo {uchwyt} nie zawiera opisu stacji i nie styka się "
                         "z żadną strefą ze stacją.")
        if nazwa in strefy:
            s = strefy[nazwa]
            s.obrys = unary_union([s.obrys, poly])
            s.punkt_stacji = s.punkt_stacji or punkt
        else:
            strefy[nazwa] = StacjaTrafo(nazwa, poly, punkt, nr)
    bez_strefy = [n for p, n in opisy if not any(s.obrys.buffer(0.5).covers(p)
                                                  for s in strefy.values())]
    for n in bez_strefy:
        ostrz.append(f"Stacja {n} leży poza obrysami !trafo.")
    return list(strefy.values()), ostrz


# ---------------------------------------------------------------- opisy słupów

def przypisz_opisy_slupow(doc: Drawing, slupy: list[Wierzcholek], cfg: Config) -> int:
    """MULTILEADER 'słup nN\\P<typ>': grot wskazuje słup -> rodzaj (nN/SN) i typ słupa."""
    if not slupy:
        return 0
    pref = cfg.prefiks_opisu_slupa.casefold()
    przypisano = 0
    for e in doc.modelspace().query("MULTILEADER"):
        ctx = e.context
        if not ctx.mtext or not ctx.leaders or not ctx.leaders[0].lines:
            continue
        tekst = _czysty_tekst(ctx.mtext.default_content)
        if not tekst.casefold().startswith(pref):
            continue
        v = ctx.leaders[0].lines[0].vertices[0]
        w = min(slupy, key=lambda s: math.hypot(s.x - v.x, s.y - v.y))
        if math.hypot(w.x - v.x, w.y - v.y) > cfg.tolerancja_slupa:
            continue
        linie = [x.strip() for x in tekst.split("\n") if x.strip()]
        m = re.search(r"\b(nN|SN|WN)\b", linie[0], re.IGNORECASE)
        w.rodzaj_slupa = {"nn": "nN", "sn": "SN", "wn": "WN"}[m.group(1).lower()] if m else None
        w.typ_slupa = " ".join(linie[1:]) or None
        przypisano += 1
    return przypisano


def kierunki_linii(slup: Wierzcholek, slupy: list[Wierzcholek]) -> list[float]:
    """Kąty [rad] odcinków linii wychodzących ze słupa."""
    return [math.atan2(slupy[n].y - slup.y, slupy[n].x - slup.x) for n in slup.sasiedzi]



# ---------------------------------------------------------------- numery słupów w sieci

def przypisz_numery_slupow(doc: Drawing, slupy: list[Wierzcholek], cfg: Config
                           ) -> tuple[int, list[str]]:
    """Teksty (TEXT/MTEXT) z warstw '_numery...' -> numer słupa w sieci.

    Przypisanie jeden-do-jednego: pary tekst-słup sortowane wg odległości,
    każdy słup i każdy tekst użyty co najwyżej raz (do cfg.odl_numeru).
    Zwraca (liczba przypisanych, ostrzeżenia).
    """
    pref = cfg.prefiks_warstwy_numerow.casefold()
    teksty = []
    for e in doc.modelspace():
        if not e.dxf.layer.casefold().startswith(pref):
            continue
        if e.dxftype() == "TEXT":
            t, p = e.dxf.text.strip(), e.dxf.insert
            if e.dxf.get("halign", 0) or e.dxf.get("valign", 0):
                p = e.dxf.get("align_point", p)
        elif e.dxftype() == "MTEXT":
            t, p = _czysty_tekst(e.text).replace("\n", " ").strip(), e.dxf.insert
        else:
            continue
        if t:
            teksty.append((t, p.x, p.y))
    pary = []
    for i, (_, x, y) in enumerate(teksty):
        for w in slupy:
            d = math.hypot(w.x - x, w.y - y)
            if d <= cfg.odl_numeru:
                pary.append((d, i, w.id))
    pary.sort()
    uzyte_t, uzyte_s = set(), set()
    for d, i, s in pary:
        if i in uzyte_t or s in uzyte_s:
            continue
        uzyte_t.add(i)
        uzyte_s.add(s)
        slupy[s].nr_w_sieci = teksty[i][0]
    ostrz = [f"Numer '{teksty[i][0]}' (warstwa {cfg.prefiks_warstwy_numerow}…) nie wskazuje "
             f"żadnego słupa - X={teksty[i][2]:.2f} Y={teksty[i][1]:.2f}"
             for i in range(len(teksty)) if i not in uzyte_t]
    return len(uzyte_t), ostrz


def ustaw_id_slupow(slupy: list[Wierzcholek]) -> None:
    for w in slupy:
        if w.nr_w_sieci:
            w.id_slupa = f"{w.stacja_trafo}/{w.nr_w_sieci}" if w.stacja_trafo else w.nr_w_sieci
        else:
            w.id_slupa = None
