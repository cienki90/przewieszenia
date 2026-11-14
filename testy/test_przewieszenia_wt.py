"""Przewieszenia: miejscowość i ulica ze słupów tabeli WT (zamiast internetu i starego CSV)."""
import csv
import glob
import os
import shutil
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import pipeline, plan as plan_mod  # noqa: E402

PLAN = os.path.join(KORZEN, "przyklady", "przewieszenia plan.dxf")

try:
    import openpyxl
except ImportError:
    openpyxl = None


@unittest.skipIf(openpyxl is None, "brak openpyxl")
class TestPrzewieszeniaWT(unittest.TestCase):
    def test_nazwy_z_wt(self):
        kat = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, kat, True)
        plan = shutil.copy2(PLAN, os.path.join(kat, "plan.dxf"))
        p = plan_mod.Plan(plan)
        slupy = [(s.x, s.y) for s in p.slupy]
        self.assertTrue(slupy)
        # tabela WT: każdy słup planu, miejscowość „Testowo”, ulica co drugi słup (reszta bez ulicy)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["L.p.", "Rejon Energetyczny", "Gmina", "Miejscowość", "Lokalizacja, ulica",
                   "Współrzędne w układzie 2000", None])
        for i, (x, y) in enumerate(slupy, 1):
            ws.append([i, "RE", "Gm", "Testowo", "Polna" if i % 2 else "", round(y, 2), round(x, 2)])
        wt = os.path.join(kat, "plan_rozbudowana.xlsx")
        wb.save(wt)
        # stary CSV z innymi nazwami (np. z geokodowania) - WT ma pierwszeństwo
        log = []
        wynik = pipeline.uruchom(pipeline.Opcje(plan=plan, katalog=kat, kroki=("przewieszenia",), adresy="brak",
                                                wt_plik=wt, eksport_dwg=False, log=log.append))
        self.assertTrue(all(k.ok for k in wynik.kroki), [k.blad for k in wynik.kroki])
        opisy = glob.glob(os.path.join(kat, "*_opisy.csv")) + glob.glob(os.path.join(os.path.dirname(plan), "*_opisy.csv"))
        self.assertTrue(opisy)
        wiersze = list(csv.DictReader(open(opisy[0], encoding="utf-8-sig"), delimiter=";"))
        self.assertTrue(wiersze)
        self.assertTrue(all(w["miejscowosc"] == "Testowo" for w in wiersze), wiersze)
        self.assertTrue(all(w["ulica"] in ("", "ul. Polna") for w in wiersze), wiersze)
        tekst = "\n".join(str(x) for x in log)
        self.assertIn(f"z warunków technicznych: {len(wiersze)} z {len(wiersze)} przewieszeń", tekst)


if __name__ == "__main__":
    unittest.main()
