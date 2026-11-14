"""Logika okna: podpinanie wyników między modułami, pliki z innego projektu, plik PZT Rysunków stałych,
pytanie z wątku pracy, okno „Stan projektu”. Ustawienia programu idą do folderu tymczasowego."""
import os
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest import mock

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KORZEN)


def _plik(*czesci):
    p = os.path.join(*czesci)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("0\nEOF\n")
    return p


class TestOkno(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["LOCALAPPDATA"] = os.path.join(cls.tmp.name, "appdata")   # nie ruszaj ustawień użytkownika
        try:
            cls.root = tk.Tk()
        except tk.TclError as ex:
            raise unittest.SkipTest(f"tkinter niedostępny: {ex}") from None
        cls.root.withdraw()
        from generator import gui
        cls.gui = gui
        cls.app = gui.Aplikacja(cls.root)
        k = cls.tmp.name
        cls.A, cls.B = os.path.join(k, "A"), os.path.join(k, "B")
        cls.szablon_a = _plik(cls.A, "rysunki stałe", "szablon.dxf")
        cls.plan_a = _plik(cls.A, "plan.dxf")
        cls.num_a = _plik(cls.A, "!ponumerowany plan.dxf")
        cls.pzt_a_stary = _plik(cls.A, "sub", "inny - PZT.dxf")
        os.utime(cls.pzt_a_stary, (1, 1))                              # starszy od „!PZT plan.dxf”
        cls.pzt_a = _plik(cls.A, "!PZT plan.dxf")
        cls.plan_b = _plik(cls.B, "plan B.dxf")
        cls.pzt_b = _plik(cls.B, "!PZT plan B.dxf")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        cls.tmp.cleanup()

    def setUp(self):
        self.app._nowy_projekt(self.A)                                 # czysty projekt w folderze A
        self.root.update()

    def test_podpinanie_wynikow(self):
        app = self.app
        app.we["przewieszenia"].set(self.plan_a)                       # ręcznie, w tym projekcie - zostaje
        app.we["zestawienie"].set(self.plan_b)                         # ręcznie, z innego projektu - zastąpiony
        krok = self.gui.pipeline.WynikKroku("numeracja", ok=True, wyjscie=self.num_a)
        app._podepnij_wyniki([krok])
        self.assertEqual(app.we["przewieszenia"].get(), self.plan_a)
        self.assertEqual(os.path.normcase(app.we["zestawienie"].get()), os.path.normcase(self.num_a))
        self.assertEqual(os.path.normcase(app.we["pzt"].get()), os.path.normcase(self.num_a))   # było puste

    def test_odpinanie_plikow_innego_projektu(self):
        app = self.app
        app.we["obliczenia"].set(self.plan_b)
        app._podpiete[str(app.we["obliczenia"])] = self.plan_b        # wpisany przez program
        app.we["numeracja"].set(self.plan_b)                           # wybrany ręcznie - zostaje
        app._odepnij_obce()
        self.assertEqual(app.we["obliczenia"].get(), "")
        self.assertEqual(app.we["numeracja"].get(), self.plan_b)

    def test_plik_pzt_rysunkow_stalych(self):
        app = self.app
        app.we["orientacje"].set(self.szablon_a)
        app.orient_zasiegi.set(self.pzt_b)                             # z innego projektu
        app._podepnij_pzt_orient()
        self.assertEqual(os.path.normcase(app.orient_zasiegi.get()), os.path.normcase(self.pzt_a))
        app.orient_zasiegi.set(self.pzt_a_stary)                       # ręczny wybór w tym projekcie
        app._podepnij_pzt_orient()
        self.assertEqual(app.orient_zasiegi.get(), self.pzt_a_stary)

    def test_pytanie_z_watku(self):
        app = self.app
        app._watek = None
        wynik = {}
        t = threading.Thread(target=lambda: wynik.setdefault("odp", app._pytaj_z_watku("Tytuł", "Treść")))
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=False) as pyt:
            t.start()
            koniec = time.time() + 5
            while app._kolejka.empty() and time.time() < koniec:
                time.sleep(0.01)
            app._pompuj()                                              # wątek główny odpowiada na pytanie
            t.join(5)
        self.assertFalse(t.is_alive())
        self.assertIs(wynik.get("odp"), False)
        pyt.assert_called_once()

    def test_powod_bledu_w_komunikacie(self):
        """Po nieudanym kroku okno komunikatu podaje powód (np. opisy wstrzymane przez nośność)."""
        from generator import pipeline
        blad = "Opisy nie zostały utworzone — obliczenia nośności mają błędy (3 poz. w 1 stacji)."
        wynik = pipeline.Wynik([pipeline.WynikKroku("opisy", ok=False, blad=blad, raport="szczegóły")])
        app = self.app
        with mock.patch.object(app, "_zapisz_projekt"), mock.patch.object(app, "_zapisz_dziennik", return_value=None), \
                mock.patch.object(app, "_odswiez_stan_projektu"), \
                mock.patch.object(self.gui.messagebox, "showwarning") as okno:
            app._zakoncz(wynik)
        self.assertIn("• opisy: " + blad, okno.call_args.args[1])
        self.assertEqual(self.gui._skroc("x" * 500, 300), "x" * 299 + "…")

    def test_otworz_folder_tam_gdzie_powstal_wynik(self):
        """Opisy i PPW trafiają do folderu szablonu, a nie obok zestawienia z Rysunków stałych -
        „Otwórz folder z wynikami” ma otwierać folder wyniku."""
        from generator import pipeline
        app = self.app
        opisy = os.path.join(self.A, "opisy", "opisy")
        os.makedirs(opisy, exist_ok=True)
        ppw = _plik(self.A, "opisy", "PPW.docx")
        for wyjscie, oczekiwany in ((opisy, opisy), (ppw, os.path.dirname(ppw))):
            app._ostatni_katalog = os.path.join(self.A, "rysunki stałe")       # folder pliku wejściowego
            wynik = pipeline.Wynik([pipeline.WynikKroku("opisy", ok=True, wyjscie=wyjscie)])
            with mock.patch.object(app, "_zapisz_projekt"), mock.patch.object(app, "_zapisz_dziennik", return_value=None), \
                    mock.patch.object(app, "_odswiez_stan_projektu"), mock.patch.object(app, "_podepnij_wyniki"), \
                    mock.patch.object(self.gui.messagebox, "askyesno", return_value=False) as pyt:
                app._zakoncz(wynik)
            self.assertEqual(os.path.normcase(app._ostatni_katalog), os.path.normcase(oczekiwany))
            self.assertIn(oczekiwany, pyt.call_args.args[1])

    def test_pliki_wg_ukladu_projektu(self):
        """Układ jak w przykładowym projekcie: puste pola wypełniają się plikami z właściwych podfolderów,
        a wypełnione ręcznie zostają; okno wyboru otwiera się w podfolderze z układu."""
        from generator import uklad_projektu as uklad
        P = os.path.join(self.tmp.name, "Projekt układu")
        pliki = {"PW Test.dwg": None, "!ponumerowany PW Test.dwg": None, "!PZT PW Test.dwg": None,
                 "DaneWektorowe_G.1.dwg": None, "warunki test_numeracja_uproszczona.xls": None,
                 "zestawienie PW Test.xlsx": None, "Obliczenia - zestawienie PW Test.xlsx": None,
                 os.path.join("opisy", "szablon.docx"): None, os.path.join("opisy", "PPW miński szablon.docx"): None,
                 os.path.join("rysunki stałe", "szablon.dwg"): None,
                 os.path.join("rysunki stałe", "rysunki stałe", "zestawienie_stacji.xlsx"): None}
        for n in pliki:
            _plik(P, n)
        app = self.app
        app._nowy_projekt(P)
        self.root.update()
        oczekiwane = {"plik_numeracja": "PW Test.dwg", "plik_pzt": "!ponumerowany PW Test.dwg",
                      "plik_przewieszenia": "!ponumerowany PW Test.dwg", "orient_zasiegi": "!PZT PW Test.dwg",
                      "plik_orientacje": os.path.join("rysunki stałe", "szablon.dwg"),
                      "wt_plik": "warunki test_numeracja_uproszczona.xls",
                      "opisy_szablon": os.path.join("opisy", "szablon.docx"),
                      "ppw_szablon": os.path.join("opisy", "PPW miński szablon.docx"),
                      "opisy_zestawienie": os.path.join("rysunki stałe", "rysunki stałe", "zestawienie_stacji.xlsx"),
                      "opisy_obliczenia": "Obliczenia - zestawienie PW Test.xlsx",
                      "ppw_zestawienie": "zestawienie PW Test.xlsx", "ppw_renumer_dxf": "!PZT PW Test.dwg"}
        pola = app._pola_projektu()
        for k, rel in oczekiwane.items():
            self.assertEqual(os.path.normcase(pola[k].get()), os.path.normcase(os.path.join(P, rel)), k)
        self.assertEqual(pola["pzt_wzorzec"].get(), "")
        self.assertEqual(os.path.normcase(uklad.folder_pola(P, "opisy_szablon")),
                         os.path.normcase(os.path.join(P, "opisy")))
        # ręcznie wybrany plik nie jest nadpisywany
        reczny = _plik(P, "inny szablon.docx")
        app.opisy_szablon.set(reczny)
        app._podpiete.pop(str(app.opisy_szablon), None)
        app._uzupelnij_z_ukladu()
        self.assertEqual(app.opisy_szablon.get(), reczny)
        # okno wyboru: folder z układu i podpowiedziany plik
        app.ppw_szablon.set("")
        with mock.patch.object(self.gui.filedialog, "askopenfilename", return_value="") as okno:
            app._wybierz_wg_ukladu(app.ppw_szablon, "t", self.gui.DOCX_TYPY)
        self.assertEqual(os.path.normcase(okno.call_args.kwargs["initialdir"]), os.path.normcase(os.path.join(P, "opisy")))
        self.assertEqual(okno.call_args.kwargs["initialfile"], "PPW miński szablon.docx")

    def test_nazwa_firmy_w_plikach_modulow(self):
        """Okno zbiera rysunki i dokumenty ze wszystkich modułów (oraz pismo WT) i pokazuje rozbieżność."""
        try:
            import docx
            import ezdxf
        except ImportError:
            self.skipTest("brak python-docx / ezdxf")
        app = self.app

        def rysunek(sciezka, firma):
            doc = ezdxf.new()
            b = doc.blocks.new("tabelka")
            b.add_mtext("INWESTOR", dxfattribs={"insert": (0, 10), "char_height": 2.0})
            b.add_mtext(firma, dxfattribs={"insert": (0, 5.6), "char_height": 2.0})
            doc.layout("Layout1").add_blockref("tabelka", (350, 50))
            doc.saveas(sciezka)
            return sciezka

        def dokument(sciezka, firma):
            d = docx.Document()
            d.add_paragraph("Inwestor:")
            d.add_paragraph(firma)
            d.save(sciezka)
            return sciezka

        plan = rysunek(os.path.join(self.A, "plan firmy.dxf"), "Firma A sp. z o. o.")
        szablon = dokument(os.path.join(self.A, "szablon opisu.docx"), "Inna Firma S.A.")
        wt = _plik(self.A, "WT", "plan_rozbudowana.xlsx")
        pismo = dokument(os.path.join(self.A, "WT", "plan_pismo.docx"), "FIRMA A SP. Z O.O.")
        app.we["pzt"].set(plan)
        app.we["numeracja"].set(plan)
        app.opisy_szablon.set(szablon)
        app.wt_plik.set(wt)
        pliki = app._pliki_firmy()
        self.assertTrue({os.path.basename(p) for _o, p in pliki} >= {"plan firmy.dxf", "szablon opisu.docx",
                                                                     "plan_pismo.docx", "plan_rozbudowana.xlsx"})
        self.assertIn(("Generator WT - pismo", pismo), pliki)
        with mock.patch.object(self.gui.messagebox, "showwarning") as ostrz:
            app._pokaz_firme()
        tekst = ostrz.call_args.args[1]
        self.assertIn("RÓŻNE nazwy firmy", tekst)
        self.assertIn("„Inna Firma S.A.”", tekst)
        app.opisy_szablon.set(dokument(os.path.join(self.A, "szablon dobry.docx"), "Firma A Sp z.o.o."))
        with mock.patch.object(self.gui.messagebox, "showinfo") as info:
            app._pokaz_firme()
        self.assertIn("ta sama we wszystkich plikach", info.call_args.args[1])

    def test_stan_projektu(self):
        from generator import stan_projektu as sp
        app = self.app
        self.assertEqual(sp.stan_pola("", self.A, False)[1], "puste")
        self.assertEqual(sp.stan_pola(self.plan_a, self.A, True)[1], "ok")
        self.assertEqual(sp.stan_pola(self.plan_b, self.A, False)[1], "uwaga")
        self.assertEqual(sp.stan_pola(os.path.join(self.A, "nie ma.dxf"), self.A, False)[1], "blad")
        wyniki = sp.znajdz_wyniki(self.A)
        pzt = dict(wyniki["pzt"])["arkusze PZT"]
        self.assertEqual(os.path.normcase(pzt[0]), os.path.normcase(self.pzt_a))   # najnowszy pierwszy
        app.wt_plik.set(self.plan_b)
        okno = sp.OknoStanu(app)
        try:
            self.assertEqual(len(okno.drzewo.get_children()), len(app._pola_modulow()))
            self.assertEqual(len(okno._obce()), 1)                     # to samo pole WT w dwóch modułach
            with mock.patch.object(sp.messagebox, "askyesno", return_value=True):
                okno._wyczysc_obce()
            self.assertEqual(app.wt_plik.get(), "")
        finally:
            okno.destroy()


if __name__ == "__main__":
    unittest.main()
