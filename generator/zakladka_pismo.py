"""Zakładka „Pismo zatwierdzające” - pismo uzgadniające kilka projektów naraz (po folderach projektów).

Tabela: jeden wiersz = jeden folder projektu, z danymi odczytanymi z projektu (miejscowości, stacje,
liczba słupów, numer WT). Podwójne kliknięcie komórki = poprawka ręczna; poprawiony numer WT
zapisuje się w pliku projektu („projekt GeneratorNN.json”), więc następnym razem już tam jest.
"""
from __future__ import annotations

import datetime
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import pismo_zatwierdzajace as pz

KOLUMNY = (("projekt", "Projekt", 170), ("miejscowosci", "Miejscowości (gminy)", 260), ("stacje", "Stacje", 150),
           ("slupy", "Słupy", 50), ("wt", "Nr WT", 120), ("uwagi", "Uwagi", 160))
EDYTOWALNE = ("miejscowosci", "stacje", "slupy", "wt")


class ZakladkaPismo:
    def __init__(self, app):
        self.app = app
        self.projekty: list[pz.Projekt] = []
        self.rejon = tk.StringVar(value=app.ust.get("pismo_rejon", ""))
        self.miejscowosc = tk.StringVar(value=app.ust.get("pismo_miejscowosc", ""))
        self.szablon = tk.StringVar(value=app.ust.get("pismo_szablon", ""))
        self.tabele = tk.BooleanVar(value=bool(app.ust.get("pismo_tabele", False)) and pz.tabele_dostepne())
        self._zbuduj()
        for f in app.ust.get("pismo_foldery") or []:
            if os.path.isdir(f):
                self._dodaj(f, zapisz=False)

    # ------------------------------------------------------------------ układ
    def _zbuduj(self):
        app = self.app
        f = app._strona("pismo", "Pismo zatwierdzające", "Pismo zatwierdzające (uzgodnienie projektów)",
                        "Jedno pismo dla kilku projektów: dla każdego wskazanego folderu projektu akapit "
                        "z miejscowościami i gminą (z Rysunków stałych), stacjami i liczbą słupów (z "
                        "zestawienia) oraz numerem WT (z opisów). Podwójne kliknięcie komórki pozwala ją "
                        "poprawić; numer WT zapamiętuje się w folderze projektu.")
        box = app._sekcja(f, "Projekty")
        ramka = ttk.Frame(box)
        ramka.pack(fill="x")
        self.tabela = ttk.Treeview(ramka, columns=[k for k, _t, _w in KOLUMNY], show="headings", height=8)
        for k, t, w in KOLUMNY:
            self.tabela.heading(k, text=t)
            self.tabela.column(k, width=w, stretch=k in ("miejscowosci", "uwagi"))
        self.tabela.pack(side="left", fill="x", expand=True)
        sb = ttk.Scrollbar(ramka, orient="vertical", command=self.tabela.yview)
        sb.pack(side="left", fill="y")
        self.tabela.configure(yscrollcommand=sb.set)
        self.tabela.bind("<Double-1>", self._edytuj)
        pr = ttk.Frame(box)
        pr.pack(fill="x", pady=(4, 0))
        ttk.Button(pr, text="Dodaj folder projektu…", command=self._wybierz).pack(side="left")
        ttk.Button(pr, text="Dodaj otwarty projekt", command=self._dodaj_otwarty).pack(side="left", padx=(6, 0))
        ttk.Button(pr, text="Usuń", command=self._usun).pack(side="left", padx=(6, 0))
        ttk.Button(pr, text="▲", width=3, command=lambda: self._przesun(-1)).pack(side="left", padx=(6, 0))
        ttk.Button(pr, text="▼", width=3, command=lambda: self._przesun(1)).pack(side="left", padx=(2, 0))
        ttk.Button(pr, text="Odczytaj ponownie", command=self._odswiez).pack(side="left", padx=(6, 0))

        box = app._sekcja(f, "Pismo")
        for etykieta, var, podp in (("Rejon Energetyczny:", self.rejon, "(np. Mińsk Mazowiecki — gdy puste, "
                                                                        "z ustawień Generatora WT projektu)"),
                                    ("Miejscowość pisma:", self.miejscowosc, "(przed datą, np. Mińsk Mazowiecki)")):
            r = ttk.Frame(box)
            r.pack(fill="x", pady=4)
            ttk.Label(r, text=etykieta, width=24).pack(side="left")
            ttk.Entry(r, textvariable=var, width=34).pack(side="left", padx=6)
            ttk.Label(r, text=podp, style="Hint.TLabel").pack(side="left")
        app._pole_pliku(box, "Szablon pisma (.docx):", self.szablon, "Wybierz szablon pisma",
                        typy=[("Dokument Word", "*.docx"), ("Wszystkie pliki", "*.*")])
        app._podpowiedz(box, "(opcjonalny — dokument z akapitem „*projekty*” w miejscu listy projektów; "
                             "może mieć też *data*, *rejon*, *razem*. Puste = prosty dokument)")
        dostepne = pz.tabele_dostepne()
        ttk.Checkbutton(box, text="Utwórz też tabele projektowe (osobno dla każdego WT)", variable=self.tabele,
                        state="normal" if dostepne else "disabled").pack(anchor="w", pady=(8, 0))
        app._podpowiedz(box, "(jak w module FINAŁ: z pliku PZT projektu, Lp i współrzędne jak w jego warunkach "
                             "technicznych; pliki „Tabela projektowa <WT>.xlsx” obok pisma)" if dostepne else
                        "(tabela projektowa jest dostępna w wersji programu z modułem warunków technicznych)")
        app._przycisk_generuj(f, "Utwórz pismo", self._generuj)

    # ------------------------------------------------------------------ lista projektów
    def _wiersz(self, p: pz.Projekt):
        return (p.nazwa, p.miejscowosci, ", ".join(p.stacje), p.slupy, p.wt, "; ".join(p.uwagi))

    def _pokaz(self):
        self.tabela.delete(*self.tabela.get_children())
        for i, p in enumerate(self.projekty):
            self.tabela.insert("", "end", iid=str(i), values=self._wiersz(p))
        if not self.rejon.get().strip():
            self.rejon.set(next((p.rejon for p in self.projekty if p.rejon), ""))

    def _zapamietaj(self):
        self.app.ust["pismo_foldery"] = [p.folder for p in self.projekty]
        self.app.ust["pismo_rejon"] = self.rejon.get().strip()
        self.app.ust["pismo_miejscowosc"] = self.miejscowosc.get().strip()
        self.app.ust["pismo_szablon"] = self.szablon.get().strip()
        self.app.ust["pismo_tabele"] = bool(self.tabele.get())
        self.app._zaplanuj_zapis()

    def _dodaj(self, folder, zapisz=True):
        folder = os.path.normpath(folder)
        if any(os.path.normcase(p.folder) == os.path.normcase(folder) for p in self.projekty):
            return
        try:
            p = pz.wczytaj_projekt(folder)
        except Exception as ex:  # noqa: BLE001 - uszkodzony plik projektu: pokaż, nie przerywaj
            p = pz.Projekt(folder, uwagi=[f"błąd odczytu: {ex}"])
        self.projekty.append(p)
        self._pokaz()
        if zapisz:
            self._zapamietaj()

    def _wybierz(self):
        start = os.path.dirname(self.projekty[-1].folder) if self.projekty else (self.app.projekt.get() or None)
        f = filedialog.askdirectory(parent=self.app.root, title="Folder projektu", initialdir=start)
        if f:
            self._dodaj(f)

    def _dodaj_otwarty(self):
        f = self.app.projekt.get().strip()
        if not f or not os.path.isdir(f):
            messagebox.showinfo(self.app.root.title(), "Nie ma otwartego projektu.", parent=self.app.root)
            return
        self._dodaj(f)

    def _zaznaczone(self):
        return sorted(int(i) for i in self.tabela.selection())

    def _usun(self):
        for i in reversed(self._zaznaczone()):
            del self.projekty[i]
        self._pokaz()
        self._zapamietaj()

    def _przesun(self, o):
        sel = self._zaznaczone()
        if len(sel) != 1 or not 0 <= sel[0] + o < len(self.projekty):
            return
        i = sel[0]
        self.projekty[i], self.projekty[i + o] = self.projekty[i + o], self.projekty[i]
        self._pokaz()
        self.tabela.selection_set(str(i + o))
        self._zapamietaj()

    def _odswiez(self):
        foldery = [p.folder for p in self.projekty]
        self.projekty = []
        for f in foldery:
            self._dodaj(f, zapisz=False)
        self._pokaz()

    # ------------------------------------------------------------------ edycja komórki
    def _edytuj(self, e):
        wiersz, kol = self.tabela.identify_row(e.y), self.tabela.identify_column(e.x)
        if not wiersz or not kol:
            return
        klucz = KOLUMNY[int(kol[1:]) - 1][0]
        if klucz not in EDYTOWALNE:
            return
        x, y, w, h = self.tabela.bbox(wiersz, kol)
        p = self.projekty[int(wiersz)]
        var = tk.StringVar(value=self._wiersz(p)[int(kol[1:]) - 1])
        pole = ttk.Entry(self.tabela, textvariable=var)
        pole.place(x=x, y=y, width=max(w, 120), height=h)
        pole.focus_set()
        pole.select_range(0, "end")

        def zatwierdz(_e=None):
            v = var.get().strip()
            pole.destroy()
            if klucz == "slupy":
                try:
                    p.slupy = int(v)
                except ValueError:
                    return
            elif klucz == "stacje":
                p.stacje = [s.strip() for s in v.split(",") if s.strip()]
            elif klucz == "wt":
                p.wt = v
                try:
                    pz.zapamietaj_wt(p.folder, v)       # numer WT zostaje w folderze projektu
                except OSError:
                    pass
            else:
                p.miejscowosci = v
            self.tabela.item(wiersz, values=self._wiersz(p))
        pole.bind("<Return>", zatwierdz)
        pole.bind("<FocusOut>", zatwierdz)
        pole.bind("<Escape>", lambda _e: pole.destroy())

    # ------------------------------------------------------------------ generowanie
    def _generuj(self):
        app = self.app
        tytul = app.root.title()
        if not self.projekty:
            messagebox.showwarning(tytul, "Dodaj co najmniej jeden folder projektu.", parent=app.root)
            return
        braki = [p.nazwa for p in self.projekty if not (p.stacje and p.miejscowosci and p.wt and p.slupy)]
        if braki and not messagebox.askyesno(
                tytul, "Niepełne dane w projektach:\n• " + "\n• ".join(braki)
                + "\n\nUzupełnij je w tabeli (podwójne kliknięcie). Utworzyć pismo mimo to?", parent=app.root):
            return
        szablon = self.szablon.get().strip() or None
        if szablon and not os.path.isfile(szablon):
            messagebox.showwarning(tytul, f"Nie ma szablonu:\n{szablon}", parent=app.root)
            return
        dzis = datetime.date.today()
        domyslny = os.path.dirname(self.projekty[0].folder)
        wyjscie = filedialog.asksaveasfilename(
            parent=app.root, title="Zapisz pismo zatwierdzające", defaultextension=".docx",
            initialdir=domyslny, initialfile=f"Pismo zatwierdzające {dzis:%Y-%m-%d}.docx",
            filetypes=[("Dokument Word", "*.docx")])
        if not wyjscie:
            return
        self._zapamietaj()
        app._pisz("\n" + "=" * 50 + "\nPISMO ZATWIERDZAJĄCE")
        try:
            plik = pz.generuj(self.projekty, wyjscie, szablon=szablon, rejon=self.rejon.get().strip(),
                              miejscowosc=self.miejscowosc.get().strip(), log=app._pisz)
        except PermissionError:
            messagebox.showerror(tytul, f"Nie można zapisać (plik otwarty w Wordzie?):\n{wyjscie}", parent=app.root)
            return
        except Exception as ex:  # noqa: BLE001
            app._pisz(f"BŁĄD: {ex}")
            messagebox.showerror(tytul, f"Nie udało się utworzyć pisma:\n{ex}", parent=app.root)
            return
        app._ostatni_plik, app._ostatni_katalog = plik, os.path.dirname(plik)
        if self.tabele.get() and pz.tabele_dostepne():
            self._tabele_w_tle(os.path.dirname(plik))
            return
        self._koniec(1)

    def _koniec(self, ile):
        app = self.app
        app.btn_otworz.configure(state="normal")
        app.btn_otworz_plik.configure(state="normal")
        app.status.configure(text=f"Gotowe — utworzono pismo zatwierdzające ({ile} plik(ów)).")
        app._okno_gotowe(ile)

    def _tabele_w_tle(self, folder):
        """Tabele projektowe (geokodowanie adresów trwa) - w osobnym wątku, dziennik przez kolejkę okna."""
        app = self.app
        projekty = list(self.projekty)
        adresy = bool(app.adresy_on.get())
        wynik = {}
        app.pracuje = True
        for b in app._przyciski:
            b.configure(state="disabled")
        app.pasek.start(40)
        app.status.configure(text="Trwa tworzenie tabel projektowych…")

        def log(t):
            app.root.after(0, app._pisz, str(t))

        def praca():
            try:
                wynik["pliki"] = pz.tabele_projektowe(projekty, folder, adresy=adresy, log=log)
            except Exception as ex:  # noqa: BLE001
                wynik["blad"] = ex
            app.root.after(0, koniec)

        def koniec():
            app.pracuje = False
            app.pasek.stop()
            for b in app._przyciski:
                b.configure(state="normal")
            if "blad" in wynik:
                app._pisz(f"BŁĄD tabel projektowych: {wynik['blad']}")
                messagebox.showerror(app.root.title(), f"Pismo utworzone, ale tabele projektowe nie:
"
                                                       f"{wynik['blad']}", parent=app.root)
            pliki = wynik.get("pliki") or []
            self._koniec(1 + len(pliki))
        threading.Thread(target=praca, daemon=True).start()
