#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Okienkowy interfejs zunifikowanego generatora - z osobnymi zakładkami dla każdego modułu.

Zakładki:
  * Wszystko (łańcuch) - zaznaczasz, co ma powstać z jednego planu DXF,
  * Przewieszenia      - rysunki zwisów + kontrola (kopia planu z numerami, kontrola stacji),
  * Zestawienie        - zestawienie słupów nN w podziale na stacje (XLSX),
  * Obliczenia         - obliczenia nośności słupów (XLSX, z zestawienia),
  * Rysunki stałe      - plan orientacyjny DXF dla każdej stacji trafo + zestawienie.

Wspólny dół okna: katalog zapisu, pasek postępu, dziennik przebiegu, pasek stanu.
Praca odbywa się w osobnym wątku. Program wymaga tylko Pythona z tkinter
(Pillow - opcjonalnie, tylko do podkładu mapowego w rysunkach stałych).
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import pipeline

TYTUL = "Generator projektów nN — przewieszenia · zestawienie · obliczenia · rysunki stałe"

OPIS_KROKOW = {
    "przewieszenia": ("Przewieszenia (rysunki zwisów)",
                      "Rysunki profili zwisów przęseł linii nN ze światłowodem — plik DXF."),
    "zestawienie":   ("Zestawienie słupów",
                      "Zestawienie słupów nN w podziale na stacje transformatorowe — plik XLSX."),
    "obliczenia":    ("Obliczenia nośności",
                      "Obliczenia nośności słupów na podstawie zestawienia — plik XLSX."),
    "orientacje":    ("Rysunki stałe (plany orientacyjne)",
                      "Osobny plan orientacyjny DXF dla każdej stacji trafo + zestawienie."),
    "pzt":           ("Arkusze PZT (A3 1:1000)",
                      "Dla każdej stacji trafo komplet arkuszy A3 1:1000 pokrywających trasę — na wzór "
                      "layoutu „a” z pliku. Minimalna liczba arkuszy, zakład 50 m."),
    "opisy":         ("Opisy techniczne (.docx)",
                      "Dla każdej stacji osobny opis techniczny .docx z szablonu Word — na podstawie "
                      "zestawienia (bezpośrednio z „Rysunków stałych”) + ręcznie podany numer WT."),
}

DXF_TYPY = [("Rysunek DXF", "*.dxf"), ("Wszystkie pliki", "*.*")]


def _wybierz_plik(parent, var, tytul):
    p = filedialog.askopenfilename(parent=parent, title=tytul, filetypes=DXF_TYPY)
    if p:
        var.set(os.path.normpath(p))


class Aplikacja:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(TYTUL)
        root.minsize(840, 760)

        # wspólne
        self.katalog = tk.StringVar()
        self.adresy_on = tk.BooleanVar(value=True)         # nazwy ulic/miejscowości z internetu
        self.pracuje = False
        self._kolejka: "queue.Queue" = queue.Queue()
        self._ostatni_wynik = None
        self._ostatni_katalog = ""

        # zakładka "Wszystko"
        self.all_plan = tk.StringVar()
        # orientacje/PZT/opisy domyślnie wyłączone - wymagają osobnego szablonu/wzorca/WT
        self.all_kroki = {k: tk.BooleanVar(value=(k not in ("orientacje", "pzt", "opisy")))
                          for k in pipeline.KROKI}

        # per-moduł: plik wejściowy
        self.we = {k: tk.StringVar() for k in pipeline.KROKI}

        # opcje przewieszeń
        self.pw_obrot = tk.StringVar(value="50")
        # opcje obliczeń
        self.obl_seed = tk.StringVar()
        self.obl_kabel = tk.StringVar(value=str(pipeline.mod_obliczenia.DOMYSLNY_KABEL))
        # opcje rysunków stałych
        self.orient_szablon = tk.StringVar()
        self.orient_plan_slupow = tk.StringVar()           # plan ze słupami (źródło miejscowości)
        self.orient_podklad = tk.BooleanVar(value=True)
        # opcje arkuszy PZT
        self.pzt_wzorzec = tk.StringVar()                  # plik z layoutem-wzorcem "a" (puste = plan)
        self.pzt_zaklad = tk.StringVar(value="50")
        # opcje opisów technicznych (.docx)
        self.opisy_szablon = tk.StringVar()                # szablon .docx (puste = dołączony)
        self.opisy_zestawienie = tk.StringVar()            # xlsx (puste = z Rysunków stałych)
        self.opisy_wt = tk.StringVar()                     # numer WT (ręcznie)

        self._przyciski = []                               # przyciski "Generuj" do blokowania
        self._buduj()

    # ================================================================= budowa UI
    def _buduj(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        self.nb = ttk.Notebook(root)
        self.nb.grid(row=0, column=0, sticky="nwe", padx=8, pady=(8, 4))

        self._zakladka_wszystko()
        self._zakladka_przewieszenia()
        self._zakladka_zestawienie()
        self._zakladka_obliczenia()
        self._zakladka_orientacje()
        self._zakladka_pzt()
        self._zakladka_opisy()

        self._dol(root)

    def _naglowek(self, ramka, tekst):
        ttk.Label(ramka, text=tekst, foreground="#555", wraplength=760,
                  justify="left").pack(anchor="w", padx=10, pady=(8, 6))

    def _pole_pliku(self, ramka, etykieta, var, tytul):
        f = ttk.Frame(ramka)
        f.pack(fill="x", padx=10, pady=4)
        ttk.Label(f, text=etykieta, width=22).pack(side="left")
        ttk.Entry(f, textvariable=var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(f, text="Wybierz…", command=lambda: _wybierz_plik(self.root, var, tytul)).pack(side="left")

    def _przycisk_generuj(self, ramka, tekst, komenda):
        b = ttk.Button(ramka, text="▶  " + tekst, command=komenda)
        b.pack(anchor="w", padx=10, pady=10)
        self._przyciski.append(b)
        return b

    # ---------------------------------------------------------------- zakładki
    def _zakladka_wszystko(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Wszystko (łańcuch)")
        self._naglowek(f, "Z jednego planu DXF utwórz od razu kilka opracowań. Zaznacz, co ma powstać.")
        self._pole_pliku(f, "Plik planu DXF:", self.all_plan, "Wybierz plik planu DXF")
        box = ttk.LabelFrame(f, text="Co wygenerować")
        box.pack(fill="x", padx=10, pady=6)
        for k in pipeline.KROKI:
            tytul, opis = OPIS_KROKOW[k]
            ttk.Checkbutton(box, text=tytul, variable=self.all_kroki[k]).pack(anchor="w", padx=8, pady=(6, 0))
            ttk.Label(box, text=opis, foreground="#777").pack(anchor="w", padx=30, pady=(0, 2))
        ttk.Label(f, text="„Obliczenia” potrzebują zestawienia — powstanie automatycznie, jeśli nie zaznaczysz "
                          "go osobno. „Rysunki stałe” używają szablonu z zakładki obok (lub dołączonego).",
                  foreground="#777", wraplength=760, justify="left").pack(anchor="w", padx=10, pady=4)
        self._przycisk_generuj(f, "Generuj zaznaczone", self._start_wszystko)

    def _zakladka_przewieszenia(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Przewieszenia")
        self._naglowek(f, "Rysunki zwisów przęseł linii nN ze światłowodem. Dodatkowo powstaje kopia planu "
                          "z numerami przewieszeń (kontrola) i sprawdzane jest przypisanie stacji trafo.")
        self._pole_pliku(f, "Plik planu DXF:", self.we["przewieszenia"], "Wybierz plik planu DXF")
        box = ttk.LabelFrame(f, text="Opcje")
        box.pack(fill="x", padx=10, pady=6)
        r = ttk.Frame(box)
        r.pack(fill="x", padx=8, pady=6)
        ttk.Label(r, text="Przęsła dłuższe niż [m] rysuj pionowo:").pack(side="left")
        ttk.Entry(r, textvariable=self.pw_obrot, width=6).pack(side="left", padx=6)
        ttk.Label(box, text="(0 = tylko gdy rysunek nie mieści się poziomo w arkuszu)",
                  foreground="#777").pack(anchor="w", padx=8, pady=(0, 6))
        self._przycisk_generuj(f, "Utwórz przewieszenia", lambda: self._start_modul("przewieszenia"))

    def _zakladka_zestawienie(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Zestawienie")
        self._naglowek(f, "Zestawienie słupów nN w podziale na stacje transformatorowe (osobny arkusz na stację, "
                          "arkusz „kontrola” ze sprawdzeniem). Plik XLSX.")
        self._pole_pliku(f, "Plik DXF:", self.we["zestawienie"], "Wybierz plik DXF")
        self._przycisk_generuj(f, "Utwórz zestawienie", lambda: self._start_modul("zestawienie"))

    def _zakladka_obliczenia(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Obliczenia")
        self._naglowek(f, "Obliczenia nośności słupów. Jako wejście podaj plik DXF — zestawienie potrzebne do "
                          "obliczeń powstanie automatycznie (w pliku tymczasowym).")
        self._pole_pliku(f, "Plik DXF:", self.we["obliczenia"], "Wybierz plik DXF")
        box = ttk.LabelFrame(f, text="Opcje")
        box.pack(fill="x", padx=10, pady=6)
        r = ttk.Frame(box)
        r.pack(fill="x", padx=8, pady=6)
        ttk.Label(r, text="Domyślny rodzaj kabla (1-11):").pack(side="left")
        ttk.Entry(r, textvariable=self.obl_kabel, width=5).pack(side="left", padx=6)
        ttk.Label(r, text="Ziarno losowania (powtarzalne kąty):").pack(side="left", padx=(16, 0))
        ttk.Entry(r, textvariable=self.obl_seed, width=8).pack(side="left", padx=6)
        self._przycisk_generuj(f, "Wykonaj obliczenia", lambda: self._start_modul("obliczenia"))

    def _zakladka_orientacje(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Rysunki stałe")
        self._naglowek(f, "Dla każdej stacji trafo z szablonu DXF powstaje osobny plan orientacyjny + zestawienie. "
                          "Nazwa miejscowości w tabelce jest ustalana z położenia słupów stacji (wg zestawienia).")
        self._pole_pliku(f, "Szablon rysunków stałych:", self.we["orientacje"], "Wybierz szablon DXF")
        ttk.Label(f, text="(puste = dołączony szablon.dxf)", foreground="#777").pack(anchor="w", padx=10)
        self._pole_pliku(f, "Plan ze słupami (nazwy):", self.orient_plan_slupow,
                         "Wybierz plan DXF ze słupami (źródło miejscowości)")
        ttk.Label(f, text="(opcjonalnie — miejscowości ustalane z geokodowania słupów tego planu i wiązane "
                          "z szablonem po NUMERZE stacji trafo; puste = słupy z samego szablonu)",
                  foreground="#777", wraplength=760, justify="left").pack(anchor="w", padx=10)
        box = ttk.LabelFrame(f, text="Opcje")
        box.pack(fill="x", padx=10, pady=6)
        ttk.Checkbutton(box, text="Pobieraj podkład mapowy (OSM/Geoportal; wymaga internetu i biblioteki Pillow)",
                        variable=self.orient_podklad).pack(anchor="w", padx=8, pady=6)
        self._przycisk_generuj(f, "Utwórz rysunki stałe", lambda: self._start_modul("orientacje"))

    def _zakladka_pzt(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Arkusze PZT")
        self._naglowek(f, "Dla każdej stacji trafo powstaje komplet arkuszy A3 1:1000 pokrywających całą trasę "
                          "(warstwa !tele) w zakresie stacji (poligony !trafo), przy minimalnej liczbie arkuszy. "
                          "Każdy arkusz to kopia layoutu-wzorca „a” z pliku.")
        self._pole_pliku(f, "Plik planu DXF:", self.we["pzt"], "Wybierz plik planu DXF")
        self._pole_pliku(f, "Plik ze wzorcem „a”:", self.pzt_wzorzec,
                         "Wybierz plik DXF z layoutem-wzorcem „a”")
        ttk.Label(f, text="(puste = wzorzec „a” z pliku planu powyżej)", foreground="#777").pack(anchor="w", padx=10)
        box = ttk.LabelFrame(f, text="Opcje")
        box.pack(fill="x", padx=10, pady=6)
        r = ttk.Frame(box)
        r.pack(fill="x", padx=8, pady=6)
        ttk.Label(r, text="Zakład (wspólny odcinek sąsiednich arkuszy) [m]:").pack(side="left")
        ttk.Entry(r, textvariable=self.pzt_zaklad, width=6).pack(side="left", padx=6)
        self._przycisk_generuj(f, "Utwórz arkusze PZT", lambda: self._start_modul("pzt"))

    def _zakladka_opisy(self):
        f = ttk.Frame(self.nb)
        self.nb.add(f, text="Opisy techniczne")
        self._naglowek(f, "Dla każdej stacji powstaje osobny opis techniczny .docx z szablonu Word. "
                          "Dane (nr stacji + miejscowość) bierzemy z zestawienia — można podpiąć wprost "
                          "plik „zestawienie_stacji.xlsx” z Rysunków stałych. Numer warunków (WT) wpisz ręcznie.")
        self._pole_pliku(f, "Zestawienie (.xlsx):", self.opisy_zestawienie,
                         "Wybierz zestawienie (np. z Rysunków stałych)")
        ttk.Label(f, text="(puste = zestawienie_stacji.xlsx z zakładki „Rysunki stałe” po jej uruchomieniu)",
                  foreground="#777").pack(anchor="w", padx=10)
        self._pole_pliku(f, "Szablon opisu (.docx):", self.opisy_szablon, "Wybierz szablon .docx")
        ttk.Label(f, text="(puste = dołączony szablon_opisu.docx)", foreground="#777").pack(anchor="w", padx=10)
        box = ttk.LabelFrame(f, text="Dane wspólne")
        box.pack(fill="x", padx=10, pady=6)
        r = ttk.Frame(box)
        r.pack(fill="x", padx=8, pady=8)
        ttk.Label(r, text="Numer warunków (WT):").pack(side="left")
        ttk.Entry(r, textvariable=self.opisy_wt, width=28).pack(side="left", padx=6)
        ttk.Label(box, text="(jeden wspólny numer dla wszystkich opisów — np. 100/RE-5/KŚ/2026)",
                  foreground="#777").pack(anchor="w", padx=8, pady=(0, 6))
        self._przycisk_generuj(f, "Utwórz opisy .docx", self._start_opisy)

    def _start_opisy(self):
        zest = self.opisy_zestawienie.get().strip()
        if not zest or not os.path.isfile(zest):
            messagebox.showwarning(TYTUL, "Wskaż plik zestawienia (.xlsx) — np. „zestawienie_stacji.xlsx” "
                                          "z Rysunków stałych.", parent=self.root)
            return
        if not self.opisy_wt.get().strip():
            if not messagebox.askyesno(TYTUL, "Nie podano numeru warunków (WT). Opisy powstaną z pustym WT. "
                                              "Kontynuować?", parent=self.root):
                return
        self._uruchom(zest, ("opisy",))

    # ---------------------------------------------------------------- dół okna
    def _dol(self, root):
        dol = ttk.Frame(root)
        dol.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        dol.columnconfigure(0, weight=1)
        dol.rowconfigure(2, weight=1)

        kat = ttk.Frame(dol)
        kat.grid(row=0, column=0, sticky="we", pady=2)
        kat.columnconfigure(1, weight=1)
        ttk.Label(kat, text="Katalog zapisu:").grid(row=0, column=0, sticky="w")
        ttk.Entry(kat, textvariable=self.katalog).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(kat, text="Zmień…", command=self._wybierz_katalog).grid(row=0, column=2)
        ttk.Checkbutton(kat, text="Nazwy miejscowości i ulic z internetu (GUGiK / OpenStreetMap)",
                        variable=self.adresy_on).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        akcja = ttk.Frame(dol)
        akcja.grid(row=1, column=0, sticky="we", pady=4)
        akcja.columnconfigure(0, weight=1)
        self.pasek = ttk.Progressbar(akcja, mode="indeterminate")
        self.pasek.grid(row=0, column=0, sticky="we")
        self.btn_otworz = ttk.Button(akcja, text="Otwórz folder wyniku",
                                     command=self._otworz_folder, state="disabled")
        self.btn_otworz.grid(row=0, column=1, padx=(10, 0))

        box = ttk.LabelFrame(dol, text="Przebieg")
        box.grid(row=2, column=0, sticky="nsew", pady=2)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.log = tk.Text(box, height=12, wrap="word", font=("Consolas", 9), state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)

        self.status = ttk.Label(root, text="Gotowe. Wybierz zakładkę, wskaż plik i kliknij „Generuj”.",
                                relief="sunken", anchor="w")
        self.status.grid(row=2, column=0, sticky="we")

    # ================================================================= logika
    def _wybierz_katalog(self):
        p = filedialog.askdirectory(parent=self.root, title="Katalog zapisu wyników",
                                     initialdir=self.katalog.get() or None)
        if p:
            self.katalog.set(os.path.normpath(p))

    def _pisz(self, tekst: str):
        self.log.configure(state="normal")
        self.log.insert("end", tekst + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _domyslny_katalog(self, plik):
        return self.katalog.get().strip() or (os.path.dirname(os.path.abspath(plik)) if plik else "")

    # ---- uruchomienie: zakładka "Wszystko" ----
    def _start_wszystko(self):
        plan = self.all_plan.get().strip()
        if not plan or not os.path.isfile(plan):
            messagebox.showwarning(TYTUL, "Wskaż istniejący plik planu DXF.", parent=self.root)
            return
        kroki = tuple(k for k in pipeline.KROKI if self.all_kroki[k].get())
        if not kroki:
            messagebox.showwarning(TYTUL, "Zaznacz przynajmniej jedną rzecz do wygenerowania.", parent=self.root)
            return
        self._uruchom(plan, kroki)

    # ---- uruchomienie: pojedynczy moduł z jego zakładki ----
    def _start_modul(self, krok):
        plik = self.we[krok].get().strip()
        if krok == "orientacje" and not plik:
            plik = self.we[krok].get().strip()      # pusty = dołączony szablon (obsłuży pipeline)
        if krok != "orientacje" and (not plik or not os.path.isfile(plik)):
            messagebox.showwarning(TYTUL, "Wskaż istniejący plik DXF.", parent=self.root)
            return
        if krok == "orientacje" and plik and not os.path.isfile(plik):
            messagebox.showwarning(TYTUL, "Wskazany szablon nie istnieje.", parent=self.root)
            return
        # dla orientacji bez pliku: użyj dołączonego szablonu jako wejścia łańcucha
        wejscie = plik
        orient_szablon = None
        if krok == "orientacje":
            from . import zasoby
            orient_szablon = plik or None
            wejscie = plik or zasoby.szablon_orientacji_dxf()
            if not wejscie:
                messagebox.showwarning(TYTUL, "Brak dołączonego szablonu — wskaż plik szablonu DXF.",
                                       parent=self.root)
                return
        self._uruchom(wejscie, (krok,), orient_szablon=orient_szablon)

    def _uruchom(self, plik, kroki, orient_szablon=None):
        if self.pracuje:
            return
        katalog = self._domyslny_katalog(plik)
        self.pracuje = True
        for b in self._przyciski:
            b.configure(state="disabled")
        self.btn_otworz.configure(state="disabled")
        self.pasek.start(12)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.status.configure(text="Trwa generowanie… (pobieranie danych z internetu może chwilę potrwać)")
        self._ostatni_katalog = katalog

        opcje = pipeline.Opcje(
            plan=plik, katalog=katalog, kroki=kroki,
            adresy="uug,osm" if self.adresy_on.get() else "brak",
            obrot_od=_float(self.pw_obrot.get(), 50.0),
            seed=_int_or_none(self.obl_seed.get()),
            kabel=_int(self.obl_kabel.get(), pipeline.mod_obliczenia.DOMYSLNY_KABEL),
            orient_podklad=self.orient_podklad.get(),
            orient_szablon=orient_szablon or (self.orient_szablon.get().strip() or None),
            orient_plan_slupow=(self.orient_plan_slupow.get().strip() or None),
            pzt_wzorzec=(self.pzt_wzorzec.get().strip() or None),
            pzt_zaklad=_float(self.pzt_zaklad.get(), 50.0),
            opisy_szablon=(self.opisy_szablon.get().strip() or None),
            opisy_zestawienie=(self.opisy_zestawienie.get().strip() or None),
            opisy_wt=self.opisy_wt.get().strip(),
            log=lambda t="": self._kolejka.put(("log", t)),
        )
        threading.Thread(target=self._praca, args=(opcje,), daemon=True).start()
        self.root.after(80, self._pompuj)

    def _praca(self, opcje):
        try:
            wynik = pipeline.uruchom(opcje)
            self._kolejka.put(("koniec", wynik))
        except Exception as ex:  # noqa: BLE001
            self._kolejka.put(("log", "\nBŁĄD: " + str(ex)))
            self._kolejka.put(("log", traceback.format_exc()))
            self._kolejka.put(("koniec", None))

    def _pompuj(self):
        try:
            while True:
                typ, dane = self._kolejka.get_nowait()
                if typ == "log":
                    self._pisz(dane)
                elif typ == "koniec":
                    self._zakoncz(dane)
                    return
        except queue.Empty:
            pass
        self.root.after(80, self._pompuj)

    def _zakoncz(self, wynik):
        self.pracuje = False
        self.pasek.stop()
        for b in self._przyciski:
            b.configure(state="normal")
        self._ostatni_wynik = wynik
        if wynik is None:
            self.status.configure(text="Wystąpił błąd — szczegóły w oknie „Przebieg”.")
            messagebox.showerror(TYTUL, "Nie udało się ukończyć pracy. Szczegóły w oknie „Przebieg”.",
                                 parent=self.root)
            return
        udane = [k for k in wynik.kroki if k.ok]
        nieudane = [k for k in wynik.kroki if not k.ok]
        self._pisz("\n" + "=" * 50)
        self._pisz("PODSUMOWANIE:")
        for k in wynik.kroki:
            self._pisz(f"  [{'OK' if k.ok else 'BŁĄD'}] {k.nazwa} — {k.wyjscie or k.blad or ''}")
        self.btn_otworz.configure(state="normal" if udane else "disabled")
        if not nieudane:
            self.status.configure(text=f"Gotowe — utworzono {len(udane)} wynik(ów).")
            if messagebox.askyesno(TYTUL, f"Gotowe! Utworzono {len(udane)} wynik(ów) w:\n{self._ostatni_katalog}"
                                          "\n\nOtworzyć folder z wynikami?", parent=self.root):
                self._otworz_folder()
        else:
            self.status.configure(text=f"Zakończono z problemami: {len(udane)} OK, {len(nieudane)} błędów.")
            messagebox.showwarning(TYTUL, f"Część kroków się nie powiodła ({len(nieudane)}). "
                                          "Szczegóły w oknie „Przebieg”.", parent=self.root)

    def _otworz_folder(self):
        folder = self._ostatni_katalog or self.katalog.get()
        if not folder or not os.path.isdir(folder):
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # noqa: S606
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", folder])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
        except Exception:  # noqa: BLE001
            messagebox.showinfo(TYTUL, f"Wyniki zapisano w:\n{folder}", parent=self.root)


def _float(s, dom):
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return dom


def _int(s, dom):
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return dom


def _int_or_none(s):
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return None


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    Aplikacja(root)
    root.mainloop()


if __name__ == "__main__":
    main()
