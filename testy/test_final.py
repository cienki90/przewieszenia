"""FINAŁ: kompletny PDF dla stacji - kolejność części i dobór arkuszy do stacji (sztuczne rysunki DXF,
bez Worda: opisy pomijane z uwagą)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import final, pipeline  # noqa: E402

try:
    import ezdxf
    import pymupdf
except ImportError:
    ezdxf = pymupdf = None


def _rysunek(sciezka, arkusze):
    """DXF z arkuszami o podanych nazwach; na każdym prostokąt o szerokości zależnej od numeru arkusza
    (po niej rozpoznajemy w PDF, który arkusz trafił na którą stronę)."""
    doc = ezdxf.new()
    for i, nazwa in enumerate(arkusze):
        lay = doc.layouts.new(nazwa)
        lay.page_setup(size=(100 + 10 * i, 100), margins=(0, 0, 0, 0), units="mm")
        lay.add_line((10, 10), (50, 50))                     # pusty arkusz nie daje się narysować
    if "Layout1" in doc.layouts and "Layout1" not in arkusze:
        doc.layouts.delete("Layout1")
    doc.saveas(sciezka)
    return sciezka


@unittest.skipIf(ezdxf is None, "brak ezdxf / pymupdf")
class TestFinal(unittest.TestCase):
    def setUp(self):
        self.kat = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.kat, True)
        k = self.kat
        os.makedirs(os.path.join(k, "rs"))
        os.makedirs(os.path.join(k, "opisy"))
        self.rs = os.path.join(k, "rs")
        _rysunek(os.path.join(self.rs, "565.dxf"), ["1", "3.1", "3.2", "3.3", "3.4"])
        _rysunek(os.path.join(self.rs, "1495.dxf"), ["1", "3.1", "3.2", "3.3", "3.4"])
        self.pzt = _rysunek(os.path.join(k, "!PZT plan.dxf"), ["565-1", "565-2", "1495-1"])
        self.przew = _rysunek(os.path.join(k, "!Przewieszenia plan.dxf"), ["1", "2"])
        with open(os.path.join(k, "!Przewieszenia plan.stacje.json"), "w", encoding="utf-8") as f:
            json.dump({"arkusze": {"1": ["ST 05-0565"], "2": ["ST 05-0565", "ST 05-1495"]}}, f)

    def _zrodla(self, przew=True):
        return final.Zrodla(opisy=os.path.join(self.kat, "opisy"), rysunki_stale=self.rs, pzt=self.pzt,
                            przewieszenia=self.przew if przew else None)

    @staticmethod
    def _szerokosci(plik):
        with pymupdf.open(plik) as d:
            return [round(s.rect.width * 25.4 / 72) for s in d]

    def test_komplet_dla_stacji(self):
        self.assertEqual(final.stacje(self._zrodla()), [565, 1495])
        log = []
        w = final.zloz(self._zrodla(), os.path.join(self.kat, "PDF"), log=log.append)
        self.assertEqual(sorted(os.path.basename(p) for p in w.pliki), ["FINAŁ ST 1495.pdf", "FINAŁ ST 565.pdf"])
        # 565: plan „1”, PZT 565-1/565-2, rysunki 3.1-3.4, przewieszenia arkusze 1 i 2
        self.assertEqual(self._szerokosci(os.path.join(self.kat, "PDF", "FINAŁ ST 565.pdf")),
                         [100, 100, 110, 110, 120, 130, 140, 100, 110])
        # 1495: plan, PZT 1495-1, rysunki 3.1-3.4, przewieszenia tylko arkusz 2
        self.assertEqual(self._szerokosci(os.path.join(self.kat, "PDF", "FINAŁ ST 1495.pdf")),
                         [100, 120, 110, 120, 130, 140, 110])
        self.assertIn("stacja 565: brak - opis", w.uwagi)

    def test_wybrane_stacje_jeden_plik_i_brak_przypisania(self):
        w = final.zloz(self._zrodla(), os.path.join(self.kat, "PDF"), wybrane=[1495], jeden_plik=True,
                       nazwa_projektu="Test", log=lambda *_: None)
        self.assertEqual([os.path.basename(p) for p in w.pliki], ["FINAŁ Test.pdf"])
        os.remove(os.path.join(self.kat, "!Przewieszenia plan.stacje.json"))
        w = final.zloz(self._zrodla(), os.path.join(self.kat, "PDF2"), wybrane=[565], log=lambda *_: None)
        self.assertTrue(any("stacje.json" in u for u in w.uwagi), w.uwagi)
        self.assertEqual(len(self._szerokosci(w.pliki[0])), 7)            # bez przewieszeń
        self.assertEqual(final.parsuj_stacje("05-0565, 1495;  "), [565, 1495])
        self.assertIsNone(final.parsuj_stacje(" "))

    def test_krok_w_programie(self):
        op = pipeline.Opcje(plan=self.pzt, katalog=self.kat, kroki=("final",), final_rysunki=self.rs,
                            final_pzt=self.pzt, final_przewieszenia=self.przew, final_stacje="565",
                            eksport_dwg=False, log=lambda *_: None)
        wynik = pipeline.uruchom(op)
        self.assertEqual([(k.nazwa, k.ok) for k in wynik.kroki], [("final", True)])
        self.assertEqual(os.path.normcase(wynik.kroki[0].wyjscie), os.path.normcase(os.path.join(self.kat, "PDF")))
        self.assertTrue(os.path.isfile(os.path.join(self.kat, "PDF", "FINAŁ ST 565.pdf")))


if __name__ == "__main__":
    unittest.main()
