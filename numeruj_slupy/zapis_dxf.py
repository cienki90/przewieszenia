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


def _strona_wymiaru(model, i, kier):
    """Zwraca znak (+1 / -1) strony linii !tele, po której leży NAJBLIŻSZY tekst
    wymiaru (text_midpoint), licząc względem normalnej do kierunku `kier`.
    Gdy brak wymiarów w pobliżu - None (użyjemy strony domyślnej)."""
    p = model.slupy[i]['p']
    nx, ny = -kier[1], kier[0]           # normalna (lewa strona kierunku)
    najl = None
    for L, p1, p2, nadpis, mid in model.wymiary:
        if mid is None:
            continue
        # wymiar dotyczy tego słupa, jeśli któryś koniec jest przy nim
        d_end = min(math.dist(p, p1), math.dist(p, p2))
        if d_end > 8.0:
            continue
        d_mid = math.dist(p, mid)
        if najl is None or d_mid < najl[0]:
            s = (mid[0] - p[0]) * nx + (mid[1] - p[1]) * ny
            najl = (d_mid, s)
    if najl is None:
        return None
    return 1.0 if najl[1] >= 0 else -1.0


def _strona_domyslna_stacji(model, i, kier):
    """Fallback strony, gdy brak wymiaru: strona przeciwna do stacji (opisy słupów
    i wymiary zwykle są po jednej stronie, a numery po drugiej - trzymamy spójność
    w obrębie obwodu). Zwraca +1/-1."""
    p = model.slupy[i]['p']
    nx, ny = -kier[1], kier[0]
    st = model.stacja_slupa.get(i)
    sp = next((s['p'] for s in model.stacje if s['nr'] == st), None)
    if sp is None:
        return -1.0
    s = (sp[0] - p[0]) * nx + (sp[1] - p[1]) * ny
    return -1.0 if s >= 0 else 1.0


def _rozmieszczenie(model, i, strona_obw):
    """Zwraca (punkt_wstawienia, kąt_tekstu_deg) dla numeru słupa i.
    Numer: obrócony zgodnie z kierunkiem linii !tele, odsunięty PROSTOPADLE na stronę
    `strona_obw` (ta sama co wymiarowanie), czytelny (nie do góry nogami)."""
    p = model.slupy[i]['p']
    kx, ky = _kierunek_przesla(model, i)
    nx, ny = -ky, kx                      # normalna (lewa strona kierunku)
    off = WYS_TEKSTU * 1.1                # odsunięcie "pod linię"
    px = p[0] + nx * off * strona_obw
    py = p[1] + ny * off * strona_obw
    kat = math.degrees(math.atan2(ky, kx))
    # czytelność: tekst w zakresie (-90, 90]; obróć o 180° gdy "do góry nogami"
    if kat <= -90 or kat > 90:
        kat += 180.0
    return (px, py), kat


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

        # --- strona obwodu = większościowa strona wymiarowania (spójnie dla całego
        #     obwodu, by numery były po jednej stronie linii, jak przy wymiarach)
        glosy = 0.0
        for i in ob['slupy']:
            kier = _kierunek_przesla(model, i)
            s = _strona_wymiaru(model, i, kier)
            if s is not None:
                glosy += s
        if glosy != 0.0:
            strona_obw = 1.0 if glosy > 0 else -1.0
        else:
            # brak wymiarów - weź stronę przeciwną do stacji (spójną dla startu)
            strona_obw = _strona_domyslna_stacji(model, ob['start'],
                                                 _kierunek_przesla(model, ob['start']))

        # --- numery jako TEXT: obrócone zgodnie z !tele, pod linią, wys. 2.5
        from ezdxf.enums import TextEntityAlignment
        for i, numer in ob['slupy'].items():
            (px, py), kat = _rozmieszczenie(model, i, strona_obw)
            txt = msp.add_text(
                numer,
                dxfattribs={'layer': warstwa_num, 'height': WYS_TEKSTU,
                            'color': 7, 'rotation': kat},
            )
            txt.set_placement((px, py), align=TextEntityAlignment.MIDDLE_CENTER)

        # --- obrys kontrolny: łamana wzdłuż ścieżki numeracji
        for a, b in _sciezka_obwodu(model, ob):
            msp.add_lwpolyline(
                [model.slupy[a]['p'], model.slupy[b]['p']],
                dxfattribs={'layer': warstwa_ctrl, 'color': kolor},
            )

    doc.saveas(sciezka_wyj)
    return sciezka_wyj
