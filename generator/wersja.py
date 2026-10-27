"""Numer wersji programu - aktualizowany automatycznie.

Format: ``<główna>.<numer kompilacji>`` (np. ``2.0.57``) + data i skrót commita, gdzie
numer kompilacji to liczba commitów w historii - rośnie przy każdej zmianie programu.

Źródło (pierwsze dostępne):
  1. plik ``_wersja.txt`` obok pakietu - zapisywany przy publikacji gotowej kopii
     (narzedzia/publikuj_gotowy.py), która nie ma repozytorium gita,
  2. git - przy uruchomieniu z repozytorium,
  3. sam numer główny (``generator.__version__``), gdy żadne z powyższych nie działa.
"""
from __future__ import annotations

import os
import subprocess

from . import __version__

PLIK_WERSJI = "_wersja.txt"

_pamiec: str | None = None


def wersja_z_gita(repo: str) -> str | None:
    """Pełny opis wersji z repozytorium gita: ``2.0.57 (2026-10-27, 89ee294)``."""
    try:
        def git(*args):
            return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                                  timeout=5, check=True,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
        licznik = git("rev-list", "--count", "HEAD")
        data, skrot = git("log", "-1", "--format=%cs %h").split()
        return f"{__version__}.{licznik} ({data}, {skrot})"
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def wersja() -> str:
    global _pamiec
    if _pamiec is None:
        tu = os.path.dirname(os.path.abspath(__file__))
        try:
            with open(os.path.join(tu, PLIK_WERSJI), encoding="utf-8") as f:
                _pamiec = f.read().strip() or None
        except OSError:
            _pamiec = None
        if not _pamiec and os.path.exists(os.path.join(os.path.dirname(tu), ".git")):
            _pamiec = wersja_z_gita(os.path.dirname(tu))
        _pamiec = _pamiec or __version__
    return _pamiec
