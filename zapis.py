"""Zapis wyniku do DXF (AutoCAD 2013, AC1027) z użyciem nagłówka/tabel/stylów z pliku szablonu.

Z szablonu usuwane są wszystkie obiekty rysunkowe i bloki (poza przestrzeniami modelu/papieru),
a następnie dopisywane są nowe encje z nowymi uchwytami (handle).
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from dxfio import fmt, get, join_entities, read_tags, split_entities, split_sections, write_tags
from rysunek import Rysunek

MODEL = "*Model_Space"


def _owner(d):
    """Właściciel obiektu = pierwszy kod 330 poza grupami 102 {...}."""
    depth = 0
    for c, v in d:
        if c == 102:
            depth += 1 if v.startswith("{") else -1
        elif c == 330 and depth == 0:
            return v
    return None


def _bez_reaktorow(d):
    out, skip = [], False
    for c, v in d:
        if c == 102 and v == "{ACAD_REACTORS":
            skip = True
            continue
        if skip:
            if c == 102 and v == "}":
                skip = False
            continue
        out.append((c, v))
    return out


class Wyjscie:
    def __init__(self, szablon: str):
        secs = split_sections(read_tags(szablon))
        self.kolejnosc = [n for n, _ in secs]
        self.S = dict(secs)
        self.usuniete: set[str] = set()
        self._max = 0
        self._przygotuj()
        self.encje: list = []       # tagi encji modelu
        self.bloki: list = []       # (nazwa, handle_rekordu, tagi encji bloku)
        self.ext = [math.inf, math.inf, -math.inf, -math.inf]
        self._nr_wym = 0

    # ------------------------------------------------------------------
    def _h(self) -> str:
        self._max += 1
        return format(self._max, "X")

    def _przygotuj(self):
        S = self.S
        for name, tags in S.items():
            for c, v in tags:
                if c in (5, 105) and name != "HEADER":
                    try:
                        self._max = max(self._max, int(v, 16))
                    except ValueError:
                        pass
        # ENTITIES -> wszystko usuwamy
        for t, d in split_entities(S["ENTITIES"]):
            h = get(d, 5)
            if h:
                self.usuniete.add(h)
        # TABLES: zostawiamy tylko rekordy bloków przestrzeni modelu/papieru
        T = split_entities(S["TABLES"])
        nowe = []
        self.br_table = None
        self.model_h = None
        for t, d in T:
            if t == "TABLE" and get(d, 2) == "BLOCK_RECORD":
                self.br_table = get(d, 5)
            if t == "BLOCK_RECORD":
                nm = get(d, 2)
                if not (nm.upper().startswith("*MODEL_SPACE") or nm.upper().startswith("*PAPER_SPACE")):
                    self.usuniete.add(get(d, 5))
                    continue
                if nm == MODEL:
                    self.model_h = get(d, 5)
                d = [(c, v) for c, v in d if c != 331]
            if t == "DIMSTYLE":
                d = _bez_reaktorow(d)
            nowe.append((t, d))
        self.tabele = nowe
        # BLOCKS: zostaw bloki należące do zachowanych rekordów
        B = split_entities(S["BLOCKS"])
        self.bloki_szablonu = []
        for t, d in B:
            if _owner(d) in self.usuniete:
                h = get(d, 5)
                if h:
                    self.usuniete.add(h)
                continue
            self.bloki_szablonu.append((t, d))
        # OBJECTS: usuń obiekty należące (pośrednio) do usuniętych encji
        O = split_entities(S["OBJECTS"])
        zmiana = True
        while zmiana:
            zmiana = False
            for t, d in O:
                h = get(d, 5)
                if h and h not in self.usuniete and _owner(d) in self.usuniete:
                    self.usuniete.add(h)
                    zmiana = True
        obj = []
        for t, d in O:
            if get(d, 5) in self.usuniete:
                continue
            if t == "DICTIONARY":
                # usuń wpisy wskazujące na usunięte obiekty
                nd, i = [], 0
                while i < len(d):
                    c, v = d[i]
                    if c == 3 and i + 1 < len(d) and d[i + 1][0] in (350, 360) and d[i + 1][1] in self.usuniete:
                        i += 2
                        continue
                    nd.append((c, v))
                    i += 1
                d = nd
            obj.append((t, d))
        self.obiekty = obj

    # ------------------------------------------------------------------
    def _rozszerz(self, x, y):
        e = self.ext
        e[0], e[1], e[2], e[3] = min(e[0], x), min(e[1], y), max(e[2], x), max(e[3], y)

    @staticmethod
    def _wspolne(h, owner, layer="0", color=None, lt=None, lts=None, lw=None):
        t = [(5, h), (330, owner), (100, "AcDbEntity"), (8, layer)]
        if color is not None:
            t.append((62, f"{color:>6}"))
        if lt:
            t.append((6, lt))
        if lts:
            t.append((48, fmt(lts)))
        if lw is not None:
            t.append((370, f"{lw:>6}"))
        return t

    def _serializuj(self, typ, e, owner, P, rot):
        """Tagi encji po transformacji P (lokalne -> globalne) i obrocie rot [deg]."""
        h = self._h()
        kw = dict(layer=e.get("layer", "0"), color=e.get("color"), lt=e.get("lt"), lts=e.get("lts"), lw=e.get("lw"))
        tags = [(0, typ)] + self._wspolne(h, owner, **kw)
        if typ == "LINE":
            (x1, y1), (x2, y2) = P(*e["p1"]), P(*e["p2"])
            tags += [(100, "AcDbLine"), (10, fmt(x1)), (20, fmt(y1)), (30, "0.0"),
                     (11, fmt(x2)), (21, fmt(y2)), (31, "0.0")]
            pts = [(x1, y1), (x2, y2)]
        elif typ == "ARC":
            cx, cy = P(*e["c"])
            tags += [(100, "AcDbCircle"), (10, fmt(cx)), (20, fmt(cy)), (30, "0.0"), (40, fmt(e["r"])),
                     (100, "AcDbArc"), (50, fmt((e["a1"] + rot) % 360)), (51, fmt((e["a2"] + rot) % 360))]
            pts = []
            for a in (e["a1"], e["a2"]):
                a = math.radians(a + rot)
                pts.append((cx + e["r"] * math.cos(a), cy + e["r"] * math.sin(a)))
        elif typ == "TEXT":
            x, y = P(*e["p"])
            al = e.get("align", 0)
            tags += [(100, "AcDbText"), (10, fmt(x)), (20, fmt(y)), (30, "0.0"), (40, fmt(e["h"])),
                     (1, e["txt"])]
            if rot:
                tags.append((50, fmt(rot)))
            if al:
                tags += [(72, f"{al:>6}"), (11, fmt(x)), (21, fmt(y)), (31, "0.0")]
            tags.append((100, "AcDbText"))
            pts = [(x, y)]
        elif typ == "MTEXT":
            x, y = P(*e["p"])
            kx, ky = e.get("kier", (1.0, 0.0))
            a = math.radians(rot)
            kx, ky = kx * math.cos(a) - ky * math.sin(a), kx * math.sin(a) + ky * math.cos(a)
            tags += [(100, "AcDbMText"), (10, fmt(x)), (20, fmt(y)), (30, "0.0"), (40, fmt(e["h"])),
                     (41, fmt(e.get("width", 0.0))), (46, "0.0"), (71, f"{e.get('attach', 1):>6}"),
                     (72, "     5"), (1, e["txt"]), (73, "     1"), (44, "1.0")]
            if abs(kx - 1) > 1e-9 or abs(ky) > 1e-9:
                tags += [(11, fmt(kx)), (21, fmt(ky)), (31, "0.0")]
            pts = [(x, y)]
        else:
            raise ValueError(typ)
        for p in pts:
            self._rozszerz(*p)
        return tags

    def _wymiar(self, u, v, P, rot):
        """Wymiar pionowy (obrócony) od osi (v=0) do najniższego punktu światłowodu."""
        self._nr_wym += 1
        nazwa = f"*D{self._nr_wym}"
        br = self._h()
        def G(du, dv):
            return P(u + du, dv)
        txt = str(Decimal(f"{v:.6f}").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        asz, tx = 0.18, 0.18
        bt = []
        def ent(typ, extra, layer="0", lw=None):
            t = [(0, typ), (5, self._h()), (330, br), (100, "AcDbEntity"), (8, layer), (62, "     0")]
            if lw is not None:
                t.append((370, f"{lw:>6}"))
            bt.extend(t + extra)
        def line(p, q):
            ent("LINE", [(100, "AcDbLine"), (10, fmt(p[0])), (20, fmt(p[1])), (30, "0.0"),
                         (11, fmt(q[0])), (21, fmt(q[1])), (31, "0.0")], lw=-2)
        # linie pomocnicze (od punktów do linii wymiarowej)
        line(G(0.055, v), G(0.18, v))
        line(G(-0.095, 0.0), G(0.18, 0.0))
        # linia wymiarowa z przerwą na tekst
        mid = v / 2
        line(G(0, v - asz), G(0, mid + tx))
        line(G(0, asz), G(0, mid - tx))
        # groty
        for tip, base in ((v, v - asz), (0.0, asz)):
            p1, p2, p3 = G(0.03, base), G(-0.03, base), G(0, tip)
            ent("SOLID", [(100, "AcDbTrace"), (10, fmt(p1[0])), (20, fmt(p1[1])), (30, "0.0"),
                          (11, fmt(p2[0])), (21, fmt(p2[1])), (31, "0.0"),
                          (12, fmt(p3[0])), (22, fmt(p3[1])), (32, "0.0"),
                          (13, fmt(p3[0])), (23, fmt(p3[1])), (33, "0.0")])
        m = G(0, mid)
        ent("MTEXT", [(100, "AcDbMText"), (10, fmt(m[0])), (20, fmt(m[1])), (30, "0.0"), (40, fmt(tx)),
                      (41, "0.0"), (46, "0.0"), (71, "     5"), (72, "     1"), (1, "\\A1;" + txt),
                      (73, "     1"), (44, "1.0")], lw=25)
        for p in (G(-0.008, v), G(-0.158, 0.0), G(0, 0.0)):
            ent("POINT", [(100, "AcDbPoint"), (10, fmt(p[0])), (20, fmt(p[1])), (30, "0.0")], layer="Defpoints")
        self.bloki.append((nazwa, br, bt))
        # encja DIMENSION w modelu
        p10, p11, p13, p14 = G(0, 0.0), G(0, mid), G(-0.008, v), G(-0.158, 0.0)
        tags = [(0, "DIMENSION")] + self._wspolne(self._h(), self.model_h, lw=25) + [
            (100, "AcDbDimension"), (280, "     0"), (2, nazwa),
            (10, fmt(p10[0])), (20, fmt(p10[1])), (30, "0.0"),
            (11, fmt(p11[0])), (21, fmt(p11[1])), (31, "0.0"),
            (70, "    32"), (71, "     5"), (42, fmt(v)), (1, txt), (73, "     0"), (74, "     0"), (75, "     0"),
            (3, "Standard"), (100, "AcDbAlignedDimension"),
            (13, fmt(p13[0])), (23, fmt(p13[1])), (33, "0.0"),
            (14, fmt(p14[0])), (24, fmt(p14[1])), (34, "0.0"),
            (50, fmt((90.0 + rot) % 360)), (100, "AcDbRotatedDimension")]
        self.encje.extend(tags)

    def dodaj(self, R: Rysunek, x0: float, y0: float, rot: int = 0):
        """Wstawia rysunek: lokalny (0,0) -> (x0,y0), obrót 0 lub 90 stopni (CCW)."""
        if rot == 0:
            P = lambda u, v: (x0 + u, y0 + v)
        elif rot == 90:
            P = lambda u, v: (x0 - v, y0 + u)
        else:
            raise ValueError("obsługiwany obrót: 0 lub 90")
        for typ, e in R.encje:
            self.encje.extend(self._serializuj(typ, e, self.model_h, P, rot))
        for w in R.wymiary:
            self._wymiar(w["u"], w["v"], P, rot)

    # ------------------------------------------------------------------
    def zapisz(self, path: str):
        S = self.S
        # TABLES + nowe rekordy bloków wymiarów
        tab = list(self.tabele)
        out_tab = []
        cur_table = None
        for t, d in tab:
            if t == "TABLE":
                cur_table = get(d, 2)
                if cur_table == "BLOCK_RECORD":
                    n = sum(1 for tt, _ in tab if tt == "BLOCK_RECORD") + len(self.bloki)
                    d = [(c, (f"{n:>6}" if c == 70 else v)) for c, v in d]
            if t == "ENDTAB" and cur_table == "BLOCK_RECORD":
                for nazwa, br, _ in self.bloki:
                    out_tab.append(("BLOCK_RECORD", [(5, br), (330, self.br_table), (100, "AcDbSymbolTableRecord"),
                                                     (100, "AcDbBlockTableRecord"), (2, nazwa), (340, "0"),
                                                     (70, "     0"), (280, "     1"), (281, "     0")]))
            out_tab.append((t, d))
        blk = list(self.bloki_szablonu)
        for nazwa, br, bt in self.bloki:
            blk.append(("BLOCK", [(5, self._h()), (330, br), (100, "AcDbEntity"), (8, "0"), (100, "AcDbBlockBegin"),
                                  (2, nazwa), (70, "     1"), (10, "0.0"), (20, "0.0"), (30, "0.0"), (3, nazwa),
                                  (1, "")]))
            blk_tags = bt
            blk.extend(split_entities(blk_tags))
            blk.append(("ENDBLK", [(5, self._h()), (330, br), (100, "AcDbEntity"), (8, "0"),
                                   (100, "AcDbBlockEnd")]))
        # HEADER
        hdr = list(S["HEADER"])
        nowe_h = format(self._max + 1, "X")
        for i, (c, v) in enumerate(hdr):
            if c == 9 and v == "$HANDSEED":
                hdr[i + 1] = (5, nowe_h)
            if c == 9 and v in ("$EXTMIN", "$EXTMAX") and self.ext[0] < math.inf:
                xs = (self.ext[0], self.ext[1]) if v == "$EXTMIN" else (self.ext[2], self.ext[3])
                hdr[i + 1] = (10, fmt(xs[0]))
                hdr[i + 2] = (20, fmt(xs[1]))
        sekcje = {"HEADER": hdr, "TABLES": join_entities(out_tab), "BLOCKS": join_entities(blk),
                  "ENTITIES": self.encje, "OBJECTS": join_entities(self.obiekty)}
        tags = []
        for name in self.kolejnosc:
            tags += [(0, "SECTION"), (2, name)] + sekcje.get(name, S[name]) + [(0, "ENDSEC")]
        tags.append((0, "EOF"))
        write_tags(path, tags)
