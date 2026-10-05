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
    def __init__(self, path: str, tol_slup: float = 1.0, max_odl_stacji: float = 150.0):
        secs = dict(split_sections(read_tags(path)))
        E = split_entities(secs["ENTITIES"])
        self.ostrzezenia: list[str] = []

        self.slupy = [
            Slup(i, getf(d, 10), getf(d, 20), get(d, 2))
            for i, (t, d) in enumerate([e for e in E if e[0] == "INSERT" and get(e[1], 2) in BLOKI_SLUPOW])
        ]
        numery = [(get(d, 1).strip(), getf(d, 10), getf(d, 20)) for t, d in E
                  if t == "TEXT" and get(d, 8) == WARSTWA_NUMEROW]
        mls = [_mleader(d) + (get(d, 8),) for t, d in E if t == "MULTILEADER"]
        self.okregi = [(getf(d, 10), getf(d, 20), getf(d, 40)) for t, d in E
                       if t == "CIRCLE" and get(d, 8) == WARSTWA_PRZEWIESZEN]
        self.trasy = []
        for t, d in E:
            if t == "LWPOLYLINE" and get(d, 8) == WARSTWA_TRASY:
                xs = [float(v) for k, v in d if k == 10]
                ys = [float(v) for k, v in d if k == 20]
                pts = list(zip(xs, ys))
                if int(get(d, 70, "0")) & 1 and pts:
                    pts.append(pts[0])
                self.trasy.append(pts)

        self._przypisz_numery(numery)
        self._przypisz_typy(mls)
        self._zbuduj_przesla(tol_slup)
        self._obwody(mls, max_odl_stacji)

    # ------------------------------------------------------------------
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

    def _przypisz_typy(self, mls):
        groty = []
        for txt, tips, _ in mls:
            if txt.lower().startswith("słup"):
                typ = txt.split("\n")[-1].strip()
                groty += [(typ, t) for t in tips]
        for s in self.slupy:
            if not groty:
                break
            typ, tip = min(groty, key=lambda g: math.dist((s.x, s.y), g[1]))
            if math.dist((s.x, s.y), tip) < 1.0:
                s.typ = typ

    def _slup_w(self, pt, tol):
        s = min(self.slupy, key=lambda s: math.dist(pt, (s.x, s.y)))
        return s.idx if math.dist(pt, (s.x, s.y)) <= tol else None

    def _zbuduj_przesla(self, tol):
        self.przesla: list[Przeslo] = []
        self.sasiedzi: dict[int, set] = {}
        for pl in self.trasy:
            v = [self._slup_w(p, tol) for p in pl]
            idx = [i for i, x in enumerate(v) if x is not None]
            for i, j in zip(idx, idx[1:]):
                if v[i] == v[j]:
                    continue
                self.przesla.append(Przeslo(v[i], v[j], pl[i:j + 1]))
                self.sasiedzi.setdefault(v[i], set()).add(v[j])
                self.sasiedzi.setdefault(v[j], set()).add(v[i])

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
    def przewieszenia(self) -> list[Przewieszenie]:
        out = []
        for n, (x, y, r) in enumerate(self.okregi, 1):
            if not self.przesla:
                break
            prz = self._przeslo_przy((x, y))
            d = prz.odleglosc((x, y))
            if d > max(r, 5.0):
                self.ostrzezenia.append(
                    f"Przewieszenie {n} ({x:.2f}, {y:.2f}): najbliższe przęsło trasy jest {d:.1f} m od okręgu")
            A, B = self.slupy[prz.a], self.slupy[prz.b]
            if klucz_sortowania(B.numer) < klucz_sortowania(A.numer):
                A, B = B, A
            wsp = A.obwody & B.obwody
            obw = sorted(wsp or (A.obwody | B.obwody))
            for s in (A, B):
                if s.numer is None:
                    self.ostrzezenia.append(f"Przewieszenie {n}: słup ({s.x:.2f}, {s.y:.2f}) bez numeru")
                if s.typ is None:
                    self.ostrzezenia.append(f"Przewieszenie {n}: słup nr {s.numer} bez typu")
            out.append(Przewieszenie(n, x, y, A, B, prz.dlugosc, obw, d))
        return out
