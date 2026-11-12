"""Stacje o tym samym numerze i różnych prefiksach (05-0073 i 09-0073) w jednym projekcie:
program nazywa arkusze, rysunki i opisy samym numerem, więc zamiast je pomieszać - zatrzymuje moduł."""
import os
import shutil
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import nazwy, obliczenia, opisy, pzt, sprawdz_plan, wt, zasoby  # noqa: E402


def _plan(stacje):
    """DXF: trasa !tele, a dla każdej stacji obrys !trafo z opisem „STACJA TRAFO <nr>” na _mm trafo."""
    import ezdxf
    from ezdxf.math import Vec2
    from ezdxf.render import mleader
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 50), (300 * len(stacje), 50)], dxfattribs={"layer": "!tele"})
    for i, nr in enumerate(stacje):
        x0 = 300 * i
        msp.add_lwpolyline([(x0, 0), (x0 + 200, 0), (x0 + 200, 100), (x0, 100)], close=True,
                           dxfattribs={"layer": "!trafo"})
        ml = msp.add_multileader_mtext("Standard", dxfattribs={"layer": "_mm trafo"})
        ml.set_content(f"STACJA TRAFO\\P{nr}")
        ml.add_leader_line(mleader.ConnectionSide.left, [Vec2(x0 + 100, 60)])
        ml.build(insert=Vec2(x0 + 110, 70))
    return doc


class TestPrefiksyStacji(unittest.TestCase):
    def setUp(self):
        self.kat = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.kat, True)

    def test_wykrywanie(self):
        self.assertEqual(nazwy.kolizje_prefiksow(["05-0073", "09-0073", "05-0100", "09-0200", "0300"]),
                         ["05-0073 i 09-0073"])
        self.assertEqual(nazwy.kolizje_prefiksow(["05-0073", "05-073", "05-0073", "73", "0073"]), [])
        self.assertEqual(nazwy.kolizje_prefiksow([]), [])
        nazwy.sprawdz_prefiksy(["09-0359", "09-0395"])               # różne numery - bez wyjątku
        with self.assertRaises(ValueError) as cm:
            nazwy.sprawdz_prefiksy(["05-0073", "09-0073"])
        self.assertIn("05-0073 i 09-0073", str(cm.exception))

    def test_pzt_i_wt_zatrzymuja_sie(self):
        plik = os.path.join(self.kat, "plan.dxf")
        _plan(["05-0073", "09-0073"]).saveas(plik)
        we = pzt.wczytaj(plik, wzorzec=False)
        with self.assertRaises(ValueError):
            pzt.dane_stacji(we)
        with self.assertRaises(ValueError):
            wt._poligony_stacji(we, [])
        raport = sprawdz_plan.sprawdz(plik)
        self.assertTrue(any(poziom == sprawdz_plan.BLAD and "05-0073 i 09-0073" in tekst
                            for poziom, tekst in raport.fakty), raport.fakty)

    def test_rozne_numery_dzialaja(self):
        plik = os.path.join(self.kat, "plan.dxf")
        _plan(["05-0073", "09-0074"]).saveas(plik)
        we = pzt.wczytaj(plik, wzorzec=False)
        stacje = pzt.dane_stacji(we)[0] if isinstance(pzt.dane_stacji(we), tuple) else pzt.dane_stacji(we)
        self.assertEqual(sorted(s.oznaczenie for s in stacje), ["05-0073", "09-0074"])
        self.assertFalse(any("prefiks" in tekst for _, tekst in sprawdz_plan.sprawdz(plik).fakty))

    def test_obliczenia_zatrzymuja_sie(self):
        stacje = [obliczenia.Stacja(n, [obliczenia.Slup("1", "P", "-10/ZN", 40, obwod=1)])
                  for n in ("05-0073", "09-0073")]
        oryg = obliczenia.czytaj_zestawienie
        obliczenia.czytaj_zestawienie = lambda *_a, **_k: (stacje, {})
        try:
            with self.assertRaises(SystemExit) as cm:
                obliczenia.oblicz("zestawienie.xlsx", os.path.join(self.kat, "o.xlsx"), seed=1, cicho=True)
        finally:
            obliczenia.czytaj_zestawienie = oryg
        self.assertIn("05-0073 i 09-0073", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.kat, "o.xlsx")))

    def test_opisy_nie_nadpisuja_pliku(self):
        try:
            import docx  # noqa: F401
            import openpyxl
        except ImportError:
            self.skipTest("brak python-docx / openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Arkusz1"
        ws.append(["Lp.", "Oznaczenie stacji", "Nr stacji", "Miejscowość"])
        ws.append([1, "05-0073", "73", "Osieck"])
        ws.append([2, "09-0073", "73", "Sobienki"])
        zest = os.path.join(self.kat, "zestawienie_stacji.xlsx")
        wb.save(zest)
        out = os.path.join(self.kat, "opisy")
        with self.assertRaises(ValueError) as cm:
            opisy.generuj(zasoby.szablon_opisu_docx(), zest, out=out, log=lambda *_: None)
        self.assertIn("73.docx (05-0073, 09-0073)", str(cm.exception))
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
