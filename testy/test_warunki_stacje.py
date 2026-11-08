"""Moduł „Warunki techniczne”: obrys !trafo bez numeru stacji bierze opis stacji spoza obrysu do 50 m."""
import os
import sys
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)


class TestStacjePozaObrysem(unittest.TestCase):
    def test_numer_stacji_do_50_m_z_ostrzezeniem(self):
        import ezdxf

        from generator.warunki import reader
        from generator.warunki.config import Config

        doc = ezdxf.new()
        msp = doc.modelspace()
        for x0 in (0, 300):
            msp.add_lwpolyline([(x0, 0), (x0 + 100, 0), (x0 + 100, 100), (x0, 100)], close=True,
                               dxfattribs={"layer": "!trafo"})
        msp.add_text("STACJA TRAFO 05-0001", dxfattribs={"layer": "!trafo_opis", "insert": (130, 50)})   # 30 m
        msp.add_text("STACJA TRAFO 05-0002", dxfattribs={"layer": "!trafo_opis", "insert": (460, 50)})   # 60 m
        strefy, ostrz = reader.wczytaj_stacje_trafo(doc, Config())
        nazwy = sorted(s.nazwa for s in strefy)
        self.assertIn("05-0001", nazwy)
        self.assertNotIn("05-0002", nazwy)
        self.assertTrue(any("30.0 m poza obrysem (szukano do 50 m)" in o for o in ostrz), ostrz)
        self.assertTrue(any("Stacja 05-0002 leży poza obrysami" in o for o in ostrz), ostrz)

    def test_opis_stacji_na_warstwie_0(self):
        """Multileader „STACJA TRAFO 09-0395” na warstwie „0” (jak w planie Osieck) też jest opisem stacji."""
        import ezdxf
        from ezdxf.math import Vec2
        from ezdxf.render import mleader

        from generator.warunki import reader
        from generator.warunki.config import Config

        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True, dxfattribs={"layer": "!trafo"})
        ml = msp.add_multileader_mtext("Standard", dxfattribs={"layer": "0"})
        ml.set_content("STACJA TRAFO\\P09-0395")
        ml.add_leader_line(mleader.ConnectionSide.left, [Vec2(50, 50)])
        ml.build(insert=Vec2(60, 60))
        strefy, ostrz = reader.wczytaj_stacje_trafo(doc, Config())
        self.assertEqual([s.nazwa for s in strefy], ["09-0395"])
        self.assertEqual(ostrz, [])


if __name__ == "__main__":
    unittest.main()
