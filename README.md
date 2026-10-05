# Przewieszenia – generator rysunków zwisów

Program tworzy rysunki przewieszeń (zwisów przęseł linii nN z projektowanym światłowodem) na podstawie planu DXF.
Wymaga tylko Pythona 3.9+, bez dodatkowych bibliotek.

```
python przewieszenia.py "przewieszenia plan.dxf"
```

Wynik: `przewieszenia plan wynik.dxf` oraz plik opisów `przewieszenia plan_opisy.csv`.

## Skąd pochodzą dane

| Dane | Źródło w planie |
|---|---|
| lokalizacja przewieszenia | okrąg na warstwie `_PRZEWIESZENIA` (środek na przęśle) |
| przęsło i jego długość | polilinia trasy na warstwie `!TELE` (odcinek między słupami najbliższy okręgowi) |
| słupy | bloki `ZN`, `E`, `R` |
| numery słupów | teksty na warstwie `_numery` (dopasowanie po odległości) |
| typy słupów | multileadery „słup nN / typ” (grot wskazuje słup) |
| obwód i stacja | multileadery „obw. nr X” i „STACJA TRAFO / nr”; obwód jest śledzony po trasie zgodnie z numeracją słupów (1 → 2 → 2.1 → 2.2 …) |

Z pliku `przewieszenia baza.dxf` (157 gotowych rysunków) program pobiera:

- wysokość zawieszenia i zwis światłowodu dla danej rozpiętości (≤22 m: 6,2 m; 23–40 m: 6,7 m; >40 m: 7,2 m; zwis 3% / 2,5%),
- wysokość linii nN i słupa dla danego typu słupa (np. słupy 10,5 m: 8,2 m; 10 m: 7,7 m),
- nagłówek, warstwy, rodzaje linii i style DXF, które służą jako szablon pliku wynikowego.

## Plik opisów (CSV)

Miejscowości i ulic nie ma w planie, więc wpisuje się je w pliku CSV (separator `;`, UTF‑8). Plik jest tworzony
przy pierwszym uruchomieniu. Po jego uzupełnieniu uruchom program ponownie. Wiersze są dopasowywane po współrzędnych
okręgu. Każde niepuste pole (np. `stacja`, `typ_l`, `rozpietosc`) nadpisuje wartość ustaloną automatycznie.
Pola `stacja2`/`obwod2` są używane, gdy przęsło łączy dwa obwody.

Jeśli stacji nie da się ustalić (opis obwodu jest dalej niż 150 m od stacji), program wpisze `ST ?` i wypisze ostrzeżenie.

## Opcje

```
-o, --wynik     plik wynikowy DXF
--baza          plik bazy (domyślnie "przewieszenia baza.dxf" obok programu)
--szablon       inny plik DXF jako szablon (domyślnie baza)
--opisy         plik CSV z opisami
--obrot-od 50   przęsła dłuższe niż 50 m są rysowane pionowo (0 = nigdy)
--warstwa, --warstwa-trasy   inne nazwy warstw
```

## Pliki

- `przewieszenia.py` – program główny
- `plan.py` – analiza planu (słupy, przęsła, obwody)
- `baza.py` – parametry odczytane z bazy rysunków
- `rysunek.py` – geometria pojedynczego rysunku (siatka, linijki, słupy, krzywe zwisu, opisy)
- `zapis.py`, `dxfio.py` – odczyt i zapis DXF
