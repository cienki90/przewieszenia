"""Uruchomienie pakietu: ``python -m generator`` otwiera okno programu.

Dla trybu wiersza poleceń użyj ``python -m generator.pipeline <plan.dxf>``.
"""
from __future__ import annotations

import sys


def main():
    # bez argumentów -> okno; z argumentami -> wiersz poleceń (łańcuch)
    if len(sys.argv) > 1:
        from .pipeline import main as cli
        return cli()
    try:
        from .gui import main as okno
    except Exception as ex:  # tkinter niedostępny -> podpowiedz tryb konsoli  # noqa: BLE001
        print("Nie można otworzyć okna programu:", ex)
        print("Uruchom w trybie wiersza poleceń: python -m generator.pipeline <plik planu.dxf>")
        return 1
    okno()
    return 0


if __name__ == "__main__":
    sys.exit(main())
