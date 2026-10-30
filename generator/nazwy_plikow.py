"""Nazwy plików wynikowych: przedrostek „!…” na początku nazwy, żeby wyniki programu leżały razem
na górze folderu projektu (Eksplorator sortuje „!” przed literami):

  !ponumerowany <plan>.dxf   - numeracja słupów
  !Przewieszenia <plan>.dxf  - przewieszenia
  !PZT <plan>.dxf            - arkusze PZT
  !PPW <plan>.dxf            - plik powykonawczy (renumeracja rysunków)

Rdzeń nazwy to nazwa planu bez przedrostków wyników (i bez końcówek starszych nazw, np.
„X - ponumerowane - PZT.dxf”), więc z „!ponumerowany X.dxf” powstaje „!PZT X.dxf”, a z niego
„!PPW X.dxf” (bez nawarstwiania przedrostków).
"""
from __future__ import annotations

import os

PONUMEROWANY = "!ponumerowany"
PRZEWIESZENIA = "!Przewieszenia"
PZT = "!PZT"
PPW = "!PPW"
PRZEDROSTKI = (PONUMEROWANY, PRZEWIESZENIA, PZT, PPW)
# końcówki nazw wyników sprzed wersji z przedrostkami („<plan> - ponumerowane.dxf” itd.)
STARE_KONCOWKI = (" - ponumerowane", " - przewieszenia", " - PZT")


def rdzen(sciezka: str) -> str:
    """Nazwa pliku bez rozszerzenia, bez przedrostków wyników programu i bez końcówek starszych nazw
    („!PZT X”, „X - ponumerowane - PZT” -> „X”)."""
    nazwa = os.path.splitext(os.path.basename(sciezka))[0]
    zmiana = True
    while zmiana:
        zmiana = False
        for p in PRZEDROSTKI:
            if nazwa.lower().startswith(p.lower() + " ") and len(nazwa) > len(p) + 1:
                nazwa = nazwa[len(p) + 1:].lstrip()
                zmiana = True
        for k in STARE_KONCOWKI:
            if nazwa.lower().endswith(k.lower()) and len(nazwa) > len(k):
                nazwa = nazwa[:-len(k)].rstrip()
                zmiana = True
    return nazwa


def wynik(przedrostek: str, plan: str, katalog: str | None = None, rozszerzenie: str = ".dxf") -> str:
    """Ścieżka wyniku „<przedrostek> <rdzeń planu><rozszerzenie>” w katalogu (domyślnie obok planu)."""
    kat = katalog if katalog is not None else os.path.dirname(os.path.abspath(plan))
    return os.path.join(kat, f"{przedrostek} {rdzen(plan)}{rozszerzenie}")


def czy_pzt(nazwa: str) -> bool:
    """Plik arkuszy PZT: „!PZT <plan>.dxf/.dwg” albo starsza nazwa „<plan> - PZT.dxf/.dwg”."""
    n = os.path.basename(nazwa).lower()
    if not n.endswith((".dxf", ".dwg")):
        return False
    return n.startswith(PZT.lower() + " ") or (n[:-4].endswith(" - pzt") and not n.startswith(("ppw ", "!ppw ")))
