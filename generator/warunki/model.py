"""Struktury danych używane w całym programie."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import Point, Polygon


@dataclass
class StacjaTrafo:
    """Zasięg stacji transformatorowej (obrys na warstwie !trafo)."""
    nazwa: str                      # np. "05-0792"
    obrys: Polygon
    punkt_stacji: Optional[Point] = None
    kolejnosc_rysunku: int = 0


@dataclass
class BlednyKlik:
    """Grupa wierzchołków odległych o mniej niż tolerancja - scalona w jeden słup."""
    x: float
    y: float
    liczba: int
    max_odleglosc: float


@dataclass
class Wierzcholek:
    """Słup = wierzchołek linii !tele (po scaleniu błędnych klików)."""
    id: int
    x: float  # współrzędna wschodnia w DXF (w geodezji: Y)
    y: float  # współrzędna północna w DXF (w geodezji: X)
    kolejnosc_rysunku: tuple[int, int] = (0, 0)
    scalonych: int = 1  # ile wierzchołków rysunku wskazuje ten słup

    nr: Optional[int] = None
    etykieta: str = ""
    grupa: str = ""
    wykluczony: bool = False   # słup pominięty w numeracji i dokumentach (zostaje w trasie)

    stacja_trafo: Optional[str] = None
    rodzaj_slupa: Optional[str] = None   # nN / SN
    typ_slupa: Optional[str] = None      # np. K-10,5/10/E
    id_slupa: Optional[str] = None       # stacja/numer, np. 05-0743/9.1
    nr_w_sieci: Optional[str] = None     # numer słupa z rysunku (warstwa _numery...)

    miejscowosc: Optional[str] = None
    ulica: Optional[str] = None
    kod: Optional[str] = None
    gmina: Optional[str] = None
    powiat: Optional[str] = None
    wojewodztwo: Optional[str] = None
    obreb: Optional[str] = None
    dzialka: Optional[str] = None
    ulica_droga: Optional[str] = None    # najbliższa nazwana droga (OSM)
    ulica_zgodna: Optional[bool] = None  # None = nie sprawdzono / brak drogi w pobliżu
    rejon: Optional[str] = None
    lat: Optional[float] = None   # WGS 84
    lon: Optional[float] = None
    rejon_skrot: Optional[str] = None
    uwagi: str = ""

    sasiedzi: set[int] = field(default_factory=set)

    @property
    def punkt(self) -> Point:
        return Point(self.x, self.y)

    def wspolrzedne(self, wgs84: bool, miejsca_2000: int = 2, miejsca_wgs: int = 7
                    ) -> tuple[float, float]:
        """(X, Y) PL-2000 albo (szerokość, długość) WGS 84 - w kolejności jak w zestawieniach."""
        if wgs84 and self.lat is not None:
            return round(self.lat, miejsca_wgs), round(self.lon, miejsca_wgs)
        return round(self.geo_x, miejsca_2000), round(self.geo_y, miejsca_2000)

    @property
    def geo_x(self) -> float:
        return self.y

    @property
    def geo_y(self) -> float:
        return self.x
