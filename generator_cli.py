#!/usr/bin/env python3
"""Wersja wiersza poleceń zunifikowanego generatora.

Przykłady:
    python generator_cli.py "przyklady/przewieszenia plan.dxf"
    python generator_cli.py "przyklady/przewieszenia plan.dxf" --tylko zestawienie,obliczenia -o wyniki
"""
from __future__ import annotations

import sys

from generator.pipeline import main

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()   # rysowanie PDF w kilku procesach (także w .exe)
    sys.exit(main())
