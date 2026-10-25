"""Trwałe ustawienia okna programu (między uruchomieniami).

Zapisywane w pliku JSON w katalogu użytkownika:
  Windows: %LOCALAPPDATA%\\GeneratorNN\\ustawienia.json
  inne:    ~/.config/GeneratorNN/ustawienia.json

Przechowujemy m.in. ostatnio wpisane numery warunków technicznych (WT) dla każdego modułu
oraz historię użytych numerów WT (lista rozwijana), a także wybrany motyw okna.
Błąd odczytu/zapisu nigdy nie przerywa pracy programu - wtedy działamy na wartościach domyślnych.
"""
from __future__ import annotations

import json
import os

HISTORIA_WT_MAX = 15


def _sciezka() -> str:
    baza = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME") \
        or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(baza, "GeneratorNN", "ustawienia.json")


def wczytaj() -> dict:
    try:
        with open(_sciezka(), encoding="utf-8") as f:
            dane = json.load(f)
        return dane if isinstance(dane, dict) else {}
    except (OSError, ValueError):
        return {}


def zapisz(dane: dict) -> None:
    sciezka = _sciezka()
    try:
        os.makedirs(os.path.dirname(sciezka), exist_ok=True)
        tmp = sciezka + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dane, f, ensure_ascii=False, indent=2)
        os.replace(tmp, sciezka)
    except OSError:
        pass


def dopisz_do_historii(historia: list, wartosc: str) -> list:
    """Nowa wartość na początek listy, bez duplikatów, najwyżej HISTORIA_WT_MAX pozycji."""
    wartosc = (wartosc or "").strip()
    if not wartosc:
        return list(historia)
    return ([wartosc] + [h for h in historia if h != wartosc])[:HISTORIA_WT_MAX]
