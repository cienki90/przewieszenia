"""Opisy techniczne: nie powstają, gdy w dołączonych obliczeniach słup nie spełnia warunku nośności."""
import os
import random
import shutil
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import obliczenia, opisy, pipeline, zasoby  # noqa: E402

try:
    import docx  # noqa: F401
    import openpyxl
except ImportError:  # moduł opisów wymaga python-docx i openpyxl
    openpyxl = None


def _stacja(nazwa, slupy):
    st = obliczenia.Stacja(nazwa, [obliczenia.Slup(nr, typ, "-10/ZN", odl, obwod=1) for nr, typ, odl in slupy])
    rng = random.Random(1)
    for s in st.slupy:
        s.oblicz(rng)
    return st


@unittest.skipIf(openpyxl is None, "brak python-docx / openpyxl")
class TestOpisyNosnosc(unittest.TestCase):
    def setUp(self):
        self.kat = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.kat, True)
        # P (przelotowy, nośność 227 daN): 40 m -> ok. 159 daN (OK), 100 m -> ok. 245 daN (za dużo)
        dobra = _stacja("05-0112", [("1", "P", 40), ("2", "P", 35)])
        zla = _stacja("05-0433", [("1", "P", 40), ("2", "P", 100), ("3", "X", 30)])
        self.obliczenia = os.path.join(self.kat, "Obliczenia - zestawienie.xlsx")
        obliczenia.zapisz_xlsx(self.obliczenia, [obliczenia.arkusz_stacji(dobra), obliczenia.arkusz_stacji(zla)])
        self.szablon = zasoby.szablon_opisu_docx()

    def _zestawienie(self, *stacje):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Arkusz1"
        ws.append(["Plik", "trafo", "miejscowosc", None, "wt"])
        for plik, trafo in stacje:
            ws.append([plik, trafo, "Osęka", None, "100/RE-5/KŚ/2026"])
        p = os.path.join(self.kat, "zestawienie.xlsx")
        wb.save(p)
        return p

    def test_kontrola_arkusza(self):
        from generator import obliczenia2word as o2w
        wb = openpyxl.load_workbook(self.obliczenia, data_only=True)
        self.assertEqual(o2w.bledy_nosnosci(wb["112"]), [])
        bledy = o2w.bledy_nosnosci(wb["433"])
        self.assertEqual(len(bledy), 2, bledy)
        self.assertRegex(bledy[0], r"^obw\. 1, słup 2: obciążenie 24\d\.\d\d daN > nośność 227 daN$")
        self.assertIn("słup 3: nieznana nośność", bledy[1])

    def test_adnotacja_uwaga_bez_wskazanego_slupa(self):
        from generator import obliczenia2word as o2w
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Sieć napowietrzna nN", None, None, None, "obw nr:", 1])
        ws.append(["Lp", None, "Nr słupa", "Nośność [daN]", "Obciążenie [daN]"])
        ws.append([1, 1, "1", 1000, 900.5])
        ws.append(["UWAGA! NIE WSZYSTKIE STANOWISKA SŁUPOWE SPEŁNIAJĄ WARUNEK NOŚNOŚCI - słupy nr: 7"])
        self.assertEqual(o2w.bledy_nosnosci(ws), ["UWAGA! NIE WSZYSTKIE STANOWISKA SŁUPOWE SPEŁNIAJĄ "
                                                  "WARUNEK NOŚNOŚCI - słupy nr: 7"])

    def test_tabela_przesunieta_jak_w_recznym_arkuszu(self):
        """Ręczne arkusze obliczeń: tabela od kolumny C, nad nią wiersz pomocniczy z „sprawdz” / „ CHECK”."""
        from generator import obliczenia2word as o2w
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append([None, None, "Sieć napowietrzna nN - obw. nN Nr 1 zasilony ze stacji trafo [30-0851]"])
        ws.append(["OB3", 1632, 1, 1, "1", "sprawdz", " CHECK", "wir. typ slupa"])
        ws.append([None, None, "Sieć napowietrzna nN ", None, None, None, "obw nr:", 2])
        ws.append([None, None, "Lp", None, "Nr słupa", "Nośność [daN]", "Obciążenie [daN]", "Typ i rodzaj słupa"])
        ws.append([None, None, 1, 1, "1", 227, 106.29, "żel. P-10/ZN"])
        ws.append([None, None, 2, 2, "2", 1000, 1702.11, "wir. N-10.5/10/E"])
        ws.append([None, None, "Całkowita długość wykorzystanej linii napowietrznej nN:"])
        ws.append([None, None, "WSZYSTKIE STANOWISKA SŁUPOWE SPEŁNIAJĄ WARUNEK NOŚNOŚCI"])
        self.assertEqual(o2w.bledy_nosnosci(ws), ["obw. 2, słup 2: obciążenie 1702.11 daN > nośność 1000 daN"])
        ws["G6"] = 702.11
        self.assertEqual(o2w.bledy_nosnosci(ws), [])

    def test_tabela_bez_kolumny_nr_slupa(self):
        """Arkusz linii SN: „Lp | Nośność | Obciążenie” - słup wskazany pozycją z Lp."""
        from generator import obliczenia2word as o2w
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append([None, None, "Sieć napowietrzna SN"])
        ws.append([None, None, "Lp", "Nośność [daN]", "Obciążenie [daN]", "Typ i rodzaj słupa"])
        ws.append([None, None, 1, 227, 170.68, "żel. P-12/ZN"])
        ws.append([None, None, 2, 227, 245.08, "żel. P-12/ZN"])
        self.assertEqual(o2w.bledy_nosnosci(ws), ["poz. 2: obciążenie 245.08 daN > nośność 227 daN"])

    def test_blad_nosnosci_blokuje_wszystkie_opisy(self):
        out = os.path.join(self.kat, "opisy")
        zest = self._zestawienie(("112", "05-0112"), ("433", "05-0433"))
        with self.assertRaises(opisy.BledyNosnosci) as cm:
            opisy.generuj(self.szablon, zest, out=out, obliczenia=self.obliczenia, log=lambda *_: None)
        self.assertFalse(os.path.exists(out), "nie powinien powstać żaden opis")
        tekst = str(cm.exception)
        self.assertIn("stacja 05-0433 (arkusz „433”)", tekst)
        self.assertIn("słup 2: obciążenie", tekst)
        self.assertNotIn("05-0112", tekst)
        self.assertIn("2 poz. w 1 stacji", cm.exception.krotko)

    def test_obliczenia_bez_bledow(self):
        out = os.path.join(self.kat, "opisy")
        zest = self._zestawienie(("112", "05-0112"))
        utworzone = opisy.generuj(self.szablon, zest, out=out, obliczenia=self.obliczenia, log=lambda *_: None)
        self.assertEqual(utworzone, ["112.docx"])
        self.assertTrue(os.path.isfile(os.path.join(out, "112.docx")))

    def test_bez_obliczen_bez_kontroli(self):
        out = os.path.join(self.kat, "opisy")
        zest = self._zestawienie(("433", "05-0433"))
        self.assertEqual(opisy.generuj(self.szablon, zest, out=out, log=lambda *_: None), ["433.docx"])

    def test_krok_w_programie(self):
        zest = self._zestawienie(("433", "05-0433"))
        op = pipeline.Opcje(plan="", opisy_zestawienie=zest, opisy_obliczenia=self.obliczenia)
        r = pipeline._krok_opisy(op, os.path.join(self.kat, "opisy"), None)
        self.assertFalse(r.ok)
        self.assertTrue(r.blad.startswith("Opisy nie zostały utworzone"), r.blad)
        self.assertIn("słup 2: obciążenie", r.raport)
        self.assertFalse(os.path.exists(os.path.join(self.kat, "opisy")))


if __name__ == "__main__":
    unittest.main()
