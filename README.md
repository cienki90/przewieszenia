# Przewieszenia – generator rysunków zwisów

**Program dla Windows:** [Przewieszenia.exe](https://github.com/cienki90/przewieszenia/releases/latest/download/Przewieszenia.exe).
Uruchom go dwuklikiem, wskaż plik planu DXF i miejsce zapisu. Nie trzeba niczego instalować. Pliki bazy i arkuszy
są wbudowane w program. Plik budowany jest automatycznie przez GitHub Actions (`.github/workflows/exe.yml`) po każdej
zmianie kodu.

Program tworzy rysunki przewieszeń (zwisów przęseł linii nN z projektowanym światłowodem) na podstawie planu DXF.
Wymaga tylko Pythona 3.9+, bez dodatkowych bibliotek.

```
python przewieszenia.py "przewieszenia plan.dxf"
```

Wynik: `przewieszenia plan wynik.dxf` oraz plik opisów `przewieszenia plan_opisy.csv`.

## Skąd pochodzą dane

| Dane | Źródło w planie |
|---|---|
| lokalizacja przewieszenia | na warstwie `_PRZEWIESZENIA`: **kreska (LINE/polilinia) przecinająca przęsło** – zalecane; albo okrąg (środek na przęśle). Jedna kreska może przeciąć kilka przęseł – powstanie rysunek dla każdego |
| przęsło | polilinia trasy na warstwie `!TELE`; słupy leżące na trasie (w wierzchołku lub na odcinku) dzielą ją na przęsła |
| długość przęsła | wymiar narysowany między słupami (np. warstwa `!wymiary`); gdy go brak – długość trasy |
| słupy | bloki `ZN`, `E`, `R`, także zagnieżdżone w innych blokach (np. `q` = słup + opis typu) |
| numery słupów | teksty na warstwie `_numery` (dopasowanie po odległości) |
| typy słupów | multileadery „słup nN / typ” (grot wskazuje słup) |
| stacja | obszar stacji – zamknięta polilinia na warstwie `!trafo_<nr>` (np. `!trafo_05-0355`); gdy go brak – najbliższy opis „STACJA TRAFO / nr” |
| obwód | multileadery „obw. nr X”; obwód jest śledzony po trasie zgodnie z numeracją słupów (1 → 2 → 2.1 → 2.2 …) |

Z pliku `przewieszenia baza.dxf` (157 gotowych rysunków) program pobiera:

- wysokość zawieszenia i zwis światłowodu dla danej rozpiętości (≤22 m: 6,2 m; 23–40 m: 6,7 m; >40 m: 7,2 m; zwis 3% / 2,5%),
- wysokość linii nN i słupa dla danego typu słupa (np. słupy 10,5 m: 8,2 m; 10 m: 7,7 m),
- nagłówek, warstwy, rodzaje linii i style DXF, które służą jako szablon pliku wynikowego.

## Miejscowości i ulice z internetu

Środek okręgu (współrzędne PUWG 2000, strefa z pierwszej cyfry X) jest przeliczany na WGS84. Program pobiera
najbliższy punkt adresowy:

1. z usługi GUGiK UUG (`GetAddressReverse`, dane PRG); „ulica Wspólna” jest skracana do „ul. Wspólna”,
2. a gdy to się nie uda, z OpenStreetMap Nominatim (najwyżej 1 zapytanie na sekundę).

Pobrane adresy trafiają do pamięci podręcznej `<plan>_adresy.json`. Program odpytuje internet tylko dla przewieszeń,
które nie mają miejscowości w pliku CSV. Opcje:

- `--odswiez-adresy` pobiera adresy ponownie dla wszystkich przewieszeń,
- `--adresy brak` wyłącza internet,
- `--adresy osm` używa tylko OpenStreetMap.

Bez internetu program działa normalnie, tylko wypisuje ostrzeżenie.

## Arkusze

Wynik powstaje na bazie `arkusze.dxf`. Przewieszenia trafiają do istniejących arkuszy (karty 1, 2, 3, …): po dwa
poziome rysunki na arkusz albo jeden pionowy. Rysunki są umieszczane w modelu dokładnie pod rzutnią każdego arkusza.
Układ arkuszy, rzutnie, skala i ustawienia drukarki (DWG To PDF, A4) pozostają bez zmian.

- Arkusze, które zostały puste, są usuwane. Opcja `--zostaw-puste-arkusze` je zachowuje.
- Gdy przewieszeń jest więcej niż arkuszy, program dodaje kopie ostatniego arkusza.
- Przęsła dłuższe niż 50 m albo za szerokie na arkusz są rysowane pionowo.
- Opisy słupów przy długich przęsłach są przesuwane, żeby zmieściły się w rzutni.

## Plik opisów (CSV)

Plik CSV (separator `;`, UTF‑8) jest tworzony przy pierwszym uruchomieniu i zawiera wszystkie ustalone dane.
Można go poprawić (np. usunąć ulicę, której nie chcesz w tytule) i uruchomić program ponownie. Wiersze są
dopasowywane po współrzędnych okręgu. Każde niepuste pole (np. `stacja`, `typ_l`, `rozpietosc`) nadpisuje wartość
ustaloną automatycznie. Pola `stacja2`/`obwod2` są używane, gdy przęsło łączy dwa obwody.

Jeśli stacji nie da się ustalić (opis obwodu jest dalej niż 150 m od stacji), program wpisze `ST ?` i wypisze ostrzeżenie.

## Opcje

```
-o, --wynik     plik wynikowy DXF
--baza          plik bazy (domyślnie "przewieszenia baza.dxf" obok programu)
--arkusze       plik z arkuszami (domyślnie "arkusze.dxf" obok programu)
--zostaw-puste-arkusze
--opisy         plik CSV z opisami
--obrot-od 50   przęsła dłuższe niż 50 m są rysowane pionowo (0 = nigdy)
--warstwa, --warstwa-trasy   inne nazwy warstw
```

## Pliki

- `przewieszenia_gui.py` – wersja okienkowa (exe)
- `przewieszenia.py` – program główny (wiersz poleceń)
- `plan.py` – analiza planu (słupy, przęsła, obwody)
- `baza.py` – parametry odczytane z bazy rysunków
- `rysunek.py` – geometria pojedynczego rysunku (siatka, linijki, słupy, krzywe zwisu, opisy)
- `geokod.py` – przeliczenie PUWG 2000 → WGS84 i pobieranie adresów (GUGiK / OSM)
- `zapis.py`, `dxfio.py` – odczyt i zapis DXF
