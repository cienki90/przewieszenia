"""Sprawdzanie ulic: porównanie ulicy z adresu (GUGiK) z drogą, przy której stoi słup.

Osie dróg z nazwami pobierane są z OpenStreetMap (Overpass API) dla obszaru projektu.
Dla każdego słupa wyznaczane są nazwane drogi w promieniu cfg.odl_ulicy:
- ulica z adresu jest wśród nich             -> zgodna,
- są drogi, ale ulica z adresu inna / brak   -> niezgodna, propozycja = najbliższa droga,
- brak nazwanych dróg w pobliżu              -> nie do sprawdzenia (zostaje ulica z adresu).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import LineString, Point

from .model import Wierzcholek

OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
TYPY_DROG = ("primary|secondary|tertiary|unclassified|residential|living_street|service|"
             "road|trunk|track|pedestrian")
USER_AGENT = "GeneratorWT/1.0 (projektowanie sieci telekomunikacyjnych)"


@dataclass
class WynikUlicy:
    slup: Wierzcholek
    ulica_adres: str | None
    ulica_droga: str | None      # najbliższa nazwana droga
    odleglosc: float | None
    zgodna: bool | None          # None = nie do sprawdzenia


def norm(nazwa: str | None) -> str:
    if not nazwa:
        return ""
    t = nazwa.casefold().strip()
    t = re.sub(r"^(ul\.|ulica|al\.|aleja|aleje|pl\.|plac|os\.|osiedle)\s+", "", t)
    t = re.sub(r"[.\-–]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _pobierz_drogi(bbox_wgs, plik_cache: Path | None, log=print) -> list[dict]:
    s, w, n, e = bbox_wgs
    zapytanie = (f'[out:json][timeout:90];way["highway"~"^({TYPY_DROG})(_link)?$"]["name"]'
                 f'({s:.5f},{w:.5f},{n:.5f},{e:.5f});out geom;')
    if plik_cache:
        klucz = hashlib.md5(zapytanie.encode()).hexdigest()[:16]
        plik = plik_cache / f"drogi_{klucz}.json"
        if plik.exists():
            return json.loads(plik.read_text(encoding="utf-8"))
    ostatni = None
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": zapytanie}, timeout=120,
                              headers={"User-Agent": USER_AGENT})
            if r.status_code == 200:
                el = r.json().get("elements", [])
                if plik_cache:
                    plik.parent.mkdir(parents=True, exist_ok=True)
                    plik.write_text(json.dumps(el), encoding="utf-8")
                return el
            ostatni = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as ex:
            ostatni = str(ex)
        log(f"Serwer dróg {url} niedostępny ({ostatni}) - próbuję następny.")
        time.sleep(1)
    raise RuntimeError(f"Nie udało się pobrać dróg z OpenStreetMap ({ostatni}).")


def sprawdz(slupy: list[Wierzcholek], epsg: int, odl: float = 30.0,
            plik_cache: Path | None = None, log=print) -> list[WynikUlicy]:
    if not slupy:
        return []
    do_wgs = Transformer.from_crs(epsg, 4326, always_xy=True)
    z_wgs = Transformer.from_crs(4326, epsg, always_xy=True)
    xs, ys = [w.x for w in slupy], [w.y for w in slupy]
    zapas = odl + 50
    lon0, lat0 = do_wgs.transform(min(xs) - zapas, min(ys) - zapas)
    lon1, lat1 = do_wgs.transform(max(xs) + zapas, max(ys) + zapas)
    drogi = _pobierz_drogi((lat0, lon0, lat1, lon1), plik_cache, log)

    geom, nazwy = [], []
    for d in drogi:
        g = d.get("geometry") or []
        if len(g) < 2:
            continue
        px, py = z_wgs.transform([p["lon"] for p in g], [p["lat"] for p in g])
        geom.append(LineString(zip(px, py)))
        nazwy.append(d["tags"]["name"])
    drzewo = STRtree(geom) if geom else None

    wyniki = []
    for w in slupy:
        p = Point(w.x, w.y)
        blisko: dict[str, float] = {}
        if drzewo is not None:
            for i in drzewo.query(p.buffer(odl)):
                dd = geom[i].distance(p)
                if dd <= odl:
                    n = nazwy[i]
                    blisko[n] = min(dd, blisko.get(n, dd))
        if not blisko:
            wyniki.append(WynikUlicy(w, w.ulica, None, None, None))
            continue
        najbl = min(blisko, key=blisko.get)
        zgodna = norm(w.ulica) in {norm(n) for n in blisko} if w.ulica else False
        wyniki.append(WynikUlicy(w, w.ulica, najbl, round(blisko[najbl], 1), zgodna))
    return wyniki
