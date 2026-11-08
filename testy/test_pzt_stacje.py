"""Arkusze PZT: opis „STACJA TRAFO <nr>” jest czytany także z warstwy innej niż „…trafo…”
(np. multileader wstawiony na warstwie „0”, jak w planie Osieck); inne teksty z tej warstwy nie."""
import os
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)


def _opis(msp, warstwa, tekst, grot):
    from ezdxf.math import Vec2
    from ezdxf.render import mleader
    ml = msp.add_multileader_mtext("Standard", dxfattribs={"layer": warstwa})
    ml.set_content(tekst)
    ml.add_leader_line(mleader.ConnectionSide.left, [Vec2(grot)])
    ml.build(insert=Vec2(grot[0] + 10, grot[1] + 10))


class TestStacjePzt(unittest.TestCase):
    def test_opisy_stacji_z_roznych_warstw(self):
        import ezdxf

        from generator import pzt

        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 50), (900, 50)], dxfattribs={"layer": "!tele"})
        for x0 in (0, 300, 600):
            msp.add_lwpolyline([(x0, 0), (x0 + 200, 0), (x0 + 200, 100), (x0, 100)], close=True,
                               dxfattribs={"layer": "!trafo"})
        _opis(msp, "_mm trafo", "STACJA TRAFO\\P09-0359", (100, 60))
        _opis(msp, "0", "STACJA TRAFO\\P09-0395", (400, 60))         # warstwa „0”
        _opis(msp, "0", "słup nN\\PP-10/ZN 0396", (450, 50))          # opis słupa - nie stacja
        _opis(msp, "legenda", "STACJA TRAFO", (700, 60))              # bez numeru - nie stacja
        with tempfile.TemporaryDirectory() as kat:
            plik = os.path.join(kat, "plan.dxf")
            doc.saveas(plik)
            we = pzt.wczytaj(plik, wzorzec=False)
        self.assertEqual(sorted(n for n, _ in we.stacje), ["09-0359", "09-0395"])
        grot = dict(we.stacje)["09-0395"]
        self.assertAlmostEqual(grot[0], 400, places=3)
        self.assertAlmostEqual(grot[1], 60, places=3)


if __name__ == "__main__":
    unittest.main()
