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


# paleta kolorów ACI dla kolejnych obwodów (pomijamy biały/czarny 7 i czerwień 1 zarezerw.)
PALETA_ACI = [1, 3, 5, 6, 2, 4, 30, 150, 190, 210, 40, 90, 230, 8, 250, 170]
WYS_TEKSTU_DOMYSLNA = 2.5          # [j. rysunku] fallback wysokości numeru


def _kolor_obwodu(k):
    return PALETA_ACI[k % len(PALETA_ACI)]


def _wysokosc_tekstu(model):
    """Wysokość numeru = mediana wysokości istniejących TEXT-ów numerów, jeśli znana;
    inaczej wartość domyślna. (Model nie przechowuje wysokości - używamy heurystyki
    opartej na rozstawie słupów, by numer był czytelny przy dowolnej skali.)"""
    # heurystyka: ~ 1/8 mediany długości przęsła
    import math
    dl = []
    for i, s in enumerate(model.slupy):
        for j in model.polaczenia[i]:
            if j > i:
                dl.append(math.dist(s['p'], model.slupy[j]['p']))
    if not dl:
        return WYS_TEKSTU_DOMYSLNA
    dl.sort()
    med = dl[len(dl) // 2]
    return max(1.0, round(med / 8.0, 2))


def _nazwa_warstwy(prefix, stacja, obwod):
    st = str(stacja).replace(' ', '_')
    return '%s_%s_%s' % (prefix, st, obwod)


def _odsuniecie(model, i, numery):
    """Mały wektor odsunięcia numeru od słupa (w stronę przeciwną do rodzica),
    by numer nie nachodził na symbol słupa. Zwraca (dx, dy)."""
    import math
    p = model.slupy[i]['p']
    # kierunek: od sąsiadów (średnia) - odsuwamy "na zewnątrz"
    sas = [j for j in model.polaczenia[i] if numery.get(j)]
    if not sas:
        return (0.0, 0.0)
    sx = sum(model.slupy[j]['p'][0] - p[0] for j in sas) / len(sas)
    sy = sum(model.slupy[j]['p'][1] - p[1] for j in sas) / len(sas)
    d = math.hypot(sx, sy)
    if d == 0:
        return (0.0, 0.0)
    h = _wysokosc_tekstu(model)
    return (-sx / d * h * 1.2, -sy / d * h * 1.2)


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
    wys = _wysokosc_tekstu(model)

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

        # --- numery jako TEXT
        for i, numer in ob['slupy'].items():
            px, py = model.slupy[i]['p']
            dx, dy = _odsuniecie(model, i, ob['slupy'])
            msp.add_text(
                numer,
                dxfattribs={'layer': warstwa_num, 'height': wys, 'color': 7},
            ).set_placement((px + dx, py + dy))

        # --- obrys kontrolny: łamana wzdłuż ścieżki numeracji
        for a, b in _sciezka_obwodu(model, ob):
            msp.add_lwpolyline(
                [model.slupy[a]['p'], model.slupy[b]['p']],
                dxfattribs={'layer': warstwa_ctrl, 'color': kolor},
            )

    doc.saveas(sciezka_wyj)
    return sciezka_wyj
