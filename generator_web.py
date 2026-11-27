#!/usr/bin/env python3
"""Wersja przeglądarkowa generatora (serwer WWW, np. na NAS) - patrz generator/web/serwer.py.

    python generator_web.py --port 8765 --dane /volume1/generator --haslo tajne
"""
import sys

from generator.web.serwer import main

if __name__ == "__main__":
    sys.exit(main())
