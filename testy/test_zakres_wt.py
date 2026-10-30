"""Kontrola zakresu WT: czy słupy z pliku WT to słupy planu (przed arkuszami PZT i rysunkami stałymi)."""
import os
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import pipeline, pzt, wt  # noqa: E402

PLAN = os.path.join(KORZEN, "przyklady", "przewieszenia plan.dxf")


def zapisz_wt(sciezka, punkty):
    """Plik WT (.xlsx) jak z Generatora WT: X (2000) = northing, Y (2000) = easting."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Nr słupa", "Rejon Energetyczny", "Gmina", "Miejscowość", "Lokalizacja, ulica", "X", "Y"])
    for i, (x, y) in enumerate(punkty, 1):
        ws.append([i, "RE", "Gmina", "Wieś", "-", round(y, 2), round(x, 2)])
    wb.save(sciezka)


class TestZakresWT(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        we = pzt.wczytaj(PLAN, wzorzec=False)
        cls.slupy = sorted({(round(x, 1), round(y, 1)) for t in we.trasy for x, y in t})
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _wt(self, nazwa, punkty):
        p = os.path.join(self.tmp.name, nazwa)
        zapisz_wt(p, punkty)
        return p

    def test_plan_ma_slupy_i_stacje(self):
        self.assertGreater(len(self.slupy), 100)

    def test_zgodny(self):
        p = wt.pokrycie_wt(PLAN, self._wt("zgodny.xlsx", self.slupy))
        self.assertEqual(p.dopasowane, p.slupy_planu)
        self.assertEqual(p.wt_poza, [])
        self.assertFalse(p.niezgodne)
        self.assertIn("zgodny z planem", p.opis())

    def test_wt_innego_projektu(self):
        p = wt.pokrycie_wt(PLAN, self._wt("inny.xlsx", [(x + 3000, y + 2000) for x, y in self.slupy]))
        self.assertEqual(p.dopasowane, 0)
        self.assertEqual(len(p.wt_poza), len(self.slupy))
        self.assertTrue(p.niezgodne)
        self.assertTrue(p.stacje_bez_wt)
        self.assertIn("NIE pokrywa", p.opis())

    def test_wt_czesci_planu(self):
        p = wt.pokrycie_wt(PLAN, self._wt("czesc.xlsx", self.slupy[: len(self.slupy) // 3]))
        self.assertLess(p.udzial_planu, wt.PROG_PLANU)
        self.assertTrue(p.niezgodne)

    def test_kilka_brakow_to_nie_niezgodnosc(self):
        # słupy wyłączone z numeracji WT są w planie, a nie ma ich w WT - to normalne
        p = wt.pokrycie_wt(PLAN, self._wt("bez5.xlsx", self.slupy[5:]))
        self.assertEqual(p.slupy_planu - p.dopasowane, 5)
        self.assertFalse(p.niezgodne)

    def test_przesuniecie_w_tolerancji(self):
        p = wt.pokrycie_wt(PLAN, self._wt("przes.xlsx", [(x + 2.5, y - 2.0) for x, y in self.slupy]))
        self.assertFalse(p.niezgodne)

    def test_uruchomienie_pyta_i_przerywa(self):
        inny = self._wt("inny2.xlsx", [(x + 3000, y) for x, y in self.slupy])
        pytania = []

        def opcje(odp):
            return pipeline.Opcje(plan=PLAN, wt_plik=inny, log=lambda *a: None,
                                  pytaj=None if odp is None else (lambda t, x: (pytania.append(t), odp)[1]))
        with self.assertRaises(pipeline._Przerwano):
            pipeline._sprawdz_zakres_wt(PLAN, opcje(False), set())
        pipeline._sprawdz_zakres_wt(PLAN, opcje(True), set())       # „Tak” - praca idzie dalej
        pipeline._sprawdz_zakres_wt(PLAN, opcje(None), set())       # CLI - tylko ostrzeżenie w logu
        self.assertEqual(len(pytania), 2)
        sprawdzone = set()
        pipeline._sprawdz_zakres_wt(PLAN, opcje(True), sprawdzone)
        pipeline._sprawdz_zakres_wt(PLAN, opcje(True), sprawdzone)   # ten sam plan i WT - bez ponownego pytania
        self.assertEqual(len(pytania), 3)

    def test_zgodny_nie_pyta(self):
        zgodny = self._wt("zgodny2.xlsx", self.slupy)
        o = pipeline.Opcje(plan=PLAN, wt_plik=zgodny, log=lambda *a: None,
                           pytaj=lambda t, x: self.fail("nie powinno być pytania"))
        pipeline._sprawdz_zakres_wt(PLAN, o, set())


if __name__ == "__main__":
    unittest.main()
