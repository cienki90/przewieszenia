#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zapis_dxf - zapis wyników numeracji do pliku DXF (biblioteka ezdxf).

Dla każdego obwodu:
  * wpisuje numery słupów jako TEXT na warstwę  _numery_<stacja>_<obwod>
    (osobna warstwa na obwód - ułatwia robienie zestawień),
  * rysuje OBRYS KONTROLNY obwodu polilinią na warstwie  _kontrola_<stacja>_<obwod>
    - inny kolor dla każdego obwodu, grubość linii 0,5 mm, warstwa NIEDRUKOWALNA.

Obrys kontrolny to łamana prowadzona wzdłuż ścieżki numeracji (rodzic->dziecko):
magistrala + odgałęzienia, dzięki czemu wizualnie widać, które słupy program połączył
w jeden obwód i w jakiej kolejności je ponumerował.

Oryginalny plik NIE jest modyfikowany - wynik zapisywany jest do nowego pliku
(domyślnie "<nazwa> - ponumerowane.dxf").
"""
import os

import ezdxf

from numeracja import _wektor


import math

# paleta kolorów ACI dla kolejnych obwodów (pomijamy biały/czarny 7 i czerwień 1 zarezerw.)
PALETA_ACI = [1, 3, 5, 6, 2, 4, 30, 150, 190, 210, 40, 90, 230, 8, 250, 170]
WYS_TEKSTU = 2.5                   # [j. rysunku] stała wysokość numeru słupa
ODSTEP_OD_LINII = 2.0              # [j. rysunku] odstęp górnej krawędzi cyfry od linii !tele


def _kolor_obwodu(k):
    return PALETA_ACI[k % len(PALETA_ACI)]


def _nazwa_warstwy(prefix, stacja, obwod):
    st = str(stacja).replace(' ', '_')
    return '%s_%s_%s' % (prefix, st, obwod)


def _kierunek_przesla(model, i):
    """Jednostkowy wektor kierunku linii !tele przy słupie i (kierunek przęsła).
    Bierzemy przęsło do najbliższego sąsiada w grafie - lokalny kierunek trasy."""
    p = model.slupy[i]['p']
    sas = list(model.polaczenia[i])
    if not sas:
        return (1.0, 0.0)
    j = min(sas, key=lambda j: math.dist(p, model.slupy[j]['p']))
    q = model.slupy[j]['p']
    vx, vy = q[0] - p[0], q[1] - p[1]
    d = math.hypot(vx, vy)
    if d == 0:
        return (1.0, 0.0)
    return (vx / d, vy / d)


def _cel_wymiaru(model, i):
    """Pozycja NAJBLIŻSZEGO tekstu wymiaru (text_midpoint) przyczepionego do słupa i,
    albo None. To jest punkt, w którego stronę ma iść numer (po stronie wymiarowania)."""
    p = model.slupy[i]['p']
    najl = None
    for L, p1, p2, nadpis, mid in model.wymiary:
        if mid is None:
            continue
        d_end = min(math.dist(p, p1), math.dist(p, p2))
        if d_end > 8.0:
            continue
        d_mid = math.dist(p, mid)
        if najl is None or d_mid < najl[0]:
            najl = (d_mid, mid)
    return najl[1] if najl else None


def _kierunek_odsuniecia(model, i):
    """Jednostkowy wektor PROSTOPADŁY do linii !tele, wskazujący stronę, w którą ma
    iść numer słupa. Znak dobierany BEZWZGLĘDNIE względem rysunku (nie zależy od tego,
    w którą stronę pokazuje lokalny kierunek przęsła):
      * w stronę najbliższego tekstu wymiaru (po tej samej stronie co wymiarowanie),
      * fallback: strona PRZECIWNA do stacji trafo.
    Zwraca (ux, uy)."""
    p = model.slupy[i]['p']
    kx, ky = _kierunek_przesla(model, i)
    nx, ny = -ky, kx                      # jedna z dwóch normalnych
    cel = _cel_wymiaru(model, i)
    if cel is not None:
        rzut = (cel[0] - p[0]) * nx + (cel[1] - p[1]) * ny
    else:
        st = model.stacja_slupa.get(i)
        sp = next((s['p'] for s in model.stacje if s['nr'] == st), None)
        if sp is not None:
            # przeciwnie do stacji: ujemny rzut wektora do stacji
            rzut = -((sp[0] - p[0]) * nx + (sp[1] - p[1]) * ny)
        else:
            rzut = 1.0
    znak = 1.0 if rzut >= 0 else -1.0
    return (nx * znak, ny * znak)


def _ma_wymiar(model, i):
    return _cel_wymiaru(model, i) is not None


def _rozmieszczenie(model, i, ref):
    """Zwraca (punkt_wstawienia, kąt_tekstu_deg, odwrocony) dla numeru słupa i.
    Numer: obrócony zgodnie z kierunkiem linii !tele (czytelny), odsunięty PROSTOPADLE
    od linii po stronie `ref` (strona wymiarowania, jedna dla całego obwodu). Punkt
    wstawienia jest tak dobrany, by GÓRNA krawędź cyfry (bliższa linii) była ODSTEP
    jednostek od linii. `odwrocony` mówi, czy tekst obrócono o 180° (do czytelności) -
    wtedy "góra" tekstu jest po przeciwnej stronie i wyrównanie trzeba odwrócić."""
    p = model.slupy[i]['p']
    kx, ky = _kierunek_przesla(model, i)
    nx, ny = -ky, kx                      # normalna do przęsła
    # dopasuj znak normalnej do ref (strona wymiarowania obwodu)
    if nx * ref[0] + ny * ref[1] < 0:
        nx, ny = -nx, -ny
    px = p[0] + nx * ODSTEP_OD_LINII
    py = p[1] + ny * ODSTEP_OD_LINII
    kat = math.degrees(math.atan2(ky, kx))
    odwrocony = kat <= -90 or kat > 90
    if odwrocony:
        kat += 180.0
    return (px, py), kat, odwrocony


def _sciezka_obwodu(model, ob):
    """Lista krawędzi (i, j) wzdłuż ścieżki numeracji obwodu (rodzic->dziecko).
    Rodzic słupa to słup o numerze bezpośrednio poprzednim, połączony w grafie."""
    numery = ob['slupy']
    nr2idx = {numery[i]: i for i in numery}
    kraw = []
    from numeracja import _num_dziecka  # noqa

    def nr_rodzica(nr):
        cz = nr.split('.')
        if len(cz) > 1 and cz[-1] == '1':
            return '.'.join(cz[:-1])
        n = int(cz[-1]) - 1
        return None if n <= 0 else '.'.join(cz[:-1] + [str(n)])

    for i, nr in numery.items():
        pr = nr_rodzica(nr)
        if pr is not None and pr in nr2idx:
            j = nr2idx[pr]
            if j in model.polaczenia[i]:
                kraw.append((j, i))
    return kraw


def zapisz(model, obwody, sciezka_wej, sciezka_wyj=None):
    """Zapisuje numery i obrysy kontrolne do nowego DXF. Zwraca ścieżkę wyniku."""
    if sciezka_wyj is None:
        baza, _ = os.path.splitext(sciezka_wej)
        sciezka_wyj = baza + ' - ponumerowane.dxf'

    # Startujemy od KOPII oryginału, żeby zachować całą zawartość rysunku.
    doc = ezdxf.readfile(sciezka_wej)
    msp = doc.modelspace()

    # stały, powtarzalny indeks koloru per (stacja, obwod)
    klucze = sorted({(o['stacja'], o['nr_obwodu']) for o in obwody})
    kolor_dla = {k: _kolor_obwodu(i) for i, k in enumerate(klucze)}

    for ob in sorted(obwody, key=lambda o: (o['stacja'], o['nr_obwodu'])):
        st, nr_obw = ob['stacja'], ob['nr_obwodu']
        kolor = kolor_dla[(st, nr_obw)]
        warstwa_num = _nazwa_warstwy('_numery', st, nr_obw)
        warstwa_ctrl = _nazwa_warstwy('_kontrola', st, nr_obw)

        if warstwa_num not in doc.layers:
            doc.layers.add(warstwa_num, color=7)
        if warstwa_ctrl not in doc.layers:
            lay = doc.layers.add(warstwa_ctrl, color=kolor)
            lay.dxf.lineweight = 50     # 0,5 mm (jednostka: setne mm)
            lay.dxf.plot = 0            # warstwa NIEDRUKOWALNA

        # --- referencyjny kierunek odsunięcia obwodu: uśredniony wektor odsunięcia
        #     słupów, które MAJĄ wymiar (wskazuje stronę wymiarowania). Dzięki temu
        #     wszystkie numery obwodu lądują PO TEJ SAMEJ stronie linii, także te,
        #     przy których lokalny kierunek przęsła jest odwrócony.
        ref = [0.0, 0.0]
        for i in ob['slupy']:
            if _ma_wymiar(model, i):
                ux, uy = _kierunek_odsuniecia(model, i)
                ref[0] += ux
                ref[1] += uy
        if ref == [0.0, 0.0]:
            # brak wymiarów w obwodzie - weź odsunięcie startu (przeciwnie do stacji)
            ref = list(_kierunek_odsuniecia(model, ob['start']))

        # --- numery jako TEXT: obrócone zgodnie z !tele, pod linią (strona = ref), wys. 2.5
        #     górna krawędź cyfry (bliższa linii) odsunięta ODSTEP_OD_LINII od !tele
        from ezdxf.enums import TextEntityAlignment
        for i, numer in ob['slupy'].items():
            (px, py), kat, odwrocony = _rozmieszczenie(model, i, (ref[0], ref[1]))
            # wyrównanie w pionie tak, by krawędź cyfry przy linii leżała w punkcie:
            # tekst nieodwrócony -> jego "góra" patrzy od linii -> wyrównaj do TOP;
            # odwrócony o 180° -> "góra" patrzy ku linii -> wyrównaj do BOTTOM
            align = (TextEntityAlignment.BOTTOM_CENTER if odwrocony
                     else TextEntityAlignment.TOP_CENTER)
            txt = msp.add_text(
                numer,
                dxfattribs={'layer': warstwa_num, 'height': WYS_TEKSTU,
                            'color': 7, 'rotation': kat},
            )
            txt.set_placement((px, py), align=align)

        # --- obrys kontrolny: łamana wzdłuż ścieżki numeracji
        for a, b in _sciezka_obwodu(model, ob):
            msp.add_lwpolyline(
                [model.slupy[a]['p'], model.slupy[b]['p']],
                dxfattribs={'layer': warstwa_ctrl, 'color': kolor},
            )

    doc.saveas(sciezka_wyj)
    return sciezka_wyj
