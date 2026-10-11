"""Odczyt pliku bazy (gotowe rysunki zwisów) i wyznaczenie parametrów do nowych rysunków.

Z każdego rysunku w bazie odczytywane są:
  * rozpiętość przęsła (szerokość siatki, skala pozioma 1:2 -> 1 jednostka = 2 m),
  * typy i wysokości słupów (grube linie słupów),
  * łuk czarny  - istniejąca linia nN (wysokość zawieszenia zależy od typu słupa),
  * łuk zielony - projektowany światłowód (wysokość zawieszenia i zwis zależą od rozpiętości).
Na tej podstawie budowane są tablice: rozpiętość -> (wysokość, zwis) oraz typ słupa -> wysokości.
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict

from dxfio import get, getf, read_tags, split_entities, split_sections

SKALA_X = 0.5  # jednostek rysunku na 1 m (poziomo)


def _moda(vals, nd=3):
    c = Counter(round(v, nd) for v in vals)
    return c.most_common(1)[0][0] if c else None


class Baza:
    def __init__(self, path: str | None):
        self.rysunki = []
        if path:
            self._czytaj(path)
        self._tablice()

    # ------------------------------------------------------------------
    def _czytaj(self, path):
        secs = dict(split_sections(read_tags(path)))
        E = split_entities(secs["ENTITIES"])
        slupy = []
        for t, d in E:
            if t == "LINE" and (get(d, 370) or "").strip() == "100":
                x1, y1, x2, y2 = getf(d, 10), getf(d, 20), getf(d, 11), getf(d, 21)
                if abs(x1 - x2) < 1e-6:  # tylko rysunki poziome
                    slupy.append((x1, min(y1, y2), abs(y2 - y1)))
        luki = []
        for t, d in E:
            if t == "ARC":
                cx, cy, r = getf(d, 10), getf(d, 20), getf(d, 40)
                a1, a2 = math.radians(getf(d, 50)), math.radians(getf(d, 51))
                luki.append(dict(p1=(cx + r * math.cos(a1), cy + r * math.sin(a1)),
                                 p2=(cx + r * math.cos(a2), cy + r * math.sin(a2)),
                                 r=r, ziel=get(d, 62) is not None and get(d, 62).strip() == "3"))
        teksty = [(get(d, 1), getf(d, 10), getf(d, 20)) for t, d in E if t == "TEXT" and get(d, 1)]
        typy = [t for t in teksty if re.match(r"^[A-Z][A-Za-z]*-\d", t[0])]

        uzyte = set()
        slupy.sort()
        for i, (x, y0, h) in enumerate(slupy):
            if i in uzyte:
                continue
            kand = [(x2 - x, j) for j, (x2, y2, h2) in enumerate(slupy)
                    if j != i and j not in uzyte and abs(y2 - y0) < 0.01 and 0 < x2 - x < 120]
            if not kand:
                continue
            w, j = min(kand)
            uzyte |= {i, j}
            ry = dict(rozp=round(w / SKALA_X, 2), h_l=round(h, 3), h_p=round(slupy[j][2], 3))
            for luk in luki:
                (u1, v1), (u2, v2) = luk["p1"], luk["p2"]
                u1, u2, v1, v2 = u1 - x, u2 - x, v1 - y0, v2 - y0
                if abs(min(u1, u2)) < 0.01 and abs(max(u1, u2) - w) < 0.01 and -1 < v1 < 12:
                    hl, hp = (v1, v2) if u1 < u2 else (v2, v1)
                    c = math.hypot(w, hp - hl)
                    s = luk["r"] - math.sqrt(max(luk["r"] ** 2 - c * c / 4, 0))
                    ry["ziel" if luk["ziel"] else "czarny"] = (round(hl, 3), round(hp, 3), s)
            if typy:
                tl = min(typy, key=lambda t: abs(t[1] - (x - 2.3)) + abs(t[2] - (y0 - 1.6)))
                tp = min(typy, key=lambda t: abs(t[1] - (x + w + 0.56)) + abs(t[2] - (y0 - 1.6)))
                if abs(tl[1] - (x - 2.3)) < 1.5 and abs(tl[2] - (y0 - 1.6)) < 1.0:
                    ry["typ_l"] = tl[0]
                if abs(tp[1] - (x + w + 0.56)) < 1.5 and abs(tp[2] - (y0 - 1.6)) < 1.0:
                    ry["typ_p"] = tp[0]
            if "ziel" in ry and abs(ry["rozp"] - round(ry["rozp"])) < 0.01:
                self.rysunki.append(ry)

    # ------------------------------------------------------------------
    def _tablice(self):
        zw = defaultdict(list)       # rozpiętość -> [(wysokość, zwis/m)]
        czarny_k = []
        czarny_tab = defaultdict(list)  # (rozpiętość, h_l, h_p) -> [strzałka]
        typ_drut = defaultdict(list)  # typ słupa -> wysokości linii nN
        typ_slup = defaultdict(list)  # typ słupa -> wysokość słupa na rysunku
        for r in self.rysunki:
            L = int(round(r["rozp"]))
            hl, hp, s = r["ziel"]
            if abs(hl - hp) < 1e-6:
                zw[L].append((hl, s))
            if "czarny" in r:
                chl, chp, cs = r["czarny"]
                czarny_k.append(cs / L)
                czarny_tab[(L, round(chl, 2), round(chp, 2))].append(cs)
                for strona, h in (("l", chl), ("p", chp)):
                    typ = r.get("typ_" + strona)
                    if typ:
                        typ_drut[typ.upper()].append(h)
                        typ_slup[typ.upper()].append(r["h_" + strona])
        self.zwis_tab = {L: (_moda([v[0] for v in vs], 2), _moda([v[1] for v in vs], 4)) for L, vs in zw.items()}
        self.czarny_tab = {k: _moda(v, 4) for k, v in czarny_tab.items()}
        self.k_czarny = round(statistics.median(czarny_k), 4) if czarny_k else 0.017
        self.typ_drut = {t: _moda(v, 2) for t, v in typ_drut.items()}
        self.typ_slup = {t: _moda(v, 2) for t, v in typ_slup.items()}

    # ------------------------------------------------------------------
    def swiatlowod(self, L: int):
        """(wysokość zawieszenia [m], zwis [m]) projektowanego światłowodu dla rozpiętości L [m]."""
        if L in self.zwis_tab:
            return self.zwis_tab[L]
        else:
            # reguła wynikająca z bazy: <=22 m: 6,2 m; 23-40 m: 6,7 m; >40 m: 7,2 m;
            # zwis 3% rozpiętości (do 45 m) lub 2,5% (powyżej 45 m)
            h = 6.2 if L <= 22 else 6.7 if L <= 40 else 7.2
            k = 0.03 if L <= 45 else 0.025
        return h, round(k * L, 4)

    def linia_nn(self, typ: str | None):
        """(wysokość zawieszenia istniejącej linii nN [m], wysokość słupa na rysunku [m])."""
        t = (typ or "").upper()
        dl = re.search(r"-(\d+(?:,\d+)?)/", t)
        dlug = float(dl.group(1).replace(",", ".")) if dl else 10.0
        drut = self.typ_drut.get(t) or (8.2 if dlug >= 10.5 else 7.7)
        slup = self.typ_slup.get(t) or (8.5 if dlug >= 10.5 else 8.0)
        return drut, slup

    def zwis_nn(self, L: int, h_l: float, h_p: float) -> float:
        """Strzałka istniejącej linii nN: z bazy (to samo przęsło i wysokości) lub k * L."""
        s = self.czarny_tab.get((L, round(h_l, 2), round(h_p, 2)))
        if s is None:
            s = self.czarny_tab.get((L, round(h_p, 2), round(h_l, 2)))
        return s if s is not None else round(self.k_czarny * L, 4)
