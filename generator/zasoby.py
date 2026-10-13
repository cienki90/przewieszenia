"""Odnajdywanie plików zasobów (baza rysunków, arkusze) niezależnie od sposobu uruchomienia.

Program może działać:
  * z kodu źródłowego – pliki DXF leżą w katalogu nadrzędnym pakietu (główny katalog repozytorium),
  * ze spakowanego pliku .exe (PyInstaller --onefile) – pliki są wypakowywane do ``sys._MEIPASS``.

Funkcja :func:`sciezka_zasobu` zwraca pierwszą istniejącą ścieżkę do danego pliku,
sprawdzając kolejno: katalog bieżący, katalog obok pliku .exe, katalog pakietu,
katalog nadrzędny pakietu oraz katalog tymczasowy PyInstallera.
"""
from __future__ import annotations

import os
import sys

# domyślne nazwy plików szablonów (DXF)
BAZA = "przewieszenia baza.dxf"
ARKUSZE = "arkusze.dxf"
SZABLON_ORIENTACJI = "szablon.dxf"       # szablon rysunków stałych (orientacje arkuszy)
SZABLON_OPISU = "szablon_opisu.docx"     # szablon opisu technicznego (.docx) - moduł Opisy
WZOR_TABELI_OBLICZEN = os.path.join("wzorce", "wzor_tabeli_obliczen.docx")  # wzorzec tabeli nośności


def _katalogi():
    """Kolejność katalogów przeszukiwanych w poszukiwaniu zasobu."""
    katalogi = [os.getcwd()]
    # katalog, w którym leży uruchomiony program/plik .exe
    if getattr(sys, "frozen", False):
        katalogi.append(os.path.dirname(os.path.abspath(sys.executable)))
    tu = os.path.dirname(os.path.abspath(__file__))
    katalogi.append(tu)                       # katalog pakietu generator/
    katalogi.append(os.path.dirname(tu))      # katalog nadrzędny (repozytorium)
    meipass = getattr(sys, "_MEIPASS", None)   # zasoby wbudowane w .exe
    if meipass:
        katalogi.append(meipass)
    # bez duplikatów, z zachowaniem kolejności
    widziane, wynik = set(), []
    for k in katalogi:
        if k and k not in widziane:
            widziane.add(k)
            wynik.append(k)
    return wynik


def sciezka_zasobu(nazwa: str):
    """Zwraca ścieżkę do pliku zasobu albo None, gdy nie znaleziono."""
    for katalog in _katalogi():
        p = os.path.join(katalog, nazwa)
        if os.path.exists(p):
            return p
    return None


def baza_dxf():
    return sciezka_zasobu(BAZA)


def arkusze_dxf():
    return sciezka_zasobu(ARKUSZE)


def szablon_orientacji_dxf():
    return sciezka_zasobu(SZABLON_ORIENTACJI)


def szablon_opisu_docx():
    return sciezka_zasobu(SZABLON_OPISU)


def wzor_tabeli_obliczen_docx():
    return sciezka_zasobu(WZOR_TABELI_OBLICZEN)
