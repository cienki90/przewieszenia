"""Numeracja: znaczniki „1”/„2” z warstw _numery* mają pierwszeństwo przed innymi liczbami w rysunku
(np. numerami punktów geodezyjnych), a obwód bez znacznika nie zabiera „1” sąsiedniego obwodu."""
import os
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import zestawienie  # noqa: E402
from generator.numeruj_slupy import model, numeracja  # noqa: E402

# dwa obwody jednej stacji, bez połączenia w sieci !tele
OBWOD_A = [(1000.0, 0.0), (1040.0, 0.0), (1080.0, 0.0), (1120.0, 0.0)]
OBWOD_B = [(1000.0, 100.0), (1000.0, 140.0), (1000.0, 180.0)]


def plan(sciezka, warstwa_znacznikow="_numery", bez_jedynki_a=False, punkty_geodezyjne=True):
    import ezdxf
    doc = ezdxf.new("R2013")
    msp = doc.modelspace()
    msp.add_lwpolyline([(900, -100), (1300, -100), (1300, 300), (900, 300)], close=True,
                       dxfattribs={"layer": "!trafo_03-1322"})
    msp.add_mtext("STACJA TRAFO\\P03-1322", dxfattribs={"layer": "trafo", "insert": (1010, 50)})
    numer = 8000
    for slupy, odsuniecie in ((OBWOD_A, (0, -4)), (OBWOD_B, (4, 0))):
        msp.add_lwpolyline(slupy, dxfattribs={"layer": "!tele"})
        for x, y in slupy:
            msp.add_mtext("słup nN\\PP-10/ZN", dxfattribs={"layer": "opisy", "insert": (x, y)})
            if punkty_geodezyjne:
                numer += 1                       # numer punktu tuż przy słupie, bliżej niż znacznik
                msp.add_text(str(numer), dxfattribs={"layer": "PointNames", "insert": (x + 1, y + 1)})
        for i, tekst in enumerate(("1", "2")):
            if bez_jedynki_a and slupy is OBWOD_A and tekst == "1":
                continue
            x, y = slupy[i]
            msp.add_text(tekst, dxfattribs={"layer": warstwa_znacznikow, "insert": (x + odsuniecie[0], y + odsuniecie[1])})
    msp.add_mtext("obw. nr 1", dxfattribs={"layer": "opisy", "insert": (1020, 0)})
    msp.add_mtext("obw. nr 2", dxfattribs={"layer": "opisy", "insert": (1000, 120)})
    doc.saveas(sciezka)
    return sciezka


class TestZnaczniki(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _numeruj(self, nazwa, **opcje):
        m = model.wczytaj(plan(os.path.join(self.tmp.name, nazwa), **opcje))
        obwody, log = numeracja.numeruj(m)
        wynik = {o["nr_obwodu"]: {m.slupy[i]["p"]: nr for i, nr in o["slupy"].items()} for o in obwody}
        return wynik, [str(u[1]) for u in log]

    def _sprawdz_oba_obwody(self, wynik):
        self.assertEqual(wynik[1], {p: str(i) for i, p in enumerate(OBWOD_A, 1)})
        self.assertEqual(wynik[2], {p: str(i) for i, p in enumerate(OBWOD_B, 1)})

    def test_numery_punktow_nie_wypieraja_znacznikow(self):
        wynik, log = self._numeruj("punkty.dxf")
        self._sprawdz_oba_obwody(wynik)
        self.assertFalse([u for u in log if "przerwa" in u or "brak znacznika" in u or "nie znaleziono" in u], log)

    def test_warstwa_numerow_z_dopiskiem(self):
        wynik, _log = self._numeruj("dopisek.dxf", warstwa_znacznikow="_numery slupow etap 4 cz. 2")
        self._sprawdz_oba_obwody(wynik)

    def test_plan_bez_warstwy_numerow_czyta_inne_liczby(self):
        wynik, _log = self._numeruj("bez_warstwy.dxf", warstwa_znacznikow="znaczniki", punkty_geodezyjne=False)
        self._sprawdz_oba_obwody(wynik)

    def test_obwod_bez_jedynki_nie_zabiera_cudzej(self):
        wynik, log = self._numeruj("bez_jedynki.dxf", bez_jedynki_a=True)
        self.assertEqual(wynik[2], {p: str(i) for i, p in enumerate(OBWOD_B, 1)})   # „1” zostaje przy obwodzie 2
        self.assertEqual(wynik[1][OBWOD_A[0]], "1")                                 # nie słup „2”
        self.assertTrue([u for u in log if 'Obwód 03-1322/1: brak znacznika "1"' in u], log)

    def test_zestawienie_czyta_tylko_numery_slupow(self):
        p = plan(os.path.join(self.tmp.name, "zestawienie.dxf"))
        self.assertEqual(sorted(t for t, _p in zestawienie.Rysunek(p).teksty), ["1", "1", "2", "2"])
        p = plan(os.path.join(self.tmp.name, "zestawienie2.dxf"), warstwa_znacznikow="znaczniki", punkty_geodezyjne=False)
        self.assertEqual(sorted(t for t, _p in zestawienie.Rysunek(p).teksty), ["1", "1", "2", "2"])


if __name__ == "__main__":
    unittest.main()
