"""Podkład rastrowy do planu orientacyjnego.

Źródło podstawowe: kafle OpenStreetMap (Web Mercator) - pobierane, sklejane
i przeliczane do układu PL-2000 projektu. Źródło zapasowe: mapa topograficzna
GUGiK (WMS, od razu w układzie 2000). Wynik: jeden plik JPG (kolor lub odcienie
szarości) + plik georeferencji .jgw.
"""
from __future__ import annotations

import io
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Polygon, box

OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
GUGIK_WMS = "https://mapy.geoportal.gov.pl/wss/service/img/guest/TOPO/MapServer/WMSServer"
USER_AGENT = "GeneratorWT/1.0 (projektowanie sieci telekomunikacyjnych)"

# Mapa zasadnicza (do interaktywnego widoku): EGiB (działki, budynki, numery) jako
# tło + sieci uzbrojenia terenu (GESUT) na wierzchu - wygląda jak mapa zasadnicza.
# Obie usługi WMS GUGiK zwracają obraz od razu w układzie PL-2000 projektu.
KIEG_WMS = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"
KIUT_WMS = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaUzbrojeniaTerenu"
MZ_WARSTWY_EGIB = "dzialki,budynki,numery_dzialek,uzytki,kontury"
MZ_WARSTWY_GESUT = ("przewod_telekomunikacyjny,przewod_elektroenergetyczny,przewod_gazowy,"
                    "przewod_wodociagowy,przewod_kanalizacyjny,przewod_cieplowniczy,"
                    "przewod_niezidentyfikowany,przewod_urzadzenia")
ATRYBUCJA_MZ = "Mapa zasadnicza (EGiB + GESUT) © GUGiK / Geoportal (geoportal.gov.pl)"
R_ZIEMI = 6378137.0
POL_OBW = math.pi * R_ZIEMI
MAKS_PIKSELI = 60_000_000

ATRYBUCJA = {"osm": "Podkład: © autorzy OpenStreetMap (openstreetmap.org/copyright)",
             "gugik": "Podkład: mapa topograficzna © GUGiK (geoportal.gov.pl)"}


@dataclass
class Podklad:
    plik: Path
    x0: float          # lewy dolny róg [m, układ projektu]
    y0: float
    szer_m: float
    wys_m: float
    piks: tuple[int, int]
    zrodlo: str


def zoom_dla_skali(mianownik: int) -> int:
    """Poziom kafli OSM dający ok. 170-220 dpi na wydruku."""
    return 16 if mianownik <= 10000 else 15


# ------------------------------------------------------------------ OSM

def _pobierz_kafel(sesja, z, x, y, katalog: Path | None) -> Image.Image | None:
    plik = katalog / str(z) / str(x) / f"{y}.png" if katalog else None
    if plik and plik.exists():
        return Image.open(plik).convert("RGB")
    for proba in range(3):
        try:
            r = sesja.get(OSM_URL.format(z=z, x=x, y=y), timeout=30)
            if r.status_code == 200:
                if plik:
                    plik.parent.mkdir(parents=True, exist_ok=True)
                    plik.write_bytes(r.content)
                return Image.open(io.BytesIO(r.content)).convert("RGB")
        except requests.RequestException:
            pass
        time.sleep(1 + proba)
    return None


def _osm(bbox, epsg, zoom, katalog_kafli, postep, obszar=None) -> tuple[np.ndarray, float]:
    xmin, ymin, xmax, ymax = bbox
    do_merc = Transformer.from_crs(epsg, 3857, always_xy=True)
    # obwiednia w Web Mercator (zagęszczone krawędzie)
    xs = np.r_[np.linspace(xmin, xmax, 20), np.full(20, xmax), np.linspace(xmax, xmin, 20),
               np.full(20, xmin)]
    ys = np.r_[np.full(20, ymin), np.linspace(ymin, ymax, 20), np.full(20, ymax),
               np.linspace(ymax, ymin, 20)]
    mx, my = do_merc.transform(xs, ys)
    n = 2 ** zoom
    tx0 = int((min(mx) + POL_OBW) / (2 * POL_OBW) * n)
    tx1 = int((max(mx) + POL_OBW) / (2 * POL_OBW) * n)
    ty0 = int((POL_OBW - max(my)) / (2 * POL_OBW) * n)
    ty1 = int((POL_OBW - min(my)) / (2 * POL_OBW) * n)
    kafle = [(x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)]
    if obszar is not None:  # tylko kafle w widoku arkuszy (+ zapas)
        do_proj = Transformer.from_crs(3857, epsg, always_xy=True)
        bok = 2 * POL_OBW / n

        def w_obszarze(xy):
            mx0 = xy[0] * bok - POL_OBW
            my1 = POL_OBW - xy[1] * bok
            px, py = do_proj.transform([mx0, mx0 + bok, mx0 + bok, mx0],
                                       [my1, my1, my1 - bok, my1 - bok])
            return Polygon(zip(px, py)).intersects(obszar)
        kafle = [k for k in kafle if w_obszarze(k)]
    if len(kafle) > 2500:
        raise ValueError(f"Za duży obszar podkładu ({len(kafle)} kafli).")

    mozaika = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (242, 239, 233))
    sesja = requests.Session()
    sesja.headers["User-Agent"] = USER_AGENT
    gotowe, brak = [0], [0]
    lock = threading.Lock()

    def praca(xy):
        img = _pobierz_kafel(sesja, zoom, xy[0], xy[1], katalog_kafli)
        with lock:
            gotowe[0] += 1
            if img is None:
                brak[0] += 1
            else:
                mozaika.paste(img, ((xy[0] - tx0) * 256, (xy[1] - ty0) * 256))
            if postep:
                postep(gotowe[0], len(kafle))

    with ThreadPoolExecutor(max_workers=2) as pula:  # zasady OSM: maks. 2 połączenia
        list(pula.map(praca, kafle))
    if brak[0] > len(kafle) * 0.2:
        raise RuntimeError(f"Nie pobrano {brak[0]} z {len(kafle)} kafli OSM.")

    # przeliczenie do układu projektu (próbkowanie dwuliniowe)
    lat = math.atan(math.sinh(math.pi * (1 - 2 * (ty0 + ty1 + 1) / 2 / n)))
    rozdz = 2 * POL_OBW / (256 * n) * math.cos(lat)  # m/piksel w terenie
    W = int(math.ceil((xmax - xmin) / rozdz))
    H = int(math.ceil((ymax - ymin) / rozdz))
    if W * H > MAKS_PIKSELI:
        k = math.sqrt(W * H / MAKS_PIKSELI)
        rozdz *= k
        W, H = int(W / k), int(H / k)
    zr = np.asarray(mozaika, dtype=np.float32)
    wynik = np.empty((H, W, 3), np.uint8)
    skala_pix = 256 * n / (2 * POL_OBW)
    ex = xmin + (np.arange(W) + 0.5) * rozdz
    for r0 in range(0, H, 256):
        r1 = min(H, r0 + 256)
        ny = ymax - (np.arange(r0, r1) + 0.5) * rozdz
        EX, NY = np.meshgrid(ex, ny)
        mx, my = do_merc.transform(EX, NY)
        px = (mx + POL_OBW) * skala_pix - tx0 * 256 - 0.5
        py = (POL_OBW - my) * skala_pix - ty0 * 256 - 0.5
        x0 = np.clip(np.floor(px).astype(int), 0, zr.shape[1] - 2)
        y0 = np.clip(np.floor(py).astype(int), 0, zr.shape[0] - 2)
        fx = np.clip(px - x0, 0, 1)[..., None]
        fy = np.clip(py - y0, 0, 1)[..., None]
        a = zr[y0, x0] * (1 - fx) + zr[y0, x0 + 1] * fx
        b = zr[y0 + 1, x0] * (1 - fx) + zr[y0 + 1, x0 + 1] * fx
        wynik[r0:r1] = np.clip(a * (1 - fy) + b * fy, 0, 255).astype(np.uint8)
    return wynik, rozdz


# ------------------------------------------------------------------ GUGiK WMS

def _gugik(bbox, epsg, rozdz, postep, obszar=None) -> tuple[np.ndarray, float]:
    xmin, ymin, xmax, ymax = bbox
    W = int(math.ceil((xmax - xmin) / rozdz))
    H = int(math.ceil((ymax - ymin) / rozdz))
    if W * H > MAKS_PIKSELI:
        k = math.sqrt(W * H / MAKS_PIKSELI)
        rozdz *= k
        W, H = int(W / k), int(H / k)
    wynik = Image.new("RGB", (W, H), "white")
    kaf = 2000
    zad = [(c, r) for r in range(0, H, kaf) for c in range(0, W, kaf)]
    if obszar is not None:
        zad = [(c, r) for c, r in zad if box(
            xmin + c * rozdz, ymax - (r + min(kaf, H - r)) * rozdz,
            xmin + (c + min(kaf, W - c)) * rozdz, ymax - r * rozdz).intersects(obszar)]
    sesja = requests.Session()
    sesja.headers["User-Agent"] = USER_AGENT
    for i, (c, r) in enumerate(zad, 1):
        w, h = min(kaf, W - c), min(kaf, H - r)
        bx0, by1 = xmin + c * rozdz, ymax - r * rozdz
        bx1, by0 = bx0 + w * rozdz, by1 - h * rozdz
        odp = sesja.get(GUGIK_WMS, timeout=120, params={
            "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": "Raster",
            "STYLES": "", "SRS": f"EPSG:{epsg}", "BBOX": f"{bx0},{by0},{bx1},{by1}",
            "WIDTH": w, "HEIGHT": h, "FORMAT": "image/jpeg"})
        odp.raise_for_status()
        if not odp.headers.get("content-type", "").startswith("image"):
            raise RuntimeError("Usługa GUGiK nie zwróciła obrazu.")
        wynik.paste(Image.open(io.BytesIO(odp.content)).convert("RGB"), (c, r))
        if postep:
            postep(i, len(zad))
    return np.asarray(wynik), rozdz


# ------------------------------------------------------------------ główna funkcja

def pobierz(bbox, epsg: int, mianownik: int, plik_jpg: Path, szarosc: bool = False,
            zrodlo: str = "osm", katalog_kafli: Path | None = None, postep=None,
            log=print, obszar=None) -> Podklad:
    """Pobiera podkład dla obwiedni bbox (xmin, ymin, xmax, ymax) w układzie EPSG projektu.

    zrodlo: 'osm' (z automatycznym przejściem na GUGiK przy błędzie) lub 'gugik'.
    obszar: wielokąt (układ projektu) - pobierane są tylko kafle, które go przecinają;
            reszta obrazu pozostaje pusta (poza widokiem arkuszy).
    """
    uzyte = zrodlo
    if zrodlo == "osm":
        try:
            obraz, rozdz = _osm(bbox, epsg, zoom_dla_skali(mianownik), katalog_kafli, postep,
                                obszar)
        except Exception as e:  # noqa: BLE001
            log(f"OSM niedostępny ({e}) - używam mapy topograficznej GUGiK.")
            uzyte = "gugik"
    if uzyte == "gugik":
        obraz, rozdz = _gugik(bbox, epsg, mianownik / 10000 * 1.5, postep, obszar)

    img = Image.fromarray(obraz)
    if szarosc:
        img = img.convert("L")
    plik_jpg.parent.mkdir(parents=True, exist_ok=True)
    img.save(plik_jpg, "JPEG", quality=88, optimize=True)
    xmin, _, _, ymax = bbox
    W, H = img.size
    # plik georeferencji (world file) - środek lewego górnego piksela
    plik_jpg.with_suffix(".jgw").write_text(
        f"{rozdz:.6f}\n0\n0\n{-rozdz:.6f}\n{xmin + rozdz / 2:.3f}\n{ymax - rozdz / 2:.3f}\n")
    return Podklad(plik_jpg, xmin, ymax - H * rozdz, W * rozdz, H * rozdz, (W, H), uzyte)


# ------------------------------------------------------------------ mapa zasadnicza (widok)

def _wms_getmap(sesja, url, warstwy, epsg, bbox, szer, wys, przezroczyste) -> Image.Image:
    xmin, ymin, xmax, ymax = bbox
    style = ",".join([""] * len(warstwy.split(",")))
    r = sesja.get(url, timeout=60, params={
        "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": warstwy,
        "STYLES": style, "SRS": f"EPSG:{epsg}", "BBOX": f"{xmin},{ymin},{xmax},{ymax}",
        "WIDTH": szer, "HEIGHT": wys, "FORMAT": "image/png",
        "TRANSPARENT": "TRUE" if przezroczyste else "FALSE"})
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image"):
        raise RuntimeError("Usługa WMS GUGiK nie zwróciła obrazu (sprawdź zakres/skalę).")
    return Image.open(io.BytesIO(r.content)).convert("RGBA")


def pobierz_mape_zasadnicza(bbox, epsg: int, szer: int, wys: int, sieci: bool = True
                            ) -> Image.Image:
    """Jeden obraz mapy zasadniczej dla obwiedni bbox (xmin, ymin, xmax, ymax) w układzie
    projektu, o rozmiarze szer×wys pikseli. EGiB (działki, budynki, numery, użytki) jako
    tło + (opcjonalnie) sieci GESUT na wierzchu. Zwraca obraz PIL (RGB).

    Lekka wersja do interaktywnego widoku na ekranie - jedno żądanie WMS na warstwę,
    bez kafli i przeliczania układu (WMS zwraca obraz wprost w EPSG projektu).
    """
    szer = max(1, min(int(szer), 2500))
    wys = max(1, min(int(wys), 2500))
    sesja = requests.Session()
    sesja.headers["User-Agent"] = USER_AGENT
    tlo = Image.new("RGBA", (szer, wys), (255, 255, 255, 255))
    egib = _wms_getmap(sesja, KIEG_WMS, MZ_WARSTWY_EGIB, epsg, bbox, szer, wys, False)
    tlo.alpha_composite(egib)
    if sieci:
        try:
            gesut = _wms_getmap(sesja, KIUT_WMS, MZ_WARSTWY_GESUT, epsg, bbox, szer, wys, True)
            tlo.alpha_composite(gesut)
        except (requests.RequestException, RuntimeError):
            pass  # brak sieci w tym rejonie nie jest błędem - zostaje samo EGiB
    return tlo.convert("RGB")
