#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
model - interpretacja wczytanego rysunku (Rysunek) na potrzeby auto-numeracji.

Buduje model dziedzinowy:
  * słupy (pozycja, oznaczenie, typ, zakres/stacja),
  * stacje trafo (numer, pozycja, zakres !trafo),
  * graf połączeń (sieć !tele + wymiary),
  * przypisanie słup -> stacja (reguła z zestawienia: zakres !trafo decyduje, a dla
    słupów poza zakresami - najbliższa stacja / drzewo),
  * STARTY obwodów = groty opisów "obw. nr X" (pierwsze przęsło),
  * markery projektanta: słup "1" i słup "2" każdego obwodu (ręczne numery w _numery).

Przynależność słupów do stacji trafo odwzorowuje `generator/zestawienie.py`
(repo przewieszenia): zakres !trafo z rozpoznaną nazwą jest rozstrzygający, inaczej
najbliższa stacja (<= TOL_STACJA) lub pojedynczy opis STACJA TRAFO.
"""
import collections
import math

try:
    from .czytaj_dxf import (RE_OBWOD, RE_SLUP, RE_STACJA, TOL_DUPLIKAT, TOL_STACJA,
                             DOMYSLNE_OZNACZENIE, Rysunek, graf_sieci, graf_wymiarow,
                             w_wielokacie)
except ImportError:  # bezpośrednie uruchomienie bez pakietu
    from czytaj_dxf import (RE_OBWOD, RE_SLUP, RE_STACJA, TOL_DUPLIKAT, TOL_STACJA,
                            DOMYSLNE_OZNACZENIE, Rysunek, graf_sieci, graf_wymiarow,
                            w_wielokacie)

BLAD, UWAGA, INFO = 'BŁĄD', 'UWAGA', 'INFO'


class Model:
    """Zinterpretowany rysunek. Pola:
      slupy      - lista dict {'oz','typ','p','obszar','nr'(opcj.), 'stacja'}
      stacje     - lista dict {'nr','p','obszar'}
      zakres_stacji - {indeks_poligonu_!trafo: nazwa_stacji}
      zakresy    - lista poligonów !trafo
      polaczenia - graf sąsiedztwa (sieć !tele + wymiary) {i: {sąsiedzi}}
      starty     - lista (nr_obwodu, grot) z opisów "obw. nr X"
      stacja_slupa - {i: nazwa_stacji}
      grupy      - {nazwa_stacji: [indeksy słupów]}
      uwagi      - lista komunikatów diagnostycznych
    """

    def __init__(self, rys):
        self.rys = rys
        self.uwagi = rys.uwagi
        self.slupy = []
        self.stacje = []
        self.starty = []
        self.zakresy = rys.zakresy
        self.wymiary = rys.wymiary       # (L, p1, p2, nadpis, text_midpoint|None)
        self.zakres_stacji = {}
        self.polaczenia = collections.defaultdict(set)
        self.stacja_slupa = {}
        self.grupy = collections.defaultdict(list)
        self._zbuduj()

    def _U(self, poziom, opis, i=None, p=None, st=None):
        self.uwagi.append({'poziom': poziom, 'opis': opis, 'slup': i,
                           'p': p if p is not None else (self.slupy[i]['p'] if i is not None else None),
                           'stacja': st})

    def _zbuduj(self):
        rys = self.rys
        slupy, stacje, starty = [], [], []

        # ---------- słupy / stacje / opisy obwodów
        for txt, p in rys.opisy:
            m = RE_SLUP.search(txt)
            if m:
                if any(math.dist(p, s['p']) < TOL_DUPLIKAT for s in slupy):
                    self._U(UWAGA, 'Zdublowany opis słupu "%s" - pominięto duplikat.'
                            % txt.replace('\n', ' '), p=p)
                    continue
                typ = m.group(2).replace(',', '.').replace(' ', '')
                oz = m.group(1) or DOMYSLNE_OZNACZENIE
                slupy.append({'oz': oz, 'typ': typ, 'p': p, 'bez_oz': not m.group(1)})
                continue
            m = RE_STACJA.search(txt)
            if m:
                stacje.append({'nr': m.group(1), 'p': p})
                continue
            m = RE_OBWOD.search(txt)
            if m:
                starty.append((int(m.group(1)), p))

        self.slupy, self.stacje, self.starty = slupy, stacje, starty

        # ---------- zakresy stacji (poligony !trafo)
        def obszar(pt):
            return next((k for k, A in enumerate(rys.zakresy) if w_wielokacie(pt, A)), None)
        self.obszar = obszar

        zakres_stacji = {k: n for k, n in enumerate(rys.nazwy_zakresow) if n}
        for s in stacje:
            s['obszar'] = obszar(s['p'])
            if s['obszar'] is not None:
                if s['obszar'] in zakres_stacji and zakres_stacji[s['obszar']] != s['nr']:
                    self._U(UWAGA, 'Opis stacji %s leży w zakresie stacji %s (warstwa zakresu).'
                            % (s['nr'], zakres_stacji[s['obszar']]), p=s['p'])
                zakres_stacji.setdefault(s['obszar'], s['nr'])
        for s in slupy:
            s['obszar'] = obszar(s['p'])
        self.zakres_stacji = zakres_stacji

        # ---------- numery podane ręcznie (markery projektanta: zwykle tylko 1 i 2)
        self._przypisz_numery()

        num = list(range(len(slupy)))

        # ---------- graf połączeń: sieć !tele + wymiary (uzupełnienie luk)
        sas_sieci = graf_sieci(rys.sieci, slupy, num)
        sas_wym = graf_wymiarow(rys.wymiary, slupy, num)
        polaczenia = collections.defaultdict(set)
        for i in num:
            polaczenia[i] |= sas_sieci.get(i, set())
            polaczenia[i] |= sas_wym.get(i, set())
        self.polaczenia = polaczenia

        # ---------- przypisanie słup -> stacja (reguła z zestawienia, uproszczona:
        # bez odczytanych numerów budujemy przynależność po zakresie !trafo, a dla słupów
        # poza zakresami - po najbliższej stacji / spójnej składowej grafu)
        self._przypisz_stacje(num)

    # -------------------------------------------------- numery ręczne (1 i 2)
    def _przypisz_numery(self):
        """Przypisuje ręczne numery (TEXT z _numery) do najbliższych słupów 1:1,
        tak jak w zestawieniu. W praktyce projektant stawia tylko '1' i '2' na obwód,
        ale obsługujemy dowolne numery (można je wykorzystać do walidacji)."""
        try:
            from .czytaj_dxf import TOL_NUMER
        except ImportError:
            from czytaj_dxf import TOL_NUMER
        slupy, teksty = self.slupy, self.rys.teksty
        pary = sorted((math.dist(tp, s['p']), i, j)
                      for i, (t, tp) in enumerate(teksty)
                      for j, s in enumerate(slupy) if math.dist(tp, s['p']) < TOL_NUMER)
        przyp, zajete = {}, set()
        for d, i, j in pary:
            if i in przyp or j in zajete:
                continue
            przyp[i] = j
            zajete.add(j)
        for i, j in przyp.items():
            slupy[j]['nr'] = teksty[i][0]
            slupy[j]['p_nr'] = teksty[i][1]

    # -------------------------------------------------- przypisanie do stacji
    def _przypisz_stacje(self, num):
        slupy, stacje = self.slupy, self.stacje
        zakres_stacji = self.zakres_stacji

        # spójne składowe grafu połączeń (do przypisania słupów poza zakresami)
        comp = {}
        cid = 0
        for i in num:
            if i in comp:
                continue
            stos = [i]
            while stos:
                x = stos.pop()
                if x in comp:
                    continue
                comp[x] = cid
                stos.extend(j for j in self.polaczenia[x] if j not in comp)
            cid += 1

        # stacja składowej: większość członków, które leżą w zakresie z nazwą
        skl_stacja = {}
        glosy = collections.defaultdict(collections.Counter)
        for i in num:
            obsz = slupy[i].get('obszar')
            if obsz is not None and obsz in zakres_stacji:
                glosy[comp[i]][zakres_stacji[obsz]] += 1
        for c, lic in glosy.items():
            skl_stacja[c] = lic.most_common(1)[0][0]

        def nazwa_stacji(i):
            obsz = slupy[i].get('obszar')
            if obsz is not None and obsz in zakres_stacji:
                return zakres_stacji[obsz]        # zakres !trafo rozstrzyga
            c = comp[i]
            if c in skl_stacja:
                return skl_stacja[c]              # stacja składowej grafu
            # poza zakresami i bez składowej z zakresem -> najbliższa stacja
            if stacje:
                d, s = min((math.dist(slupy[i]['p'], s['p']), s['nr']) for s in stacje)
                if d <= TOL_STACJA or not self.zakresy:
                    return s
            return 'obszar_%d' % (obsz + 1) if obsz is not None else 'nieznana'

        for i in num:
            st = nazwa_stacji(i)
            self.stacja_slupa[i] = st
            self.grupy[st].append(i)


def wczytaj(sciezka):
    """Wczytuje DXF i zwraca gotowy Model."""
    return Model(Rysunek(sciezka))
