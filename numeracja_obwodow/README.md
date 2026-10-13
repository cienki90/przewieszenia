# numeracja_obwodow

Samodzielna logika **numeracji słupów w obwodach**, wyekstrahowana z generatora
zestawień (`generator/zestawienie.py`, repo `przewieszenia`). Fundament pod nowy
program do **automatycznego numerowania** słupów.

Zależności: tylko biblioteka standardowa Pythona (`math`, `collections`).

## Konwencja numeracji

| Wzorzec        | Znaczenie                                             |
|----------------|-------------------------------------------------------|
| `1, 2, 3, ...` | kolejne słupy wzdłuż obwodu (magistrala)              |
| `x.1, x.2`     | odgałęzienie odchodzące od słupa `x`                  |
| `x.y.1`        | odgałęzienie zagnieżdżone (od słupa `x.y`)            |

Każdy obwód ma **własną** numerację od `1`. Numery mogą się powtarzać między
obwodami, nie mogą w obrębie jednego obwodu.

## Model danych

Słup = zwykły `dict`: `{'nr': str|None, 'p': (x, y), ...}`. Funkcje operują na
listach słupów i grafach sąsiedztwa `{indeks: {sąsiedzi}}`, więc źródło danych
(DXF, baza, wejście ręczne) jest dowolne.

## Funkcje

### Narzędzia numerów
- `klucz(nr)` – `'2.1.3'` → `(2, 1, 3)` do sortowania/porównań.
- `nr_rodzica(nr)` – numer słupa poprzedniego (`'3.1'`→`'3'`, `'5'`→`'4'`, `'1'`→`None`).
- `nr_odgalezienia(nr)` – `'2.1'`→`'2'` (słup, od którego odchodzi gałąź).
- `dozwolony_rodzic(nr, nr_r, numery)` – czy połączenie zgadza się z numeracją.

### Graf „ciągu logicznego"
- `graf_sieci(sieci, slupy, num, tol)` – graf sąsiedztwa z polilinii warstwy sieci
  (np. `!tele`); pewniejszy niż wymiary (brak dziur w gałęziach).
- `polacz_grafy(*grafy)` – suma grafów (np. sieć + wymiary).

### Podział na obwody (dla ISTNIEJĄCYCH numerów)
- `obwod_od(start, wolne, polaczenia, slupy)` – BFS gałęzi; nie wchodzi na numer
  już użyty w obwodzie (rozdziela dwa obwody startujące od sąsiednich „nr 1").
- `podziel_na_obwody(ids, polaczenia, slupy, opisy_obw, poz_stacji)` – pełny podział
  słupów stacji na obwody; grot opisu „obw. nr X" wskazuje start obwodu.

### Nadawanie numerów (sedno nowego programu)
- `nadaj_numery(start, polaczenia, slupy, nalezy, poz_stacji)` – automatycznie numeruje
  słupy jednego obwodu od `start` (= `'1'`): magistrala `1,2,3,...`, boczne gałęzie
  `x.1, x.2, ...`. `poz_stacji` ustala kierunek „na wprost" na starcie.

## Kryterium magistrali: NA WPROST, zgodnie z kierunkiem od stacji

`nadaj_numery` prowadzi **ciąg główny (magistralę) „na wprost"**: w każdym rozwidleniu
kontynuacją jest gałąź o **najmniejszym kącie skrętu** względem kierunku dojścia
(słup poprzedni → bieżący). Na starcie kierunkiem dojścia jest wektor **od stacji do
słupa nr 1** (parametr `poz_stacji`). Gałęzie o większym skręcie stają się
odgałęzieniami `x.1, x.2, ...` (kolejność wg rosnącego kąta).

Dzięki temu magistrala idzie trasą „na wprost" **nawet jeśli odnoga jest dłuższa** –
patrz Demo 2 poniżej.

Alternatywne kryteria (do podmiany funkcji sortującej `dzieci` w `nadaj_numery`,
reszta logiki bez zmian): najdłuższa gałąź, warstwa/typ słupa itp.

## Szybki start

```python
import collections
from numeracja_obwodow import nadaj_numery

stacja = (-10, 0)
slupy = [{'nr': None, 'p': (i * 10, 0)} for i in range(3)]  # trasa prosto w prawo
slupy.append({'nr': None, 'p': (10, 10)})                    # odnoga w górę od środka
g = collections.defaultdict(set)
for a, b in [(0, 1), (1, 2), (1, 3)]:
    g[a].add(b); g[b].add(a)

print(nadaj_numery(0, g, slupy, poz_stacji=stacja))
# {0: '1', 1: '2', 2: '3', 3: '2.1'}  - magistrala na wprost, odnoga = 2.1
```

Uruchom `python3 numeracja_obwodow.py`, aby zobaczyć wbudowane demo (w tym przypadek,
gdy magistrala idzie na wprost mimo dłuższej odnogi).

## Pochodzenie

Skopiowano i uporządkowano z `generator/zestawienie.py` (branch `program-polaczony`):
reguły numeracji, budowa grafu `!tele`, podział na obwody (BFS z regułą braku
powtórki numeru) oraz nowy generator `nadaj_numery` (odwrotny kierunek: z gałęzi
→ numery).
