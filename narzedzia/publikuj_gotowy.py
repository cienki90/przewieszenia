#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publikacja „czystej” kopii programu - bez przykładów i materiałów pomocniczych.

Kopiuje do wskazanego katalogu tylko pliki potrzebne do działania programu (kod, szablony,
skrypty uruchomieniowe), w stanie z OSTATNIEGO COMMITA (HEAD) - niezatwierdzone zmiany
robocze nie trafiają do kopii.

Kopia jest lustrem: pliki programu usunięte z repozytorium znikają też z kopii. Inne pliki
w katalogu docelowym (np. wyniki pracy użytkownika) nie są ruszane - skrypt prowadzi listę
plików, które sam umieścił (``.pliki_programu.txt``), i usuwa tylko z niej.

Użycie:
    python narzedzia/publikuj_gotowy.py "D:/…/GOTOWE PROJEKTY/PGE MAKER"
    python narzedzia/publikuj_gotowy.py "D:/…/PGE MAKER" --zainstaluj-hook [--galaz PGE_MAKER_CLAUDE]

``--zainstaluj-hook`` instaluje hooki gita (post-commit, post-merge, post-rewrite), które po
każdym commicie / pull na wskazanej gałęzi automatycznie odświeżają kopię.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

# co trafia do gotowego programu (ścieżki z repozytorium; katalog = cała zawartość)
PLIKI_PROGRAMU = [
    "generator/",
    "generator_gui.py",
    "generator_cli.py",
    "uruchom.bat",
    "generuj.bat",
    "setup.bat",
    "requirements.txt",
    # szablony i bazy używane przez program (generator/zasoby.py)
    "przewieszenia baza.dxf",
    "arkusze.dxf",
    "szablon.dxf",
    "szablon_opisu.docx",
    "PPW miński szablon.docx",
    "wzorce/",
]
# wyjątki wewnątrz katalogów programu (dokumentacja dla programistów)
POMIN = {"generator/numeruj_slupy/README.md"}

MANIFEST = ".pliki_programu.txt"
PLIK_WERSJI = "generator/_wersja.txt"     # odczytywany przez generator/wersja.py
INSTRUKCJA = "INSTRUKCJA.txt"
HOOKI = ("post-commit", "post-merge", "post-rewrite")

TRESC_INSTRUKCJI = """\
GENERATOR PROJEKTÓW nN — gotowy program
=======================================
Wersja: {wersja}

Pierwsze uruchomienie (raz na komputerze):
  1. Zainstaluj Pythona 3.10+ ze strony https://www.python.org/
     (zaznacz „Add Python to PATH” oraz „tcl/tk and IDLE”).
  2. Uruchom  setup.bat  — sprawdzi Pythona i zainstaluje potrzebne biblioteki.

Praca:
  * uruchom.bat            — okno programu (moduły w panelu po lewej),
  * generuj.bat plan.dxf   — wersja wiersza poleceń (jeden moduł na uruchomienie).

Numery warunków (WT), motyw okna i ostatni moduł są zapamiętywane w
%LOCALAPPDATA%\\GeneratorNN\\ustawienia.json.

Ten katalog jest odświeżany automatycznie z repozytorium (gałąź {galaz}, commit {commit}).
Nie zmieniaj tu plików programu — zmiany zostaną nadpisane przy następnej aktualizacji.
Własne pliki (np. wyniki) możesz tu trzymać — aktualizacja ich nie usuwa.
"""


def _git(repo, *args, tekst=True):
    wynik = subprocess.run(["git", "-C", repo, *args], capture_output=True, check=True)
    return wynik.stdout.decode("utf-8") if tekst else wynik.stdout


def _pliki_z_head(repo) -> list[str]:
    wszystkie = _git(repo, "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", "-z", "HEAD")
    wszystkie = [p for p in wszystkie.split("\0") if p]
    wybrane = []
    for p in wszystkie:
        if p in POMIN:
            continue
        if any(p == w or (w.endswith("/") and p.startswith(w)) for w in PLIKI_PROGRAMU):
            wybrane.append(p)
    return wybrane


def _zapisz_jesli_inny(sciezka, dane: bytes) -> bool:
    try:
        with open(sciezka, "rb") as f:
            if f.read() == dane:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(sciezka) or ".", exist_ok=True)
    tmp = sciezka + ".tmp_publikacja"
    with open(tmp, "wb") as f:
        f.write(dane)
    os.replace(tmp, sciezka)
    return True


def publikuj(repo: str, cel: str) -> tuple[int, int, int]:
    """Odświeża kopię programu w katalogu ``cel``. Zwraca (zmienione, bez zmian, usunięte)."""
    repo = os.path.abspath(repo)
    cel = os.path.abspath(cel)
    os.makedirs(cel, exist_ok=True)
    pliki = _pliki_z_head(repo)
    if not pliki:
        raise RuntimeError("W HEAD nie ma plików programu - sprawdź repozytorium.")

    zmienione = bez_zmian = 0
    for p in pliki:
        dane = _git(repo, "show", f"HEAD:{p}", tekst=False)
        if _zapisz_jesli_inny(os.path.join(cel, *p.split("/")), dane):
            zmienione += 1
        else:
            bez_zmian += 1

    galaz = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    commit = _git(repo, "rev-parse", "--short", "HEAD").strip()
    # numer wersji dla kopii (bez gita): <główna z generator/__init__.py>.<liczba commitów>
    init = _git(repo, "show", "HEAD:generator/__init__.py")
    glowna = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    licznik = _git(repo, "rev-list", "--count", "HEAD").strip()
    data = _git(repo, "log", "-1", "--format=%cs").strip()
    wersja = f"{glowna.group(1) if glowna else '0'}.{licznik} ({data}, {commit})"
    _zapisz_jesli_inny(os.path.join(cel, *PLIK_WERSJI.split("/")), (wersja + "\n").encode("utf-8"))
    pliki = pliki + [PLIK_WERSJI]

    instrukcja = TRESC_INSTRUKCJI.format(galaz=galaz, commit=commit, wersja=wersja).replace("\n", "\r\n")
    _zapisz_jesli_inny(os.path.join(cel, INSTRUKCJA), instrukcja.encode("utf-8"))

    # usuń pliki programu, których już nie ma (tylko te, które sami wcześniej umieściliśmy)
    usuniete = 0
    sciezka_manifestu = os.path.join(cel, MANIFEST)
    try:
        with open(sciezka_manifestu, encoding="utf-8") as f:
            poprzednie = {ln.strip() for ln in f if ln.strip()}
    except OSError:
        poprzednie = set()
    for p in sorted(poprzednie - set(pliki) - {INSTRUKCJA}):
        pelna = os.path.join(cel, *p.split("/"))
        if os.path.isfile(pelna):
            os.remove(pelna)
            usuniete += 1
            katalog = os.path.dirname(pelna)          # sprzątnij puste katalogi po programie
            while katalog != cel and os.path.isdir(katalog) and not os.listdir(katalog):
                os.rmdir(katalog)
                katalog = os.path.dirname(katalog)
    _zapisz_jesli_inny(sciezka_manifestu, ("\n".join(sorted(pliki + [INSTRUKCJA])) + "\n").encode("utf-8"))
    return zmienione, bez_zmian, usuniete


def zainstaluj_hook(repo: str, cel: str, galaz: str) -> list[str]:
    """Hooki gita odświeżające kopię po commicie / pull / amend na gałęzi ``galaz``."""
    katalog_hookow = _git(repo, "rev-parse", "--git-path", "hooks").strip()
    if not os.path.isabs(katalog_hookow):
        katalog_hookow = os.path.join(repo, katalog_hookow)
    os.makedirs(katalog_hookow, exist_ok=True)
    skrypt = "narzedzia/publikuj_gotowy.py"
    tresc = f"""#!/bin/sh
# Automatyczna publikacja czystej kopii programu (narzedzia/publikuj_gotowy.py).
[ "$(git rev-parse --abbrev-ref HEAD)" = "{galaz}" ] || exit 0
CEL='{cel}'
if command -v python >/dev/null 2>&1; then PY=python; else PY="py -3"; fi
$PY "{skrypt}" "$CEL" --cicho || echo "UWAGA: nie udało się odświeżyć kopii programu w $CEL"
exit 0
"""
    zapisane = []
    for nazwa in HOOKI:
        sciezka = os.path.join(katalog_hookow, nazwa)
        with open(sciezka, "w", encoding="utf-8", newline="\n") as f:
            f.write(tresc)
        os.chmod(sciezka, 0o755)
        zapisane.append(sciezka)
    return zapisane


def main(argv=None):
    for strumien in (sys.stdout, sys.stderr):
        try:
            strumien.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="Publikacja czystej kopii programu (bez przykładów).")
    ap.add_argument("cel", help="katalog gotowego programu")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="repozytorium źródłowe (domyślnie to, w którym leży skrypt)")
    ap.add_argument("--zainstaluj-hook", action="store_true",
                    help="zainstaluj hooki gita - automatyczna publikacja po każdym commicie")
    ap.add_argument("--galaz", default="PGE_MAKER_CLAUDE", help="gałąź publikowana przez hooki")
    ap.add_argument("--cicho", action="store_true", help="jedna linia podsumowania")
    a = ap.parse_args(argv)

    if a.zainstaluj_hook:
        for h in zainstaluj_hook(a.repo, os.path.abspath(a.cel), a.galaz):
            print("hook:", h)
    zm, bz, us = publikuj(a.repo, a.cel)
    if a.cicho:
        print(f"Kopia programu odświeżona ({a.cel}): zmienione {zm}, usunięte {us}.")
    else:
        print(f"Kopia programu: {a.cel}")
        print(f"  zmienione/nowe: {zm}, bez zmian: {bz}, usunięte: {us}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
