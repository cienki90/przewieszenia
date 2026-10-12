"""Zunifikowany generator projektów linii nN z pojedynczego pliku DXF.

Pakiet łączy narzędzia działające na jednym rysunku planu DXF:

* ``przewieszenia`` – rysunki zwisów (przewieszeń) przęseł linii nN ze światłowodem,
* ``zestawienie``   – zestawienie słupów nN w podziale na stacje transformatorowe (XLSX),
* ``obliczenia``    – obliczenia nośności słupów na podstawie zestawienia (XLSX),
* ``orientacje``    – rysunki stałe: plan orientacyjny DXF dla każdej stacji trafo + podkład mapowy,
* ``pzt``           – arkusze PZT A3 1:1000 dla zakresów stacji trafo.

Moduł :mod:`generator.pipeline` spina kroki w jedno uruchomienie,
a :mod:`generator.gui` daje interfejs okienkowy z zakładką dla każdego modułu.

Rdzeń korzysta tylko z biblioteki standardowej Pythona 3.9+; biblioteka Pillow jest
potrzebna wyłącznie do podkładu mapowego w rysunkach stałych.
"""
from __future__ import annotations

__all__ = ["pipeline", "zasoby"]
__version__ = "1.0-mini-final"
