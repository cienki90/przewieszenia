"""Moduł „Warunki techniczne”: okręgi uwag (scalenia, przęsła 50-60 m i > 60 m) na niedrukowalnej
warstwie WT_uwagi o grubości 1.00 mm w rysunku numeracji."""
import os
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)


class TestUwagiNaRysunku(unittest.TestCase):
    def test_okregi_uwag(self):
        import ezdxf

        from generator.warunki.config import Config
        from generator.warunki.projekt import Projekt

        with tempfile.TemporaryDirectory() as kat:
            doc = ezdxf.new()
            msp = doc.modelspace()
            x0, y0 = 7_500_000.0, 5_700_000.0
            tele = {"layer": "!tele"}
            msp.add_lwpolyline([(x0 + x, y0) for x in (0, 45, 100, 165)], dxfattribs=tele)  # 45, 55, 65 m
            msp.add_lwpolyline([(x0 + 165.3, y0), (x0 + 165.3, y0 + 40)], dxfattribs=tele)  # klik 0.3 m obok
            plik = os.path.join(kat, "plan.dxf")
            doc.saveas(plik)
            p = Projekt(Config())
            p.wczytaj(plik)
            p.zastosuj_stan()
            p.planuj()
            wy = os.path.join(kat, "plan_numeracja.dxf")
            p.zapisz_dxf(wy)
            wynik = ezdxf.readfile(wy)
            lay = wynik.layers.get("WT_uwagi")
            self.assertEqual((lay.dxf.plot, lay.dxf.lineweight), (0, 100))
            kolory = sorted(k.dxf.color for k in wynik.modelspace().query('CIRCLE[layer=="WT_uwagi"]'))
            self.assertEqual(kolory, sorted([p.KOLOR_SCALENIA, p.KOLOR_PRZESLA, p.KOLOR_PRZESLA_BLAD]))
            self.assertEqual(p.cfg.przeslo_ostrzezenie, 50.0)


if __name__ == "__main__":
    unittest.main()
