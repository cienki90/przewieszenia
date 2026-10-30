"""Plik stanu projektu (<projekt>.wt.json obok pliku DXF).

Zapamiętuje to, co użytkownik zmienił ręcznie, żeby nie przepadło przy ponownej
analizie ani po zamknięciu programu:
- poprawki słupów (miejscowość, ulica, gmina, rodzaj, typ, nr w sieci, uwagi),
- słupy wyłączone z numeracji,
- ustawienia zlecenia i numeracji (prefiks, numer startowy, zakładka, operator…).

Słupy są rozpoznawane po położeniu (X, Y z dokładnością do 1 cm), bo ich numery
wewnętrzne zależą od kolejności rysowania i tolerancji scalania.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

WERSJA = 1
ODL_DOPASOWANIA = 0.5  # [m] słup z pliku stanu = najbliższy słup rysunku w tej odległości

# pola słupa, które użytkownik może poprawić ręcznie
POLA_RECZNE = ("miejscowosc", "ulica", "gmina", "rodzaj_slupa", "typ_slupa", "nr_w_sieci",
               "uwagi")


def plik_stanu(dxf: str | Path) -> Path:
    p = Path(dxf)
    return p.with_name(p.stem + ".wt.json")


def klucz(x: float, y: float) -> str:
    return f"{x:.2f};{y:.2f}"


def _xy(k: str) -> tuple[float, float] | None:
    try:
        x, y = k.split(";")
        return float(x), float(y)
    except ValueError:
        return None


def pusty() -> dict:
    return {"wersja": WERSJA, "ustawienia": {}, "slupy": {}}


def wczytaj(plik: Path) -> dict:
    """Stan z pliku albo pusty stan (brak pliku / plik uszkodzony)."""
    if not plik.exists():
        return pusty()
    try:
        d = json.loads(plik.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return pusty()
    if not isinstance(d, dict):
        return pusty()
    wynik = pusty()
    wynik["ustawienia"] = d.get("ustawienia") or {}
    wynik["slupy"] = d.get("slupy") or {}
    return wynik


def zapisz(plik: Path, dane: dict) -> None:
    """Zapis przez plik tymczasowy - przerwany zapis nie psuje poprzedniego stanu."""
    tmp = plik.with_name(plik.name + ".tmp")
    tmp.write_text(json.dumps({**dane, "wersja": WERSJA}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, plik)


def dopasuj(slupy_stanu: dict, slupy) -> tuple[dict, list[str]]:
    """Przypisuje wpisy stanu do słupów rysunku: {id słupa: (klucz, wpis)} oraz lista
    kluczy, których nie udało się dopasować (słup usunięty/przesunięty w rysunku)."""
    wg_klucza = {klucz(w.x, w.y): w for w in slupy}
    wynik, brak = {}, []
    for k, wpis in slupy_stanu.items():
        w = wg_klucza.get(k)
        if w is None:
            xy = _xy(k)
            if xy is not None:
                w = min(slupy, key=lambda s: math.hypot(s.x - xy[0], s.y - xy[1]), default=None)
                if w is not None and math.hypot(w.x - xy[0], w.y - xy[1]) > ODL_DOPASOWANIA:
                    w = None
        if w is None or w.id in wynik:
            brak.append(k)
        else:
            wynik[w.id] = (k, wpis)
    return wynik, brak
