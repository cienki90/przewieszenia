"""Nazwy plików wynikowych: przedrostki „!…”, rdzeń nazwy, rozpoznawanie PZT, plik powykonawczy."""
import os
import sys
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import nazwy_plikow as np  # noqa: E402
from generator import pipeline, ppw  # noqa: E402

A = os.path.join(KORZEN, "_a")


class TestRdzen(unittest.TestCase):
    def test_przedrostki(self):
        self.assertEqual(np.rdzen("!PZT !ponumerowany X.dxf"), "X")
        self.assertEqual(np.rdzen(os.path.join(A, "!Przewieszenia PW Cyganka.dwg")), "PW Cyganka")
        self.assertEqual(np.rdzen("!ppw x.dxf"), "x")                      # wielkość liter bez znaczenia

    def test_stare_koncowki(self):
        self.assertEqual(np.rdzen("pw_final2 - ponumerowane - PZT.dxf"), "pw_final2")
        self.assertEqual(np.rdzen("!ponumerowany X - ponumerowane.dwg"), "X")
        self.assertEqual(np.rdzen("plan - przewieszenia.dxf"), "plan")

    def test_bez_zmian(self):
        self.assertEqual(np.rdzen("Plan zwykły.dxf"), "Plan zwykły")
        self.assertEqual(np.rdzen("!PZT.dxf"), "!PZT")                       # sam przedrostek to nie wynik
        self.assertEqual(np.rdzen("plan - kontrola.dxf"), "plan - kontrola")


class TestWyniki(unittest.TestCase):
    def test_wynik(self):
        self.assertEqual(np.wynik(np.PZT, os.path.join(A, "!ponumerowany X.dxf")), os.path.join(A, "!PZT X.dxf"))
        self.assertEqual(np.wynik(np.PONUMEROWANY, "X.dwg", katalog=A), os.path.join(A, "!ponumerowany X.dxf"))

    def test_domyslne_wyjscia(self):
        w = pipeline.domyslne_wyjscia(os.path.join(A, "!ponumerowany PW Cyganka.dwg"))
        nazwy = {k: os.path.basename(v) for k, v in w.items()}
        self.assertEqual(nazwy["numeracja"], "!ponumerowany PW Cyganka.dxf")
        self.assertEqual(nazwy["przewieszenia"], "!Przewieszenia PW Cyganka.dxf")
        self.assertEqual(nazwy["pzt"], "!PZT PW Cyganka.dxf")
        self.assertEqual(nazwy["ppw_renumer"], "!PPW PW Cyganka.dxf")
        self.assertEqual(nazwy["zestawienie"], "zestawienie PW Cyganka.xlsx")

    def test_czy_pzt(self):
        tak = ("!PZT X.dwg", "!pzt x.dxf", "X - PZT.dxf", "PW Cyganka - ponumerowane - PZT.dwg")
        nie = ("PPW X - PZT.dxf", "!PPW X - PZT.dxf", "X - PZT - kontrola.dxf", "!PZT X.pdf", "PZT.dxf")
        for n in tak:
            self.assertTrue(np.czy_pzt(n), n)
        for n in nie:
            self.assertFalse(np.czy_pzt(n), n)


class TestPowykonawczy(unittest.TestCase):
    def test_z_pzt(self):
        self.assertEqual(ppw.nazwa_powykonawcza(os.path.join(A, "!PZT X.dxf")), os.path.join(A, "!PPW X.dxf"))
        self.assertEqual(ppw.nazwa_powykonawcza(os.path.join(A, "X - ponumerowane - PZT.dxf")),
                         os.path.join(A, "!PPW X.dxf"))

    def test_stary_przedrostek(self):
        self.assertEqual(ppw.nazwa_powykonawcza(os.path.join(A, "PPW X.dxf")), os.path.join(A, "!PPW X.dxf"))

    def test_nie_nadpisuje_wejscia(self):
        wej = os.path.join(A, "!PPW X.dxf")
        self.assertEqual(ppw.nazwa_powykonawcza(wej), os.path.join(A, "!PPW !PPW X.dxf"))
        b = os.path.join(KORZEN, "_b")
        self.assertEqual(ppw.nazwa_powykonawcza(wej, b), os.path.join(b, "!PPW X.dxf"))


if __name__ == "__main__":
    unittest.main()
