"""Odczyt miejscowości i ulic ze współrzędnych (geokodowanie odwrotne przez internet).

Współrzędne planu: PUWG 2000 (strefa wyznaczana z pierwszej cyfry X: 5,6,7,8 -> EPSG:2176..2179).
Źródła (w kolejności):
  1. GUGiK UUG (usługa urzędowa, adresy z PRG) - services.gugik.gov.pl/uug
  2. OpenStreetMap Nominatim - nominatim.openstreetmap.org
Wyniki są zapisywane w pamięci podręcznej (plik JSON), aby nie odpytywać serwerów wielokrotnie.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request

UA = "przewieszenia-generator/1.0 (https://github.com/cienki90/przewieszenia)"

# --- PUWG 2000 -> WGS84 (odwzorowanie Gaussa-Krügera, elipsoida GRS80) ---
_A = 6378137.0
_F = 1 / 298.257222101
_M0 = 0.999923


def puwg2000_do_wgs84(x: float, y: float):
    """x = wschód (np. 7530960), y = północ (np. 5768454) -> (szer., dług.) w stopniach."""
    strefa = int(x // 1_000_000)
    lon0 = math.radians(3 * strefa)
    e2 = _F * (2 - _F)
    ep2 = e2 / (1 - e2)
    E = (x - strefa * 1_000_000 - 500_000) / _M0
    N = y / _M0
    # szerokość "footpoint"
    n = _F / (2 - _F)
    Am = _A / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    mu = N / Am
    phi1 = (mu + (3 * n / 2 - 27 * n ** 3 / 32) * math.sin(2 * mu)
            + (21 * n ** 2 / 16 - 55 * n ** 4 / 32) * math.sin(4 * mu)
            + (151 * n ** 3 / 96) * math.sin(6 * mu) + (1097 * n ** 4 / 512) * math.sin(8 * mu))
    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    Nn = _A / math.sqrt(1 - e2 * s * s)
    Rr = _A * (1 - e2) / (1 - e2 * s * s) ** 1.5
    eta2 = ep2 * c * c
    D = E / Nn
    lat = phi1 - (Nn * t / Rr) * (D ** 2 / 2 - (5 + 3 * t * t + eta2 - 9 * eta2 * t * t) * D ** 4 / 24
                                   + (61 + 90 * t * t + 45 * t ** 4) * D ** 6 / 720)
    lon = lon0 + (D - (1 + 2 * t * t + eta2) * D ** 3 / 6
                  + (5 + 28 * t * t + 24 * t ** 4) * D ** 5 / 120) / c
    return math.degrees(lat), math.degrees(lon)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pl"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


_SKROTY = (("ulica ", "ul. "), ("aleja ", "al. "), ("aleje ", "al. "), ("plac ", "pl. "),
           ("osiedle ", "os. "), ("rondo ", "rondo "), ("skwer ", "skwer "))


def skroc_ulice(nazwa: str) -> str:
    """'ulica Wspólna' -> 'ul. Wspólna'; 'Wspólna' -> 'ul. Wspólna'."""
    n = (nazwa or "").strip()
    if not n:
        return ""
    low = n.lower()
    for pelna, skrot in _SKROTY:
        if low.startswith(pelna):
            return skrot + n[len(pelna):].strip()
    if low.startswith(("ul.", "al.", "pl.", "os.")):
        return n
    return "ul. " + n


def _uug(lat, lon):
    """GUGiK UUG - najbliższy punkt adresowy z PRG."""
    url = ("https://services.gugik.gov.pl/uug/?request=GetAddressReverse"
           f"&location=POINT({lon:.7f}%20{lat:.7f})&srid=4326")
    d = json.loads(_get(url))
    res = d.get("results") or {}
    if not res:
        return None
    r = res[sorted(res, key=lambda k: int(k) if str(k).isdigit() else 0)[0]]
    return (r.get("city") or "").strip(), skroc_ulice(r.get("street") or "")


def _nominatim(lat, lon):
    q = urllib.parse.urlencode(dict(format="jsonv2", lat=f"{lat:.7f}", lon=f"{lon:.7f}", zoom=17,
                                    addressdetails=1, **{"accept-language": "pl"}))
    d = json.loads(_get("https://nominatim.openstreetmap.org/reverse?" + q))
    a = d.get("address", {})
    miejsc = a.get("village") or a.get("town") or a.get("city") or a.get("hamlet") or a.get("suburb") or ""
    return miejsc, skroc_ulice(a.get("road") or "")


ZRODLA = {"uug": _uug, "osm": _nominatim}


class Geokoder:
    def __init__(self, cache_path: str | None = None, zrodla=("uug", "osm"), opoznienie: float = 1.1):
        self.cache_path = cache_path
        self.cache = {}
        self.zrodla = [z for z in zrodla if z in ZRODLA]
        self.opoznienie = opoznienie  # Nominatim (OSM): max 1 zapytanie / s
        self._ostatnio = 0.0
        self.bledy: list[str] = []
        if cache_path and os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                self.cache = json.load(f)

    def zapisz(self):
        if self.cache_path:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=1)

    def adres(self, x: float, y: float):
        """Zwraca (miejscowość, ulica) dla punktu w PUWG 2000 lub None przy błędzie."""
        k = f"{x:.1f},{y:.1f}"
        if k in self.cache:
            return tuple(self.cache[k])
        lat, lon = puwg2000_do_wgs84(x, y)
        for z in self.zrodla:
            if z == "osm":
                czekaj = self.opoznienie - (time.time() - self._ostatnio)
                if czekaj > 0:
                    time.sleep(czekaj)
            try:
                wynik = ZRODLA[z](lat, lon)
            except Exception as ex:  # brak internetu / błąd serwera
                self.bledy.append(f"{z} ({x:.2f}, {y:.2f}): {ex}")
                wynik = None
            finally:
                if z == "osm":
                    self._ostatnio = time.time()
            if wynik and wynik[0]:
                self.cache[k] = list(wynik)
                return wynik
        return None
