"""Moduł nr 1 - uruchamianie programu Generator WT (etap warunków technicznych) i odbiór jego wyników.

Generator WT to osobny program (okno PySide6/Qt): analiza planu, numeracja słupów, pismo
o dostęp do słupów, zestawienia i arkusze. Uruchamiamy go jako OSOBNY PROCES (Qt i tkinter nie
mogą dzielić jednej pętli okna), a po jego zamknięciu zbieramy wyniki zapisane obok pliku DXF:
  <nazwa>_pismo.docx, _rozbudowana.xlsx, _uproszczona.xls, _tabela_projektowa.xlsx,
  _numeracja.dxf (+ .pdf), _orientacja.dxf (+ .jpg/.pdf).
Zestawienie uproszczone (.xls) zasila dalsze moduły jako plik „Warunki techniczne”.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

# przyrostki wyników Generatora WT -> opis (kolejność = kolejność w raporcie)
WYNIKI = (
    ("_pismo.docx", "pismo - zapytanie o dostęp do słupów"),
    ("_uproszczona.xls", "zestawienie uproszczone (WT)"),
    ("_rozbudowana.xlsx", "zestawienie rozbudowane"),
    ("_tabela_projektowa.xlsx", "tabela projektowa"),
    ("_numeracja.dxf", "numeracja + arkusze 1:1000"),
    ("_numeracja.pdf", "arkusze 1:1000 (PDF)"),
    ("_orientacja.dxf", "plan orientacyjny"),
    ("_orientacja.pdf", "plan orientacyjny (PDF)"),
)


def czy_generator_wt(sciezka: str) -> bool:
    """Folder z uruchom.pyw + generator_wt/ albo plik .exe Generatora WT."""
    if not sciezka:
        return False
    if os.path.isfile(sciezka):
        return sciezka.lower().endswith(".exe")
    return (os.path.isfile(os.path.join(sciezka, "uruchom.pyw"))
            and os.path.isdir(os.path.join(sciezka, "generator_wt")))


def znajdz_generator_wt(katalogi_startowe=()) -> str | None:
    """Szuka Generatora WT obok programu: folder „GENERATOR_WT*” (albo „Generator WT*”) w folderze
    nadrzędnym, a także w „GOTOWE PROJEKTY” - tak leżą programy u użytkownika."""
    baza = [os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))]
    baza += [k for k in katalogi_startowe if k]
    kandydaci = []
    for k in baza:
        for gora in (k, os.path.dirname(k), os.path.dirname(os.path.dirname(k))):
            for podfolder in ("", "GOTOWE PROJEKTY"):
                folder = os.path.join(gora, podfolder) if podfolder else gora
                kandydaci += glob.glob(os.path.join(folder, "GENERATOR_WT*"))
                kandydaci += glob.glob(os.path.join(folder, "Generator WT*"))
    for k in kandydaci:
        if czy_generator_wt(k):
            return os.path.normpath(k)
        exe = os.path.join(k, "Generator WT.exe")
        if os.path.isfile(exe):
            return os.path.normpath(exe)
    return None


def uruchom(sciezka: str) -> subprocess.Popen:
    """Uruchamia Generator WT jako osobny proces (okno bez konsoli)."""
    if sciezka.lower().endswith(".exe"):
        return subprocess.Popen([sciezka], cwd=os.path.dirname(sciezka))
    python = (shutil.which("pythonw") or shutil.which("pyw")
              or (sys.executable if not getattr(sys, "frozen", False) else None))
    if not python:
        raise FileNotFoundError("Nie znaleziono Pythona do uruchomienia Generatora WT "
                                "(zainstaluj Pythona albo wskaż plik „Generator WT.exe”).")
    flagi = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen([python, "uruchom.pyw"], cwd=sciezka, creationflags=flagi)


def znajdz_wyniki(folder: str, od_czasu: float = 0.0) -> dict:
    """{przyrostek: najnowszy plik} wyników Generatora WT w folderze (i podfolderach do 2 poziomów),
    zmienionych nie wcześniej niż `od_czasu`."""
    wynik = {}
    if not folder or not os.path.isdir(folder):
        return wynik
    for przyrostek, _opis in WYNIKI:
        pliki = []
        for wzor in ("*", os.path.join("*", "*"), os.path.join("*", "*", "*")):
            pliki += glob.glob(os.path.join(folder, wzor + przyrostek))
        pliki = [p for p in pliki if os.path.getmtime(p) >= od_czasu]
        if pliki:
            wynik[przyrostek] = max(pliki, key=os.path.getmtime)
    return wynik
