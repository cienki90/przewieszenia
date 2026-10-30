# Generator projektów nN — przewieszenia · zestawienie · obliczenia

Jeden program, który z **pliku planu DXF** tworzy opracowania projektu linii nN z projektowanym
światłowodem. **Każdy moduł uruchamia się osobno** (własna zakładka w oknie / `--tylko <moduł>`
w wierszu poleceń) — program nie ma łańcucha „wszystko naraz”:

| Krok | Co powstaje | Plik |
|---|---|---|
| **Przewieszenia** | rysunki zwisów (profile przęseł) linii nN ze światłowodem | `<plan> - przewieszenia.dxf` |
| **Zestawienie** | zestawienie słupów nN w podziale na stacje transformatorowe | `zestawienie <plan>.xlsx` |
| **Obliczenia** | obliczenia nośności słupów na podstawie zestawienia | `Obliczenia - zestawienie <plan>.xlsx` |
| **Rysunki stałe** | osobny plan orientacyjny DXF dla każdej stacji trafo + zestawienie | `rysunki stałe/<nr>.dxf`, `rysunki stałe/zestawienie_stacji.xlsx` |
| **Arkusze PZT** | komplet arkuszy A3 1:1000 dla każdej stacji (minimalna liczba, zakład 50 m) | `<plan> - PZT.dxf` |
| **Opisy techniczne** | osobny opis techniczny `.docx` dla każdej stacji (z szablonu Word) | `opisy/<nr>.docx` |
| **Zakładki** | strony-przekładki (nr stacji / miejscowość / WT) dla każdej stacji | `zakladki.docx` lub `zakladki.pdf` |

> **Podgląd i przesuwanie arkuszy PZT.** W zakładce „Arkusze PZT” przycisk „Podgląd i przesuwanie
> arkuszy…” otwiera (tylko na żądanie) mapę poglądową wybranej stacji: zasięg, trasę `!tele` i arkusze
> (z marginesem i strefą tabelki). Arkusze przeciąga się myszą; niepokryte odcinki trasy świecą na
> czerwono. Rozkład stacji liczony jest w tle dopiero po jej wybraniu. Zapisany układ trafia do
> `<plan> - arkusze PZT.json` obok planu, a generowanie PZT używa go zamiast rozkładu automatycznego
> (z ostrzeżeniem, gdy ręczny układ nie pokrywa całej trasy). Podwójne kliknięcie dodaje arkusz, Delete
> usuwa zaznaczony, „Domknij dziury” dokłada arkusze na niepokrytej trasie, a pole „Podkład mapowy”
> pokazuje pod spodem mapę OSM (pobieraną na żądanie, kafle zapamiętywane na dysku).

## Moduł nr 1: Generator WT

Zakładka „1. Generator WT” uruchamia osobny program **Generator WT** (etap warunków technicznych:
numeracja, pismo o dostęp do słupów, zestawienia, arkusze) w jego własnym oknie. Program jest
znajdowany sam (folder `GENERATOR_WT*` obok programu lub w `GOTOWE PROJEKTY`) albo wskazywany
przyciskiem „Wskaż…” (folder z `uruchom.pyw` lub `Generator WT.exe`). Po zamknięciu Generatora WT
(albo przyciskiem „Podepnij wyniki WT”) jego wyniki z folderu projektu są wypisywane w „Przebiegu”,
a zestawienie uproszczone `*_uproszczona.xls` trafia do pola „Warunki techniczne” (PZT, Rysunki
stałe, Opisy). Generator WT działa jako osobny proces - ma własne biblioteki (PySide6).

## Udogodnienia okna

- **Projekt** — pasek „Projekt” w nagłówku. Pliki i opcje wszystkich modułów zapisują się w
  `projekt GeneratorNN.json` w folderze planu (projekt zakłada się sam przy pierwszym uruchomieniu
  modułu); ostatni projekt wraca przy starcie, „Ostatnie” przełącza między projektami.
- **Sprawdź plan** — szybka kontrola planu (trasa, zasięgi, odnośniki stacji, słupy, numery, opisy
  obwodów, zaznaczenia przewieszeń, layout „a”) i lista gotowości każdego modułu — przed generowaniem.
- **Dziennik** — przebieg każdego uruchomienia dopisywany do `dziennik GeneratorNN.txt` w katalogu
  wyników; przycisk „Kopiuj dziennik”.
- **Nazwy miejscowości…** (Rysunki stałe, Arkusze PZT) — ręczna poprawka nazw stacji (np. gdy
  geokodowanie dało „????”). Zapis do `nazwy miejscowości.csv` w folderze projektu i od razu do
  `zestawienie_stacji.xlsx`; poprawki mają pierwszeństwo przed WT i geokodowaniem.
- **Przeciąganie plików** z Eksploratora na okno — na pole albo w dowolne miejsce zakładki (pole
  dobierane po typie pliku); plik projektu otwiera projekt.

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
> **PDF dla każdej stacji.** Opcja „Twórz PDF dla każdej stacji” (CLI `--pdf-stacji`) tworzy obok
> każdego rysunku `<nr>.pdf` — strona na każdy arkusz, warstwy niedrukowalne pominięte, podkład jako JPG
> (odtworzenie programu DXF2PDF). Przycisk „PDF z gotowych rysunków…” (CLI `--tylko pdf <folder>`) robi
> to samo dla istniejącego folderu rysunków DXF/DWG. W odróżnieniu od dawnego DXF2PDF rzutnie mapy
> nie wychodzą puste (statusy rzutni i punkt celu widoku są poprawiane w pamięci).
>
> **Szablon bez stacji + zasięgi z pliku PZT.** Szablon rysunków stałych może zawierać sam podkład
> i tabelkę — bez zasięgów i odnośników stacji. Wtedy wskaż **plik PZT** (pole „Plik PZT (stacje i słupy)”,
> CLI `--zasiegi plik_PZT.dxf`): program przenosi z niego do szablonu zasięgi z warstw `!trafo_<nr>`
> (na warstwę `!trafo`) i odnośniki „STACJA TRAFO”, po czym tworzy osobny rysunek dla każdej stacji.
> Plik PZT jest też źródłem słupów do nazw miejscowości. Po module „Arkusze PZT” pole wypełnia się samo.
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
> samym pliku — wystarczy, że **numery stacji się zgadzają**. Gdy moduł uruchomiono na planie tras (ze słupami),
> plan jest automatycznie źródłem miejscowości dla szablonu; można też wskazać go ręcznie
> (`--plan-slupow`, w oknie pole „Plik PZT (stacje i słupy)” — przy szablonie z własnymi stacjami plik służy tylko jako źródło słupów). Stacje wiązane są po numerze
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

**Okno ma panel modułów po lewej** (nowoczesny wygląd w stylu Windows 11, tryb jasny/ciemny
przełączany w nagłówku) — „Numeracja słupów”,
„Przewieszenia”, „Zestawienie”, „Obliczenia”, „Rysunki stałe”, „Arkusze PZT”, „Opisy techniczne”,
„PPW”, „Zakładki” — każda z własnym wyborem pliku i opcjami. Na dole okna wspólny katalog zapisu,
pasek postępu i dziennik przebiegu.

> **Numery warunków (WT) są zapamiętywane.** Raz wpisany numer WT (moduły Opisy, PPW, Zakładki)
> wraca przy kolejnym uruchomieniu programu, a wcześniej użyte numery są dostępne na liście
> rozwijanej pola WT. Ustawienia (numery WT, motyw, ostatni moduł) zapisywane są w pliku
> `%LOCALAPPDATA%\GeneratorNN\ustawienia.json`.

> **Zakładki** (strony-przekładki): dla każdej stacji trafo tworzy osobną stronę w rozmiarze
> **Com-10 (104,7 × 241,3 mm)**, z trzema liniami przy górze strony (wyśrodkowanymi poziomo,
> pogrubioną czcionką 12 pt) — **numer stacji** (`ST <nr>`), **miejscowość** i **numer warunków (WT)**.
> Dane pochodzą z pliku zestawienia — zwykle z **„zestawienie_stacji.xlsx” z „Rysunków stałych”**
> (rozpoznawanie kolumn jest wspólne z modułem „Opisy”, więc działa też z formatem „domtel”
> `Plik/trafo/miejscowosc/wt`). Numer WT — jeden wspólny — wpisuje się ręcznie, gdy zestawienie
> go nie zawiera. **Format wyniku jest przełączany:** `.docx` (edytowalny w Wordzie, wymaga
> `python-docx`) albo `.pdf` (gotowy do druku, generowany na czystym Pythonie — bez dodatkowych
> bibliotek). PDF ma **osadzoną czcionkę TrueType** (DejaVu Sans Bold, w `generator/fonty/`),
> więc polskie znaki (ą ć ę ł ń ś ź ż …) wyświetlają się poprawnie w każdym czytniku —
> także w Adobe Acrobat Reader.
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
> nieniszcząco plik `PPW <nazwa>.dxf`. CLI: `--ppw-renumeruj plik.dxf`.

> **Numeracja słupów** (z repo gałęzi `numeracja-slupow`): automatycznie numeruje słupy nN.
> W planie zaznacz ręcznie numery „1” i „2” dwóch pierwszych słupów każdego obwodu (warstwa
> `_numery`) oraz opis „obw. nr X” (grot na pierwszym przęśle); program numeruje resztę
> (magistrala „na wprost”, odgałęzienia `x.1, x.2…` od lewej) i tworzy `… - ponumerowane.dxf`
> z numerami na warstwach `_numery_<stacja>_<obwod>` oraz obrysami kontrolnymi. Wymaga biblioteki
> **ezdxf** (w `.exe` wbudowana).

## Pliki DWG

Każdy moduł przyjmuje na wejściu **DXF albo DWG** (plan, szablon rysunków stałych, plik PZT,
wzorzec PZT, plik do renumeracji). Plik DWG jest najpierw zamieniany na tymczasowy DXF — nazwy
i katalog wyników są takie same jak dla oryginału. **Rysunki wynikowe są domyślnie
zapisywane jako DWG** (format AutoCAD 2018), a gdy nie wykryto ODA File Converter — jako DXF.
Zapis w DXF można wymusić, odznaczając w oknie „Zapisuj rysunki jako DWG” (pod katalogiem zapisu)
albo opcją `--dxf` w wierszu poleceń.

Format DWG jest zamknięty, dlatego potrzebny jest darmowy **ODA File Converter**
(<https://www.opendesign.com/guestfiles/oda_file_converter>) — program znajduje go sam w
`C:\Program Files\ODA\…`, w folderach `ODA*` na dyskach (np. `D:\programy\oda`) lub w PATH;
inną lokalizację wskazuje się przyciskiem **„Wskaż ODA…”** w oknie (zapamiętywane) albo zmienną `GENERATOR_ODA`. Zapasowo
działa **LibreDWG** (`dwg2dxf`/`dxf2dwg`, katalog w `GENERATOR_LIBREDWG`). Bez konwertera program działa
na DXF jak dotąd.

## Program dla Windows (.exe)

Plik `GeneratorNN.exe` jest budowany automatycznie przez GitHub Actions po każdej zmianie kodu
(zakładka **Releases**). Uruchom go dwuklikiem — pliki bazy i arkuszy są wbudowane w program,
nie trzeba niczego instalować.

## Gotowy program (czysta kopia)

`narzedzia/publikuj_gotowy.py` tworzy kopię programu **bez przykładów i materiałów pomocniczych**
(tylko kod, szablony i skrypty `.bat`, w stanie z ostatniego commita) wraz z plikiem `INSTRUKCJA.txt`.
Kopia może być odświeżana **automatycznie** hookami gita (po commicie, pull i amend na gałęzi
`PGE_MAKER_CLAUDE`). Hooki są lokalne - zainstaluj je raz na danym klonie:

```bash
python narzedzia/publikuj_gotowy.py "D:/OneDrive/MMUI/ai test/GOTOWE PROJEKTY/PGE MAKER" --zainstaluj-hook
```

Bez hooków kopię odświeża to samo polecenie bez `--zainstaluj-hook`. Pliki programu usunięte
z repozytorium znikają też z kopii; własne pliki w katalogu kopii (np. wyniki) nie są ruszane.

## Uruchomienie z kodu (Windows)

- `setup.bat` — sprawdza Pythona i `tkinter` (oraz opcjonalnie instaluje PyInstaller),
- `uruchom.bat` — otwiera **okno** programu,
- `generuj.bat "plan.dxf" przewieszenia` — wersja **wiersza poleceń**, jeden moduł (można przeciągnąć
  plik DXF na `.bat` — wtedy program zapyta o moduł),
- `sprawdz.bat` — test: uruchamia kolejno moduły przewieszenia, zestawienie i obliczenia na pliku
  przykładowym i sprawdza wyniki.

Pliki `.bat` obsługują polskie znaki (`chcp 65001`) i same wykrywają Pythona (`py -3` lub `python`).

## Uruchomienie z kodu (dowolny system)

```bash
# okno programu
python -m generator            # albo: python generator_gui.py

# wiersz poleceń - jeden moduł na uruchomienie
python -m generator.pipeline "przewieszenia plan.dxf" --tylko przewieszenia

# tylko wybrane kroki, inny katalog zapisu
python generator_cli.py "przewieszenia plan.dxf" --tylko obliczenia -o wyniki

# rysunki stałe z wybranego szablonu, bez pobierania podkładu z internetu
python generator_cli.py plan.dxf --tylko orientacje --szablon-orientacji szablon.dxf --bez-podkladu
```

Najważniejsze opcje wiersza poleceń:

```
-o, --katalog         katalog zapisu wyników (domyślnie obok planu)
--tylko <moduł>       (wymagane) jeden moduł: numeracja, przewieszenia, zestawienie, obliczenia,
                      orientacje, pzt, opisy, ppw, zakladki
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
słupów) oraz style DXF. Odczytana baza jest zapamiętywana w pamięci podręcznej
(`%LOCALAPPDATA%\GeneratorNN\cache`), więc kolejne uruchomienia nie parsują ponownie ~12 MB pliku;
zmiana pliku bazy automatycznie unieważnia cache. Wynik powstaje w układzie arkuszy z `arkusze.dxf` (po dwa poziome rysunki
na arkusz albo jeden pionowy; puste arkusze są usuwane).

Na **każdym arkuszu wynikowym** rysowana jest **ramka okalająca rzutnię** — zamknięta polilinia
w przestrzeni papieru, dopasowana do prostokąta rzutni (warstwa `0`, grubość linii 0,30 mm).
Wyłączenie: `--bez-ramki`.

Środek znacznika (PUWG 2000) jest przeliczany na WGS84 i program pobiera najbliższy adres z
GUGiK UUG, a gdy się nie uda — z OpenStreetMap. Adresy trafiają do pamięci podręcznej
wspólnej dla wszystkich planów: `%LOCALAPPDATA%\GeneratorNN\cache\adresy.json` (dawne pliki
`<plan>_adresy.json` są nadal czytane). Bez internetu program działa normalnie (opcja „bez internetu” /
`--adresy brak`). Ręczne poprawki nazw (okno „Nazwy miejscowości…”) uzupełniają miejscowość, gdy
geokodowanie jej nie ustaliło.

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
  pipeline.py           – uruchamianie pojedynczego modułu (okno i wiersz poleceń)
  gui.py                – interfejs okienkowy: panel modułów, tryb jasny/ciemny (sv-ttk, opcjonalnie)
  ustawienia.py         – zapamiętywanie ustawień okna między uruchomieniami (numery WT, motyw)
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
  _ttf.py               – minimalny czytnik TrueType (bez bibliotek) do osadzania czcionki w PDF zakładek
  fonty/                – dołączona czcionka DejaVu Sans Bold (osadzana w PDF; polskie znaki w Acrobat)
  obliczenia2word.py    – (opcjonalnie) tabela nośności słupów dołączana do opisu .docx
  zasoby.py             – odnajdywanie plików bazy/arkuszy/szablonu (kod źródłowy lub .exe)
```
