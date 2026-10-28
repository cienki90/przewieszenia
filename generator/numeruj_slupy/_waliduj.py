#!/usr/bin/env python3
"""Walidacja: nadane numery vs istniejące (ground truth) na pliku z pełną numeracją.

Dla uczciwości testu program dostaje tylko starty 'obw. nr X' i markery; porównujemy
nadane numery z numerami już wpisanymi w DXF."""
import sys

try:
    from .model import wczytaj
    from .numeracja import numeruj
except ImportError:
    from model import wczytaj
    from numeracja import numeruj

m = wczytaj(sys.argv[1])
obwody, log = numeruj(m)

print('obwodów:', len(obwody))
zgodne = rozne = bez_gt = 0
szczegoly = []
for ob in sorted(obwody, key=lambda o: (o['stacja'], o['nr_obwodu'])):
    for i, nadany in ob['slupy'].items():
        gt = m.slupy[i].get('nr')
        if gt is None:
            bez_gt += 1
        elif gt == nadany:
            zgodne += 1
        else:
            rozne += 1
            szczegoly.append((ob['stacja'], ob['nr_obwodu'], gt, nadany,
                              round(m.slupy[i]['p'][0], 1), round(m.slupy[i]['p'][1], 1)))

ponumerowane = sum(len(o['slupy']) for o in obwody)
print('ponumerowanych słupów:', ponumerowane, 'z', len(m.slupy))
print('ZGODNE z istniejącymi:', zgodne, ' RÓŻNE:', rozne, ' bez GT:', bez_gt)
print()
print('=== obwody (stacja / nr / liczba słupów / słup2?) ===')
for ob in sorted(obwody, key=lambda o: (o['stacja'], o['nr_obwodu'])):
    s2 = any(m.slupy[i].get('nr') == '2' and i != ob['start'] and i in ob['ids']
             for i in ob['ids'])
    print('  %-10s obw %d  słupów: %3d' % (ob['stacja'], ob['nr_obwodu'], len(ob['slupy'])))
if szczegoly:
    print()
    print('=== ROZBIEŻNOŚCI (stacja, obw, istniejący->nadany, x, y) ===')
    for s in szczegoly[:40]:
        print('   %-10s obw %d  %-6s -> %-6s  @ (%s, %s)' % s)
if log:
    print()
    print('=== log numeracji ===')
    for poz, opis, i in log:
        print('   [%s] %s' % (poz, opis))
