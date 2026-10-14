#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
numeracja_obwodow - samodzielna logika numeracji słupów w obwodach.

Wyekstrahowano z generatora zestawień (generator/zestawienie.py, repo przewieszenia).
Moduł jest fundamentem programu do AUTOMATYCZNEGO numerowania słupów: zawiera zarówno
narzędzia do interpretowania ISTNIEJĄCYCH numerów (klucz, numer rodzica, zgodność
połączenia z numeracją), jak i funkcje do:
  * budowy grafu "ciągu logicznego" sieci (z polilinii warstwy !tele + wymiarów),
  * podziału słupów stacji na obwody (gałęzie o ciągłej, niepowtarzalnej numeracji),
  * NADAWANIA numerów słupom w obwodzie (generator numeracji 1, 2, ..., x.1, x.2 ...).

Konwencja numeracji słupów (jak w projektach nN):
  * numer główny:         1, 2, 3, ...            - kolejne słupy wzdłuż obwodu
  * odgałęzienie:         x.1, x.2, ...           - gałąź odchodząca od słupa x
  * zagnieżdżenie:        x.y.1, x.y.2, ...        - odgałęzienie od słupa x.y
  * każdy obwód ma własną numerację od 1 (numery mogą się powtarzać MIĘDZY obwodami,
    nie mogą w obrębie jednego obwodu)

Zależności: tylko biblioteka standardowa (math, collections). Model słupa to zwykły
dict: {'nr': str|None, 'p': (x, y), ...}; funkcje przyjmują listy/sąsiedztwa, więc
łatwo je podłączyć do dowolnego źródła danych (DXF, baza, ręczne wejście).
"""
import collections
import math

# ------------------------------------------------------------- stałe konfiguracyjne
TOL_SIEC = 8.0          # [m] maks. odległość wierzchołka polilinii sieci od słupa


# =============================================================== numery - narzędzia
def klucz(nr):
    """Numer słupa '2.1.3' -> krotka (2, 1, 3) do sortowania/porównań."""
    return tuple(int(x) for x in nr.split('.'))


def nr_rodzica(nr):
    """Numer słupa POPRZEDNIEGO w numeracji:
      '1'    -> None   (początek obwodu)
      '5'    -> '4'    (poprzedni główny)
      '3.1'  -> '3'    (odgałęzienie wychodzi ze słupa 3)
      '3.4'  -> '3.3'  (poprzedni w odgałęzieniu)
    """
    cz = nr.split('.')
    if len(cz) > 1 and cz[-1] == '1':
        return '.'.join(cz[:-1])
    n = int(cz[-1]) - 1
    return None if n <= 0 else '.'.join(cz[:-1] + [str(n)])


def nr_odgalezienia(nr):
    """'2.1' -> '2' (słup, od którego odchodzi odgałęzienie); dla pozostałych None."""
    cz = nr.split('.')
    return '.'.join(cz[:-1]) if len(cz) > 1 and cz[-1] == '1' else None


def dozwolony_rodzic(nr, nr_r, numery):
    """Czy połączenie słupa `nr` ze słupem `nr_r` zgadza się z numeracją.
    `numery` - zbiór numerów już obecnych w tym samym obwodzie.

    Reguły:
      * nr_r jest bezpośrednim poprzednikiem nr                       -> OK
      * nr jest odgałęzieniem (x.1) - musi wychodzić dokładnie ze słupa x
      * brak numeru-rodzica w obwodzie = luka w numeracji             -> odrzuć
      * dopuszczalna kontynuacja numeracji po zakończonym odgałęzieniu
        (np. 1.6 od 1.2, albo 7.4 od 7)
    """
    pn = nr_rodzica(nr)
    if nr_r == pn:
        return True
    if nr_odgalezienia(nr) is not None:
        return False
    if pn not in numery:
        return False
    cz, czr = nr.split('.'), nr_r.split('.')
    if czr == cz[:len(czr)] and len(czr) < len(cz):
        return True
    return czr[:-1] == cz[:-1] and int(czr[-1]) < int(cz[-1])


# =============================================================== graf "ciągu logicznego"
def graf_sieci(sieci, slupy, num, tol=TOL_SIEC):
    """Graf sąsiedztwa słupów z polilinii warstwy sieci (np. !tele).
    Kolejne wierzchołki polilinii, które pokrywają się ze słupami, tworzą krawędź
    słup-słup. To pewniejszy ciąg logiczny niż wymiary (brak dziur w gałęziach).

    sieci  - lista polilinii; każda to lista punktów [(x, y), ...]
    slupy  - lista dictów słupów z kluczem 'p' = (x, y)
    num    - lista indeksów słupów (do grafu bierzemy tylko te)
    Zwraca: defaultdict(set) i -> {sąsiedzi}
    """
    sas = collections.defaultdict(set)
    if not num:
        return sas

    def slup_przy(pt):
        d, j = min((math.dist(pt, slupy[i]['p']), i) for i in num)
        return j if d <= tol else None

    for pts in sieci:
        seq = []
        for pt in pts:
            j = slup_przy(pt)
            if j is not None and (not seq or seq[-1] != j):
                seq.append(j)
        for a, b in zip(seq, seq[1:]):
            if a != b:
                sas[a].add(b)
                sas[b].add(a)
    return sas


def polacz_grafy(*grafy):
    """Suma kilku grafów sąsiedztwa (np. sieć !tele + graf wymiarów)."""
    out = collections.defaultdict(set)
    for g in grafy:
        for i, sasiedzi in g.items():
            out[i] |= set(sasiedzi)
    return out


# =============================================================== podział na obwody
def obwod_od(start, wolne, polaczenia, slupy):
    """BFS po grafie połączeń od słupa `start`; NIE wchodzi na numer już obecny
    w obwodzie - to rozdziela splecione gałęzie przy stacji (dwa słupy "nr 1"
    obok siebie, połączone przęsłem, trafiają do osobnych obwodów).

    start      - indeks słupa startowego (słup "nr 1" danego obwodu)
    wolne      - set indeksów słupów jeszcze nieprzypisanych
    polaczenia - graf sąsiedztwa (sieć + wymiary)
    Zwraca: set indeksów słupów tworzących obwód.
    """
    grupa = {start}
    numery = {slupy[start]['nr']}
    kol = collections.deque([start])
    while kol:
        i = kol.popleft()
        for j in polaczenia[i]:
            if j in wolne and j not in grupa and slupy[j]['nr'] not in numery:
                grupa.add(j)
                numery.add(slupy[j]['nr'])
                kol.append(j)
    return grupa


def podziel_na_obwody(ids, polaczenia, slupy, opisy_obw=None, poz_stacji=None,
                      domyka_numeracja=True):
    """Dzieli słupy jednej stacji na obwody (gałęzie ciągłej numeracji od "nr 1").

    ids         - lista indeksów słupów tej stacji
    polaczenia  - graf sąsiedztwa (sieć !tele + wymiary)
    slupy       - lista dictów słupów ('nr', 'p')
    opisy_obw   - opcjonalnie [(numer_obwodu, punkt_grota)]: grot opisu "obw. nr X"
                  wskazuje pierwsze przęsło -> start obwodu = słup najbliższy grotowi
    poz_stacji  - opcjonalnie (x, y) stacji; używane do kolejności gałęzi bez opisu
    domyka_numeracja - czy dołączać słupy nieosiągalne z grafu po ciągłości numeracji

    Zwraca: (obw_slupa, obw_grup, log)
      obw_slupa - dict indeks_słupa -> numer_obwodu
      obw_grup  - [(numer_obwodu, set(indeksy))]
      log       - lista komunikatów (uwagi/błędy) jako (poziom, opis, indeks|None)
    """
    opisy_obw = opisy_obw or []
    log = []
    wolne = set(ids)
    obw_grup = []
    uzyte_nr = set()

    # 1) obwody wskazane grotem "obw. nr X": start = słup najbliższy grotowi
    for n, grot in sorted(opisy_obw, key=lambda x: x[0]):
        if n in uzyte_nr or not wolne:
            continue
        start = min(wolne, key=lambda i: math.dist(grot, slupy[i]['p']))
        grupa = obwod_od(start, wolne, polaczenia, slupy)
        wolne -= grupa
        obw_grup.append((n, grupa))
        uzyte_nr.add(n)
    powt_opis = len(opisy_obw) != len({n for n, _ in opisy_obw})

    # 2) pozostałe gałęzie bez (rozpoznanego) opisu: każdy wolny "nr 1" = nowy obwód
    while True:
        jedynki = [i for i in wolne if slupy[i]['nr'] == '1']
        if not jedynki:
            break
        start = min(jedynki, key=lambda i: math.dist(slupy[i]['p'], poz_stacji)
                    if poz_stacji else 0.0)
        grupa = obwod_od(start, wolne, polaczenia, slupy)
        wolne -= grupa
        n = min(set(range(1, 1000)) - uzyte_nr)
        uzyte_nr.add(n)
        obw_grup.append((n, grupa))
        if len(obw_grup) > 1 and not powt_opis:
            log.append(('UWAGA', 'Nie rozpoznano opisu "obw. nr" dla tego obwodu - '
                        'przyjęto obwód %d.' % n, start))
    if powt_opis:
        log.append(('UWAGA', 'Powtórzony numer obwodu w opisach - ponumerowano po kolei.', None))

    # 3) domknięcie: słupy nieosiągalne z grafu (luki w sieci) -> po ciągłości numeracji
    if domyka_numeracja:
        numery_grup = [{slupy[i]['nr'] for i in gr} for _, gr in obw_grup]
        zmiana = True
        while zmiana and wolne and obw_grup:
            zmiana = False
            for i in sorted(wolne, key=lambda i: klucz(slupy[i]['nr'])):
                nr = slupy[i]['nr']
                pn = nr_rodzica(nr)
                kand = []
                for k, (_, gr) in enumerate(obw_grup):
                    if nr in numery_grup[k]:
                        continue
                    if pn is not None and pn in numery_grup[k]:
                        d = min(math.dist(slupy[i]['p'], slupy[j]['p']) for j in gr)
                        kand.append((d, k))
                if kand:
                    kand.sort()
                    k = kand[0][1]
                    obw_grup[k][1].add(i)
                    numery_grup[k].add(nr)
                    wolne.discard(i)
                    zmiana = True

    # 4) resztki: słup bez połączenia i bez ciągłości - do najbliższego obwodu z błędem
    for i in sorted(wolne, key=lambda i: klucz(slupy[i]['nr'])):
        if obw_grup:
            k = min(range(len(obw_grup)),
                    key=lambda k: min(math.dist(slupy[i]['p'], slupy[j]['p'])
                                      for j in obw_grup[k][1]))
            obw_grup[k][1].add(i)
            log.append(('BŁĄD', 'Słup nie łączy się siecią ani numeracją z żadnym obwodem - '
                        'dołączono do najbliższego obwodu %d.' % obw_grup[k][0], i))
        else:
            n = min(set(range(1, 1000)) - uzyte_nr)
            uzyte_nr.add(n)
            obw_grup.append((n, {i}))
            log.append(('UWAGA', 'Słup bez połączenia - przyjęto osobny obwód %d.' % n, i))

    obw_slupa = {i: n for n, gr in obw_grup for i in gr}
    return obw_slupa, obw_grup, log


# =============================================================== NADAWANIE numerów
def _wektor(a, b):
    return (b[0] - a[0], b[1] - a[1])


def _dlugosc(v):
    return math.hypot(v[0], v[1])


def _kat_skretu(v_wejscia, v_wyjscia):
    """Kąt [rad] między kierunkiem dojścia a kierunkiem wyjścia (0 = prosto dalej,
    pi = zawrót). Mniejszy kąt = bardziej "na wprost"."""
    la, lb = _dlugosc(v_wejscia), _dlugosc(v_wyjscia)
    if la == 0 or lb == 0:
        return math.pi
    cos = (v_wejscia[0] * v_wyjscia[0] + v_wejscia[1] * v_wyjscia[1]) / (la * lb)
    return math.acos(max(-1.0, min(1.0, cos)))


def nadaj_numery(start, polaczenia, slupy, nalezy=None, poz_stacji=None):
    """AUTOMATYCZNE numerowanie słupów jednego obwodu, zaczynając od `start` (nr 1).

    Idzie wzdłuż grafu `polaczenia` i nadaje numery:
      * ciąg główny:  1, 2, 3, ...  - magistrala prowadzona "NA WPROST",
      * odgałęzienia: gdy ze słupa wychodzi więcej niż jedna nieodwiedzona krawędź,
        boczne gałęzie dostają numerację x.1, x.2, ... (zagnieżdżenia x.y.1 analogicznie).

    Wybór "ciągu głównego" vs "odgałęzienia" (kryterium: NA WPROST):
      W każdym rozwidleniu magistralą jest gałąź o NAJMNIEJSZYM kącie skrętu względem
      kierunku dojścia (słup poprzedni -> bieżący). Na starcie kierunek dojścia to
      wektor od stacji do słupa nr 1 (parametr `poz_stacji`); jeśli stacji nie podano,
      za kierunek startowy bierzemy wektor do najdalszego sąsiada (przybliżenie "dalej
      w sieć"). Boczne gałęzie (większy skręt) stają się odgałęzieniami x.n, kolejność
      bocznych wg rosnącego kąta.

    start      - indeks słupa startowego (dostanie numer '1')
    polaczenia - graf sąsiedztwa
    slupy      - lista dictów z 'p' = (x, y); NIE jest modyfikowana
    nalezy     - opcjonalny set indeksów ograniczający numerację do jednego obwodu
    poz_stacji - opcjonalnie (x, y) stacji; ustala kierunek "na wprost" na starcie
    Zwraca: dict indeks_słupa -> nadany numer (str)
    """
    if nalezy is None:
        nalezy = set()
        stos = [start]
        while stos:
            x = stos.pop()
            if x in nalezy:
                continue
            nalezy.add(x)
            stos.extend(j for j in polaczenia[x] if j not in nalezy)

    numery = {start: '1'}

    def num_dziecka(nr_rodz, kolejny_glowny, idx_galezi):
        """kolejny_glowny=True -> następny numer główny (nr_rodz+1 na tym poziomie);
        False -> odgałęzienie nr_rodz.(idx)."""
        if kolejny_glowny:
            cz = nr_rodz.split('.')
            return '.'.join(cz[:-1] + [str(int(cz[-1]) + 1)])
        return '%s.%d' % (nr_rodz, idx_galezi)

    # kierunek dojścia na starcie: od stacji do słupa nr 1 (jeśli znana),
    # inaczej od najdalszego sąsiada (żeby magistrala poszła "w głąb" sieci)
    if poz_stacji is not None:
        v_start = _wektor(poz_stacji, slupy[start]['p'])
    else:
        sasiedzi = [j for j in polaczenia[start] if j in nalezy]
        if sasiedzi:
            daleki = max(sasiedzi, key=lambda j: math.dist(slupy[start]['p'], slupy[j]['p']))
            v_start = _wektor(slupy[daleki]['p'], slupy[start]['p'])
        else:
            v_start = (1.0, 0.0)

    # DFS: w każdym słupie magistralę kontynuuj najbardziej "na wprost", resztę jako odgałęzienia
    def odwiedz(i, rodzic, v_wejscia):
        dzieci = [j for j in polaczenia[i] if j in nalezy and j != rodzic and j not in numery]
        if not dzieci:
            return
        # sortuj wg kąta skrętu: najmniejszy = magistrala, większe = odgałęzienia
        dzieci.sort(key=lambda j: _kat_skretu(v_wejscia, _wektor(slupy[i]['p'], slupy[j]['p'])))
        glowny = dzieci[0]
        numery[glowny] = num_dziecka(numery[i], True, 0)
        boczne_idx = 1
        for j in dzieci[1:]:
            numery[j] = num_dziecka(numery[i], False, boczne_idx)
            boczne_idx += 1
        for j in dzieci:
            odwiedz(j, i, _wektor(slupy[i]['p'], slupy[j]['p']))

    odwiedz(start, None, v_start)
    return numery


# =============================================================== pomocnicze (demo)
if __name__ == '__main__':
    # Magistrala "na wprost" od stacji. Słup 1 przy stacji, trasa biegnie na wprost
    # w prawo (oś X); od słupa 2 odchodzi w górę krótka odnoga.
    stacja = (-10, 0)
    slupy = [
        {'nr': None, 'p': (0, 0)},    # 0 -> start (nr 1)
        {'nr': None, 'p': (10, 0)},   # 1  -> na wprost
        {'nr': None, 'p': (20, 0)},   # 2  -> na wprost
        {'nr': None, 'p': (10, 10)},  # 3  -> odnoga w górę od słupa 1
    ]
    g = collections.defaultdict(set)
    for a, b in [(0, 1), (1, 2), (1, 3)]:
        g[a].add(b); g[b].add(a)
    print('Demo 1 (na wprost):', nadaj_numery(0, g, slupy, poz_stacji=stacja))
    # oczekiwane: {0:'1', 1:'2', 2:'3', 3:'2.1'} - magistrala prosto, odnoga = 2.1

    # Rozwidlenie: magistrala "na wprost" ma iść prosto, choć odnoga jest DŁUŻSZA.
    stacja2 = (-10, 0)
    slupy2 = [
        {'nr': None, 'p': (0, 0)},    # 0 start
        {'nr': None, 'p': (10, 0)},   # 1 prosto
        {'nr': None, 'p': (20, 0)},   # 2 prosto (magistrala, krótsza)
        {'nr': None, 'p': (10, 10)},  # 3 skręt w górę ...
        {'nr': None, 'p': (10, 20)},  # 4 ... dłuższa odnoga
        {'nr': None, 'p': (10, 30)},  # 5
    ]
    g2 = collections.defaultdict(set)
    for a, b in [(0, 1), (1, 2), (1, 3), (3, 4), (4, 5)]:
        g2[a].add(b); g2[b].add(a)
    print('Demo 2 (na wprost, nie najdłuższa):',
          nadaj_numery(0, g2, slupy2, poz_stacji=stacja2))
    # oczekiwane: magistrala 1-2-3 prosto (0,1,2), odnoga w górę = 2.1, 2.2, 2.3 (idx 3,4,5)
