"""Nazwa firmy (inwestora) ta sama we wszystkich etapach: odczyt z tabelki rysunku i z dokumentu
Word, porównanie odporne na zapis („Sp z.o.o.” = „sp. z o. o.”), pytanie przed uruchomieniem modułu."""
import os
import shutil
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)

from generator import firma, pipeline  # noqa: E402

try:
    import docx
    import ezdxf
except ImportError:
    docx = ezdxf = None


@unittest.skipIf(docx is None, "brak python-docx / ezdxf")
class TestFirma(unittest.TestCase):
    def setUp(self):
        self.kat = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.kat, True)

    def _rysunek(self, nazwa_pliku, firma_txt, w_bloku=True):
        doc = ezdxf.new()
        cel = doc.blocks.new("tabelka") if w_bloku else doc.layout("Layout1")
        for tekst, xy in (("INWESTOR", (0, 10)), (firma_txt + "\\Pul. Testowa 1, 00-001 Miasto", (0, 5.6)),
                          ("Obiekt:", (-39, -2.6)), ("Numer stacji trafo:", (-9, -14.8)), ("05-0001", (-8, -20))):
            cel.add_mtext(tekst, dxfattribs={"insert": xy, "char_height": 2.0})
        if w_bloku:
            doc.layout("Layout1").add_blockref("tabelka", (350, 50))
        doc.modelspace().add_mtext("STACJA TRAFO\\P05-0001", dxfattribs={"insert": (5, 5), "char_height": 2.0})
        p = os.path.join(self.kat, nazwa_pliku)
        doc.saveas(p)
        return p

    def _dokument(self, nazwa_pliku, firma_txt, wt=False):
        d = docx.Document()
        if wt:
            t = d.add_table(rows=2, cols=2)
            t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Pełna nazwa", firma_txt
            t.rows[1].cells[0].text, t.rows[1].cells[1].text = "NIP", "1234567890"
        else:
            d.add_paragraph("2. Inwestor:\t3")                    # spis treści - to nie nazwa
            d.add_paragraph("2. Inwestor i zleceniodawca\t7")
            d.add_paragraph("Inwestor:")
            d.add_paragraph("")
            d.add_paragraph(firma_txt)
            d.add_paragraph("ul. Testowa 1")
        p = os.path.join(self.kat, nazwa_pliku)
        d.save(p)
        return p

    def test_klucz(self):
        self.assertEqual(firma.klucz("InterWan Sp z.o.o."), firma.klucz("InterWan sp. z o. o."))
        self.assertEqual(firma.klucz("Interwan Spółka z ograniczoną odpowiedzialnością"), firma.klucz("INTERWAN SP. Z O.O."))
        self.assertNotEqual(firma.klucz("InterWan sp. z o. o."), firma.klucz("24IT Media sp. z o. o."))

    def test_odczyt_z_rysunku_i_dokumentu(self):
        self.assertEqual(firma.nazwy_z_pliku(self._rysunek("a.dxf", "Firma A sp. z o. o.")), ["Firma A sp. z o. o."])
        self.assertEqual(firma.nazwy_z_pliku(self._rysunek("b.dxf", "Firma A sp. z o. o.", w_bloku=False)),
                         ["Firma A sp. z o. o."])
        self.assertEqual(firma.nazwy_z_pliku(self._dokument("o.docx", "Firma A Sp z.o.o.")), ["Firma A Sp z.o.o."])
        self.assertEqual(firma.nazwy_z_pliku(self._dokument("wt.docx", "Firma A", wt=True)), ["Firma A"])
        # rysunek bez tabelki i plik, którego nie ma
        doc = ezdxf.new()
        doc.modelspace().add_mtext("Inwestor zastępczy", dxfattribs={"insert": (0, 0)})
        pusty = os.path.join(self.kat, "pusty.dxf")
        doc.saveas(pusty)
        self.assertEqual(firma.nazwy_z_pliku(pusty), [])
        self.assertIsNone(firma.nazwy_z_pliku(os.path.join(self.kat, "nie ma.dxf")))

    def test_raport(self):
        a = self._rysunek("plan.dxf", "Firma A sp. z o. o.")
        b = self._dokument("opis.docx", "Firma A Sp z.o.o.")
        c = self._dokument("ppw.docx", "Inna Firma S.A.")
        zgodne, _ = firma.raport(firma.zbierz([("Plan", a), ("Opisy - szablon", b), ("Zestawienie", "x.xlsx")]))
        self.assertTrue(zgodne)
        zgodne, linie = firma.raport(firma.zbierz([("Plan", a), ("Opisy - szablon", b), ("PPW - szablon", c)]))
        self.assertFalse(zgodne)
        tekst = "\n".join(linie)
        self.assertIn("„Firma A sp. z o. o.”", tekst)
        self.assertIn("„Inna Firma S.A.”", tekst)
        self.assertIn("PPW - szablon: ppw.docx", tekst)

    def test_ukryta_nazwa_w_skoroszycie(self):
        """Zestawienie i obliczenia dostają nazwę firmy z planu jako właściwość dokumentu - nie ma jej
        w komórkach, a sprawdzanie nazwy firmy ją odczytuje."""
        import openpyxl
        plan = os.path.join(KORZEN, "przyklady", "przewieszenia plan.dxf")
        kopia = shutil.copy2(plan, os.path.join(self.kat, "plan.dxf"))
        firma_planu = firma.firma_z_plikow(kopia)
        wynik = pipeline.uruchom(pipeline.Opcje(plan=kopia, katalog=self.kat, kroki=("zestawienie", "obliczenia"),
                                                eksport_dwg=False, seed=1, log=lambda *_: None))
        self.assertTrue(all(k.ok for k in wynik.kroki))
        for k in wynik.kroki:
            self.assertEqual(firma.nazwy_z_pliku(k.wyjscie), [firma_planu] if firma_planu else [])
        # ręcznie: zapis, nadpisanie, znaki specjalne; komórki bez zmian i bez nazwy firmy
        p = os.path.join(self.kat, "tabela.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append(["Lp", "Nr słupa"])
        wb.save(p)
        self.assertEqual(firma.nazwy_z_pliku(p), [])
        self.assertTrue(firma.oznacz_xlsx(p, "Firma <A> & Syn sp. z o. o.\nul. Testowa 1"))
        self.assertEqual(firma.nazwy_z_xlsx(p), ["Firma <A> & Syn sp. z o. o."])
        self.assertTrue(firma.oznacz_xlsx(p, "Inna Firma S.A."))
        self.assertEqual(firma.nazwy_z_xlsx(p), ["Inna Firma S.A."])
        wb = openpyxl.load_workbook(p)
        komorki = [c for ws in wb.worksheets for r in ws.iter_rows(values_only=True) for c in r if c]
        self.assertEqual(komorki, ["Lp", "Nr słupa"])
        self.assertFalse(firma.oznacz_xlsx(p, ""))
        self.assertFalse(firma.oznacz_xlsx(os.path.join(self.kat, "nie ma.xlsx"), "X sp."))
        # skoroszyt z inną firmą niż szablon opisu - pytanie przed modułem
        szablon = self._dokument("szablon3.docx", "Firma A sp. z o. o.")
        pytania = []
        op = pipeline.Opcje(plan="", kroki=("opisy",), opisy_szablon=szablon, opisy_obliczenia=p,
                            log=lambda *_: None, pytaj=lambda t, x: pytania.append(x) or False)
        self.assertIn("różne nazwy firmy", pipeline._sprawdz_firme(op))
        self.assertIn("Opisy techniczne - obliczenia: tabela.xlsx", pytania[0])

    def test_pytanie_przed_modulem(self):
        szablon = self._dokument("szablon.docx", "Inna Firma S.A.")
        plan = self._rysunek("plan.dxf", "Firma A sp. z o. o.")
        pytania, log = [], []

        def opcje(odp):
            return pipeline.Opcje(plan=os.path.join(self.kat, "zest.xlsx"), katalog=self.kat, kroki=("opisy",),
                                  opisy_szablon=szablon, opisy_zestawienie=os.path.join(self.kat, "zest.xlsx"),
                                  firma_pliki=(("Arkusze PZT - Plik planu", plan),), log=log.append,
                                  pytaj=lambda tytul, tekst: pytania.append(tekst) or odp)

        wynik = pipeline.uruchom(opcje(False))                      # „Nie” - moduł nie rusza
        self.assertEqual([(k.nazwa, k.ok) for k in wynik.kroki], [("opisy", False)])
        self.assertIn("różne nazwy firmy", wynik.kroki[0].blad)
        self.assertIn("Inna Firma S.A.", pytania[0])
        self.assertIn("Firma A sp. z o. o.", pytania[0])
        self.assertFalse(os.path.exists(os.path.join(self.kat, "opisy")))
        self.assertIsNone(pipeline._sprawdz_firme(opcje(True)))     # „Tak” - praca idzie dalej
        # ta sama firma w obu plikach - bez pytania
        pytania.clear()
        zgodny = self._dokument("szablon2.docx", "FIRMA A SP. Z O.O.")
        op = pipeline.Opcje(plan="", kroki=("opisy",), opisy_szablon=zgodny, firma_pliki=(("Plan", plan),),
                            log=log.append, pytaj=lambda *_: pytania.append(1) or False)
        self.assertIsNone(pipeline._sprawdz_firme(op))
        self.assertEqual(pytania, [])
        self.assertTrue(any("Nazwa firmy zgodna w 2 plikach" in str(x) for x in log), log)
        # kroki bez plików z nazwą firmy (zestawienie, obliczenia) - kontrola się nie włącza
        op = pipeline.Opcje(plan=plan, kroki=("zestawienie",), firma_pliki=(("Opisy", szablon), ("Plan", plan)),
                            log=log.append, pytaj=lambda *_: pytania.append(1) or False)
        self.assertIsNone(pipeline._sprawdz_firme(op))
        self.assertEqual(pytania, [])


if __name__ == "__main__":
    unittest.main()
