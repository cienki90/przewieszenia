#!/usr/bin/env python3
"""Wersja przeglądarkowa generatora - serwer WWW do uruchomienia na NAS (albo dowolnym komputerze).

Działa na samym Pythonie (biblioteka standardowa); moduły generatora korzystają z tych samych
bibliotek co wersja okienkowa (requirements.txt, bez sv-ttk). Każde zadanie to osobny folder
z plikami wejściowymi i wynikami, a moduł uruchamiany jest w OSOBNYM PROCESIE (wiersz poleceń
generatora) - kilka osób może pracować jednocześnie, a błąd modułu nie zatrzymuje serwera.

Użycie:
    python generator_web.py                       # http://<adres NAS>:8765
    python generator_web.py --port 8080 --dane /volume1/generator --haslo tajne
"""
from __future__ import annotations

import argparse
import base64
import hmac
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

KATALOG_PROGRAMU = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRONA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strona.html")
MAKS_PLIK = 500 * 1024 * 1024                     # największy przyjmowany plik [B]
RE_ID = re.compile(r"^[0-9a-f]{12}$")

# ---------------------------------------------------------------------------
# Opis modułów dla strony: pola formularza i sposób zamiany na argumenty wiersza poleceń.
# Rodzaje pól: plik (jeden plik), pliki (kilka plików -> folder), tekst, liczba, wybor, flaga.
# „arg” - opcja wiersza poleceń; „plan” - pole jest plikiem/folderem głównym (argument pozycyjny);
# „odwrotnie” - flaga zaznaczona = opcji NIE dodajemy (np. podkład mapowy -> --bez-podkladu).
DWG = ".dxf,.dwg"
XLS = ".xlsx,.xls"
DOCX = ".docx"
POLE_DXF = {"id": "dxf", "rodzaj": "flaga", "etykieta": "Rysunki wynikowe w DXF (zamiast DWG)",
            "arg": "--dxf", "domyslnie": True}
POLE_INTERNET = {"id": "internet", "rodzaj": "flaga", "domyslnie": True,
                 "etykieta": "Nazwy miejscowości i ulic z internetu (GUGiK / OpenStreetMap)",
                 "arg": "--adresy", "wartosc_nie": "brak"}
POLE_WT_PLIK = {"id": "wt", "rodzaj": "plik", "typy": XLS, "arg": "--wt",
                "etykieta": "Plik warunków technicznych (WT) – opcjonalnie"}

MODULY = [
    {"id": "numeracja", "nazwa": "Numeracja słupów",
     "opis": "Numeruje słupy nN. W planie zaznacz ręcznie „1” i „2” dwóch pierwszych słupów każdego "
             "obwodu (warstwa _numery) oraz opis „obw. nr X”.",
     "pola": [{"id": "plan", "rodzaj": "plik", "typy": DWG, "plan": True, "wymagane": True,
               "etykieta": "Plik planu DXF/DWG"}, POLE_DXF]},
    {"id": "przewieszenia", "nazwa": "Przewieszenia",
     "opis": "Rysunki zwisów przęseł linii nN ze światłowodem oraz kopia planu z numerami przewieszeń.",
     "pola": [{"id": "plan", "rodzaj": "plik", "typy": DWG, "plan": True, "wymagane": True,
               "etykieta": "Plik planu DXF/DWG"},
              {"id": "obrot", "rodzaj": "liczba", "arg": "--obrot-od", "domyslnie": "45",
               "etykieta": "Przęsła dłuższe niż [m] rysuj pionowo (0 = tylko gdy trzeba)"},
              POLE_WT_PLIK, POLE_INTERNET,
              {"id": "puste", "rodzaj": "flaga", "arg": "--zostaw-puste-arkusze",
               "etykieta": "Zostaw puste arkusze"}, POLE_DXF]},
    {"id": "zestawienie", "nazwa": "Zestawienie",
     "opis": "Zestawienie słupów nN w podziale na stacje transformatorowe (.xlsx).",
     "pola": [{"id": "plan", "rodzaj": "plik", "typy": DWG, "plan": True, "wymagane": True,
               "etykieta": "Plik planu DXF/DWG"}]},
    {"id": "obliczenia", "nazwa": "Obliczenia",
     "opis": "Obliczenia nośności słupów. Podaj plan (zestawienie powstanie samo) ALBO własne zestawienie.",
     "pola": [{"id": "plan", "rodzaj": "plik", "typy": DWG, "plan": True,
               "etykieta": "Plik planu DXF/DWG"},
              {"id": "zest", "rodzaj": "plik", "typy": XLS, "arg": "--obliczenia-zestawienie",
               "etykieta": "Własne zestawienie (.xlsx) – zamiast planu"},
              {"id": "kabel", "rodzaj": "liczba", "arg": "--kabel", "domyslnie": "",
               "etykieta": "Domyślny rodzaj kabla (1–11, puste = domyślny)"},
              {"id": "seed", "rodzaj": "liczba", "arg": "--seed",
               "etykieta": "Ziarno losowania kątów (puste = losowo)"}]},
    {"id": "orientacje", "nazwa": "Rysunki stałe",
     "opis": "Osobny plan orientacyjny dla każdej stacji trafo + zestawienie stacji.",
     "pola": [{"id": "plan", "rodzaj": "plik", "typy": DWG, "plan": True,
               "etykieta": "Szablon rysunków stałych (puste = dołączony szablon.dxf)"},
              {"id": "zasiegi", "rodzaj": "plik", "typy": DWG, "arg": "--zasiegi",
               "etykieta": "Plik PZT (stacje i słupy)"},
              {"id": "slupy", "rodzaj": "plik", "typy": DWG, "arg": "--plan-slupow",
               "etykieta": "Plan ze słupami – źródło miejscowości (opcjonalnie)"},
              POLE_WT_PLIK,
              {"id": "podklad", "rodzaj": "flaga", "arg": "--bez-podkladu", "odwrotnie": True,
               "domyslnie": True, "etykieta": "Pobieraj podkład mapowy (OSM/Geoportal; wymaga internetu)"},
              {"id": "pdf", "rodzaj": "flaga", "arg": "--pdf-stacji",
               "etykieta": "Osobny PDF dla każdej stacji"}, POLE_DXF]},
    {"id": "pzt", "nazwa": "Arkusze PZT",
     "opis": "Komplet arkuszy A3 1:1000 dla każdej stacji (zakład między arkuszami).",
     "pola": [{"id": "plan", "rodzaj": "plik", "typy": DWG, "plan": True, "wymagane": True,
               "etykieta": "Plik planu DXF/DWG"},
              {"id": "wzorzec", "rodzaj": "plik", "typy": DWG, "arg": "--pzt-wzorzec",
               "etykieta": "Plik z layoutem-wzorcem „a” (puste = plan)"},
              {"id": "zaklad", "rodzaj": "liczba", "arg": "--pzt-zaklad", "domyslnie": "50",
               "etykieta": "Zakład sąsiednich arkuszy [m]"},
              POLE_WT_PLIK, POLE_INTERNET, POLE_DXF]},
    {"id": "opisy", "nazwa": "Opisy techniczne",
     "opis": "Osobny opis techniczny .docx dla każdej stacji (z szablonu Word).",
     "pola": [{"id": "zest", "rodzaj": "plik", "typy": XLS, "arg": "--opisy-zestawienie", "plan": True,
               "wymagane": True, "etykieta": "Zestawienie stacji (zestawienie_stacji.xlsx)"},
              {"id": "szablon", "rodzaj": "plik", "typy": DOCX, "arg": "--opisy-szablon",
               "etykieta": "Szablon opisu .docx (puste = dołączony)"},
              {"id": "obl", "rodzaj": "plik", "typy": XLS, "arg": "--opisy-obliczenia",
               "etykieta": "Obliczenia nośności (.xlsx) – opcjonalnie"},
              {"id": "wt_nr", "rodzaj": "tekst", "arg": "--opisy-wt", "etykieta": "Numer warunków (WT)"}]},
    {"id": "ppw", "nazwa": "PPW",
     "opis": "Zbiorczy opis techniczny (.docx) dla całego projektu.",
     "pola": [{"id": "zest", "rodzaj": "plik", "typy": XLS, "arg": "--ppw-zestawienie", "plan": True,
               "wymagane": True, "etykieta": "Zestawienie słupów (z modułu „Zestawienie”)"},
              {"id": "zest_st", "rodzaj": "plik", "typy": XLS, "arg": "--ppw-zestawienie-stacji",
               "etykieta": "Zestawienie stacji – miejscowości (zestawienie_stacji.xlsx)"},
              {"id": "szablon", "rodzaj": "plik", "typy": DOCX, "arg": "--ppw-szablon",
               "etykieta": "Szablon PPW .docx (puste = dołączony)"},
              {"id": "wt_nr", "rodzaj": "tekst", "arg": "--ppw-wt", "etykieta": "Numer warunków (WT)"}]},
    {"id": "ppw_renumer", "nazwa": "PPW – renumeracja rysunków",
     "opis": "Numery rysunku w tabelkach arkuszy STACJA-ARKUSZ oraz „Projekt powykonawczy”.",
     "pola": [{"id": "plik", "rodzaj": "plik", "typy": DWG, "arg": "--ppw-renumeruj", "plan": True,
               "wymagane": True, "etykieta": "Plik DXF/DWG z arkuszami (np. PZT)"}, POLE_DXF]},
    {"id": "zakladki", "nazwa": "Zakładki",
     "opis": "Strony-przekładki (nr stacji / miejscowość / WT) dla każdej stacji.",
     "pola": [{"id": "zest", "rodzaj": "plik", "typy": XLS, "arg": "--zakladki-zestawienie", "plan": True,
               "wymagane": True, "etykieta": "Zestawienie stacji (zestawienie_stacji.xlsx)"},
              {"id": "format", "rodzaj": "wybor", "arg": "--zakladki-format", "opcje": ["pdf", "docx"],
               "domyslnie": "pdf", "etykieta": "Format wyniku"},
              {"id": "wt_nr", "rodzaj": "tekst", "arg": "--zakladki-wt", "etykieta": "Numer warunków (WT)"}]},
    {"id": "pdf", "nazwa": "PDF z rysunków",
     "opis": "Każdy arkusz (layout) rysunków DXF/DWG jako strona PDF – bez CAD-a.",
     "pola": [{"id": "rysunki", "rodzaj": "pliki", "typy": DWG, "plan": True, "wymagane": True,
               "etykieta": "Rysunki DXF/DWG (można zaznaczyć kilka)"}]},
]
MODULY_WG_ID = {m["id"]: m for m in MODULY}


def _bezpieczna_nazwa(nazwa: str) -> str:
    """Nazwa pliku bez folderów i znaków niedozwolonych (polskie litery zostają)."""
    nazwa = os.path.basename((nazwa or "").replace("\\", "/")).strip()
    nazwa = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nazwa).strip(". ")
    return nazwa[:180] or "plik"


def argumenty(modul: dict, opcje: dict, pliki: dict, zasob_szablonu: str | None = None) -> list:
    """Argumenty wiersza poleceń generatora dla modułu i wartości formularza.

    pliki: id pola -> ścieżka wgranego pliku (dla pola „pliki” - folder z plikami)."""
    argv, plan = [], None
    for pole in modul["pola"]:
        pid, rodzaj = pole["id"], pole["rodzaj"]
        if rodzaj in ("plik", "pliki"):
            sciezka = pliki.get(pid)
            if not sciezka:
                if pole.get("wymagane"):
                    raise ValueError(f"Brak pliku: {pole['etykieta']}")
                continue
            if pole.get("plan") and plan is None:
                plan = sciezka
            if pole.get("arg"):
                argv += [pole["arg"], sciezka]
            continue
        wartosc = opcje.get(pid, pole.get("domyslnie"))
        if rodzaj == "flaga":
            zaznaczone = bool(wartosc)
            if "wartosc_nie" in pole:
                if not zaznaczone:
                    argv += [pole["arg"], pole["wartosc_nie"]]
            elif zaznaczone != bool(pole.get("odwrotnie")):
                argv.append(pole["arg"])
        else:
            wartosc = str(wartosc if wartosc is not None else "").strip()
            if rodzaj == "liczba" and wartosc:
                float(wartosc.replace(",", "."))          # ValueError dla nie-liczby
                wartosc = wartosc.replace(",", ".")
            if rodzaj == "wybor" and wartosc not in pole["opcje"]:
                raise ValueError(f"Niedozwolona wartość: {pole['etykieta']}")
            if wartosc:
                argv += [pole["arg"], wartosc]
    mid = modul["id"]
    if mid == "orientacje" and not plan:
        plan = zasob_szablonu
        if not plan:
            raise ValueError("Brak dołączonego szablonu rysunków stałych - wgraj szablon.")
    if mid == "obliczenia" and not plan:
        plan = pliki.get("zest")
        if not plan:
            raise ValueError("Wgraj plik planu albo własne zestawienie.")
    if mid == "ppw_renumer":
        return ["-"] + argv                               # plan pozycyjny jest wtedy nieużywany
    if not plan:
        raise ValueError("Brak pliku wejściowego.")
    return [plan, "--tylko", mid] + argv


# ---------------------------------------------------------------------------
class Zadanie:
    """Jedno uruchomienie modułu: folder z wejściem i wynikami + dziennik przebiegu."""

    def __init__(self, katalog: str, zid: str):
        self.id = zid
        self.katalog = katalog
        self.wejscie = os.path.join(katalog, "wejscie")
        self.wyniki = os.path.join(katalog, "wyniki")
        self.dziennik = os.path.join(katalog, "przebieg.txt")
        self.plik_stanu = os.path.join(katalog, "stan.json")

    # stan zapisywany w pliku - przetrwa ponowne uruchomienie serwera
    def stan(self) -> dict:
        try:
            with open(self.plik_stanu, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"stan": "nowe"}

    def zapisz_stan(self, **zmiany):
        s = self.stan()
        s.update(zmiany)
        tmp = self.plik_stanu + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False)
        os.replace(tmp, self.plik_stanu)

    def pliki_wynikowe(self) -> list:
        """Pliki utworzone lub zmienione przez moduł (wejście bez zmian się nie liczy)."""
        wgrane = self.stan().get("wgrane", {})
        wynik = []
        for baza in (self.wyniki, self.wejscie):
            for kat, _, pliki in os.walk(baza):
                for nazwa in pliki:
                    p = os.path.join(kat, nazwa)
                    wzgl = os.path.relpath(p, self.katalog).replace(os.sep, "/")
                    if wgrane.get(wzgl) == os.path.getmtime(p):
                        continue                           # wgrany plik, niezmieniony
                    # nazwa względem folderu projektu: w wejściu bez folderu pola (wejscie/<pole>/…)
                    nazwa_wzgl = os.path.relpath(p, baza).replace(os.sep, "/")
                    if baza == self.wejscie:
                        nazwa_wzgl = nazwa_wzgl.partition("/")[2] or nazwa_wzgl
                    wynik.append({"sciezka": wzgl, "nazwa": nazwa_wzgl, "rozmiar": os.path.getsize(p)})
        return sorted(wynik, key=lambda w: w["nazwa"].lower())


class Serwer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, adres, dane: str, haslo: str = "", rownolegle: int = 2, dni: float = 7.0):
        super().__init__(adres, Obsluga)
        self.dane = os.path.abspath(dane)
        self.zadania = os.path.join(self.dane, "zadania")
        os.makedirs(self.zadania, exist_ok=True)
        self.haslo = haslo
        self.dni = dni
        self.miejsca = threading.Semaphore(max(1, rownolegle))
        self.procesy: dict[str, subprocess.Popen] = {}
        self.blokada = threading.Lock()
        try:
            sys.path.insert(0, KATALOG_PROGRAMU)
            from generator import zasoby
            self.szablon_orientacji = zasoby.szablon_orientacji_dxf()
        except Exception:  # noqa: BLE001 - bez szablonu moduł zgłosi czytelny błąd
            self.szablon_orientacji = None
        self.sprzataj()

    def zadanie(self, zid: str) -> Zadanie | None:
        if not RE_ID.match(zid or ""):
            return None
        kat = os.path.join(self.zadania, zid)
        return Zadanie(kat, zid) if os.path.isdir(kat) else None

    def nowe_zadanie(self) -> Zadanie:
        zid = uuid.uuid4().hex[:12]
        kat = os.path.join(self.zadania, zid)
        os.makedirs(os.path.join(kat, "wejscie"))
        os.makedirs(os.path.join(kat, "wyniki"))
        z = Zadanie(kat, zid)
        z.zapisz_stan(stan="nowe", utworzone=time.time(), wgrane={})
        return z

    def sprzataj(self):
        """Usuwa zadania starsze niż self.dni (wyniki trzeba pobrać wcześniej)."""
        if self.dni <= 0:
            return
        granica = time.time() - self.dni * 86400
        for zid in os.listdir(self.zadania):
            kat = os.path.join(self.zadania, zid)
            if RE_ID.match(zid) and os.path.isdir(kat) and os.path.getmtime(kat) < granica \
                    and zid not in self.procesy:
                shutil.rmtree(kat, ignore_errors=True)

    def uruchom(self, z: Zadanie, argv: list):
        z.zapisz_stan(stan="w kolejce", argv=argv, start=time.time())
        threading.Thread(target=self._praca, args=(z, argv), daemon=True).start()

    def _praca(self, z: Zadanie, argv: list):
        with self.miejsca:
            z.zapisz_stan(stan="trwa")
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
            cmd = [sys.executable, os.path.join(KATALOG_PROGRAMU, "generator_cli.py")] + argv \
                + ["-o", z.wyniki]
            with open(z.dziennik, "w", encoding="utf-8") as log:
                log.write("Uruchamiam moduł…\n")
                log.flush()
                try:
                    p = subprocess.Popen(cmd, cwd=z.wyniki, stdout=log, stderr=subprocess.STDOUT, env=env)
                except OSError as ex:
                    log.write(f"BŁĄD: nie udało się uruchomić modułu: {ex}\n")
                    z.zapisz_stan(stan="błąd", koniec=time.time())
                    return
                with self.blokada:
                    self.procesy[z.id] = p
                kod = p.wait()
                with self.blokada:
                    self.procesy.pop(z.id, None)
            przerwane = z.stan().get("stan") == "przerwane"
            z.zapisz_stan(stan="przerwane" if przerwane else ("gotowe" if kod == 0 else "błąd"),
                          kod=kod, koniec=time.time())
        self.sprzataj()

    def przerwij(self, z: Zadanie):
        with self.blokada:
            p = self.procesy.get(z.id)
        if p:
            z.zapisz_stan(stan="przerwane")
            p.terminate()


class Obsluga(BaseHTTPRequestHandler):
    server: Serwer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):            # cichy dziennik dostępu (tylko błędy)
        pass

    # ---- odpowiedzi
    def _wyslij(self, kod, tresc: bytes, typ="application/json; charset=utf-8", naglowki=None):
        self.send_response(kod)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(tresc)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (naglowki or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(tresc)

    def _json(self, dane, kod=HTTPStatus.OK):
        self._wyslij(kod, json.dumps(dane, ensure_ascii=False).encode("utf-8"))

    def _blad(self, kod, tekst):
        self._json({"blad": tekst}, kod)

    def _autoryzacja(self) -> bool:
        if not self.server.haslo:
            return True
        nagl = self.headers.get("Authorization", "")
        if nagl.startswith("Basic "):
            try:
                _, _, haslo = base64.b64decode(nagl[6:]).decode("utf-8").partition(":")
            except ValueError:
                haslo = ""
            if hmac.compare_digest(haslo.encode(), self.server.haslo.encode()):
                return True
        self._wyslij(HTTPStatus.UNAUTHORIZED, "Wymagane hasło".encode(), "text/plain; charset=utf-8",
                     {"WWW-Authenticate": 'Basic realm="Generator nN", charset="UTF-8"'})
        return False

    def _tresc_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1024 * 1024:
            raise ValueError("Za duże zapytanie.")
        dane = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(dane, dict):
            raise ValueError("Nieprawidłowe zapytanie.")
        return dane

    # ---- trasy
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._autoryzacja():
            return
        url = urlparse(self.path)
        cz = [unquote(c) for c in url.path.strip("/").split("/") if c]
        if not cz:
            with open(STRONA, "rb") as f:
                return self._wyslij(HTTPStatus.OK, f.read(), "text/html; charset=utf-8")
        if cz == ["api", "moduly"]:
            from generator.wersja import wersja
            return self._json({"moduly": MODULY, "wersja": wersja()})
        if len(cz) >= 3 and cz[:2] == ["api", "zadanie"]:
            z = self.server.zadanie(cz[2])
            if not z:
                return self._blad(HTTPStatus.NOT_FOUND, "Nie ma takiego zadania (mogło zostać usunięte).")
            if len(cz) == 3:
                return self._stan_zadania(z, parse_qs(url.query))
            if cz[3:] == ["wyniki.zip"]:
                return self._zip(z)
            if cz[3] == "plik" and len(cz) > 4:
                return self._pobierz(z, "/".join(cz[4:]))
        self._blad(HTTPStatus.NOT_FOUND, "Nie znaleziono.")

    def do_POST(self):
        if not self._autoryzacja():
            return
        cz = [unquote(c) for c in urlparse(self.path).path.strip("/").split("/") if c]
        try:
            if cz == ["api", "zadanie"]:
                z = self.server.nowe_zadanie()
                return self._json({"id": z.id})
            if len(cz) == 4 and cz[:2] == ["api", "zadanie"]:
                z = self.server.zadanie(cz[2])
                if not z:
                    return self._blad(HTTPStatus.NOT_FOUND, "Nie ma takiego zadania.")
                if cz[3] == "start":
                    return self._start(z, self._tresc_json())
                if cz[3] == "przerwij":
                    self.server.przerwij(z)
                    return self._json({"ok": True})
        except ValueError as ex:
            return self._blad(HTTPStatus.BAD_REQUEST, str(ex))
        self._blad(HTTPStatus.NOT_FOUND, "Nie znaleziono.")

    def do_PUT(self):
        """Wgranie pliku: PUT /api/zadanie/<id>/plik?pole=<id pola>&nazwa=<nazwa pliku> (treść = plik)."""
        if not self._autoryzacja():
            return
        url = urlparse(self.path)
        cz = [unquote(c) for c in url.path.strip("/").split("/") if c]
        q = parse_qs(url.query)
        z = self.server.zadanie(cz[2]) if len(cz) == 4 and cz[:2] == ["api", "zadanie"] and cz[3] == "plik" else None
        if not z:
            return self._blad(HTTPStatus.NOT_FOUND, "Nie ma takiego zadania.")
        if z.stan().get("stan") not in ("nowe",):
            return self._blad(HTTPStatus.CONFLICT, "Zadanie już uruchomiono - utwórz nowe.")
        pole = re.sub(r"[^a-z0-9_]", "", (q.get("pole") or [""])[0].lower())
        nazwa = _bezpieczna_nazwa((q.get("nazwa") or [""])[0])
        n = int(self.headers.get("Content-Length") or -1)
        if not pole or n < 0:
            return self._blad(HTTPStatus.BAD_REQUEST, "Brak pola, nazwy albo długości pliku.")
        if n > MAKS_PLIK:
            return self._blad(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Plik jest za duży.")
        kat = os.path.join(z.wejscie, pole)
        os.makedirs(kat, exist_ok=True)
        cel = os.path.join(kat, nazwa)
        with open(cel, "wb") as f:
            zostalo = n
            while zostalo > 0:
                kawalek = self.rfile.read(min(zostalo, 1024 * 1024))
                if not kawalek:
                    break
                f.write(kawalek)
                zostalo -= len(kawalek)
        if zostalo:
            os.remove(cel)
            return self._blad(HTTPStatus.BAD_REQUEST, "Przerwane wgrywanie pliku.")
        wzgl = os.path.relpath(cel, z.katalog).replace(os.sep, "/")
        z.zapisz_stan(wgrane={**z.stan().get("wgrane", {}), wzgl: os.path.getmtime(cel)})
        self._json({"ok": True, "plik": wzgl})

    # ---- akcje
    def _start(self, z: Zadanie, dane: dict):
        if z.stan().get("stan") != "nowe":
            return self._blad(HTTPStatus.CONFLICT, "Zadanie już uruchomiono - utwórz nowe.")
        modul = MODULY_WG_ID.get(dane.get("modul"))
        if not modul:
            raise ValueError("Nieznany moduł.")
        pliki = {}
        for pole in modul["pola"]:
            kat = os.path.join(z.wejscie, pole["id"])
            if pole["rodzaj"] in ("plik", "pliki") and os.path.isdir(kat) and os.listdir(kat):
                pliki[pole["id"]] = kat if pole["rodzaj"] == "pliki" else \
                    os.path.join(kat, sorted(os.listdir(kat))[-1])
        opcje = dane.get("opcje") or {}
        if not isinstance(opcje, dict):
            raise ValueError("Nieprawidłowe opcje.")
        argv = argumenty(modul, opcje, pliki, self.server.szablon_orientacji)
        z.zapisz_stan(modul=modul["id"])
        self.server.uruchom(z, argv)
        self._json({"ok": True})

    def _stan_zadania(self, z: Zadanie, q):
        od = int((q.get("od") or ["0"])[0] or 0)
        tekst = ""
        try:
            with open(z.dziennik, "rb") as f:
                f.seek(od)
                surowe = f.read()
            # ucięty znak UTF-8 na końcu - dokończy go następne zapytanie
            tekst = surowe.decode("utf-8", errors="ignore")
            od += len(tekst.encode("utf-8"))
            # ścieżki wewnętrzne serwera są użytkownikowi niepotrzebne - zostaje sama nazwa pliku
            for kat in (z.wyniki, z.wejscie):
                tekst = re.sub(re.escape(kat + os.sep) + r"(?:[a-z0-9_]+" + re.escape(os.sep) + ")?"
                               if kat == z.wejscie else re.escape(kat + os.sep), "", tekst)
                tekst = tekst.replace(kat, "")
        except OSError:
            pass
        s = z.stan()
        wynik = {"id": z.id, "stan": s.get("stan"), "modul": s.get("modul"), "przebieg": tekst, "od": od}
        if s.get("stan") in ("gotowe", "błąd", "przerwane"):
            wynik["pliki"] = z.pliki_wynikowe()
        self._json(wynik)

    def _sciezka_w_zadaniu(self, z: Zadanie, wzgl: str):
        p = os.path.realpath(os.path.join(z.katalog, wzgl))
        kat = os.path.realpath(z.katalog)
        if os.path.commonpath([p, kat]) != kat or not os.path.isfile(p):
            return None
        return p

    def _pobierz(self, z: Zadanie, wzgl: str):
        p = self._sciezka_w_zadaniu(z, wzgl)
        if not p:
            return self._blad(HTTPStatus.NOT_FOUND, "Nie ma takiego pliku.")
        typy = {".pdf": "application/pdf", ".xlsx": "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet", ".docx": "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document", ".txt": "text/plain; charset=utf-8"}
        typ = typy.get(os.path.splitext(p)[1].lower(), "application/octet-stream")
        nazwa = os.path.basename(p)
        with open(p, "rb") as f:
            tresc = f.read()
        self._wyslij(HTTPStatus.OK, tresc, typ, {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nazwa)}"})

    def _zip(self, z: Zadanie):
        bufor = io.BytesIO()
        with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as zf:
            for w in z.pliki_wynikowe():
                zf.write(os.path.join(z.katalog, w["sciezka"]), w["nazwa"])
            if os.path.isfile(z.dziennik):
                zf.write(z.dziennik, "przebieg.txt")
        nazwa = f"wyniki {z.stan().get('modul') or ''} {z.id}.zip".replace("  ", " ")
        self._wyslij(HTTPStatus.OK, bufor.getvalue(), "application/zip", {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nazwa)}"})


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Generator projektów nN - wersja przeglądarkowa (serwer WWW).")
    ap.add_argument("--adres", default="0.0.0.0", help="adres nasłuchu (domyślnie wszystkie interfejsy)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("GENERATOR_PORT", 8765)))
    ap.add_argument("--dane", default=os.environ.get("GENERATOR_DANE") or os.path.join(KATALOG_PROGRAMU, "_web"),
                    help="folder na zadania (pliki wgrane i wyniki)")
    ap.add_argument("--haslo", default=os.environ.get("GENERATOR_HASLO", ""),
                    help="hasło dostępu (puste = bez hasła; zalecane, gdy NAS jest widoczny poza domem/biurem)")
    ap.add_argument("--rownolegle", type=int, default=2, help="ile modułów może pracować jednocześnie")
    ap.add_argument("--dni", type=float, default=7.0, help="po ilu dniach usuwać stare zadania (0 = nigdy)")
    a = ap.parse_args(argv)
    for strumien in (sys.stdout, sys.stderr):
        try:
            strumien.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    serwer = Serwer((a.adres, a.port), a.dane, a.haslo, a.rownolegle, a.dni)
    print(f"Generator nN (przeglądarka) działa: http://{'localhost' if a.adres == '0.0.0.0' else a.adres}:{a.port}")
    print(f"Zadania w: {serwer.dane}" + ("" if a.haslo else "  (bez hasła)"))
    try:
        serwer.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
