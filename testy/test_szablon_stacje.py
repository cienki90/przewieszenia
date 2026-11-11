"""Rysunki stałe: szablon ze stacjami innego projektu (np. dołączony, przykładowy) + plik PZT -
rysunki mają powstać dla stacji z pliku PZT, a nie dla stacji szablonu."""
import os
import sys
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import orientacje, zasoby  # noqa: E402

PZT = os.path.join(KORZEN, "przyklady", "pw_final2 - ponumerowane - PZT.dxf")


class TestSzablonStacje(unittest.TestCase):
    def test_stacje_z_pliku_gdy_szablon_ma_cudze(self):
        szablon = orientacje.DxfDocument.load(zasoby.szablon_orientacji_dxf())
        cudze = {s.designation for s in orientacje.find_stations(szablon)}
        z_pliku = {s.designation for s in orientacje.find_stations(orientacje.DxfDocument.load(PZT))
                   if s.zone_poly is not None}
        self.assertTrue(cudze and z_pliku and not (cudze & z_pliku))       # przykładowy szablon: inne stacje
        log = []
        wynik = orientacje.wstaw_stacje_z_pliku(szablon, PZT, log=log.append)
        stacje = orientacje.find_stations(wynik)
        self.assertEqual({s.designation for s in stacje}, z_pliku)
        self.assertTrue(all(s.zone_poly is not None for s in stacje))
        self.assertTrue(any("stacje innego projektu" in x for x in log), log)

        # szablon z TYMI SAMYMI stacjami co plik - zostaje bez zmian, jak dotąd
        log.clear()
        self.assertIs(orientacje.wstaw_stacje_z_pliku(wynik, PZT, log=log.append), wynik)
        self.assertTrue(any("Szablon ma własne stacje" in x for x in log), log)
        self.assertFalse(any("UWAGA" in x for x in log), log)


if __name__ == "__main__":
    unittest.main()
