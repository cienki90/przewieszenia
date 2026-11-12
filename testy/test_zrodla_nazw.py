"""Nazwy miejscowości w Rysunkach stałych / PZT bez pliku WT: pierwsze źródło to GUGiK UUG
(te same nazwy co w Generatorze WT), Nominatim dopiero gdy UUG nie znajdzie adresu. Bez internetu -
odpowiedzi usług są podstawione."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import orientacje  # noqa: E402

UUG = {"results": {"1": {"city": "Osieck", "street": "ks. Olszewskiego", "number": "3",
                         "jednostka": "{Polska,mazowieckie,otwocki,Osieck}", "distance": "176.2"}}}
NOMINATIM = {"address": {"village": "Rudnik", "municipality": "gmina Osieck", "county": "powiat otwocki",
                         "state": "województwo mazowieckie"}}


class TestZrodlaNazw(unittest.TestCase):
    def setUp(self):
        self.kat = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.kat, True)
        self.pytane = []

    def _resolver(self, uug):
        r = orientacje.PlaceResolver(Path(self.kat), verify=False, log=lambda *_: None)

        def get(key, url, data=None):
            self.pytane.append(key)
            return json.dumps(uug if key == "uug" else NOMINATIM).encode("utf-8")

        r._get = get
        return r

    def test_uug_pierwszy_i_wystarcza(self):
        self.assertEqual(orientacje.DEFAULT_PLACE_ORDER[:2], ("uug", "nominatim"))
        w = self._resolver(UUG).resolve(51.96, 21.44, 7528000.0, 5759000.0, 7)
        self.assertEqual((w["miejscowosc"], w["gmina"], w["powiat"], w["wojewodztwo"]),
                         ("Osieck", "Osieck", "otwocki", "mazowieckie"))
        self.assertEqual(w["zrodlo"], orientacje.PLACE_SOURCE_NAMES["uug"])
        self.assertEqual(self.pytane, ["uug"])                      # Nominatim nie jest pytany

    def test_bez_adresu_w_poblizu_pyta_nominatim(self):
        w = self._resolver({"results": {}}).resolve(51.96, 21.44, 7528000.0, 5759000.0, 7)
        self.assertEqual(w["miejscowosc"], "Rudnik")
        self.assertEqual(w["zrodlo"], orientacje.PLACE_SOURCE_NAMES["nominatim"])
        self.assertEqual(self.pytane, ["uug", "nominatim"])


if __name__ == "__main__":
    unittest.main()
