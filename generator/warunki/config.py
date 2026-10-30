"""Ustawienia programu - nazwy warstw, wygląd numeracji, tolerancje, ścieżki."""
import sys
from dataclasses import dataclass, field
from pathlib import Path

# [GeneratorNN] Szablony leżą w pakiecie (generator/warunki/szablony - także w .exe, bo
# PyInstaller umieszcza moduł w _MEIPASS/generator/warunki), a dane użytkownika (słowniki
# operatorów/rejonów, pamięć kafli) w %LOCALAPPDATA%\GeneratorNN\warunki - przeżywają aktualizacje.
import os

SZABLONY = Path(__file__).resolve().parent / "szablony"
DANE = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".config") / "GeneratorNN" / "warunki"
KATALOG = DANE      # zgodność z oryginałem (autotest itp.)


@dataclass
class Config:
    # --- Warstwy wejściowe (nazwy bez rozróżniania wielkości liter) ---
    warstwa_tele: str = "!tele"     # polilinie, wierzchołek = słup
    warstwa_trafo: str = "!trafo"   # obrysy zasięgu stacji trafo
    prefiks_warstwy_trafo: str = "_trafo"  # ...oraz warstwy o nazwie zaczynającej się od
    # Opisy stacji: MULTILEADER/TEXT/MTEXT na warstwach zawierających ten fragment
    fragment_warstwy_opisu_trafo: str = "trafo"
    # Opisy słupów (MULTILEADER "słup nN\\P<typ>") - strzałka wskazuje słup
    prefiks_opisu_slupa: str = "słup"
    # Numery słupów w sieci (np. 9, 9.1, 14.2) - teksty na warstwach o nazwie zaczynającej się od:
    prefiks_warstwy_numerow: str = "_numery"
    odl_numeru: float = 15.0   # maks. odległość tekstu numeru od słupa [m]

    # --- Numeracja w DXF (wygląd jak w numeracja_leader.dxf) ---
    warstwa_numeracji: str = "makro-numeracja-punktow"
    kolor_warstwy: int = 7
    styl_tekstu: str = "GeodText"
    czcionka_stylu: str = "romans.shx"
    wysokosc_tekstu: float = 3.0
    odsuniecie_x: float = 3.73     # załamanie odnośnika względem słupa
    odsuniecie_y: float = 3.0
    polka: float = 0.18            # długość "półki" odnośnika
    odstep_tekstu: float = 0.09    # odstęp tekstu od końca półki
    grubosc_linii: int = 30        # 0.30 mm
    # Odnośnik po stronie z dala od linii (True) albo zawsze w prawo-górę (False)
    inteligentny_kierunek: bool = True

    # Raport długich przęseł [m]: pokazywane powyżej progu, na czerwono powyżej progu błędu
    przeslo_ostrzezenie: float = 55.0
    przeslo_blad: float = 60.0

    # Wierzchołki bliżej niż ta odległość [m] = jeden słup (błędny klik)
    tolerancja_slupa: float = 5.0

    numer_startowy: int = 1
    prefiks: str = ""

    grupa_nieznana: str = "NIEUSTALONA MIEJSCOWOŚĆ"
    promien_adresu: int = 300
    odl_ulicy: float = 30.0   # sprawdzanie ulic: drogi OSM w tej odległości od słupa [m]
    miejsca_po_przecinku: int = 2
    # Współrzędne w zestawieniach i piśmie: False = PL-2000 (X, Y), True = WGS 84 (szer., dł.)
    wgs84: bool = False
    miejsca_wgs84: int = 7

    # Domyślne wartości kolumn zestawienia rozbudowanego
    linie_swiatlowodowe: int = 1
    linie_abonenckie: int = 0

    # --- Arkusze rysunkowe (szablon szablony/arkusze_wt.dxf) ---
    uklad_trasy: str = "a (2)"            # układ szablonu dla arkuszy trasy
    uklad_orientacji: str = "ORIENTACJA"  # układ szablonu dla planu orientacyjnego
    skala_arkuszy: int = 1000
    zakladka: float = 10.0                # zakładka arkuszy wzdłuż trasy [m]
    margines_mm: float = 10.0             # odstęp trasy od ramki i tabelki [mm papieru]
    margines_orientacji_mm: float = 5.0
    zapas_podkladu_mm: float = 10.0       # podkład poza widokiem arkusza orientacji [mm papieru]
    warstwa_obrysow: str = "WT_arkusze"   # obrysy arkuszy w modelu (niedrukowalna)
    wysokosc_branzy: float = 1.75         # tekst w polu "Branża:" tabelki [mm]
    nazwa_orientacji: str = "Plan orientacyjny - układ arkusza"
    warstwa_trasy_orientacji: str = "WT_trasa"
    warstwa_podkladu: str = "WT_podklad"

    # --- Format rysunków wynikowych (numeracja, plan orientacyjny): "dwg" albo "dxf" ---
    # DWG wymaga programu ODA File Converter (patrz dwg.py); pusta ścieżka = szukaj sam
    format_rysunkow: str = "dwg"
    oda_sciezka: str = ""

    # --- Pliki ---
    szablon_pisma: Path = field(default_factory=lambda: SZABLONY / "pismo_warunki.docx")
    szablon_rozbudowana: Path = field(default_factory=lambda: SZABLONY / "rozbudowana.xlsx")
    szablon_projektowa: Path = field(default_factory=lambda: SZABLONY / "tabela_projektowa.xlsx")
    szablon_uproszczona: Path = field(default_factory=lambda: SZABLONY / "uproszczona.xls")
    szablon_arkuszy: Path = field(default_factory=lambda: SZABLONY / "arkusze_wt.dxf")
    katalog_kafli: Path = field(default_factory=lambda: DANE / "kafle")
    plik_slownikow: Path = field(default_factory=lambda: DANE / "slowniki.xlsx")
