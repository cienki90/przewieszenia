"""Geometria pojedynczego rysunku zwisu (przewieszenia) w układzie lokalnym.

Układ lokalny: u - wzdłuż przęsła [jednostki rysunku, 1 j = 2 m], v - wysokość [m, skala 1:1].
Początek (0, 0) = podstawa lewego słupa.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

SKALA_X = 0.5      # jednostek rysunku na 1 m (poziomo)
WYS_SIATKI = 8.5   # wysokość siatki/linijek [m]
KOLOR_SWIATLOWODU = 3

KROPKOWA = dict(lt="ACAD_ISO07W100", lts=0.1, lw=15)


@dataclass
class Dane:
    """Dane wejściowe jednego rysunku."""
    slup_l: str
    typ_l: str
    slup_p: str
    typ_p: str
    rozp: int                         # rozpiętość [m]
    obwody: list                      # [(stacja, obwód)]
    miejscowosc: str = ""
    ulica: str = ""
    h_swiatl: tuple = (6.2, 6.2)      # wysokość zawieszenia światłowodu (L, P)
    zwis_swiatl: float = 0.0          # zwis (strzałka) światłowodu [m]
    h_nn: tuple = (7.7, 7.7)          # wysokość zawieszenia istniejącej linii nN (L, P)
    zwis_nn: float = 0.0
    h_slup: tuple = (8.0, 8.0)        # wysokość słupa na rysunku (L, P)
    szer_okna: float | None = None    # szerokość widoku arkusza wzdłuż przęsła (rysunek wyśrodkowany)


@dataclass
class Rysunek:
    encje: list = field(default_factory=list)  # (typ, dict)
    wymiary: list = field(default_factory=list)

    def linia(self, u1, v1, u2, v2, **kw):
        self.encje.append(("LINE", dict(p1=(u1, v1), p2=(u2, v2), **kw)))

    def tekst(self, u, v, h, txt, align=0, **kw):
        self.encje.append(("TEXT", dict(p=(u, v), h=h, txt=txt, align=align, **kw)))


def szer_tekstu(txt: str, h: float) -> float:
    """Przybliżona szerokość tekstu czcionką Arial."""
    waskie = sum(ch in "ilj.,:;!|'1/ -()rtfI" for ch in txt)
    return h * (0.56 * (len(txt) - waskie) + 0.3 * waskie)


def luk_przez(h1, h2, w, s):
    """Łuk od (0,h1) do (w,h2) o strzałce s (prostopadle do cięciwy, w jednostkach rysunku).

    Zwraca (środek, promień, kąt_pocz, kąt_kon, najniższy_punkt)."""
    P1, P2 = (0.0, h1), (w, h2)
    c = math.dist(P1, P2)
    s = max(s, 1e-4)
    r = (c * c / 4 + s * s) / (2 * s)
    mx, my = (P1[0] + P2[0]) / 2, (P1[1] + P2[1]) / 2
    dx, dy = (P2[0] - P1[0]) / c, (P2[1] - P1[1]) / c
    nx, ny = -dy, dx  # normalna "do góry"
    cx, cy = mx + nx * (r - s), my + ny * (r - s)
    a1 = math.degrees(math.atan2(P1[1] - cy, P1[0] - cx)) % 360
    a2 = math.degrees(math.atan2(P2[1] - cy, P2[0] - cx)) % 360
    if 0 <= cx <= w:
        low = (cx, cy - r)
    else:
        low = P1 if h1 < h2 else P2
    return (cx, cy), r, a1, a2, low


def zbuduj(d: Dane) -> Rysunek:
    R = Rysunek()
    L = d.rozp
    w = L * SKALA_X

    # --- linijki (lewa i prawa) z podziałką co 0,1 m ---
    for x0, kier in ((0.0, -1), (w, 1)):
        R.linia(x0, WYS_SIATKI, x0, 0.0)
        for i in range(0, int(round(WYS_SIATKI * 10)) + 1):
            v = i / 10
            dl = 0.5 if i % 10 == 0 else 0.25
            R.linia(x0, v, x0 + kier * dl, v)
    # opisy wysokości
    for m in range(0, int(WYS_SIATKI) + 1):
        R.tekst(-0.72, m - 0.174, 0.4, str(m), align=2)
        R.tekst(w + 0.69, m - 0.174, 0.4, str(m))

    # --- siatka kropkowa: poziomo co 1 m, pionowo co 2 m ---
    u_last = math.floor(w + 1e-9)
    for m in range(0, int(WYS_SIATKI) + 1):
        R.linia(0.0, m, float(u_last) if u_last > 0 else w, m, **KROPKOWA)
    for k in range(1, int(u_last) + 1):
        R.linia(float(k), 0.0, float(k), WYS_SIATKI, **KROPKOWA)
    if abs(w - u_last) > 1e-9:
        R.linia(w, 0.0, w, WYS_SIATKI, **KROPKOWA)

    # --- oś pozioma: linia, podziałka co 0,4 m (0,2 j), opisy co 2 m ---
    R.linia(0.0, 0.0, w, 0.0)
    n = int(math.floor(w / 0.2 + 1e-9))
    for i in range(1, n + 1):
        u = i * 0.2
        R.linia(u, 0.0, u, -0.5 if i % 5 == 0 else -0.25)
    if abs(n * 0.2 - w) > 1e-9:
        R.linia(w, 0.0, w, -0.25)
    for m in range(2, L + 1, 2):
        if m < L or L % 2 == 0:
            R.tekst(m * SKALA_X, -1.076, 0.4, str(m), align=1)
    if L % 2:
        R.tekst(w + 0.15, -1.076, 0.4, str(L), align=1)
    R.linia(0.0, 0.0, w / 2, 0.0, layer="ramka")

    # --- słupy ---
    R.linia(0.0, 0.0, 0.0, d.h_slup[0], lw=100)
    R.linia(w, 0.0, w, d.h_slup[1], lw=100)
    for u in (0.0, w):
        R.encje.append(("MTEXT", dict(p=(u - 0.708, 1.786), h=0.4, txt="SŁUP", width=1.537, attach=1)))
    R.encje.append(("MTEXT", dict(p=(-1.603, 2.102), h=0.28, txt="wysokość zawieszenia przewodu [m]",
                                  width=9.28, attach=1, kier=(0.0, 1.0))))
    # opisy słupów - przesuwane do środka, gdy nie mieszczą się w widoku arkusza
    ul, up = -2.30, w + 0.58
    if d.szer_okna:
        lim_l = w / 2 - d.szer_okna / 2 + 0.3
        lim_p = w / 2 + d.szer_okna / 2 - 0.3
        dl_p = max(szer_tekstu(f"Słup nr {d.slup_p}", 0.4), szer_tekstu(d.typ_p or "", 0.4))
        ul = max(ul, lim_l)
        up = min(up, lim_p - dl_p)
    R.tekst(ul, -0.902, 0.4, f"Słup nr {d.slup_l}")
    R.tekst(ul - 0.034, -1.569, 0.4, d.typ_l or "")
    R.tekst(up, -0.969, 0.4, f"Słup nr {d.slup_p}")
    R.tekst(up - 0.031, -1.574, 0.4, d.typ_p or "")

    # --- legenda ---
    R.linia(0.105, -2.63, 1.036, -2.63, color=KOLOR_SWIATLOWODU, lw=25)
    R.tekst(1.285, -2.82, 0.4, "projektowany światłowód")

    # --- tytuł ---
    y = 9.07
    if len(d.obwody) <= 1:
        for st, ob in d.obwody:
            R.tekst(w / 2, y, 0.3, ob, align=1)
            R.tekst(w / 2, y + 0.56, 0.3, st, align=1)
    else:
        for (st, ob), u in zip(d.obwody, (0.0, w)):
            R.tekst(u, y, 0.3, ob, align=1)
            R.tekst(u, y + 0.56, 0.3, st, align=1)
    yt = y + 1.23
    if d.ulica:
        R.tekst(w / 2, yt, 0.6, d.ulica, align=1)
        yt += 0.87
    if d.miejscowosc:
        R.tekst(w / 2, yt, 0.6, d.miejscowosc, align=1)

    # --- krzywe zwisu ---
    c, r, a1, a2, _ = luk_przez(d.h_nn[0], d.h_nn[1], w, d.zwis_nn)
    R.encje.append(("ARC", dict(c=c, r=r, a1=a1, a2=a2, lw=30)))
    c, r, a1, a2, low = luk_przez(d.h_swiatl[0], d.h_swiatl[1], w, d.zwis_swiatl)
    R.encje.append(("ARC", dict(c=c, r=r, a1=a1, a2=a2, lw=30, color=KOLOR_SWIATLOWODU)))

    # --- wymiar najniższego punktu światłowodu ---
    R.wymiary.append(dict(u=low[0], v=low[1]))
    return R


def obwiednia(R: Rysunek):
    """Obwiednia rysunku w układzie lokalnym (z przybliżoną szerokością tekstów)."""
    us, vs = [], []
    for t, e in R.encje:
        if t == "LINE":
            for k in ("p1", "p2"):
                us.append(e[k][0])
                vs.append(e[k][1])
        elif t == "TEXT":
            u, v = e["p"]
            sz = szer_tekstu(e["txt"], e["h"])
            u0 = u - sz / 2 if e.get("align") == 1 else u - sz if e.get("align") == 2 else u
            us += [u0, u0 + sz]
            vs += [v, v + e["h"]]
        elif t == "MTEXT" and "kier" not in e:
            u, v = e["p"]
            us += [u, u + szer_tekstu(e["txt"], e["h"])]
            vs += [v - e["h"], v]
    return min(us), min(vs), max(us), max(vs)
