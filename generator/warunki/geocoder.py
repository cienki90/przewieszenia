"""Automatyczne uzupełnianie danych adresowych z usług GUGiK.

- ULDK (uldk.gugik.gov.pl)   -> gmina, powiat, województwo, obręb, nr działki
- UUG  (services.gugik.gov.pl/uug) -> najbliższy punkt adresowy: miejscowość, ulica, kod

Wyniki są zapisywane w pliku cache, żeby nie odpytywać usług ponownie
przy kolejnych uruchomieniach dla tego samego projektu.
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from .model import Wierzcholek

ULDK_URL = "https://uldk.gugik.gov.pl/"
UUG_URL = "https://services.gugik.gov.pl/uug/"
from .config import DANE  # [GeneratorNN] pamięć adresów w danych użytkownika, nie w folderze programu
CACHE = DANE / "cache_geokodowania.json"


def wykryj_epsg(x_easting: float) -> int:
    """Układ PL-2000 po pierwszej cyfrze współrzędnej wschodniej (5..8 -> strefa)."""
    strefa = int(x_easting // 1_000_000)
    if strefa in (5, 6, 7, 8):
        return 2171 + strefa  # 2176, 2177, 2178, 2179
    if 100_000 <= x_easting <= 900_000:
        return 2180  # PL-1992
    raise ValueError(f"Nie rozpoznano układu współrzędnych dla X={x_easting}")


class Geokoder:
    def __init__(self, epsg: int, promien_adresu: int = 300, timeout: int = 20,
                 plik_cache: Path = CACHE):
        self.epsg = epsg
        self.promien = promien_adresu
        self.timeout = timeout
        self.plik_cache = plik_cache
        self._lock = threading.Lock()
        self.cache: dict[str, dict] = {}
        if plik_cache.exists():
            try:
                self.cache = json.loads(plik_cache.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.cache = {}
        self.sesja = requests.Session()

    def _klucz(self, x, y):
        return f"{self.epsg}:{x:.2f}:{y:.2f}"

    def _uldk(self, x, y) -> dict:
        r = self.sesja.get(ULDK_URL, params={
            "request": "GetParcelByXY", "xy": f"{x},{y},{self.epsg}",
            "result": "teryt,voivodeship,county,commune,region,parcel"},
            timeout=self.timeout)
        r.raise_for_status()
        linie = r.text.strip().splitlines()
        if len(linie) < 2 or linie[0].strip() != "0":
            return {}
        teryt, woj, pow_, gmina, obreb, dzialka = (linie[1].split("|") + [""] * 6)[:6]
        return {"teryt_dzialki": teryt, "wojewodztwo": woj, "powiat": pow_,
                "gmina": gmina, "obreb": obreb, "dzialka": dzialka}

    def _uug(self, x, y) -> dict:
        r = self.sesja.get(UUG_URL, params={
            "request": "GetAddressReverse", "location": f"POINT({x} {y})",
            "srid": self.epsg, "radius": self.promien}, timeout=self.timeout)
        r.raise_for_status()
        wyniki = (r.json() or {}).get("results") or {}
        if not wyniki:
            return {}
        a = next(iter(wyniki.values()))
        return {"miejscowosc": a.get("city") or "", "ulica": a.get("street") or "",
                "kod": a.get("code") or "", "nr_adresu": a.get("number") or "",
                "odl_adresu": a.get("distance")}

    def dane(self, x: float, y: float) -> dict:
        k = self._klucz(x, y)
        with self._lock:
            if k in self.cache:
                return self.cache[k]
        wynik: dict = {}
        bledy = []
        for f in (self._uldk, self._uug):
            try:
                wynik.update(f(x, y))
            except (requests.RequestException, ValueError) as e:
                bledy.append(f"{f.__name__}: {e}")
        if bledy:
            wynik["blad"] = "; ".join(bledy)
        else:
            with self._lock:
                self.cache[k] = wynik
        return wynik

    def zapisz_cache(self):
        with self._lock:  # inne wątki mogą w tym czasie dopisywać wyniki
            tekst = json.dumps(self.cache, ensure_ascii=False, indent=1)
        self.plik_cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.plik_cache.with_name(self.plik_cache.name + ".tmp")
        tmp.write_text(tekst, encoding="utf-8")
        os.replace(tmp, self.plik_cache)  # przerwany zapis nie psuje poprzedniego pliku


def uzupelnij(wierzcholki: list[Wierzcholek], geokoder: Geokoder, watki: int = 8,
              postep=None, zapis_co: int = 50) -> int:
    """Uzupełnia dane adresowe wierzchołków. Zwraca liczbę błędów.
    Cache jest zapisywany co 'zapis_co' słupów - przerwane pobieranie nie przepada."""
    bledy = 0
    gotowe = 0

    def praca(w: Wierzcholek):
        return w, geokoder.dane(w.x, w.y)

    with ThreadPoolExecutor(max_workers=watki) as pula:
        for w, d in pula.map(praca, wierzcholki):
            if zapis_co and gotowe and gotowe % zapis_co == 0:
                geokoder.zapisz_cache()
            w.miejscowosc = d.get("miejscowosc") or None
            w.ulica = d.get("ulica") or None
            w.kod = d.get("kod") or None
            w.gmina = d.get("gmina") or None
            w.powiat = d.get("powiat") or None
            w.wojewodztwo = d.get("wojewodztwo") or None
            w.obreb = d.get("obreb") or None
            w.dzialka = d.get("dzialka") or None
            if "blad" in d:
                bledy += 1
                w.uwagi = (w.uwagi + " Błąd geokodowania.").strip()
            gotowe += 1
            if postep:
                postep(gotowe, len(wierzcholki))
    geokoder.zapisz_cache()
    return bledy
