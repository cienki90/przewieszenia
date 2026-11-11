"""Postęp na żywo: wydruki modułu trafiają do logu od razu (nie dopiero po zakończeniu kroku)
i nie pojawiają się w nim drugi raz razem z raportem kroku."""
import os
import shutil
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import pipeline  # noqa: E402

PLAN = os.path.join(KORZEN, "przyklady", "przewieszenia plan.dxf")


class TestPostep(unittest.TestCase):
    def tearDown(self):
        pipeline._POSTEP.update(log=None, pokazane=[])

    def test_linie_ida_do_logu_w_trakcie(self):
        log = []
        pipeline._POSTEP.update(log=log.append, pokazane=[])

        def modul():
            print("stacja 1/3")
            self.assertEqual(log, ["stacja 1/3"])            # widać, zanim moduł skończy
            print("stacja", end=" ")
            self.assertEqual(log, ["stacja 1/3"])            # niepełna linia czeka na koniec
            print("2/3")
            print("ostatnia bez końca linii", end="", file=sys.stderr)
            return "wynik"

        wynik, tekst = pipeline._przechwyc(modul)
        self.assertEqual(wynik, "wynik")
        self.assertEqual(log, ["stacja 1/3", "stacja 2/3", "ostatnia bez końca linii"])
        self.assertEqual(tekst, "stacja 1/3\nstacja 2/3\nostatnia bez końca linii")
        raport = tekst + "\nRaport zwrócony przez moduł\nstacja 1/3"   # druga „stacja 1/3” nie była na żywo
        self.assertEqual(pipeline._bez_pokazanych(raport, pipeline._POSTEP["pokazane"]),
                         "Raport zwrócony przez moduł\nstacja 1/3")

    def test_log_print_nie_zapetla_sie(self):
        """W wierszu poleceń log=print: linia idzie na prawdziwy ekran, a nie z powrotem do przechwytywania."""
        ekran = []

        class Ekran:
            def write(self, s):
                ekran.append(s)

            def flush(self):
                pass

        stary = sys.stdout
        sys.stdout = Ekran()
        try:
            pipeline._POSTEP.update(log=print, pokazane=[])
            _, tekst = pipeline._przechwyc(lambda: print("krok"))
        finally:
            sys.stdout = stary
        self.assertEqual(tekst, "krok\n")
        self.assertEqual("".join(ekran), "krok\n")

    def test_bez_kroku_tylko_przechwytuje(self):
        _, tekst = pipeline._przechwyc(lambda: print("cicho"))
        self.assertEqual(tekst, "cicho\n")

    def test_krok_nie_powtarza_linii(self):
        kat = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, kat, True)
        plan = shutil.copy2(PLAN, os.path.join(kat, "plan.dxf"))
        log = []
        wynik = pipeline.uruchom(pipeline.Opcje(plan=plan, katalog=kat, kroki=("zestawienie", "obliczenia"),
                                                eksport_dwg=False, log=log.append, seed=1))
        self.assertTrue(all(k.ok for k in wynik.kroki), [k.blad for k in wynik.kroki])
        linie = [x for t in log for x in str(t).splitlines() if x.strip()]
        zapis = [x for x in linie if x.startswith("Zapisano: ")]
        self.assertTrue(zapis, linie)
        for x in zapis:                                        # raport modułu obliczeń: raz, nie dwa razy
            self.assertEqual(linie.count(x), 1, x)
        self.assertIsNone(pipeline._POSTEP["log"])


if __name__ == "__main__":
    unittest.main()
