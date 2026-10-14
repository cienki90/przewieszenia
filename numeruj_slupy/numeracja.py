#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
numeracja - AUTOMATYCZNE nadawanie numerów słupom na podstawie markerów projektanta.

Wejście (Model z model.py):
  * graf połączeń (sieć !tele + wymiary),
  * starty obwodów = groty opisów "obw. nr X" (słup "1" = najbliższy grotowi),
  * markery kierunku: słup "2" = ręczny numer '2' przy słupie sąsiednim do "1".

Dla każdego obwodu:
  1) start = słup "1" (najbliższy grotowi "obw. nr X"),
  2) GRANICA obwodu: BFS po grafie, który NIE przekracza innego startowego słupa "1"
     (ani cudzego słupa "2") - to rozdziela splecione obwody przy wspólnej stacji,
  3) kierunek magistrali "na wprost" = wektor słup "1" -> słup "2" (gdy "2" wskazany),
     inaczej wektor od stacji do słupa "1" (jak w numeracja_obwodow.nadaj_numery),
  4) numeracja: magistrala 1,2,3,... (najmniejszy kąt skrętu), boczne gałęzie x.1,x.2...

Rdzeń algorytmu numerowania (kąt skrętu = magistrala "na wprost") pochodzi z modułu
`numeracja_obwodow` (funkcje _wektor/_kat_skretu/num_dziecka). Tutaj dołożony jest wybór
startu/kierunku z markerów oraz granica obwodu wg innych startów.
"""
import collections
import math


def _wektor(a, b):
    return (b[0] - a[0], b[1] - a[1])


def _dlugosc(v):
    return math.hypot(v[0], v[1])


def _kat_skretu(v_wej, v_wyj):
    """Kąt [rad] między kierunkiem dojścia a wyjścia (0 = prosto, pi = zawrót)."""
    la, lb = _dlugosc(v_wej), _dlugosc(v_wyj)
    if la == 0 or lb == 0:
        return math.pi
    cos = (v_wej[0] * v_wyj[0] + v_wej[1] * v_wyj[1]) / (la * lb)
    return math.acos(max(-1.0, min(1.0, cos)))


def _num_dziecka(nr_rodz, glowny, idx):
    if glowny:
        cz = nr_rodz.split('.')
        return '.'.join(cz[:-1] + [str(int(cz[-1]) + 1)])
    return '%s.%d' % (nr_rodz, idx)


def _strona(v_mag, v):
    """Iloczyn wektorowy: >0 = lewa strona magistrali (CCW), <0 = prawa (CW)."""
    return v_mag[0] * v[1] - v_mag[1] * v[0]


def _starty_stacji(model, st, ids):
    """Zwraca listę (nr_obwodu, start_idx, grot) dla stacji `st`.

    Grot opisu "obw. nr X" wskazuje PIERWSZE PRZĘSŁO (odcinek słup "1"-słup "2"), więc
    geometrycznie może wypaść bliżej słupa "2" niż "1". Dlatego START obwodu to słup
    oznaczony ręcznie numerem "1" NAJBLIŻSZY grotowi (a nie dowolny najbliższy słup).
    Gdy w tej stacji nie ma słupa "1" przy grocie, w ostateczności bierzemy najbliższy
    słup grotowi (z uwagą)."""
    obszar = model.obszar
    sp = next((s['p'] for s in model.stacje if s['nr'] == st), None)

    def grot_tej_stacji(p):
        o = obszar(p)
        if o is not None and model.zakres_stacji.get(o) == st:
            return True
        return sp is not None and math.dist(p, sp) < 150.0 and o is None

    jedynki = [i for i in ids if model.slupy[i].get('nr') == '1']
    starty = []
    uzyte = set()
    for n, grot in sorted(model.starty, key=lambda x: x[0]):
        if not grot_tej_stacji(grot):
            continue
        kand1 = [i for i in jedynki if i not in uzyte]
        if kand1:
            start = min(kand1, key=lambda i: math.dist(grot, model.slupy[i]['p']))
        else:
            kand = [i for i in ids if i not in uzyte]
            if not kand:
                continue
            start = min(kand, key=lambda i: math.dist(grot, model.slupy[i]['p']))
        starty.append((n, start, grot))
        uzyte.add(start)
    return starty


def _slup2(model, start, obwod_ids, grot=None):
    """Słup '2' obwodu (kierunek magistrali). Priorytet:
      1) sąsiad słupa start (w grafie) z ręcznym numerem '2',
      2) słup '2' w obwodzie najbliższy grotowi (gdy sieć ma lukę przy starcie),
      3) None (brak - kierunek zostanie wzięty od stacji).
    """
    sas2 = [j for j in model.polaczenia[start]
            if j in obwod_ids and model.slupy[j].get('nr') == '2']
    if sas2:
        if grot is not None:
            return min(sas2, key=lambda j: math.dist(grot, model.slupy[j]['p']))
        return sas2[0]
    kand = [j for j in obwod_ids if model.slupy[j].get('nr') == '2' and j != start]
    if kand:
        ref = grot if grot is not None else model.slupy[start]['p']
        return min(kand, key=lambda j: math.dist(ref, model.slupy[j]['p']))
    return None


def _obwod_bfs(model, start, dozwolone, blokady):
    """BFS po grafie od `start` w obrębie `dozwolone` (słupy tej stacji), NIE wchodząc
    na słup z `blokady` (inne starty / cudze '2'). Zwraca zbiór indeksów obwodu."""
    grupa = {start}
    kol = collections.deque([start])
    while kol:
        i = kol.popleft()
        for j in model.polaczenia[i]:
            if j in dozwolone and j not in grupa and j not in blokady:
                grupa.add(j)
                kol.append(j)
    return grupa


def nadaj_numery_obwod(model, start, obwod_ids, slup2=None):
    """Nadaje numery słupom jednego obwodu. Zwraca {idx: 'numer'}.
    Kierunek magistrali: start -> slup2 (gdy podany), inaczej od stacji do startu."""
    slupy = model.slupy
    numery = {start: '1'}

    if slup2 is not None:
        v_start = _wektor(slupy[start]['p'], slupy[slup2]['p'])
    else:
        st = model.stacja_slupa.get(start)
        sp = next((s['p'] for s in model.stacje if s['nr'] == st), None)
        if sp is not None:
            v_start = _wektor(sp, slupy[start]['p'])
        else:
            sasiedzi = [j for j in model.polaczenia[start] if j in obwod_ids]
            if sasiedzi:
                daleki = max(sasiedzi, key=lambda j: math.dist(slupy[start]['p'], slupy[j]['p']))
                v_start = _wektor(slupy[daleki]['p'], slupy[start]['p'])
            else:
                v_start = (1.0, 0.0)

    def odwiedz(i, rodzic, v_wej):
        dzieci = [j for j in model.polaczenia[i]
                  if j in obwod_ids and j != rodzic and j not in numery]
        if not dzieci:
            return
        # magistrala = gałąź najbardziej "na wprost" (najmniejszy kąt skrętu)
        dzieci.sort(key=lambda j: _kat_skretu(v_wej, _wektor(slupy[i]['p'], slupy[j]['p'])))
        glowny = dzieci[0]
        boczne = dzieci[1:]
        # boczne odgałęzienia numerujemy OD LEWEJ STRONY magistrali (CCW) - ta reguła
        # odtwarza w 100% ręczną numerację projektanta (walidacja na zofinin - PZT: 135/135)
        v_mag = _wektor(slupy[i]['p'], slupy[glowny]['p'])
        boczne.sort(key=lambda j: -_strona(v_mag, _wektor(slupy[i]['p'], slupy[j]['p'])))
        numery[glowny] = _num_dziecka(numery[i], True, 0)
        for k, j in enumerate(boczne, start=1):
            numery[j] = _num_dziecka(numery[i], False, k)
        for j in [glowny] + boczne:
            odwiedz(j, i, _wektor(slupy[i]['p'], slupy[j]['p']))

    odwiedz(start, None, v_start)
    return numery


def _ostatni_magistrali(numery):
    """Zwraca (idx, numer) słupa o najwyższym numerze GŁÓWNYM (bez kropki) - koniec
    magistrali, od którego kontynuujemy numerację po przerwie w sieci !tele."""
    glowne = [(int(nr), i) for i, nr in numery.items() if '.' not in nr]
    if not glowne:
        return None, None
    n, i = max(glowne)
    return i, str(n)


def _kontynuuj_od(model, wejscie, start, obwod_ids, nr_startowy):
    """Numeruje doczepiony ciąg jako kontynuację magistrali, zaczynając od słupa `start`
    numerem `nr_startowy` i idąc "w głąb" ciągu (kierunek dojścia = `wejscie`->start).
    Zwraca {idx: numer}. Rozgałęzienia w ciągu numeruje jak zwykle (x.1, x.2 od lewej)."""
    slupy = model.slupy
    numery = {start: str(nr_startowy)}
    v_start = _wektor(slupy[wejscie]['p'], slupy[start]['p']) if wejscie is not None \
        else _wektor(slupy[start]['p'], slupy[start]['p'])

    def odwiedz(i, rodzic, v_wej):
        dzieci = [j for j in model.polaczenia[i]
                  if j in obwod_ids and j != rodzic and j not in numery]
        if not dzieci:
            return
        dzieci.sort(key=lambda j: _kat_skretu(v_wej, _wektor(slupy[i]['p'], slupy[j]['p'])))
        glowny = dzieci[0]
        boczne = dzieci[1:]
        v_mag = _wektor(slupy[i]['p'], slupy[glowny]['p'])
        boczne.sort(key=lambda j: -_strona(v_mag, _wektor(slupy[i]['p'], slupy[j]['p'])))
        numery[glowny] = _num_dziecka(numery[i], True, 0)
        for k, j in enumerate(boczne, start=1):
            numery[j] = _num_dziecka(numery[i], False, k)
        for j in [glowny] + boczne:
            odwiedz(j, i, _wektor(slupy[i]['p'], slupy[j]['p']))

    odwiedz(start, None, v_start)
    return numery


def numeruj(model):
    """Numeruje wszystkie obwody rysunku. Zwraca:
      obwody - lista dict {'stacja','nr_obwodu','start','slupy':{idx:numer}, 'ids':set}
      log    - lista komunikatów (poziom, opis, idx|None)
    """
    log = []
    obwody = []

    for st in sorted(model.grupy):
        ids = model.grupy[st]
        starty = _starty_stacji(model, st, ids)

        if not starty:
            # brak opisu "obw. nr X" dla tej stacji - przyjmij słupy '1' jako starty
            jedynki = [i for i in ids if model.slupy[i].get('nr') == '1']
            if not jedynki:
                log.append((('UWAGA'), 'Stacja %s: brak opisu "obw. nr" i brak słupa "1" '
                            '- pomijam.' % st, None))
                continue
            sp = next((s['p'] for s in model.stacje if s['nr'] == st), None)
            jedynki.sort(key=lambda i: math.dist(model.slupy[i]['p'], sp) if sp else 0.0)
            starty = [(k + 1, i, None) for k, i in enumerate(jedynki)]
            log.append(('UWAGA', 'Stacja %s: brak opisów "obw. nr" - obwody ponumerowano '
                        'po kolei od słupów "1".' % st, None))

        start_idx = {s for _, s, _ in starty}

        for nr_obw, start, grot in starty:
            # blokady = inne starty tej stacji + słupy '2' innych obwodów
            inne_starty = start_idx - {start}
            dozwolone = set(ids)
            obwod_ids = _obwod_bfs(model, start, dozwolone, inne_starty)
            slup2 = _slup2(model, start, obwod_ids, grot)
            # usuń z obwodu cudze '2' (gdyby BFS je złapał mimo blokady startów)
            cudze2 = {s2 for o, so, go in starty if o != nr_obw
                      for s2 in [_slup2(model, so, obwod_ids, go)] if s2 is not None}
            obwod_ids -= (cudze2 - {slup2} if slup2 else cudze2)

            if slup2 is None:
                log.append(('UWAGA', 'Obwód %s/%d: nie znaleziono słupa "2" (kierunku) '
                            '- magistrala poprowadzona od stacji.' % (st, nr_obw), start))

            przyp = nadaj_numery_obwod(model, start, obwod_ids, slup2)
            obwody.append({'stacja': st, 'nr_obwodu': nr_obw, 'start': start,
                           'grot': grot, 'slupy': przyp, 'ids': set(przyp)})

        # ---------- zszycie przerw w sieci !tele (reguła projektanta):
        # słupy w zakresie !trafo tej stacji, które zostały wolne (oderwany ciąg, bo
        # linia !tele ma przerwę i NIE ma wymiaru), doczepiamy do obwodu kontynuując
        # numerację magistrali. Dopasowanie: najbliższy WOLNY KONIEC ciągu do ostatniego
        # słupa magistrali danego obwodu (w obrębie tej samej stacji).
        _zszyj_przerwy(model, st, ids, obwody, log)

    return obwody, log


def _zszyj_przerwy(model, st, ids, obwody, log):
    """Doczepia wolne słupy (w zakresie !trafo stacji st) do obwodów, kontynuując
    numerację magistrali od ostatniego ponumerowanego słupa."""
    obwody_st = [o for o in obwody if o['stacja'] == st]
    if not obwody_st:
        return

    def wolne_w_zakresie():
        objete = set()
        for o in obwody_st:
            objete |= o['ids']
        wolne = set()
        for i in ids:
            if i in objete:
                continue
            # tylko słupy leżące w zakresie !trafo z nazwą tej stacji (pewna przynależność)
            obsz = model.slupy[i].get('obszar')
            if obsz is not None and model.zakres_stacji.get(obsz) == st:
                wolne.add(i)
        return wolne

    postep = True
    while postep:
        postep = False
        wolne = wolne_w_zakresie()
        if not wolne:
            break

        # spójne składowe wolnych słupów (oderwane ciągi)
        skladowe = []
        poz = set(wolne)
        while poz:
            s0 = next(iter(poz))
            gr, stos = set(), [s0]
            while stos:
                x = stos.pop()
                if x in gr:
                    continue
                gr.add(x)
                poz.discard(x)
                stos.extend(j for j in model.polaczenia[x] if j in poz)
            skladowe.append(gr)

        # najlepsze dopasowanie (ostatni słup magistrali obwodu <-> wolny koniec ciągu)
        najlepsze = None   # (dystans, obwod, koniec_idx, skladowa)
        for ob in obwody_st:
            io, no = _ostatni_magistrali(ob['slupy'])
            if io is None:
                continue
            po = model.slupy[io]['p']
            for gr in skladowe:
                konce = [i for i in gr if sum(1 for j in model.polaczenia[i] if j in gr) <= 1]
                if not konce:
                    konce = list(gr)
                for k in konce:
                    d = math.dist(po, model.slupy[k]['p'])
                    if najlepsze is None or d < najlepsze[0]:
                        najlepsze = (d, ob, k, gr, io, int(no))
        if najlepsze is None:
            break

        d, ob, koniec, gr, io, no = najlepsze
        przyp = _kontynuuj_od(model, io, koniec, gr, no + 1)
        ob['slupy'].update(przyp)
        ob['ids'] |= set(przyp)
        log.append(('UWAGA', 'Obwód %s/%d: przerwa w sieci !tele - doczepiono %d słup(ów) '
                    'z zakresu stacji (kontynuacja numeracji od nr %d, luka %.0f m).'
                    % (st, ob['nr_obwodu'], len(przyp), no + 1, d), koniec))
        postep = True
