#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
numeruj - automatyczna numeracja słupów nN w rysunku DXF.

Program czyta rysunek DXF, w którym projektant zaznaczył DWA pierwsze słupy każdego
obwodu (ręczne numery "1" i "2" na warstwie _numery) oraz opis "obw. nr X" (grot
wskazuje pierwsze przęsło). Resztę słupów program numeruje sam:
  * magistrala "na wprost" (najmniejszy kąt skrętu), kierunek z pary słup 1 -> słup 2,
  * odgałęzienia x.1, x.2 ... numerowane od lewej strony magistrali,
  * każdy obwód = osobna numeracja od 1, ograniczona stacją trafo i innymi startami.

Wynik zapisywany do nowego pliku DXF:
  * numery jako TEXT na warstwach  _numery_<stacja>_<obwod>,
  * obrys kontrolny obwodu na warstwach _kontrola_<stacja>_<obwod> (inny kolor,
    0,5 mm, warstwa NIEDRUKOWALNA).

Użycie:
  python numeruj.py plik.dxf [-o wynik.dxf]
  python numeruj.py                 (okno wyboru pliku - GUI)
"""
import argparse
import os
import sys

from model import wczytaj
from numeracja import numeruj as _numeruj
from zapis_dxf import zapisz


def przetworz(dxf, wyjscie=None):
    """Pełny przebieg: wczytanie -> numeracja -> zapis DXF. Zwraca (ścieżka, raport)."""
    model = wczytaj(dxf)
    obwody, log = _numeruj(model)
    wynik = zapisz(model, obwody, dxf, wyjscie)

    ile_slupow = sum(len(o['slupy']) for o in obwody)
    raport = ['%s -> %s' % (os.path.basename(dxf), os.path.basename(wynik))]
    raport.append('   stacji: %d   obwodów: %d   ponumerowanych słupów: %d / %d'
                  % (len(model.grupy), len(obwody), ile_slupow, len(model.slupy)))
    for ob in sorted(obwody, key=lambda o: (o['stacja'], o['nr_obwodu'])):
        raport.append('   %-14s obw %d:  %3d słupów' % (ob['stacja'], ob['nr_obwodu'],
                                                        len(ob['slupy'])))
    if ile_slupow < len(model.slupy):
        raport.append('   UWAGA: %d słupów nie trafiło do żadnego obwodu '
                      '(brak opisu "obw. nr" lub markerów 1/2?).'
                      % (len(model.slupy) - ile_slupow))
    for poziom, opis, _ in log:
        raport.append('   [%s] %s' % (poziom, opis))
    return wynik, '\n'.join(raport)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Automatyczna numeracja słupów nN w DXF.')
    ap.add_argument('dxf', nargs='*', help='plik(i) DXF do ponumerowania')
    ap.add_argument('-o', '--wyjscie', help='ścieżka pliku wynikowego (gdy jeden plik)')
    args = ap.parse_args(argv)

    if not args.dxf:
        try:
            from gui import gui
        except Exception as e:
            print('Brak plików i nie udało się uruchomić GUI:', e)
            return 2
        gui()
        return 0

    for dxf in args.dxf:
        if not os.path.isfile(dxf):
            print('Nie znaleziono pliku:', dxf)
            continue
        try:
            _, raport = przetworz(dxf, args.wyjscie if len(args.dxf) == 1 else None)
            print(raport)
        except Exception as e:
            print('BŁĄD przy %s: %s' % (dxf, e))
    return 0


if __name__ == '__main__':
    sys.exit(main())
