"""Opis „STACJA TRAFO” rozpoznawany jednakowo w numeracji/zestawieniu, PZT i sprawdzaniu planu."""
import pytest

from generator import pzt, sprawdz_plan
from generator.numeruj_slupy import czytaj_dxf


def test_ten_sam_wzorzec_we_wszystkich_modulach():
    assert pzt.WZOR_STACJI == czytaj_dxf.WZOR_STACJI == sprawdz_plan.WZOR_STACJI


@pytest.mark.parametrize("tekst", ["STACJA TRAFO\n03-0551", "STACJA TRAFO 03-0551", "STACJA TRAFO:\n03-0551",
                                   "Stacja trafo nr 03-0551", "STACJA TRAFO\nST 03-0551",
                                   'STACJA TRAFO\n03-0551 "Karczew"'])
def test_odmiany_opisu(tekst):
    assert czytaj_dxf.RE_STACJA.search(tekst).group(1) == "03-0551"


def test_krotki_numer():
    assert czytaj_dxf.RE_STACJA.search("STACJA TRAFO\n551").group(1) == "551"


def test_pzt_poligon_bez_opisu_jak_w_numeracji():
    """PZT: poligon bez opisu dostaje tylko wolną stację do 300 m - jak numeracja i zestawienie."""
    kw = lambda x0, y0, a=100: [(x0, y0), (x0 + a, y0), (x0 + a, y0 + a), (x0, y0 + a)]
    we = pzt.Wejscie([], [[None, kw(0, 0), "A"], [None, kw(200, 0), "B"], [None, kw(5000, 0), "C"]],
                     [("03-0001", (50, 50)), ("03-0002", (330, 50))], (0, 0), (0, 0, 0, 0))
    ost = []
    assert pzt.numery_poligonow(we, {}, ost) == ["03-0001", "03-0002", None]
    assert any("pominięto" in o for o in ost)
