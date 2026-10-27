"""Zunifikowany generator projektów linii nN z pojedynczego pliku DXF.

Pakiet łączy trzy narzędzia działające na jednym rysunku planu DXF:

* ``przewieszenia`` – rysunki zwisów (przewieszeń) przęseł linii nN ze światłowodem,
* ``zestawienie``   – zestawienie słupów nN w podziale na stacje transformatorowe (XLSX),
* ``obliczenia``    – obliczenia nośności słupów na podstawie zestawienia (XLSX).

Moduł :mod:`generator.pipeline` spina te trzy kroki w jedno uruchomienie,
a :mod:`generator.gui` daje prosty interfejs okienkowy.

Wszystkie moduły korzystają tylko z biblioteki standardowej Pythona 3.9+
(bez zewnętrznych zależności).
"""
from __future__ import annotations

__all__ = ["pipeline", "zasoby"]
# numer główny wersji (zmieniany ręcznie przy dużych zmianach); pełny numer z kolejnym
# numerem kompilacji podaje generator.wersja.wersja()
__version__ = "2.0"
