"""Numeracja wierzchołków !tele.

Zasady:
- numeracja ciągła 1..N, idzie wzdłuż trasy od słupa początkowego,
- wierzchołki w zasięgu jednej stacji trafo (!trafo) mają numery kolejne,
  bez przeplatania z innymi strefami,
- wierzchołki poza strefami trafo są grupowane wg miejscowości,
- kolejność grup = kolejność, w jakiej trasa do nich wchodzi.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from shapely.geometry import Point

from .config import Config
from .model import StacjaTrafo, Wierzcholek


@dataclass
class Grupa:
    nazwa: str
    stacja: StacjaTrafo | None
    wierzcholki: list[Wierzcholek] = field(default_factory=list)


def przypisz_strefy(wierzcholki: list[Wierzcholek], stacje: list[StacjaTrafo]) -> None:
    """Przypisuje stację trafo (najmniejszą strefę, w której leży wierzchołek)."""
    wg_pola = sorted(stacje, key=lambda s: s.obrys.area)
    for w in wierzcholki:
        p = Point(w.x, w.y)
        s = next((s for s in wg_pola if s.obrys.covers(p)), None)
        w.stacja_trafo = s.nazwa if s else None


def _dfs(start: int, wszystkie: list[Wierzcholek], dozwolone: set[int],
         odwiedzone: set[int]) -> list[int]:
    """Przejście wzdłuż trasy; odgałęzienia w kolejności rysowania."""
    wynik, stos = [], [start]
    while stos:
        i = stos.pop()
        if i in odwiedzone:
            continue
        odwiedzone.add(i)
        wynik.append(i)
        nast = sorted((n for n in wszystkie[i].sasiedzi
                       if n in dozwolone and n not in odwiedzone),
                      key=lambda n: wszystkie[n].kolejnosc_rysunku, reverse=True)
        stos.extend(nast)
    return wynik


def kolejnosc_trasy(wszystkie: list[Wierzcholek]) -> list[int]:
    """Kolejność wszystkich wierzchołków wzdłuż trasy.

    Start: koniec linii (słup z jednym sąsiadem), który pojawia się w rysunku
    najwcześniej - zwykle początek pierwszej narysowanej polilinii.
    Każdy rozłączny fragment trasy jest przechodzony po kolei.
    """
    wszystkie_id = {w.id for w in wszystkie}
    odwiedzone: set[int] = set()
    wynik: list[int] = []
    while len(odwiedzone) < len(wszystkie):
        pozostale = [w for w in wszystkie if w.id not in odwiedzone]
        start = min(pozostale, key=lambda w: (len(w.sasiedzi) > 1, w.kolejnosc_rysunku))
        wynik += _dfs(start.id, wszystkie, wszystkie_id, odwiedzone)
    return wynik


def utworz_grupy(wszystkie: list[Wierzcholek], stacje: list[StacjaTrafo],
                 cfg: Config) -> list[Grupa]:
    przypisz_strefy(wszystkie, stacje)
    stacje_wg_nazwy = {s.nazwa: s for s in stacje}
    # Strefa trafo = jedna grupa (nawet jeśli trasa z niej wychodzi i wraca).
    # Poza strefami: kolejne odcinki trasy w tej samej miejscowości - nowa grupa
    # przy każdej zmianie, żeby numery nie przeskakiwały wzdłuż trasy.
    grupy: "OrderedDict[tuple, Grupa]" = OrderedDict()
    poprz_klucz = None
    nr_odcinka = 0
    for i in kolejnosc_trasy(wszystkie):
        w = wszystkie[i]
        if w.wykluczony:
            w.grupa = ""
            continue
        if w.stacja_trafo:
            klucz = ("trafo", w.stacja_trafo)
            nazwa = w.stacja_trafo
        else:
            nazwa = w.miejscowosc or cfg.grupa_nieznana
            if poprz_klucz is None or poprz_klucz[:2] != ("miejsc", nazwa):
                nr_odcinka += 1
            klucz = ("miejsc", nazwa, nr_odcinka)
        poprz_klucz = klucz
        w.grupa = nazwa
        if klucz not in grupy:
            grupy[klucz] = Grupa(nazwa, stacje_wg_nazwy.get(w.stacja_trafo or ""))
        grupy[klucz].wierzcholki.append(w)
    return list(grupy.values())


def zaplanuj_numeracje(wszystkie: list[Wierzcholek], grupy: list[Grupa],
                       cfg: Config) -> list[Wierzcholek]:
    """Nadaje numery ciągłe. Zwraca wierzchołki w kolejności numerów.

    Słupy wykluczone (w.wykluczony) nie dostają numeru i nie trafiają do planu -
    zostają jednak w self.slupy, więc trasa i arkusze obejmują je nadal."""
    for w in wszystkie:  # wyczyść poprzednią numerację (np. po zmianie wykluczeń)
        w.nr = None
        w.etykieta = ""
    wynik: list[Wierzcholek] = []
    nr = cfg.numer_startowy
    for g in grupy:
        # g.wierzcholki są już w kolejności trasy - startujemy od wejścia trasy w grupę
        dozwolone = {w.id for w in g.wierzcholki}
        odwiedzone: set[int] = set()
        for w in g.wierzcholki:
            if w.id in odwiedzone:
                continue
            for i in _dfs(w.id, wszystkie, dozwolone, odwiedzone):
                v = wszystkie[i]
                v.nr = nr
                v.etykieta = f"{cfg.prefiks}{nr}"
                wynik.append(v)
                nr += 1
    return wynik
