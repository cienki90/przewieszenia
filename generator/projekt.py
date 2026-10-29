"""Projekt - zapamiętane pliki i opcje modułów dla jednego zadania (folderu planu).

Plik ``projekt GeneratorNN.json`` w folderze projektu przechowuje wartości pól okna (pliki
wejściowe każdego modułu, opcje, numery WT) oraz listę pól wypełnionych automatycznie
wynikami programu. Dzięki temu po ponownym uruchomieniu wszystkie zakładki są od razu
wypełnione, a nowe wyniki dalej podmieniają pliki wpisane przez program (nie ręczne wybory).
"""
from __future__ import annotations

import json
import os

NAZWA_PLIKU = "projekt GeneratorNN.json"
WERSJA = 1
OSTATNIE_MAX = 10


def sciezka(folder_lub_plik: str) -> str:
    """Ścieżka pliku projektu dla folderu (albo samego pliku projektu)."""
    p = os.path.abspath(folder_lub_plik)
    return p if p.lower().endswith(".json") else os.path.join(p, NAZWA_PLIKU)


def folder(sciezka_projektu: str) -> str:
    p = os.path.abspath(sciezka_projektu)
    return os.path.dirname(p) if p.lower().endswith(".json") else p


def wczytaj(folder_lub_plik: str) -> dict | None:
    """Dane projektu albo None (brak pliku / plik uszkodzony)."""
    try:
        with open(sciezka(folder_lub_plik), encoding="utf-8") as f:
            dane = json.load(f)
    except (OSError, ValueError):
        return None
    return dane if isinstance(dane, dict) else None


def zapisz(folder_projektu: str, pola: dict, auto: list) -> str:
    """Zapisuje pola okna do pliku projektu; zwraca jego ścieżkę."""
    p = sciezka(folder_projektu)
    dane = {"wersja": WERSJA, "pola": pola, "auto": sorted(auto)}
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dane, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def dopisz_ostatni(lista: list, folder_projektu: str) -> list:
    folder_projektu = os.path.normpath(folder_projektu)
    return ([folder_projektu] + [f for f in lista if os.path.normcase(f) != os.path.normcase(folder_projektu)]
            )[:OSTATNIE_MAX]
