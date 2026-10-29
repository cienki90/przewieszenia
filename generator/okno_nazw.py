"""Okno „Nazwy miejscowości” - ręczna poprawka nazw stacji (gdy geokodowanie dało „????” lub złą nazwę).

Lista stacji pochodzi z zestawienia stacji (Rysunki stałe) i z pliku poprawek. Poprawki zapisywane
są w ``nazwy miejscowości.csv`` w folderze projektu (używają ich Rysunki stałe i Arkusze PZT), a
zestawienie stacji jest od razu poprawiane (Opisy, PPW i Zakładki czytają nazwy z niego).
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import nazwy


class OknoNazw(tk.Toplevel):
    def __init__(self, master, plik_csv: str, zestawienie: str | None = None, log=print):
        super().__init__(master)
        self.title("Nazwy miejscowości stacji trafo")
        self.geometry("720x480")
        self.transient(master)
        self.plik_csv, self.zestawienie, self.log = plik_csv, zestawienie, log
        self.poprawki = nazwy.wczytaj(plik_csv)
        self.auto = {}                                   # nr -> (oznaczenie, nazwa automatyczna)
        if zestawienie and os.path.isfile(zestawienie):
            try:
                for ozn, nr, miejsc in nazwy.z_zestawienia(zestawienie):
                    self.auto[nr] = (ozn, miejsc)
            except Exception as ex:  # noqa: BLE001 - zestawienie jest tylko podpowiedzią
                self.log(f"Nie udało się odczytać zestawienia stacji: {ex}")
        self._buduj()
        self._wypelnij()

    def _buduj(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        zrodlo = os.path.basename(self.zestawienie) if self.zestawienie and self.auto else "brak (uruchom Rysunki stałe)"
        ttk.Label(self, padding=(12, 10, 12, 4), wraplength=690, justify="left", text=(
            "Podwójne kliknięcie wiersza - wpisz poprawną nazwę. Poprawki mają pierwszeństwo przed "
            "geokodowaniem i WT (Rysunki stałe, Arkusze PZT) i od razu trafiają do zestawienia stacji "
            f"(Opisy, PPW, Zakładki).\nZestawienie: {zrodlo}")).grid(row=0, column=0, columnspan=2, sticky="w")
        self.tab = ttk.Treeview(self, columns=("stacja", "auto", "poprawka"), show="headings", selectmode="browse")
        for kol, tytul, szer in (("stacja", "Stacja", 120), ("auto", "Ustalona automatycznie", 250),
                                 ("poprawka", "Poprawka", 250)):
            self.tab.heading(kol, text=tytul)
            self.tab.column(kol, width=szer, anchor="w")
        self.tab.grid(row=1, column=0, sticky="nsew", padx=(12, 0), pady=4)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tab.yview)
        sb.grid(row=1, column=1, sticky="ns", padx=(0, 12), pady=4)
        self.tab.configure(yscrollcommand=sb.set)
        self.tab.bind("<Double-1>", lambda e: self._edytuj())
        dol = ttk.Frame(self, padding=12)
        dol.grid(row=2, column=0, columnspan=2, sticky="we")
        ttk.Button(dol, text="Popraw…", command=self._edytuj).pack(side="left")
        ttk.Button(dol, text="Usuń poprawkę", command=self._usun).pack(side="left", padx=6)
        ttk.Button(dol, text="Dodaj stację…", command=self._dodaj).pack(side="left")
        ttk.Button(dol, text="Anuluj", command=self.destroy).pack(side="right")
        ttk.Button(dol, text="Zapisz", command=self._zapisz, style="Accent.TButton").pack(side="right", padx=6)

    def _wypelnij(self):
        self.tab.delete(*self.tab.get_children())
        for nr in sorted(set(self.auto) | set(self.poprawki)):
            ozn, auto = self.auto.get(nr, (str(nr), ""))
            self.tab.insert("", "end", iid=str(nr), values=(ozn, auto or "—", self.poprawki.get(nr, "")))

    def _wybrany(self):
        sel = self.tab.selection()
        return int(sel[0]) if sel else None

    def _edytuj(self):
        nr = self._wybrany()
        if nr is None:
            return
        teraz = self.poprawki.get(nr) or self.auto.get(nr, ("", ""))[1]
        nowa = simpledialog.askstring("Nazwa miejscowości", f"Stacja {self.auto.get(nr, (nr,))[0]}:",
                                      initialvalue="" if teraz in ("????", "—") else teraz, parent=self)
        if nowa is not None:
            if nowa.strip():
                self.poprawki[nr] = nowa.strip()
            else:
                self.poprawki.pop(nr, None)
            self._wypelnij()
            self.tab.selection_set(str(nr))

    def _usun(self):
        nr = self._wybrany()
        if nr is not None:
            self.poprawki.pop(nr, None)
            self._wypelnij()

    def _dodaj(self):
        nr = nazwy.nr_stacji(simpledialog.askstring("Dodaj stację", "Numer stacji (np. 05-0565):", parent=self))
        if nr is not None:
            self.auto.setdefault(nr, (str(nr), ""))
            self._wypelnij()
            self.tab.selection_set(str(nr))
            self._edytuj()

    def _zapisz(self):
        try:
            nazwy.zapisz(self.plik_csv, self.poprawki)
            zmian = 0
            if self.poprawki and self.zestawienie and os.path.isfile(self.zestawienie):
                zmian = nazwy.popraw_zestawienie(self.zestawienie, self.poprawki)
        except (OSError, PermissionError) as ex:
            messagebox.showerror("Nazwy miejscowości", f"Nie udało się zapisać (plik otwarty w Excelu?):\n{ex}",
                                 parent=self)
            return
        self.log(f"Nazwy miejscowości: {len(self.poprawki)} poprawek -> {self.plik_csv}"
                 + (f"; zestawienie stacji poprawione ({zmian})" if zmian else ""))
        self.destroy()
