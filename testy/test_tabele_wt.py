"""Odczyt wszystkich rodzajów tabel WT: każdy układ ma dać te same słupy co plan."""
import os
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import orientacje, pzt, wt  # noqa: E402

PLAN = os.path.join(KORZEN, "przyklady", "przewieszenia plan.dxf")
NAGLOWEK_ROZBUDOWANA = ["L.p.", "Rejon Energetyczny", "Gmina", "Miejscowość", "Lokalizacja, ulica",
                        "Współrzędne w układzie 2000", None, "Numer inwentarzowy linii",
                        "Numer stacji transformatorowej", "Rodzaj słupa nN/SN\n"]
NAGLOWEK_PROJEKTOWA = ["Lp", "Miejscowość ", "Lokalizacja, ulica", "Gmina", "Stacja Transormatorowa", "Nr słupa",
                       "Współrzedne GPS dla elementu", None, "Liczba Podwieszonych kabli"]


def dms(st):
    d = int(st)
    m = int((st - d) * 60)
    return f"{d}°{m:02d}'{(st - d - m / 60) * 3600:06.3f}\""


class TestTabeleWT(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        we = pzt.wczytaj(PLAN, wzorzec=False)
        cls.slupy = sorted({(round(x, 2), round(y, 2)) for t in we.trasy for x, y in t})
        cls.tmp = tempfile.TemporaryDirectory()
        cls.strefa = orientacje.pl2000_zone_from_easting(cls.slupy[0][0])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _zapisz(self, nazwa, arkusze):
        """arkusze: {nazwa arkusza: wiersze} -> plik .xlsx."""
        from openpyxl import Workbook
        wb = Workbook()
        wb.remove(wb.active)
        for n, wiersze in arkusze.items():
            ws = wb.create_sheet(n)
            for w in wiersze:
                ws.append(w)
        p = os.path.join(self.tmp.name, nazwa)
        wb.save(p)
        return p

    def _sprawdz_zgodnosc(self, plik):
        p = wt.pokrycie_wt(PLAN, plik)
        self.assertEqual(p.dopasowane, p.slupy_planu)
        self.assertEqual(p.wt_poza, [])
        self.assertFalse(p.niezgodne)

    def test_rozbudowana_wspolrzedne_jako_tekst(self):
        wiersze = [[":19/RE-5/KŚ/2022"], ["Wykaz słupów wykorzystywanych"], NAGLOWEK_ROZBUDOWANA]
        wiersze += [[i, "Mińsk", "Gmina", "Wieś", "-", f"{y:.2f}", f"{x:.2f}", None, "05-0729", "nN"]
                    for i, (x, y) in enumerate(self.slupy, 1)]
        wiersze += [[], ["Wykaz dotyczy łącznie…"]]
        p = self._zapisz("rozbudowana.xlsx", {"Zał.1": wiersze, "Arkusz1": [[0, 1, 2], [1, 52.23, 21.25]]})
        s = wt.wczytaj_wt(p)
        self.assertEqual(len(s), len(self.slupy))
        self.assertEqual((s[1].nr, s[1].miejscowosc, s[1].ulica), ("2", "Wieś", ""))
        self._sprawdz_zgodnosc(p)

    def test_tekst_z_przecinkiem_i_spacjami(self):
        wiersze = [["Nr słupa", "Miejscowość", "X", "Y"]]
        wiersze += [[i, "Wieś", f"{y:_.2f}".replace("_", " ").replace(".", ","), f"{x:.2f}".replace(".", ",")]
                    for i, (x, y) in enumerate(self.slupy, 1)]
        self._sprawdz_zgodnosc(self._zapisz("tekst.xlsx", {"WT": wiersze}))

    def _gps(self):
        return [orientacje.pl2000_to_wgs84(x, y, self.strefa) for x, y in self.slupy]   # (lat, lon)

    def test_tabela_projektowa_wgs84(self):
        wiersze = [NAGLOWEK_PROJEKTOWA]
        wiersze += [[i, "Wieś", "-", "Gmina", "05-0729", i, round(lat, 7), round(lon, 7), 1]
                    for i, (lat, lon) in enumerate(self._gps(), 1)]
        self._sprawdz_zgodnosc(self._zapisz("projektowa.xlsx", {"Arkusz1": wiersze}))

    def test_wgs84_stopnie_minuty_sekundy(self):
        wiersze = [["Lp", "Miejscowość", "Szerokość", "Długość"]]
        wiersze += [[i, "Wieś", dms(lat) + " N", dms(lon) + " E"] for i, (lat, lon) in enumerate(self._gps(), 1)]
        self._sprawdz_zgodnosc(self._zapisz("dms.xlsx", {"Arkusz1": wiersze}))

    def test_skoroszyt_z_wieloma_numerami_wt(self):
        pol = len(self.slupy) // 2
        wiersz = lambda i, x, y: [i, "RE Mińsk", "Gmina", "Wieś", "-", y, x, "05-0342"]  # noqa: E731
        nagl = ["L.p.", "Rejon Energetyczny", "Gmina", "Miejscowość", "Ulica", "Numer słupa w terenie"]
        a = [nagl] + [wiersz(i, x, y) for i, (x, y) in enumerate(self.slupy[:pol], 1)]
        b = [nagl] + [wiersz(i, x, y) for i, (x, y) in enumerate(self.slupy[pol:], 1)]
        inne = [nagl] + [wiersz(i, x + 9000, y) for i, (x, y) in enumerate(self.slupy[:20], 1)]
        p = self._zapisz("zeszyt.xlsx", {"87 RE-5 KŚ 2026": a, "88 RE-5 KŚ 2026": b, "90 RE-5 KŚ 2026": inne})
        self.assertEqual(len(wt.wczytaj_wt(p)), len(self.slupy) + 20)      # wszystkie arkusze, nie tylko pierwszy
        pok = wt.pokrycie_wt(PLAN, p)
        self.assertEqual(pok.pominiete_arkusze, ["90 RE-5 KŚ 2026"])       # inne zadanie nie psuje wyniku
        self.assertEqual(pok.slupy_wt, len(self.slupy))
        self.assertFalse(pok.niezgodne)
        self.assertIn("pominięte arkusze", pok.opis())

    def test_ten_sam_slup_w_dwoch_arkuszach_raz(self):
        wiersze = [["Lp", "Miejscowość", "X", "Y"]] + [[i, "Wieś", y, x] for i, (x, y) in enumerate(self.slupy, 1)]
        p = self._zapisz("dubel.xlsx", {"A": wiersze, "B": wiersze})
        self.assertEqual(len(wt.wczytaj_wt(p)), len(self.slupy))

    def test_lista_wspolrzednych_bez_miejscowosci(self):
        nagl = ["Lp.", "Nr polilinii", "X (PL-2000) [m]\npółnoc", "Y (PL-2000) [m]\nwschód"]
        warunki = [nagl] + [[i, 1, y, x] for i, (x, y) in enumerate(self.slupy, 1)] + [[None, None, None, None, 14462.8]]
        trasy = [nagl] + [[i, 1, y + 500, x] for i, (x, y) in enumerate(self.slupy, 1)]
        p = self._zapisz("lista.xlsx", {"Info": [["Arkusz", "Plik"]], "Trasy zaprojektowane": trasy,
                                        "Złożone warunki": warunki})
        s = wt.wczytaj_wt(p)
        self.assertEqual(len(s), len(self.slupy))                          # tylko arkusz warunków
        self.assertEqual(s[0].arkusz, "Złożone warunki")
        self._sprawdz_zgodnosc(p)
        mapa, ostrz = wt.miejscowosci_stacji_z_wt(PLAN, p)                 # nazwy trzeba ustalić inaczej
        self.assertEqual(mapa, {})
        self.assertIn("nie ma miejscowości", ostrz[0])

    def test_slup_bez_miejscowosci_liczy_sie_w_zakresie(self):
        wiersze = [["Lp", "Miejscowość", "X", "Y"]]
        wiersze += [[i, "-" if i % 2 else "Wieś", y, x] for i, (x, y) in enumerate(self.slupy, 1)]
        p = self._zapisz("puste.xlsx", {"WT": wiersze})
        self.assertEqual(len(wt.wczytaj_wt(p)), len(self.slupy))
        self._sprawdz_zgodnosc(p)
        self.assertNotIn("", {m for ms in wt.miejscowosci_stacji_z_wt(PLAN, p)[0].values() for m in ms})

    def test_uproszczona_xls_z_przykladow(self):
        s = wt.wczytaj_wt(os.path.join(KORZEN, "przyklady", "WT_uproszczona.xls"))
        self.assertGreater(len(s), 0)
        self.assertTrue(all(s_.miejscowosc for s_ in s))

    def test_inna_tabela_to_nie_wt(self):
        p = self._zapisz("zestawienie.xlsx", {"Arkusz1": [["Plik", "trafo", "miejscowosc", "wt"],
                                                          [841, "05-0841", "Rysie", "69/RE-5/KŚ/2026"]]})
        with self.assertRaises(ValueError):
            wt.wczytaj_wt(p)


if __name__ == "__main__":
    unittest.main()
