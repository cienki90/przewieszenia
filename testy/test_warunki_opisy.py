"""Moduł „Warunki techniczne”: rodzaj i typ słupa także z opisu w bloku wstawionym przy słupie."""
import os
import sys
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)


class TestOpisyWBlokach(unittest.TestCase):
    def test_opis_z_bloku_i_pierwszenstwo_multileadera(self):
        import ezdxf
        from ezdxf.math import Vec2
        from ezdxf.render import mleader

        from generator.warunki import reader
        from generator.warunki.config import Config

        def opis(uklad, tekst, grot):
            ml = uklad.add_multileader_mtext("Standard")
            ml.set_content(tekst)
            ml.add_leader_line(mleader.ConnectionSide.left, [Vec2(grot)])
            ml.build(insert=Vec2(0, 8))

        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (40, 0), (80, 0)], dxfattribs={"layer": "!tele"})
        opis(doc.blocks.new("q"), "słup nN\\PP-10/ZN", (0, 0))
        msp.add_blockref("q", (0, 0), dxfattribs={"rotation": 37})
        msp.add_blockref("q", (40, 0))
        opis(msp, "słup SN\\PRPK-10,5/10/E", (40, 0))

        cfg = Config()
        slupy, _ = reader.wczytaj_slupy(doc, cfg)
        self.assertEqual(reader.przypisz_opisy_slupow(doc, slupy, cfg), 2)
        wg_x = {s.x: s for s in slupy}
        self.assertEqual((wg_x[0].rodzaj_slupa, wg_x[0].typ_slupa), ("nN", "P-10/ZN"))
        self.assertEqual((wg_x[40].rodzaj_slupa, wg_x[40].typ_slupa), ("SN", "RPK-10,5/10/E"))
        self.assertIsNone(wg_x[80].typ_slupa)


if __name__ == "__main__":
    unittest.main()
