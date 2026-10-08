"""Analiza pliku planu: lokalizacje przewieszeń (okręgi), słupy, numery, typy, obwody i stacje."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from dxfio import get, getf, mtext_plain, read_tags, seg_dist, split_entities, split_sections

# --- domyślne nazwy warstw / bloków (można zmienić parametrami programu) ---
WARSTWA_PRZEWIESZEN = "_PRZEWIESZENIA"
WARSTWA_TRASY = "!TELE"          # polilinie trasy światłowodu
WARSTWA_NUMEROW = "_numery"       # teksty z numerami słupów
BLOKI_SLUPOW = ("ZN", "E", "R")   # bloki symboli słupów nN


@dataclass
class Slup:
    idx: int
    x: float
    y: float
    blok: str
    numer: str | None = None
    typ: str | None = None
    obwody: set = field(default_factory=set)  # {(stacja, obwód)}


@dataclass
class Przeslo:
    a: int          # indeks słupa
    b: int
    sciezka: list   # punkty trasy od a do b

    @property
    def dlugosc(self) -> float:
        return sum(math.dist(p, q) for p, q in zip(self.sciezka, self.sciezka[1:]))

    def odleglosc(self, pt) -> float:
        return min(seg_dist(pt, p, q) for p, q in zip(self.sciezka, self.sciezka[1:]))


@dataclass
class Przewieszenie:
    nr: int
    x: float
    y: float
    slup_l: Slup
    slup_p: Slup
    dlugosc: float
    obwody: list  # [(stacja, obwód)]
    odl_od_trasy: float


def _mleader(d):
    """Zwraca (tekst, [punkty grotów]) dla MULTILEADER."""
    txt = mtext_plain(get(d, 304, "") or "")
    linie, cur = [], None
    for i, (k, v) in enumerate(d):
        if k == 304 and v == "LEADER_LINE{":
            cur = []
            linie.append(cur)
        elif k == 305:
            cur = None
        elif cur is not None and k == 10:
            cur.append((float(v), float(d[i + 1][1])))
    return txt, [ln[0] for ln in linie if ln]


def _klucz(n):
    if n and re.fullmatch(r"\d+(\.\d+)*", n):
        return tuple(int(x) for x in n.split("."))
    return None


def _nastepny(p, q) -> bool:
    """Czy słup q jest kolejnym po p w numeracji obwodu (np. 3->4, 2->2.1, 2.3->2.4)."""
    P, Q = _klucz(p), _klucz(q)
    if P is None or Q is None:
        return False
    if len(Q) == len(P) + 1 and Q[:-1] == P and Q[-1] == 1:
        return True
    return len(Q) == len(P) and Q[:-1] == P[:-1] and Q[-1] == P[-1] + 1


def klucz_sortowania(n):
    k = _klucz(n)
    return (0, k) if k is not None else (1, (n or "",))


class Plan:
    def __init__(self, path: str, tol_slup: float = 2.0, max_odl_stacji: float = 150.0):
        secs = dict(split_sections(read_tags(path)))
        E = split_entities(secs["ENTITIES"])
        self.ostrzezenia: list[str] = []

        # bloki - słupy mogą być wstawione bezpośrednio (ZN/E/R) albo zagnieżdżone w innym bloku
        # (np. blok "q" = słup ZN + opis typu); rozwijamy wstawienia rekurencyjnie
        bloki, cur = {}, None
        for t, d in split_entities(secs["BLOCKS"]):
            if t == "BLOCK":
                cur = get(d, 2)
                bloki[cur] = (getf(d, 10, 0.0), getf(d, 20, 0.0), [])
            elif t == "ENDBLK":
                cur = None
            elif cur is not None:
                bloki[cur][2].append((t, d))
        slupy, mls = [], []
        for t, d in E:
            if t == "INSERT":
                self._rozwin(d, bloki, slupy, mls, (0.0, 0.0, 1.0, 1.0, 0.0), 0)
            elif t == "MULTILEADER":
                mls.append(_mleader(d) + (get(d, 8),))
        # usuń duplikaty (ten sam słup wstawiony dwa razy)
        uniq = []
        for x, y, b in slupy:
            if all(math.dist((x, y), (u[0], u[1])) > 0.05 for u in uniq):
                uniq.append((x, y, b))
        self.slupy = [Slup(i, x, y, b) for i, (x, y, b) in enumerate(uniq)]
        numery = [(get(d, 1).strip(), getf(d, 10), getf(d, 20)) for t, d in E
                  if t == "TEXT" and get(d, 8) == WARSTWA_NUMEROW and (get(d, 1) or "").strip()]
        # znaczniki przewieszeń: okręgi oraz kreski (LINE / LWPOLYLINE) przecinające przęsło
        self.znaczniki = []
        for t, d in E:
            if get(d, 8) != WARSTWA_PRZEWIESZEN:
                continue
            if t == "CIRCLE":
                self.znaczniki.append(("O", (getf(d, 10), getf(d, 20)), getf(d, 40)))
            elif t == "LINE":
                self.znaczniki.append(("K", [(getf(d, 10), getf(d, 20)), (getf(d, 11), getf(d, 21))], 0.0))
            elif t == "LWPOLYLINE":
                pts = list(zip([float(v) for k, v in d if k == 10], [float(v) for k, v in d if k == 20]))
                if len(pts) >= 2:
                    self.znaczniki.append(("K", pts, 0.0))
        self.okregi = [(z[1][0], z[1][1], z[2]) for z in self.znaczniki if z[0] == "O"]
        # obszary stacji: zamknięte polilinie na warstwach "!trafo_<nr stacji>"
        self.obszary = []
        for t, d in E:
            L = get(d, 8) or ""
            if t == "LWPOLYLINE" and L.lower().startswith("!trafo_"):
                pts = list(zip([float(v) for k, v in d if k == 10], [float(v) for k, v in d if k == 20]))
                if len(pts) >= 3:
                    self.obszary.append(("ST " + L[7:].strip(), pts))
        self.trasy = []
        for t, d in E:
            if t == "LWPOLYLINE" and get(d, 8) == WARSTWA_TRASY:
                xs = [float(v) for k, v in d if k == 10]
                ys = [float(v) for k, v in d if k == 20]
                pts = list(zip(xs, ys))
                if int(get(d, 70, "0")) & 1 and pts:
                    pts.append(pts[0])
                self.trasy.append(pts)

        # wymiary przęseł (np. warstwa !wymiary): punkty definicyjne 13/14 przy słupach, wartość 42 lub tekst
        self.wymiary = []
        for t, d in E:
            if t == "DIMENSION" and get(d, 13) is not None and get(d, 14) is not None:
                v = getf(d, 42)
                txt = (get(d, 1) or "").strip()
                try:
                    if txt and txt != "<>":
                        v = float(re.sub(r"\\[A-Za-z][^;]*;", "", txt).replace(",", ".").split()[0])
                except ValueError:
                    pass
                self.wymiary.append((v, (getf(d, 13), getf(d, 23)), (getf(d, 14), getf(d, 24))))
        self._przypisz_numery(numery)
        self._przypisz_typy(mls, tol=max(2.0, tol_slup))
        self._zbuduj_przesla(tol_slup)
        self._obwody(mls, max_odl_stacji)

    # ------------------------------------------------------------------
    @staticmethod
    def _rozwin(d, bloki, slupy, mls, xf, glebokosc):
        """Rozwija wstawienie bloku: zbiera słupy (x, y, blok) i multileadery (tekst, groty) w układzie świata.

        xf = (ox, oy, sx, sy, rot) - przekształcenie bloku nadrzędnego."""
        def swiat(x, y, xf):
            ox, oy, sx, sy, r = xf
            x, y = x * sx, y * sy
            c, s = math.cos(r), math.sin(r)
            return ox + x * c - y * s, oy + x * s + y * c

        nazwa = get(d, 2)
        x, y = swiat(getf(d, 10, 0.0), getf(d, 20, 0.0), xf)
        if nazwa in BLOKI_SLUPOW:
            slupy.append((x, y, nazwa))
            return
        if nazwa not in bloki or glebokosc > 5:
            return
        bx, by, ents = bloki[nazwa]
        sx = getf(d, 41, 1.0) * xf[2]
        sy = getf(d, 42, 1.0) * xf[3]
        rot = math.radians(getf(d, 50, 0.0)) + xf[4]
        # punkt bazowy bloku przesuwa zawartość
        c, s = math.cos(rot), math.sin(rot)
        ox = x - (bx * sx * c - by * sy * s)
        oy = y - (bx * sx * s + by * sy * c)
        nxf = (ox, oy, sx, sy, rot)
        for t, e in ents:
            if t == "INSERT":
                Plan._rozwin(e, bloki, slupy, mls, nxf, glebokosc + 1)
            elif t == "MULTILEADER":
                txt, tips = _mleader(e)
                mls.append((txt, [swiat(px, py, nxf) for px, py in tips], get(e, 8)))

    def _przypisz_numery(self, numery):
        """Przypisanie numerów do słupów - dopasowanie minimalizujące sumę odległości."""
        pary = sorted(
            (math.dist((s.x, s.y), (t[1], t[2])), s.idx, j)
            for s in self.slupy for j, t in enumerate(numery)
            if math.dist((s.x, s.y), (t[1], t[2])) < 15
        )
        przyp, uzyte = {}, set()
        for _, i, j in pary:
            if i not in przyp and j not in uzyte:
                przyp[i] = j
                uzyte.add(j)
        # poprawa zamianami par (2-opt) - np. gdy numer leży pomiędzy dwoma słupami
        pos = {j: (t[1], t[2]) for j, t in enumerate(numery)}
        P = {s.idx: (s.x, s.y) for s in self.slupy}
        zmiana = True
        while zmiana:
            zmiana = False
            klucze = list(przyp)
            for ia, a in enumerate(klucze):
                for b in klucze[ia + 1:]:
                    if math.dist(P[a], P[b]) > 30:
                        continue
                    ja, jb = przyp[a], przyp[b]
                    teraz = math.dist(P[a], pos[ja]) + math.dist(P[b], pos[jb])
                    nowe = math.dist(P[a], pos[jb]) + math.dist(P[b], pos[ja])
                    if nowe < teraz - 1e-9:
                        przyp[a], przyp[b] = jb, ja
                        zmiana = True
            # wolne numery bliżej niż przypisane
            wolne = set(range(len(numery))) - set(przyp.values())
            for a in klucze:
                for j in list(wolne):
                    if math.dist(P[a], pos[j]) < math.dist(P[a], pos[przyp[a]]) - 1e-9:
                        # tylko jeśli żaden inny słup nie jest bliżej tego numeru
                        if all(math.dist(P[a], pos[j]) <= math.dist(P[o], pos[j]) for o in P if o != a):
                            wolne.add(przyp[a])
                            wolne.discard(j)
                            przyp[a] = j
                            zmiana = True
        for i, j in przyp.items():
            self.slupy[i].numer = numery[j][0]

    def _przypisz_typy(self, mls, tol=2.0):
        groty = []
        for txt, tips, _ in mls:
            if txt.lower().startswith("słup"):
                typ = txt.split("\n")[-1].strip()
                groty += [(typ, t) for t in tips]
        for s in self.slupy:
            if not groty:
                break
            typ, tip = min(groty, key=lambda g: math.dist((s.x, s.y), g[1]))
            if math.dist((s.x, s.y), tip) < tol:
                s.typ = typ

    def _slup_w(self, pt, tol):
        s = min(self.slupy, key=lambda s: math.dist(pt, (s.x, s.y)))
        return s.idx if math.dist(pt, (s.x, s.y)) <= tol else None

    def _zbuduj_przesla(self, tol):
        """Przęsła = odcinki trasy między kolejnymi słupami leżącymi NA trasie
        (w wierzchołku albo w dowolnym miejscu odcinka, z tolerancją tol)."""
        self.przesla: list[Przeslo] = []
        self.sasiedzi: dict[int, set] = {}
        for pl in self.trasy:
            if len(pl) < 2:
                continue
            xs = [p[0] for p in pl]
            ys = [p[1] for p in pl]
            bb = (min(xs) - tol, min(ys) - tol, max(xs) + tol, max(ys) + tol)
            kand = [s for s in self.slupy if bb[0] <= s.x <= bb[2] and bb[1] <= s.y <= bb[3]]
            # kilometraż wierzchołków
            km = [0.0]
            for a, b in zip(pl, pl[1:]):
                km.append(km[-1] + math.dist(a, b))
            na_trasie = []  # (kilometraż, idx słupa, punkt)
            for s in kand:
                best = None
                for k, (a, b) in enumerate(zip(pl, pl[1:])):
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    L2 = dx * dx + dy * dy
                    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((s.x - a[0]) * dx + (s.y - a[1]) * dy) / L2))
                    q = (a[0] + t * dx, a[1] + t * dy)
                    dd = math.dist((s.x, s.y), q)
                    if dd <= tol and (best is None or dd < best[0]):
                        best = (dd, km[k] + t * math.sqrt(L2), q, k)
                if best:
                    na_trasie.append((best[1], s.idx, best[2], best[3]))
            na_trasie.sort()
            for (m1, a, p1, k1), (m2, b, p2, k2) in zip(na_trasie, na_trasie[1:]):
                if a == b or m2 - m1 < 0.5:
                    continue
                sciezka = [p1] + pl[k1 + 1:k2 + 1] + [p2]
                self.przesla.append(Przeslo(a, b, sciezka))
                self.sasiedzi.setdefault(a, set()).add(b)
                self.sasiedzi.setdefault(b, set()).add(a)

    def _przeslo_przy(self, pt):
        return min(self.przesla, key=lambda p: p.odleglosc(pt))

    def _obwody(self, mls, max_odl):
        stacje = [(t.split("\n")[-1].strip(), tips[0]) for t, tips, _ in mls
                  if "STACJA" in t.upper() and tips]
        S = self.slupy
        for txt, tips, _ in mls:
            if not txt.lower().startswith("obw") or not tips:
                continue
            tip = tips[0]
            obw = txt.strip()
            if stacje:
                st, pos = min(stacje, key=lambda s: math.dist(s[1], tip))
                stn = "ST " + st if math.dist(pos, tip) <= max_odl else "ST ?"
            else:
                stn = "ST ?"
            strefa = self.stacja_w(tip)
            if strefa:
                stn = strefa
            prz = self._przeslo_przy(tip)
            a, b = prz.a, prz.b
            if _nastepny(S[b].numer, S[a].numer):
                a, b = b, a
            galaz_a = None
            if _nastepny(S[a].numer, S[b].numer):
                start = [a, b]
                galaz_a = a  # z pierwszego słupa przęsła dozwolone tylko odgałęzienia (n -> n.1)
            else:
                # przęsło nie jest ciągłe w numeracji - początek obwodu to słup bliższy opisowi
                start = [min((a, b), key=lambda i: math.dist((S[i].x, S[i].y), tip))]
            # przejście po trasie zgodnie z ciągłością numeracji (1 -> 2 -> 2.1 -> 2.2 ...)
            odw = set(start)
            stos = list(start)
            while stos:
                q = stos.pop()
                S[q].obwody.add((stn, obw))
                for r in self.sasiedzi.get(q, ()):
                    if r in odw:
                        continue
                    if q == galaz_a:
                        K, R_ = _klucz(S[q].numer), _klucz(S[r].numer)
                        if not (K and R_ and len(R_) == len(K) + 1 and R_[:-1] == K):
                            continue
                    if _nastepny(S[q].numer, S[r].numer) or S[r].numer is None or S[q].numer is None:
                        odw.add(r)
                        stos.append(r)
        # słupy bez obwodu: składowe spójne -> obwód najbliższego słupa z obwodem
        bez = {s.idx for s in S if not s.obwody and s.idx in self.sasiedzi}
        z = [s for s in S if s.obwody]
        while bez and z:
            start = bez.pop()
            comp, stos = {start}, [start]
            while stos:
                u = stos.pop()
                for r in self.sasiedzi.get(u, ()):
                    if r in bez:
                        bez.discard(r)
                        comp.add(r)
                        stos.append(r)
            best = min(((math.dist((S[c].x, S[c].y), (o.x, o.y)), o) for c in comp for o in z),
                       key=lambda t: t[0])[1]
            for c in comp:
                S[c].obwody = set(best.obwody)

    # ------------------------------------------------------------------
    def dlugosc_przesla(self, A, B, prz, tol=4.0):
        """Długość przęsła: z wymiaru narysowanego między słupami, a gdy go brak - z długości trasy."""
        a, b = (A.x, A.y), (B.x, B.y)
        best = None
        for v, p, q in self.wymiary:
            e = min(math.dist(p, a) + math.dist(q, b), math.dist(p, b) + math.dist(q, a))
            if e < tol and v and (best is None or e < best[0]):
                best = (e, v)
        return best[1] if best else prz.dlugosc

    def stacja_w(self, pt):
        """Stacja, w której obszarze (!trafo_<nr>) leży punkt; None gdy żadna."""
        x, y = pt
        for nazwa, P in self.obszary:
            wew = False
            for (x1, y1), (x2, y2) in zip(P, P[1:] + P[:1]):
                if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    wew = not wew
            if wew:
                return nazwa
        return None

    @staticmethod
    def _przeciecie(a, b, c, d):
        """Punkt przecięcia odcinków ab i cd albo None."""
        r = (b[0] - a[0], b[1] - a[1])
        q = (d[0] - c[0], d[1] - c[1])
        den = r[0] * q[1] - r[1] * q[0]
        if abs(den) < 1e-12:
            return None
        t = ((c[0] - a[0]) * q[1] - (c[1] - a[1]) * q[0]) / den
        u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
        if 0 <= t <= 1 and 0 <= u <= 1:
            return a[0] + t * r[0], a[1] + t * r[1]
        return None

    def _trafienia(self, zn):
        """Lista (przęsło, punkt, odległość) wskazanych znacznikiem."""
        typ, geo, r = zn
        if typ == "O":
            prz = self._przeslo_przy(geo)
            return [(prz, geo, prz.odleglosc(geo))]
        out = []
        for prz in self.przesla:
            for c, d in zip(geo, geo[1:]):
                for a, b in zip(prz.sciezka, prz.sciezka[1:]):
                    p = self._przeciecie(a, b, c, d)
                    if p and all(prz is not o[0] for o in out):
                        out.append((prz, p, 0.0))
        if not out:  # kreska nie przecina trasy - najbliższe przęsło do środka kreski
            m = geo[len(geo) // 2 - 1]
            m = ((m[0] + geo[len(geo) // 2][0]) / 2, (m[1] + geo[len(geo) // 2][1]) / 2)
            prz = self._przeslo_przy(m)
            out.append((prz, m, prz.odleglosc(m)))
        return out

    def przewieszenia(self) -> list[Przewieszenie]:
        out = []
        n = 0
        for zn in self.znaczniki:
            if not self.przesla:
                break
            for prz, (x, y), d in self._trafienia(zn):
                limit = max(zn[2], 5.0) if zn[0] == "O" else 5.0
                if d > limit:
                    self.ostrzezenia.append(
                        f"Pominięto znacznik w ({x:.2f}, {y:.2f}): nie leży na trasie {WARSTWA_TRASY} "
                        f"(najbliższe przęsło {d:.1f} m dalej)")
                    continue
                if any({o.slup_l.idx, o.slup_p.idx} == {prz.a, prz.b} for o in out):
                    self.ostrzezenia.append(f"Pominięto powtórzone zaznaczenie przęsła w ({x:.2f}, {y:.2f})")
                    continue
                n += 1
                A, B = self.slupy[prz.a], self.slupy[prz.b]
                if klucz_sortowania(B.numer) < klucz_sortowania(A.numer):
                    A, B = B, A
                wsp = A.obwody & B.obwody
                obw = sorted(wsp or (A.obwody | B.obwody))
                strefa = self.stacja_w(prz.sciezka[len(prz.sciezka) // 2]) or self.stacja_w((x, y))
                if strefa:
                    obw = [(strefa if st in ("ST ?", "") else st, ob) for st, ob in obw] or [(strefa, "")]
                for s_ in (A, B):
                    if s_.numer is None:
                        self.ostrzezenia.append(f"Przewieszenie {n}: słup ({s_.x:.2f}, {s_.y:.2f}) bez numeru")
                    if s_.typ is None:
                        self.ostrzezenia.append(f"Przewieszenie {n}: słup nr {s_.numer} bez typu")
                out.append(Przewieszenie(n, x, y, A, B, self.dlugosc_przesla(A, B, prz), obw, d))
        return out
