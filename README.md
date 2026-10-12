# Generator projektów nN — przewieszenia · zestawienie · obliczenia

Jeden program, który z **jednego pliku planu DXF** tworzy trzy opracowania projektu linii nN
z projektowanym światłowodem:

| Krok | Co powstaje | Plik |
|---|---|---|
| **Przewieszenia** | rysunki zwisów (profile przęseł) linii nN ze światłowodem | `<plan> - przewieszenia.dxf` |
| **Zestawienie** | zestawienie słupów nN w podziale na stacje transformatorowe | `zestawienie <plan>.xlsx` |
| **Obliczenia** | obliczenia nośności słupów na podstawie zestawienia | `Obliczenia - zestawienie <plan>.xlsx` |

Dodatkowo krok **Przewieszenia** tworzy plik **kontrolny** `<plan> - kontrola.dxf` — kopię planu
(oryginał pozostaje nietknięty) z **numerem przewieszenia wpisanym w miejscu każdego zaznaczenia**,
na drukowalnej warstwie `_PRZEWIESZENIA_KONTROLA`. Ten sam numer pojawia się na odpowiadającym
rysunku zwisu, dzięki czemu łatwo sprawdzić, który rysunek dotyczy którego przęsła na planie.

Program łączy trzy wcześniejsze narzędzia (generator przewieszeń oraz programy „zestawienie”
i „obliczenia” z repozytorium `mm`) w jedną aplikację z prostym oknem. Wymaga tylko
**Pythona 3.9+** ze standardowym modułem `tkinter` — bez żadnych dodatkowych bibliotek.

## Program dla Windows (.exe)

Plik `GeneratorNN.exe` jest budowany automatycznie przez GitHub Actions po każdej zmianie kodu
(zakładka **Releases**). Uruchom go dwuklikiem — pliki bazy i arkuszy są wbudowane w program,
nie trzeba niczego instalować.

## Uruchomienie z kodu (Windows)

- `setup.bat` — sprawdza Pythona i `tkinter` (oraz opcjonalnie instaluje PyInstaller),
- `uruchom.bat` — otwiera **okno** programu,
- `generuj.bat "plan.dxf"` — wersja **wiersza poleceń** (można przeciągnąć plik DXF na `.bat`),
- `sprawdz.bat` — test: uruchamia cały łańcuch na pliku przykładowym i sprawdza wyniki.

Pliki `.bat` obsługują polskie znaki (`chcp 65001`) i same wykrywają Pythona (`py -3` lub `python`).

## Uruchomienie z kodu (dowolny system)

```bash
# okno programu
python -m generator            # albo: python generator_gui.py

# wiersz poleceń (cały łańcuch)
python -m generator.pipeline "przewieszenia plan.dxf"

# tylko wybrane kroki, inny katalog zapisu
python generator_cli.py "przewieszenia plan.dxf" --tylko zestawienie,obliczenia -o wyniki
```

Najważniejsze opcje wiersza poleceń:

```
-o, --katalog         katalog zapisu wyników (domyślnie obok planu)
--tylko a,b,c         które kroki: przewieszenia,zestawienie,obliczenia
--adresy uug,osm      źródła nazw miejscowości/ulic (albo "brak" = bez internetu)
--obrot-od 50         przęsła dłuższe niż 50 m rysowane pionowo
--seed 1              powtarzalne obliczenia (kąty słupów narożnych)
--kabel 3             domyślny rodzaj kabla w obliczeniach (1-11)
```

Sam generator przewieszeń (`python -m generator.przewieszenia`) ma dodatkowo opcje kontroli:

```
--kontrola <plik>     plik kontrolny: kopia planu z numerami (domyślnie "<plan> - kontrola.dxf")
--bez-kontroli        nie twórz kopii planu z numerami przewieszeń
--bez-kontroli-stacji nie sprawdzaj po numeracji stacji trafo na podstawie zestawienia
```

> **Obliczenia** potrzebują zestawienia. Jeśli włączysz je bez kroku „zestawienie”, program
> zbuduje zestawienie w pliku tymczasowym, wykona obliczenia i plik tymczasowy usunie.

## Jak program czyta dane z planu DXF

Wszystkie kroki działają na tym samym rysunku planu. Rozpoznawanie stacji transformatorowych,
do których należą słupy, jest wspólnym, mocnym punktem narzędzi `mm` i generatora przewieszeń.

| Dane | Źródło w planie |
|---|---|
| lokalizacja przewieszenia | warstwa `_PRZEWIESZENIA`: kreska przecinająca przęsło (zalecane) lub okrąg |
| przęsło / trasa | polilinia na warstwie `!TELE`; słupy na trasie dzielą ją na przęsła |
| długość przęsła | wymiar między słupami (np. warstwa `!wymiary`); gdy brak — długość trasy |
| słupy | bloki `ZN`, `E`, `R` (także zagnieżdżone w innych blokach, np. `q`) |
| numery słupów | teksty na warstwie `_numery` |
| typy słupów | multileadery „słup nN / typ” |
| stacja | obszar `!trafo_<nr>` (np. `!trafo_05-0355`); gdy brak — opis „STACJA TRAFO / nr” |
| obwód | multileadery „obw. nr X”; śledzony po trasie zgodnie z numeracją słupów |

#### Kontrola stacji trafo (po numeracji)

Po ustaleniu numeracji program **ponownie sprawdza stację trafo** dopisaną do każdego
przewieszenia, posiłkując się analizą **zestawienia** (to ona najpewniej rozpoznaje, do której
stacji należy dany słup — po obszarach `!trafo_<nr>` i drzewie sieci). Jeżeli oba słupy przęsła
należą — wg zestawienia — do tej samej stacji, a na rysunku jest inna (albo `ST ?`), stacja jest
**poprawiana**, a w raporcie pojawia się informacja o zmianie. Gdy słupy wskazują dwie różne
stacje (przęsło na granicy), program tego nie zmienia, tylko sygnalizuje do sprawdzenia.
Wyłączenie: `--bez-kontroli-stacji`.

### Przewieszenia — baza i arkusze

Z `przewieszenia baza.dxf` pobierane są wysokości zawieszenia i zwisy (dla rozpiętości i typów
słupów) oraz style DXF. Wynik powstaje w układzie arkuszy z `arkusze.dxf` (po dwa poziome rysunki
na arkusz albo jeden pionowy; puste arkusze są usuwane).

Środek znacznika (PUWG 2000) jest przeliczany na WGS84 i program pobiera najbliższy adres z
GUGiK UUG, a gdy się nie uda — z OpenStreetMap. Adresy trafiają do pamięci podręcznej
`<plan>_adresy.json`. Bez internetu program działa normalnie (opcja „bez internetu” / `--adresy brak`).

### Zestawienie — kontrola poprawności

Zestawienie tworzy arkusz zbiorczy, osobny arkusz dla każdej stacji (Nr słupa, Oznaczenie, Typ,
Odległość, Mufa, Obwód) oraz arkusz **„kontrola”** z automatycznym sprawdzeniem (błędy/uwagi ze
współrzędnymi miejsca na rysunku; wiersze są kolorowane).

### Obliczenia — nośność słupów

Obliczenia czytają zestawienie (`.xls`/`.xlsx`) i dla każdej stacji liczą nośność i obciążenie
słupów, zestawienie osprzętu oraz sumy, w układzie zgodnym z dotychczasowymi obliczeniami, wraz
z podpisami projektantów. Słupy niespełniające warunku nośności są wyróżniane.

## Pliki programu

```
generator_gui.py        – start okna (używany też przy budowie .exe)
generator_cli.py        – start wiersza poleceń
generator/
  pipeline.py           – łańcuch: DXF -> przewieszenia + zestawienie + obliczenia
  gui.py                – interfejs okienkowy (jedno okno, pasek postępu, log)
  przewieszenia.py      – generator rysunków przewieszeń
  kontrola.py           – kopia planu z numerami przewieszeń (kontrola powiązania)
  plan.py, baza.py, rysunek.py, zapis.py, dxfio.py, geokod.py – obsługa przewieszeń
  zestawienie.py        – zestawienie słupów nN z DXF (z programu "mm")
  obliczenia.py         – obliczenia nośności słupów (z programu "mm")
  zasoby.py             – odnajdywanie plików bazy/arkuszy (kod źródłowy lub .exe)
```
