# Generator projektów nN — przewieszenia · zestawienie · obliczenia

Jeden program, który z **jednego pliku planu DXF** tworzy trzy opracowania projektu linii nN
z projektowanym światłowodem:

| Krok | Co powstaje | Plik |
|---|---|---|
| **Przewieszenia** | rysunki zwisów (profile przęseł) linii nN ze światłowodem | `<plan> - przewieszenia.dxf` |
| **Zestawienie** | zestawienie słupów nN w podziale na stacje transformatorowe | `zestawienie <plan>.xlsx` |
| **Obliczenia** | obliczenia nośności słupów na podstawie zestawienia | `Obliczenia - zestawienie <plan>.xlsx` |
| **Rysunki stałe** | osobny plan orientacyjny DXF dla każdej stacji trafo + zestawienie | `rysunki stałe/<nr>.dxf`, `rysunki stałe/zestawienie_stacji.xlsx` |
| **Arkusze PZT** | komplet arkuszy A3 1:1000 dla każdej stacji (minimalna liczba, zakład 50 m) | `<plan> - PZT.dxf` |
| **Opisy techniczne** | osobny opis techniczny `.docx` dla każdej stacji (z szablonu Word) | `opisy/<nr>.docx` |
| **Zakładki** | strony-przekładki (nr stacji / miejscowość / WT) dla każdej stacji | `zakladki.docx` lub `zakladki.pdf` |

> **Opisy techniczne** (z repo `generator_opisow`): dla każdej stacji z zestawienia tworzy opis
> `.docx` z szablonu Word (kontrolki `trafo`, `miejscowosc`, `wt`). Zestawienie można **podpiąć
> wprost z „Rysunków stałych”** (`zestawienie_stacji.xlsx`) — program rozpoznaje kolumny po
> nagłówkach (`Oznaczenie stacji`→trafo, `Nr stacji`→nazwa pliku, `Miejscowość`), więc działa też
> z formatem „domtel” (`Plik/trafo/miejscowosc/wt`). **Numer warunków (WT)** – jeden wspólny –
> wpisuje się ręcznie (pole „Numer warunków (WT)” / `--opisy-wt`), bo nie ma go w zestawieniu z
> Orientacji. Opcjonalnie dołącza tabelę nośności słupów z pliku obliczeń. Wymaga bibliotek
> `python-docx` i `openpyxl` (w `.exe` są wbudowane).

> **Arkusze PZT** (odpowiednik programu AutoLISP `PZT_ARKUSZE`, przeniesiony na Pythona bez CAD-a):
> dla każdej stacji trafo tworzy komplet arkuszy A3 1:1000 pokrywających całą trasę (`!tele`)
> w jej zakresie (poligony `!trafo`), przy minimalnej liczbie arkuszy i zakładzie 50 m między
> sąsiednimi arkuszami. Każdy arkusz to kopia **layoutu-wzorca „a”** (ramka A3, tabelka, legenda,
> rzutnia 1:1000) — z pliku planu albo ze wskazanego pliku-wzorca. Wynik to kopia planu z dopisanymi
> layoutami; model pozostaje praktycznie bez zmian.
>
> **Zasięgi innych stacji są ukrywane na arkuszu:** poligony zakresu każdej stacji są przenoszone
> na własną warstwę `!trafo_<nr>`, a w rzutni każdego arkusza **zamrażane są warstwy pozostałych
> stacji** — dzięki temu na arkuszu danej stacji widać tylko jej zasięg, nie zasięgi sąsiednich
> stacji (tak jak w programie LISP).

> **Uwaga o rysunkach stałych (orientacjach):** ten krok działa na **szablonie rysunków stałych**
> (`szablon.dxf` – wszystkie stacje na jednym rysunku, z odnośnikami „STACJA TRAFO” i obrysami
> zasięgu na warstwie `!trafo`), a nie na planie tras. W oknie można wskazać własny szablon;
> gdy pole zostanie puste, użyty jest **dołączony `szablon.dxf`**. Pobieranie podkładu mapowego
> (OSM / Geoportal) wymaga internetu i biblioteki **Pillow** — bez nich krok działa z opcją
> „bez podkładu”. W pliku .exe Pillow i szablon są już wbudowane.
>
> **Szybkość:** nazwa miejscowości jest ustalana z pierwszego źródła, które odpowie (bez
> odpytywania wszystkich serwisów), a słupy stacji są grupowane przestrzennie — geokodujemy
> jeden punkt na grupę, nie każdy słup. Dzięki temu generowanie jest szybkie nawet przy wielu
> słupach. Pełną weryfikację nazw między źródłami włącza opcja `--weryfikuj-nazwy` (wolniej).
>
> **Nazwa miejscowości w tabelce** jest ustalana z **geokodowania słupów danej stacji trafo**:
> dla każdego słupa odczytujemy miejscowość, więc wiadomo, jakie miejscowości obejmuje stacja;
> w tabelce wpisujemy tę z największą liczbą słupów (pełny zasięg trafia do uwag/kolumny „inne”).
> Przypisanie „który słup leży w której stacji” pochodzi z analizy **zestawienia** (obszary
> `!trafo_<nr>` + drzewo sieci).
>
> **Powiązanie po numerze stacji trafo.** Słupy i szablon rysunków stałych nie muszą być w tym
> samym pliku — wystarczy, że **numery stacji się zgadzają**. W łańcuchu plan tras (ze słupami)
> jest automatycznie źródłem miejscowości dla szablonu; można też wskazać go ręcznie
> (`--plan-slupow`, w oknie pole „Plan ze słupami”). Stacje wiązane są po numerze
> (`03-0541` = `0541` = `541`). Gdy nie ma ani planu ze słupami, ani słupów w szablonie,
> program wraca do położenia odnośnika stacji.

Arkusze przewieszeń są **segregowane po stacjach trafo** (w kolejności numeru stacji):
na jednym arkuszu nie ma rysunków z dwóch różnych stacji — zmiana stacji zaczyna nowy arkusz
(ostatni arkusz stacji może mieć jeden rysunek, jeśli liczba jest nieparzysta). Przęsło łączące
dwie stacje jest **powtórzone na arkuszach obu stacji**.

Dodatkowo krok **Przewieszenia** tworzy plik **kontrolny** `<plan> - kontrola.dxf` — kopię planu
(oryginał pozostaje nietknięty) z **numerem przewieszenia wpisanym w miejscu każdego zaznaczenia**,
na drukowalnej warstwie `_PRZEWIESZENIA_KONTROLA`. Ten sam numer pojawia się na odpowiadającym
rysunku zwisu, dzięki czemu łatwo sprawdzić, który rysunek dotyczy którego przęsła na planie.

> **Plik opisów `<plan>_opisy.csv`.** Dane geometryczne/techniczne (numery i typy słupów,
> rozpiętość przęsła) są **zawsze odczytywane z rysunku** — po poprawieniu rysunku i ponownym
> uruchomieniu program bierze nowe wartości, nie stare z CSV. Z pliku CSV pobierane są tylko pola
> opisowe/ręczne: miejscowość, ulica oraz ewentualna korekta stacji/obwodu. Dzięki temu CSV nie
> „zamraża” danych z rysunku.

Program łączy wcześniejsze narzędzia (generator przewieszeń, programy „zestawienie” i „obliczenia”
z repozytorium `mm` oraz „rysunki stałe” z repo `Orientacje-arkusze`) w jedną aplikację z oknem.
Wymaga **Pythona 3.9+** ze standardowym `tkinter`; biblioteka Pillow jest potrzebna tylko do
podkładu mapowego w rysunkach stałych.

**Okno ma osobną zakładkę dla każdego modułu** — „Wszystko (łańcuch)”, „Numeracja słupów”,
„Przewieszenia”, „Zestawienie”, „Obliczenia”, „Rysunki stałe”, „Arkusze PZT”, „Opisy techniczne”,
„PPW”, „Zakładki” — każda z własnym wyborem pliku i opcjami. Na dole okna wspólny katalog zapisu,
pasek postępu i dziennik przebiegu.

> **Zakładki** (strony-przekładki): dla każdej stacji trafo tworzy osobną stronę z trzema
> wyśrodkowanymi liniami — **numer stacji** (`ST <nr>`), **miejscowość** i **numer warunków (WT)**.
> Dane pochodzą z pliku zestawienia — zwykle z **„zestawienie_stacji.xlsx” z „Rysunków stałych”**
> (rozpoznawanie kolumn jest wspólne z modułem „Opisy”, więc działa też z formatem „domtel”
> `Plik/trafo/miejscowosc/wt`). Numer WT — jeden wspólny — wpisuje się ręcznie, gdy zestawienie
> go nie zawiera. **Format wyniku jest przełączany:** `.docx` (edytowalny w Wordzie, wymaga
> `python-docx`) albo `.pdf` (gotowy do druku, generowany na czystym Pythonie — bez dodatkowych
> bibliotek; polskie znaki osadzane przez własne kodowanie `/Differences` czcionki Helvetica).
> CLI: `--tylko zakladki --zakladki-zestawienie zestawienie_stacji.xlsx --zakladki-format pdf
> --zakladki-wt 71/RE-5/KŚ/2026`.

> **PPW** (zbiorczy opis techniczny): tworzy JEDEN dokument `.docx` dla całego projektu
> (wszystkie stacje trafo naraz) z szablonu Word (domyślnie „PPW miński szablon.docx”).
> Znaczniki tekstowe w szablonie — `*mmmm*` (miejscowości), `*xxxxx*` (numery stacji),
> `*wwww*` (numer WT) — są podstawiane danymi, a tabela „Zestawienie zbiorcze słupów”
> (Nr stacji / Ilość słupów / Długość / Numer arkusza + SUMA) wypełniana z pliku modułu
> „Zestawienie”. Miejscowości pochodzą z „zestawienie_stacji.xlsx” (Rysunki stałe), numer WT
> wpisuje się ręcznie, numery arkuszy nadawane są kolejno. Wymaga `python-docx` i `openpyxl`.
>
> Zakładka „PPW” ma też **renumerację numerów rysunku** (odpowiednik polecenia `PPW` z AutoLISP
> `PPW_RENUMER.lsp`, przeniesiony na Pythona bez CAD-a): dla arkuszy o nazwach `STACJA-ARKUSZ`
> (np. `112-1`) wpisuje do tabelki numer rysunku (stacje kolejno `1,2,3…`; wiele arkuszy →
> `1.1, 1.2…`; jeden arkusz → bez kropki) i zamienia „Projekt wykonawczy” → „Projekt
> powykonawczy”. Pole numeru rozpoznawane uniwersalnie (MTEXT wys. 2.0, treść `N`/`N.N`; styl
> `LEGENDA` preferowany, ale niewymagany). Działa na czystym Pythonie (bez `ezdxf`), tworzy
> nieniszcząco `… - powykonawczy.dxf`. CLI: `--ppw-renumeruj plik.dxf`.

> **Numeracja słupów** (z repo gałęzi `numeracja-slupow`): automatycznie numeruje słupy nN.
> W planie zaznacz ręcznie numery „1” i „2” dwóch pierwszych słupów każdego obwodu (warstwa
> `_numery`) oraz opis „obw. nr X” (grot na pierwszym przęśle); program numeruje resztę
> (magistrala „na wprost”, odgałęzienia `x.1, x.2…` od lewej) i tworzy `… - ponumerowane.dxf`
> z numerami na warstwach `_numery_<stacja>_<obwod>` oraz obrysami kontrolnymi. Wymaga biblioteki
> **ezdxf** (w `.exe` wbudowana).

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

# rysunki stałe z wybranego szablonu, bez pobierania podkładu z internetu
python generator_cli.py plan.dxf --tylko orientacje --szablon-orientacji szablon.dxf --bez-podkladu
```

Najważniejsze opcje wiersza poleceń:

```
-o, --katalog         katalog zapisu wyników (domyślnie obok planu)
--tylko a,b,c         które kroki: przewieszenia,zestawienie,obliczenia,orientacje,pzt
--szablon-orientacji  szablon DXF dla rysunków stałych (domyślnie dołączony szablon.dxf)
--bez-podkladu        rysunki stałe bez pobierania podkładu mapowego (bez internetu/Pillow)
--pzt-wzorzec <plik>  plik DXF z layoutem-wzorcem „a” dla arkuszy PZT (domyślnie plan wejściowy)
--pzt-zaklad 50       arkusze PZT: wspólny odcinek trasy sąsiednich arkuszy [m]
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
  gui.py                – interfejs okienkowy z zakładkami (osobna zakładka na moduł + „Wszystko”)
  numeruj_slupy/        – automatyczna numeracja słupów nN (podpakiet; z gałęzi numeracja-slupow, wymaga ezdxf)
  przewieszenia.py      – generator rysunków przewieszeń
  kontrola.py           – kopia planu z numerami przewieszeń (kontrola powiązania)
  plan.py, baza.py, rysunek.py, zapis.py, dxfio.py, geokod.py – obsługa przewieszeń
  zestawienie.py        – zestawienie słupów nN z DXF (z programu "mm")
  obliczenia.py         – obliczenia nośności słupów (z programu "mm")
  orientacje.py         – rysunki stałe: plan orientacyjny per stacja + podkład mapowy (z repo Orientacje-arkusze)
  pzt.py                – arkusze PZT A3 1:1000 per stacja (z repo ARKUSZE_PZT; rozkład jak generator_wt/arkusze.py)
  opisy.py              – opisy techniczne .docx z szablonu Word + zestawienia (z repo generator_opisow)
  ppw.py                – PPW: zbiorczy opis techniczny .docx dla całego projektu (znaczniki + tabela zbiorcza)
  zakladki.py           – Zakładki: strony-przekładki (nr stacji / miejscowość / WT) w .docx albo .pdf (z repo zakladki)
  obliczenia2word.py    – (opcjonalnie) tabela nośności słupów dołączana do opisu .docx
  zasoby.py             – odnajdywanie plików bazy/arkuszy/szablonu (kod źródłowy lub .exe)
```
