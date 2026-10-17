# -*- coding: utf-8 -*-
"""Minimalny czytnik TrueType (bez bibliotek zewnętrznych) do OSADZANIA czcionki w PDF.

Potrzebny modułowi „Zakładki” przy zapisie PDF: osadzamy prawdziwą czcionkę .ttf
(DejaVu Sans Bold), żeby polskie znaki (ą ć ę ł ń ś ź ż …) wyświetlały się poprawnie
w KAŻDYM czytniku - także w Adobe Acrobat Reader, który bywa rygorystyczny wobec
glifów bazowych czcionek z tablicą /Differences.

Czytamy tylko to, co potrzebne do złożenia złożonej czcionki (Type0 / CIDFontType2):
  * head  - unitsPerEm oraz bbox (xMin,yMin,xMax,yMax),
  * cmap  - mapowanie Unicode -> numer glifu (GID); obsługa formatu 4 (BMP) i 12,
  * hmtx  - szerokości glifów (advance width),
  * hhea/maxp - liczby potrzebne do odczytu hmtx.
Sam plik .ttf jest osadzany w PDF w całości (FontFile2) - to najprostsze i w pełni
zgodne podejście (bez tworzenia podzbioru glifów).
"""
from __future__ import annotations

import struct


class TTF:
    def __init__(self, data: bytes):
        self.data = data
        self._tabele = {}
        self._czytaj_katalog()
        self.unitsPerEm, self.bbox = self._czytaj_head()
        self.cmap = self._czytaj_cmap()           # {kod_unicode: gid}
        self.hmtx = self._czytaj_hmtx()            # {gid: advance w jednostkach fontu}

    # -- katalog tabel --
    def _czytaj_katalog(self):
        numt = struct.unpack(">H", self.data[4:6])[0]
        off = 12
        for _ in range(numt):
            tag, _csum, o, l = struct.unpack(">4sIII", self.data[off:off + 16])
            off += 16
            self._tabele[tag.decode("latin1")] = (o, l)

    def _tab(self, tag):
        if tag not in self._tabele:
            raise ValueError(f"Czcionka nie ma tabeli {tag!r}.")
        return self._tabele[tag]

    # -- head --
    def _czytaj_head(self):
        o, _l = self._tab("head")
        unitsPerEm = struct.unpack(">H", self.data[o + 18:o + 20])[0]
        xMin, yMin, xMax, yMax = struct.unpack(">hhhh", self.data[o + 36:o + 44])
        return unitsPerEm, (xMin, yMin, xMax, yMax)

    def _indexToLocFormat(self):
        o, _l = self._tab("head")
        return struct.unpack(">h", self.data[o + 50:o + 52])[0]

    # -- cmap (Unicode -> GID): preferuj (3,1) format 4, potem (3,10)/(0,10) format 12 --
    def _czytaj_cmap(self):
        o, _l = self._tab("cmap")
        d = self.data
        ntab = struct.unpack(">H", d[o + 2:o + 4])[0]
        wybrany = None
        for i in range(ntab):
            pid, eid, so = struct.unpack(">HHI", d[o + 4 + i * 8:o + 4 + i * 8 + 8])
            fmt = struct.unpack(">H", d[o + so:o + so + 2])[0]
            # najlepszy: Windows Unicode BMP (3,1) format 4; potem pełny Unicode format 12
            if pid == 3 and eid == 1 and fmt == 4:
                wybrany = (o + so, fmt)
                break
            if fmt == 12 and wybrany is None:
                wybrany = (o + so, fmt)
            if wybrany is None and fmt == 4:
                wybrany = (o + so, fmt)
        if wybrany is None:
            raise ValueError("Czcionka nie ma obsługiwanej podtabeli cmap (format 4/12).")
        start, fmt = wybrany
        return self._cmap_fmt4(start) if fmt == 4 else self._cmap_fmt12(start)

    def _cmap_fmt4(self, o):
        d = self.data
        segX2 = struct.unpack(">H", d[o + 6:o + 8])[0]
        segc = segX2 // 2
        p = o + 14
        endCode = struct.unpack(">%dH" % segc, d[p:p + segX2]); p += segX2 + 2
        startCode = struct.unpack(">%dH" % segc, d[p:p + segX2]); p += segX2
        idDelta = struct.unpack(">%dh" % segc, d[p:p + segX2]); p += segX2
        idRangeBase = p
        idRangeOffset = struct.unpack(">%dH" % segc, d[p:p + segX2])
        mapa = {}
        for i in range(segc):
            s, e = startCode[i], endCode[i]
            if s == 0xFFFF:
                continue
            for c in range(s, e + 1):
                if idRangeOffset[i] == 0:
                    g = (c + idDelta[i]) & 0xFFFF
                else:
                    gi = idRangeBase + i * 2 + idRangeOffset[i] + (c - s) * 2
                    g = struct.unpack(">H", d[gi:gi + 2])[0]
                    if g != 0:
                        g = (g + idDelta[i]) & 0xFFFF
                if g != 0:
                    mapa[c] = g
        return mapa

    def _cmap_fmt12(self, o):
        d = self.data
        ngroups = struct.unpack(">I", d[o + 12:o + 16])[0]
        mapa = {}
        p = o + 16
        for _ in range(ngroups):
            sc, ec, sg = struct.unpack(">III", d[p:p + 12]); p += 12
            for i, c in enumerate(range(sc, ec + 1)):
                mapa[c] = sg + i
        return mapa

    # -- hmtx (GID -> advance) --
    def _czytaj_hmtx(self):
        oh, _ = self._tab("hhea")
        numHM = struct.unpack(">H", self.data[oh + 34:oh + 36])[0]
        om, _ = self._tab("maxp")
        numGlyphs = struct.unpack(">H", self.data[om + 4:om + 6])[0]
        o, _l = self._tab("hmtx")
        d = self.data
        hmtx = {}
        aw = 0
        for g in range(numHM):
            aw, _lsb = struct.unpack(">Hh", d[o + g * 4:o + g * 4 + 4])
            hmtx[g] = aw
        # pozostałe glify mają szerokość ostatniego z pełnych rekordów
        for g in range(numHM, numGlyphs):
            hmtx[g] = aw
        return hmtx

    # -- API dla PDF --
    def gid(self, ch: str) -> int:
        return self.cmap.get(ord(ch), 0)

    def advance_1000(self, ch: str) -> int:
        """Szerokość znaku przeskalowana do jednostek PDF (1000/em)."""
        g = self.gid(ch)
        aw = self.hmtx.get(g, 0)
        return round(aw * 1000.0 / self.unitsPerEm)
