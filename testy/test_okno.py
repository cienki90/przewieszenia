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
