#!/usr/bin/env python3
"""Punkt startowy okienkowej wersji programu (używany też przy budowie pliku .exe).

Uruchom dwuklikiem (po zbudowaniu .exe) albo:  python generator_gui.py
"""
from __future__ import annotations

from generator.gui import main

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()   # rysowanie PDF w kilku procesach (także w .exe)
    main()
