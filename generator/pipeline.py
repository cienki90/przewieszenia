#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Łańcuch przetwarzania: jeden plik DXF -> przewieszenia + zestawienie + obliczenia.

Z jednego rysunku planu DXF program może wykonać (dowolny podzbiór):

  1. PRZEWIESZENIA – rysunki zwisów przęseł linii nN ze światłowodem  -> plik DXF,
  2. ZESTAWIENIE   – zestawienie słupów nN w podziale na stacje          -> plik XLSX,
  3. OBLICZENIA    – obliczenia nośności słupów (na podstawie zestawienia) -> plik XLSX.

Krok OBLICZENIA korzysta z wyniku kroku ZESTAWIENIE. Jeśli włączono obliczenia bez
zestawienia, program i tak zbuduje zestawienie (w pliku tymczasowym), żeby mieć dane
wejściowe do obliczeń.

Użycie z wiersza poleceń:
    python -m generator.pipeline plan.dxf
    python -m generator.pipeline plan.dxf --tylko zestawienie,obliczenia -o wyniki/
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field

from . import obliczenia as mod_obliczenia
from . import opisy as mod_opisy
from . import orientacje as mod_orientacje
from . import przewieszenia as mod_przewieszenia
from . import pzt as mod_pzt
from . import zestawienie as mod_zestawienie
from .numeruj_slupy import przetworz as _numeruj_slupy

# nazwy kroków (kolejność ma znaczenie) - „numeracja” jako pierwszy (projektant najpierw
# numeruje słupy w planie, potem robi resztę; krok tworzy osobny plik „… - ponumerowane.dxf”)
KROKI = ("numeracja", "przewieszenia", "zestawienie", "obliczenia", "orientacje", "pzt", "opisy")


# ---------------------------------------------------------------------------
@dataclass
class Opcje:
    """Ustawienia uruchomienia łańcucha."""
    plan: str                                   # plik planu DXF (wejście)
    katalog: str | None = None                  # katalog zapisu (domyślnie obok planu)
    kroki: tuple = KROKI                         # które kroki wykonać
    # przewieszenia
    adresy: str = "uug,osm"                     # źródła nazw ulic ("brak" = bez internetu)
    obrot_od: float = 50.0
    zostaw_puste_arkusze: bool = False
    # obliczenia
    seed: int | None = None
    kabel: int = mod_obliczenia.DOMYSLNY_KABEL
    obliczenia_zestawienie: str | None = None    # własny plik zestawienia (.xls/.xlsx) - pomija budowanie z DXF
    # orientacje (rysunki stałe)
    orient_podklad: bool = True                  # pobierać podkład mapowy (wymaga internetu + Pillow)
    orient_szablon: str | None = None            # szablon rysunków stałych (gdy inny niż plan; None = dołączony)
    orient_plan_slupow: str | None = None        # plan ze słupami - źródło miejscowości (wiązanie po nr stacji)
    # arkusze PZT
    pzt_wzorzec: str | None = None               # plik z layoutem-wzorcem "a" (None = plan wejściowy)
    pzt_zaklad: float = 50.0                     # wspólny odcinek trasy sąsiednich arkuszy [m]
    # Warunki Techniczne (WT) - źródło miejscowości słupów wg zasięgu stacji (zamiast geokodowania)
    wt_plik: str | None = None                   # plik WT (.xls/.xlsx); None = geokodowanie
    # opisy techniczne (.docx)
    opisy_szablon: str | None = None             # szablon .docx (None = dołączony szablon_opisu.docx)
    opisy_zestawienie: str | None = None         # xlsx z danymi (None = zestawienie z kroku orientacje)
    opisy_wt: str = ""                           # numer warunków (WT) - wspólny, wpisywany ręcznie
    opisy_obliczenia: str | None = None          # opcjonalny xlsx obliczeń (tabela nośności)
    log: object = print                          # funkcja logowania (podmieniana w GUI)


@dataclass
class WynikKroku:
    nazwa: str
    ok: bool
    wyjscie: str | None = None
    raport: str = ""
    blad: str | None = None


@dataclass
class Wynik:
    kroki: list = field(default_factory=list)   # [WynikKroku]

    @property
    def ok(self) -> bool:
        return all(k.ok for k in self.kroki) and bool(self.kroki)

    def plik(self, nazwa_kroku: str):
        for k in self.kroki:
            if k.nazwa == nazwa_kroku and k.ok:
                return k.wyjscie
        return None


# ---------------------------------------------------------------------------
def _bazowa_nazwa(plan: str) -> str:
    return os.path.splitext(os.path.basename(plan))[0]


def domyslne_wyjscia(plan: str, katalog: str | None = None) -> dict:
    """Domyślne ścieżki wyników dla danego planu."""
    kat = katalog or os.path.dirname(os.path.abspath(plan))
    baza = _bazowa_nazwa(plan)
    return {
        "numeracja": os.path.join(kat, f"{baza} - ponumerowane.dxf"),
        "przewieszenia": os.path.join(kat, f"{baza} - przewieszenia.dxf"),
        "zestawienie": os.path.join(kat, f"zestawienie {baza}.xlsx"),
        "obliczenia": os.path.join(kat, f"Obliczenia - zestawienie {baza}.xlsx"),
        "orientacje": os.path.join(kat, "rysunki stałe"),   # podfolder z planami stacji + zestawieniem
        "pzt": os.path.join(kat, f"{baza} - PZT.dxf"),       # kopia planu z arkuszami PZT
        "opisy": os.path.join(kat, "opisy"),                 # podfolder z opisami .docx
    }


def _przechwyc(funkcja, *args, **kwargs):
    """Uruchamia funkcję, przechwytując jej wydruki (stdout/stderr) do tekstu."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        wynik = funkcja(*args, **kwargs)
    return wynik, buf.getvalue()


# ---------------------------------------------------------------------------
def uruchom(opcje: Opcje) -> Wynik:
    """Wykonuje wybrane kroki łańcucha i zwraca zbiorczy wynik."""
    log = opcje.log or (lambda *_: None)
    plan = opcje.plan
    kroki = [k for k in KROKI if k in opcje.kroki]          # zachowaj właściwą kolejność
    # wyjątek: same obliczenia z własnym plikiem zestawienia nie wymagają planu DXF -
    # nazwy wyników i katalog bierzemy wtedy z pliku zestawienia
    tylko_obliczenia_z_zest = (set(kroki) <= {"obliczenia"} and bool(opcje.obliczenia_zestawienie))
    if not os.path.isfile(plan):
        if tylko_obliczenia_z_zest and os.path.isfile(opcje.obliczenia_zestawienie):
            plan = opcje.obliczenia_zestawienie
        else:
            raise FileNotFoundError(f"Nie znaleziono pliku planu DXF: {plan}")
    katalog = opcje.katalog or os.path.dirname(os.path.abspath(plan))
    os.makedirs(katalog, exist_ok=True)
    wyj = domyslne_wyjscia(plan, katalog)
    # gdy „planem” jest plik zestawienia (obliczenia z własnego zestawienia), nie dubluj słowa
    # „zestawienie” w nazwie wyniku obliczeń: "zestawienie X.xlsx" -> "Obliczenia - zestawienie X.xlsx"
    if tylko_obliczenia_z_zest:
        baza = _bazowa_nazwa(plan)
        rdzen = baza[len("zestawienie"):].strip() if baza.lower().startswith("zestawienie") else baza
        wyj["obliczenia"] = os.path.join(katalog, f"Obliczenia - zestawienie {rdzen}.xlsx")

    # obliczenia wymagają zestawienia. Priorytet: własny plik wskazany przez użytkownika;
    # w przeciwnym razie zbuduj zestawienie (osobny krok albo tymczasowo z planu DXF).
    zestawienie_plik = None
    zestawienie_tymczasowe = False
    if "obliczenia" in kroki and opcje.obliczenia_zestawienie:
        if not os.path.isfile(opcje.obliczenia_zestawienie):
            raise FileNotFoundError(
                f"Nie znaleziono pliku zestawienia dla obliczeń: {opcje.obliczenia_zestawienie}")
        zestawienie_plik = opcje.obliczenia_zestawienie    # użyj wprost, nie buduj z DXF
    elif "obliczenia" in kroki and "zestawienie" not in kroki:
        kroki.insert(kroki.index("obliczenia"), "zestawienie")
        zestawienie_tymczasowe = True

    # opisy mogą korzystać z zestawienia_stacji.xlsx z kroku „orientacje” - uruchom go wcześniej,
    # gdy opisy zaznaczono bez własnego zestawienia i bez orientacji
    orient_zest = None
    if ("opisy" in kroki and "orientacje" not in kroki
            and not opcje.opisy_zestawienie):
        kroki.insert(kroki.index("opisy"), "orientacje")

    wynik = Wynik()

    for krok in kroki:
        tymczasowy = zestawienie_tymczasowe and krok == "zestawienie"
        log(f"\n=== {krok.upper()} ===")
        try:
            if krok == "numeracja":
                r = _krok_numeracja(plan, wyj["numeracja"])
            elif krok == "przewieszenia":
                r = _krok_przewieszenia(plan, wyj["przewieszenia"], opcje)
            elif krok == "zestawienie":
                r = _krok_zestawienie(plan, wyj["zestawienie"], tymczasowy, katalog)
                zestawienie_plik = r.wyjscie
            elif krok == "obliczenia":
                if not zestawienie_plik:
                    raise RuntimeError("Brak zestawienia - nie można wykonać obliczeń.")
                r = _krok_obliczenia(zestawienie_plik, wyj["obliczenia"], opcje)
            elif krok == "orientacje":
                szablon = opcje.orient_szablon
                plan_slupow = None
                if not szablon:
                    from . import zasoby
                    szablon = zasoby.szablon_orientacji_dxf() or plan
                if opcje.orient_plan_slupow:
                    plan_slupow = opcje.orient_plan_slupow        # jawnie wskazany plan ze słupami
                elif os.path.abspath(szablon) != os.path.abspath(plan):
                    # szablon rysunków stałych jest innym plikiem niż plan tras ze słupami ->
                    # miejscowości ustal ze słupów planu i powiąż z szablonem po NUMERZE stacji
                    plan_slupow = plan
                r = _krok_orientacje(szablon, wyj["orientacje"], opcje, plan_slupow)
            elif krok == "pzt":
                r = _krok_pzt(plan, wyj["pzt"], opcje)
            elif krok == "opisy":
                r = _krok_opisy(opcje, wyj["opisy"], orient_zest)
            else:
                continue
            if krok == "orientacje" and r.ok and r.wyjscie:
                zc = os.path.join(r.wyjscie, "zestawienie_stacji.xlsx")
                orient_zest = zc if os.path.exists(zc) else orient_zest
        except Exception as ex:  # noqa: BLE001 - raport trafia do użytkownika
            r = WynikKroku(krok, ok=False, blad=str(ex),
                           raport=traceback.format_exc())
            log(f"BŁĄD: {ex}")
        if r.raport:
            log(r.raport.rstrip())
        if r.ok and not tymczasowy and r.wyjscie:
            log(f"-> zapisano: {r.wyjscie}")
        # krok tymczasowy (zestawienie pomocnicze) nie trafia do podsumowania
        if not tymczasowy:
            wynik.kroki.append(r)

    # sprzątanie pliku tymczasowego zestawienia
    if zestawienie_tymczasowe and zestawienie_plik and os.path.exists(zestawienie_plik):
        try:
            os.remove(zestawienie_plik)
        except OSError:
            pass

    return wynik


# ---------------------------------------------------------------------------
def _krok_numeracja(plan: str, wyjscie: str) -> WynikKroku:
    """Numeracja słupów nN: z planu z zaznaczonymi słupami „1” i „2” każdego obwodu
    tworzy „… - ponumerowane.dxf” z numerami i obrysami kontrolnymi (wymaga ezdxf)."""
    def uruchom():
        return _numeruj_slupy(plan, wyjscie)   # zwraca (ścieżka_wyniku, raport_tekstowy)
    try:
        (wynik, wydruk) = _przechwyc(uruchom)
    except ImportError:
        return WynikKroku("numeracja", ok=False,
                          raport="Moduł numeracji słupów wymaga biblioteki ezdxf "
                                 "(zainstaluj: pip install ezdxf).",
                          blad="Brak biblioteki ezdxf.")
    plik = wynik[0] if isinstance(wynik, tuple) else (wynik if isinstance(wynik, str) else wyjscie)
    raport_mod = wynik[1] if isinstance(wynik, tuple) and len(wynik) > 1 else ""
    tekst = (raport_mod + ("\n" if raport_mod and wydruk else "") + (wydruk or "")).strip()
    ok = bool(plik) and os.path.exists(plik)
    return WynikKroku("numeracja", ok=ok, wyjscie=plik if ok else None, raport=tekst,
                      blad=None if ok else "Nie udało się ponumerować słupów "
                                           "(czy w planie są markery „1” i „2” oraz opisy „obw. nr”?).")


# ---------------------------------------------------------------------------
def _krok_przewieszenia(plan: str, wyjscie: str, opcje: Opcje) -> WynikKroku:
    # kopia planu z numerami przewieszeń trafia do katalogu wyników (obok rysunków)
    kontrola = os.path.join(os.path.dirname(wyjscie),
                            _bazowa_nazwa(plan) + " - kontrola.dxf")
    argv = [plan, "-o", wyjscie, "--adresy", opcje.adresy, "--obrot-od", str(opcje.obrot_od),
            "--kontrola", kontrola]
    if opcje.zostaw_puste_arkusze:
        argv.append("--zostaw-puste-arkusze")
    kod, raport = _przechwyc(mod_przewieszenia.main, argv)
    ok = (kod == 0) and os.path.exists(wyjscie)
    r = WynikKroku("przewieszenia", ok=ok, wyjscie=wyjscie if ok else None, raport=raport,
                   blad=None if ok else "Nie udało się utworzyć rysunków przewieszeń.")
    if ok and os.path.exists(kontrola):
        r.raport = (r.raport + f"\n-> kopia planu z numerami (kontrola): {kontrola}").strip()
    return r


def _krok_zestawienie(plan: str, wyjscie: str, tymczasowy: bool, katalog: str) -> WynikKroku:
    if tymczasowy:
        fd, wyjscie = tempfile.mkstemp(suffix=".xlsx", prefix="zestawienie_", dir=katalog)
        os.close(fd)
    raport, log = _przechwyc(mod_zestawienie.przetworz, plan, wyjscie)
    ok = os.path.exists(wyjscie)
    tekst = (log + ("\n" if log and raport else "") + (raport or "")).strip()
    return WynikKroku("zestawienie", ok=ok, wyjscie=wyjscie if ok else None, raport=tekst,
                      blad=None if ok else "Nie udało się utworzyć zestawienia.")


def _krok_obliczenia(zestawienie_plik: str, wyjscie: str, opcje: Opcje) -> WynikKroku:
    wynik, raport = _przechwyc(mod_obliczenia.oblicz, zestawienie_plik, wyjscie,
                               opcje.seed, opcje.kabel, True)
    plik = wynik[0] if isinstance(wynik, tuple) else wyjscie
    linie = wynik[2] if isinstance(wynik, tuple) and len(wynik) > 2 else []
    tekst = ("\n".join(linie) + ("\n" if linie and raport else "") + (raport or "")).strip()
    ok = os.path.exists(plik)
    return WynikKroku("obliczenia", ok=ok, wyjscie=plik if ok else None, raport=tekst,
                      blad=None if ok else "Nie udało się wykonać obliczeń.")


def _nazwy_csv_z_wt(plan_slupow: str, wt_plik: str, wyjscie_dir: str, log=print):
    """Buduje CSV 'numer;miejscowość' z Warunków Technicznych (dla kroku orientacje).

    Miejscowości ustalane wg zasięgu stacji (słupy WT dopasowane do wierzchołków !tele w !trafo).
    Zwraca ścieżkę CSV albo None, gdy nie udało się nic ustalić."""
    try:
        from . import wt as mod_wt
    except ImportError:
        import wt as mod_wt
    try:
        mapa, ostrz = mod_wt.miejscowosci_stacji_z_wt(plan_slupow, wt_plik, log=log)
    except Exception as ex:  # noqa: BLE001 - WT jest dodatkiem; przy błędzie zostaje geokodowanie
        log(f"UWAGA: nie udało się odczytać miejscowości z WT ({ex}) - użyję geokodowania.")
        return None
    for o in ostrz:
        log("UWAGA: " + o)
    if not mapa:
        return None
    import csv as _csv
    sciezka = os.path.join(wyjscie_dir, "_nazwy_wt.csv")
    with open(sciezka, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f, delimiter=";", quoting=_csv.QUOTE_MINIMAL)
        w.writerow(["numer", "miejscowosc"])
        for nr, miejsc in sorted(mapa.items()):
            w.writerow([nr, ", ".join(miejsc)])
    return sciezka


def _krok_orientacje(szablon: str, wyjscie_dir: str, opcje: Opcje, plan_slupow=None) -> WynikKroku:
    """Rysunki stałe (orientacje): dla każdej stacji trafo z szablonu - osobny plan DXF + zestawienie.

    szablon       - szablon rysunków stałych (odnośniki 'STACJA TRAFO' + obrysy !trafo),
    plan_slupow   - opcjonalny plan ze słupami: miejscowości ustalane z geokodowania słupów
                    i wiązane z szablonem po NUMERZE stacji trafo."""
    os.makedirs(wyjscie_dir, exist_ok=True)
    argv = [szablon, "--wyniki", wyjscie_dir, "--bez-pytania"]
    if not opcje.orient_podklad:
        argv.append("--bez-podkladu")
    if plan_slupow:
        argv += ["--plan-slupow", plan_slupow]
    # miejscowości z Warunków Technicznych (WT) - nadrzędne źródło nazw, spójne z PZT/opisami
    nazwy_csv = None
    if opcje.wt_plik and plan_slupow:
        nazwy_csv = _nazwy_csv_z_wt(plan_slupow, opcje.wt_plik, wyjscie_dir, log=opcje.log)
        if nazwy_csv:
            argv += ["--nazwy", nazwy_csv]
    kod, raport = _przechwyc(mod_orientacje.main, argv)
    # sukces: powstało zestawienie_stacji.xlsx albo przynajmniej jeden plik .dxf
    zest = os.path.join(wyjscie_dir, "zestawienie_stacji.xlsx")
    pliki_dxf = [f for f in os.listdir(wyjscie_dir)] if os.path.isdir(wyjscie_dir) else []
    ok = (kod == 0) and (os.path.exists(zest) or any(f.lower().endswith(".dxf") for f in pliki_dxf))
    return WynikKroku("orientacje", ok=ok, wyjscie=wyjscie_dir if ok else None, raport=raport,
                      blad=None if ok else "Nie udało się utworzyć rysunków stałych "
                                           "(czy rysunek zawiera opisy STACJA TRAFO i obrysy !trafo?).")


def _krok_pzt(dxf: str, wyjscie: str, opcje: Opcje) -> WynikKroku:
    """Arkusze PZT: dla każdej stacji trafo komplet arkuszy A3 1:1000 pokrywających trasę.

    Wzorzec layoutu „a” jest w pliku wejściowym albo w osobnym pliku (opcje.pzt_wzorzec)."""
    def uruchom():
        return mod_pzt.przetworz(dxf, wyjscie, wzorzec=opcje.pzt_wzorzec,
                                 adresy=opcje.adresy, wt_plik=opcje.wt_plik,
                                 zaklad=opcje.pzt_zaklad, log=print)
    (wynik, raport) = _przechwyc(uruchom)
    plik = wynik[0] if isinstance(wynik, tuple) else wyjscie
    ok = os.path.exists(plik)
    return WynikKroku("pzt", ok=ok, wyjscie=plik if ok else None, raport=raport,
                      blad=None if ok else "Nie udało się utworzyć arkuszy PZT "
                                           "(czy w pliku są warstwy !tele, !trafo i layout-wzorzec „a”?).")


def _krok_opisy(opcje: Opcje, wyjscie_dir: str, orient_zest) -> WynikKroku:
    """Opisy techniczne .docx: dla każdej stacji z zestawienia osobny plik .docx z szablonu.

    Zestawienie: wskazane przez użytkownika albo zestawienie_stacji.xlsx z kroku „orientacje”.
    Numer WT (jeden wspólny) wpisywany ręcznie - gdy zestawienie go nie zawiera."""
    from . import zasoby
    szablon = opcje.opisy_szablon or zasoby.szablon_opisu_docx()
    zestawienie = opcje.opisy_zestawienie or orient_zest
    if not szablon:
        return WynikKroku("opisy", ok=False, blad="Brak szablonu opisu (.docx) - wskaż plik szablonu.")
    if not zestawienie:
        return WynikKroku("opisy", ok=False,
                          blad="Brak zestawienia - wskaż plik .xlsx albo włącz krok „rysunki stałe” "
                               "(użyte zostanie jego zestawienie_stacji.xlsx).")
    # domyślnie zapisuj opisy w FOLDERZE WSKAZANEGO szablonu (gdy użytkownik podał własny szablon);
    # dla szablonu dołączonego (z zasobów/.exe) zostaje podfolder „opisy” w katalogu wyników
    if opcje.opisy_szablon and os.path.isfile(opcje.opisy_szablon):
        wyjscie_dir = os.path.dirname(os.path.abspath(opcje.opisy_szablon))
    os.makedirs(wyjscie_dir, exist_ok=True)

    def uruchom():
        return mod_opisy.generuj(szablon, zestawienie, out=wyjscie_dir, wt=opcje.opisy_wt,
                                 obliczenia=opcje.opisy_obliczenia, log=print)
    try:
        (utworzone, raport) = _przechwyc(uruchom)
    except ImportError:
        return WynikKroku("opisy", ok=False,
                          raport="Moduł opisów wymaga bibliotek python-docx i openpyxl "
                                 "(zainstaluj: pip install python-docx openpyxl).",
                          blad="Brak bibliotek python-docx / openpyxl.")
    pliki = [f for f in os.listdir(wyjscie_dir) if f.lower().endswith(".docx")] if os.path.isdir(wyjscie_dir) else []
    ok = bool(pliki)
    return WynikKroku("opisy", ok=ok, wyjscie=wyjscie_dir if ok else None, raport=raport,
                      blad=None if ok else "Nie utworzono żadnego opisu .docx.")


# ---------------------------------------------------------------------------
def main(argv=None):
    for strumien in (sys.stdout, sys.stderr):  # polskie znaki w konsoli Windows
        try:
            strumien.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(
        description="Zunifikowany generator: z jednego planu DXF tworzy przewieszenia, "
                    "zestawienie słupów i obliczenia nośności.")
    ap.add_argument("plan", help="plik DXF planu")
    ap.add_argument("-o", "--katalog", default=None,
                    help="katalog zapisu wyników (domyślnie obok planu)")
    ap.add_argument("--tylko", default=",".join(KROKI),
                    help="które kroki wykonać, po przecinku: przewieszenia,zestawienie,obliczenia "
                         f"(domyślnie wszystkie: {','.join(KROKI)})")
    ap.add_argument("--adresy", default="uug,osm",
                    help="źródła nazw miejscowości/ulic: uug,osm lub 'brak' (bez internetu)")
    ap.add_argument("--obrot-od", type=float, default=50.0,
                    help="przęsła dłuższe niż ta wartość [m] rysowane pionowo (0 = tylko gdy trzeba)")
    ap.add_argument("--zostaw-puste-arkusze", action="store_true")
    ap.add_argument("--seed", type=int, default=None,
                    help="ziarno losowania kątów słupów narożnych (powtarzalne obliczenia)")
    ap.add_argument("--kabel", type=int, default=mod_obliczenia.DOMYSLNY_KABEL,
                    help="domyślny rodzaj kabla w obliczeniach (1-11)")
    ap.add_argument("--obliczenia-zestawienie", default=None,
                    help="własny plik zestawienia (.xls/.xlsx) do obliczeń - zamiast budowania z planu DXF")
    ap.add_argument("--bez-podkladu", action="store_true",
                    help="rysunki stałe (orientacje) bez pobierania podkładu mapowego z internetu")
    ap.add_argument("--szablon-orientacji", default=None,
                    help="plik szablonu DXF dla rysunków stałych (domyślnie dołączony 'szablon.dxf')")
    ap.add_argument("--plan-slupow", default=None,
                    help="plan DXF ze słupami - źródło miejscowości dla rysunków stałych "
                         "(wiązanie z szablonem po numerze stacji trafo; domyślnie plan wejściowy)")
    ap.add_argument("--pzt-wzorzec", default=None,
                    help="plik DXF z layoutem-wzorcem „a” dla arkuszy PZT (domyślnie plan wejściowy)")
    ap.add_argument("--pzt-zaklad", type=float, default=50.0,
                    help="arkusze PZT: wspólny odcinek trasy sąsiednich arkuszy [m] (domyślnie 50)")
    ap.add_argument("--wt", default=None,
                    help="plik Warunków Technicznych (.xls/.xlsx) - miejscowości słupów wg zasięgu "
                         "stacji trafo (zamiast geokodowania; współrzędne PUWG2000 lub WGS84)")
    ap.add_argument("--opisy-szablon", default=None,
                    help="szablon .docx dla opisów technicznych (domyślnie dołączony szablon_opisu.docx)")
    ap.add_argument("--opisy-zestawienie", default=None,
                    help="plik .xlsx z danymi do opisów (domyślnie zestawienie_stacji.xlsx z rysunków stałych)")
    ap.add_argument("--opisy-wt", default="",
                    help="numer warunków technicznych (WT) do opisów - jeden wspólny, wpisywany ręcznie")
    ap.add_argument("--opisy-obliczenia", default=None,
                    help="opcjonalny .xlsx z obliczeniami nośności - dołącza tabelę do opisów")
    a = ap.parse_args(argv)

    wybrane = tuple(k.strip().lower() for k in a.tylko.split(",") if k.strip())
    nieznane = [k for k in wybrane if k not in KROKI]
    if nieznane:
        ap.error(f"nieznane kroki: {', '.join(nieznane)} (dozwolone: {', '.join(KROKI)})")

    opcje = Opcje(plan=a.plan, katalog=a.katalog, kroki=wybrane, adresy=a.adresy,
                  obrot_od=a.obrot_od, zostaw_puste_arkusze=a.zostaw_puste_arkusze,
                  seed=a.seed, kabel=a.kabel, obliczenia_zestawienie=a.obliczenia_zestawienie,
                  orient_podklad=not a.bez_podkladu,
                  orient_szablon=a.szablon_orientacji, orient_plan_slupow=a.plan_slupow,
                  pzt_wzorzec=a.pzt_wzorzec, pzt_zaklad=a.pzt_zaklad, wt_plik=a.wt,
                  opisy_szablon=a.opisy_szablon, opisy_zestawienie=a.opisy_zestawienie,
                  opisy_wt=a.opisy_wt, opisy_obliczenia=a.opisy_obliczenia, log=print)
    wynik = uruchom(opcje)

    print("\n" + "=" * 60)
    print("PODSUMOWANIE")
    for k in wynik.kroki:
        stan = "OK   " if k.ok else "BŁĄD "
        print(f"  [{stan}] {k.nazwa:<14} {k.wyjscie or k.blad or ''}")
    return 0 if wynik.ok else 1


if __name__ == "__main__":
    sys.exit(main())
