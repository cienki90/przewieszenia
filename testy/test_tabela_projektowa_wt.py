"""Tabela projektowa: numeracja i układ współrzędnych jak we wcześniejszych WT."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import load_workbook  # noqa: E402

from generator.warunki import export  # noqa: E402
from generator.warunki.config import Config  # noqa: E402
from generator.warunki.model import Wierzcholek  # noqa: E402
from generator.wt import SlupWT  # noqa: E402


def test_numeracja_z_wt_przekreslenie_i_nowe_na_koncu():
    wt = [SlupWT(x=7535000.0 + 50 * i, y=5787000.0, miejscowosc="A", nr=str(i + 1), lp=i + 1) for i in range(3)]
    proj = [Wierzcholek(id=0, x=7535100.5, y=5787000.0), Wierzcholek(id=1, x=7535000.2, y=5787000.0),
            Wierzcholek(id=2, x=7536000.0, y=5787000.0)]
    for i, w in enumerate(proj):
        w.etykieta = str(10 + i)
    with tempfile.TemporaryDirectory() as d:
        plik = os.path.join(d, "t.xlsx")
        export.zapisz_projektowa(proj, plik, Config(), wt=wt)
        ws = load_workbook(plik).worksheets[0]
        wiersze = list(ws.iter_rows(min_row=2, values_only=True))
        assert [r[0] for r in wiersze] == [1, 2, 3, 4]
        assert [r[5] for r in wiersze] == [11, 2, 10, 12]          # Lp 2 z WT niewykorzystany
        assert ws.cell(3, 1).font.strike and not ws.cell(2, 1).font.strike
        assert ws.cell(1, 7).value == "Współrzędne PL-2000"
        assert wiersze[0][6] == 5787000.0 and wiersze[0][7] == 7535000.2   # X północna, Y wschodnia
