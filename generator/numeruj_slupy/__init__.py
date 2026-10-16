"""Podpakiet numeracji słupów nN (z repo gałęzi numeracja-slupow).

Publiczne wejście: :func:`przetworz` (plik DXF -> plik „… - ponumerowane.dxf” + raport).
Zapis wyniku wymaga biblioteki ``ezdxf`` (opcjonalna - importowana leniwie w zapis_dxf).
"""
from __future__ import annotations

try:
    from .numeruj import przetworz
except ImportError:  # bezpośrednie uruchomienie
    from numeruj import przetworz

__all__ = ["przetworz"]
