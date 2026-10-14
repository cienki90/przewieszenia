# numeruj_slupy (beta)

Automatyczna **numeracja słupów nN** w rysunku DXF. Projektant zaznacza tylko dwa
pierwsze słupy każdego obwodu, a program numeruje resztę i rysuje warstwy kontrolne.

## Jak przygotować rysunek (wejście)

W rysunku DXF (ASCII), dla **każdego obwodu**:

1. **Słup „1" i „2"** – wpisz ręcznie numer `1` i `2` (TEXT) przy dwóch pierwszych
   słupach obwodu, na warstwie numerów (`_numery`). Kierunek **1 → 2** wyznacza
   magistralę („na wprost”), czyli w którą stronę biegnie obwód od stacji.
2. **Opis „obw. nr X”** – multileader/TEXT z tekstem `obw. nr X`, którego **grot
   wskazuje pierwsze przęsło** (odcinek między słupem 1 a 2). To wiąże obwód z numerem.

Pozostałe elementy rozpoznawane są jak w generatorze zestawień (`generator/zestawienie.py`):
- słupy – opisy `słup nN … <oznaczenie>-<typ>` (bloki/MULTILEADER/MTEXT),
- stacje – `STACJA TRAFO <numer>` i zakresy (zamknięte polilinie na warstwie `!trafo`),
- ciąg logiczny sieci – polilinie na warstwie `!tele` (łączą słupy), uzupełniane
  wymiarami (DIMENSION) tam, gdzie sieć ma lukę.

## Co robi program (wyjście)

Tworzy **nowy** plik DXF `… - ponumerowane.dxf` (oryginał nie jest zmieniany):

- **numery słupów** jako TEXT, każdy obwód na osobnej warstwie
  `_numery_<stacja>_<obwod>` (np. `_numery_05-0433_1`) – ułatwia robienie zestawień,
- **obrys kontrolny** każdego obwodu – łamana prowadzona wzdłuż ścieżki numeracji
  (magistrala + odgałęzienia) na warstwie `_kontrola_<stacja>_<obwod>`:
  **inny kolor** dla każdego obwodu, grubość linii **0,5 mm**, warstwa **NIEDRUKOWALNA**.

### Reguła numeracji

- magistrala: `1, 2, 3, …` – w każdym rozwidleniu kontynuacja „na wprost”
  (najmniejszy kąt skrętu względem kierunku dojścia; na starcie kierunek 1→2),
- odgałęzienia: `x.1, x.2, …` – numerowane **od lewej strony** magistrali,
- zagnieżdżenia: `x.y.1, …` analogicznie.
- każdy obwód ma własną numerację od `1`; granicę obwodu wyznacza stacja trafo
  oraz starty innych obwodów (BFS nie przekracza cudzego słupa „1”).

Walidacja na rysunkach z pełną numeracją odtworzyła numerację projektanta
(np. `zofinin - PZT.dxf`: 135/135 słupów, `pw.dxf`: 339/341).

## Uruchomienie (Windows)

1. `setup.bat` – jednorazowo: tworzy `.venv` i instaluje `ezdxf`.
2. `uruchom.bat` – uruchamia program:
   - bez argumentu → **okno wyboru pliku** (GUI),
   - `uruchom.bat "rysunek.dxf"` → numeruje jeden plik z linii poleceń.
3. `sprawdz.bat "rysunek z pełną numeracją.dxf"` – test: porównuje nadane numery
   z już wpisanymi (do kontroli algorytmu na gotowych rysunkach).

## Uruchomienie (wiersz poleceń)

```
python numeruj.py rysunek.dxf                 # -> rysunek - ponumerowane.dxf
python numeruj.py rysunek.dxf -o wynik.dxf
python numeruj.py                             # GUI
```

Wymagania: Python 3.8+ oraz `ezdxf` (patrz `requirements.txt`).

## Pliki

| plik             | rola                                                              |
|------------------|-------------------------------------------------------------------|
| `numeruj.py`     | punkt wejścia (CLI + wywołanie GUI), przebieg i raport            |
| `gui.py`         | okno tkinter: wybór pliku, uruchomienie, log                     |
| `czytaj_dxf.py`  | parser DXF + model encji (logika z `generator/zestawienie.py`)   |
| `model.py`       | słupy/stacje/graf/przypisanie do stacji + starty i markery 1/2   |
| `numeracja.py`   | nadawanie numerów (magistrala „na wprost”, odgałęzienia od lewej)|
| `zapis_dxf.py`   | zapis numerów i obrysów kontrolnych do nowego DXF (ezdxf)        |
| `_waliduj.py`    | narzędzie testowe (porównanie z numeracją obecną w DXF)          |
