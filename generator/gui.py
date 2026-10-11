#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Okienkowy interfejs zunifikowanego generatora (przewieszenia + zestawienie + obliczenia).

Jedno okno: użytkownik wskazuje plik planu DXF, zaznacza, co ma powstać,
wybiera katalog zapisu i klika „Generuj". Praca odbywa się w osobnym wątku,
a postęp i raport są wyświetlane na bieżąco. Program nie wymaga instalowania
żadnych bibliotek (sam Python ze standardowym tkinter).
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

TYTUL = "Generator projektów nN — przewieszenia · zestawienie · obliczenia"

OPIS_KROKOW = {
    "przewieszenia": ("Przewieszenia (rysunki zwisów)",
                      "Rysunki profili zwisów przęseł linii nN ze światłowodem — plik DXF."),
    "zestawienie":   ("Zestawienie słupów",
                      "Zestawienie słupów nN w podziale na stacje transformatorowe — plik XLSX."),
    "obliczenia":    ("Obliczenia nośności",
                      "Obliczenia nośności słupów na podstawie zestawienia — plik XLSX."),
}


class Aplikacja:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(TYTUL)
        root.minsize(760, 620)

        self.plan = tk.StringVar()
        self.katalog = tk.StringVar()
        self.kroki = {k: tk.BooleanVar(value=True) for k in pipeline.KROKI}
        self.adresy_on = tk.BooleanVar(value=True)
        self.pracuje = False
        self._kolejka: "queue.Queue" = queue.Queue()
        self._ostatni_wynik = None

        self._buduj()
        self.plan.trace_add("write", lambda *_: self._odswiez_katalog())

    # ------------------------------------------------------------------ UI
    def _buduj(self):
        pad = dict(padx=10, pady=6)
        root = self.root
        root.columnconfigure(0, weight=1)

        # --- 1. Plik planu DXF ---
        ramka_plik = ttk.LabelFrame(root, text="1. Plik planu DXF (dane wejściowe)")
        ramka_plik.grid(row=0, column=0, sticky="we", **pad)
        ramka_plik.columnconfigure(0, weight=1)
        ttk.Entry(ramka_plik, textvariable=self.plan).grid(row=0, column=0, sticky="we", padx=8, pady=8)
        ttk.Button(ramka_plik, text="Wybierz…", command=self._wybierz_plan).grid(row=0, column=1, padx=8, pady=8)

        # --- 2. Co wygenerować ---
        ramka_kroki = ttk.LabelFrame(root, text="2. Co wygenerować")
        ramka_kroki.grid(row=1, column=0, sticky="we", **pad)
        ramka_kroki.columnconfigure(0, weight=1)
        for i, k in enumerate(pipeline.KROKI):
            tytul, opis = OPIS_KROKOW[k]
            cb = ttk.Checkbutton(ramka_kroki, text=tytul, variable=self.kroki[k], command=self._odswiez_przyciski)
            cb.grid(row=i * 2, column=0, sticky="w", padx=8, pady=(8 if i == 0 else 2, 0))
            ttk.Label(ramka_kroki, text=opis, foreground="#555").grid(row=i * 2 + 1, column=0, sticky="w",
                                                                      padx=30, pady=(0, 4))
        ttk.Label(ramka_kroki, text="Wskazówka: „Obliczenia” potrzebują zestawienia — zostanie ono "
                                    "utworzone automatycznie, jeśli nie zaznaczysz go osobno.",
                  foreground="#777", wraplength=680).grid(row=99, column=0, sticky="w", padx=8, pady=(2, 8))

        # --- 3. Opcje i katalog ---
        ramka_opcje = ttk.LabelFrame(root, text="3. Opcje i miejsce zapisu")
        ramka_opcje.grid(row=2, column=0, sticky="we", **pad)
        ramka_opcje.columnconfigure(1, weight=1)
        ttk.Checkbutton(ramka_opcje, text="Pobieraj nazwy miejscowości i ulic z internetu (GUGiK / OpenStreetMap)",
                        variable=self.adresy_on).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 2))
        ttk.Label(ramka_opcje, text="Katalog zapisu:").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(ramka_opcje, textvariable=self.katalog).grid(row=1, column=1, sticky="we", padx=4, pady=8)
        ttk.Button(ramka_opcje, text="Zmień…", command=self._wybierz_katalog).grid(row=1, column=2, padx=8, pady=8)

        # --- 4. Akcja ---
        ramka_akcja = ttk.Frame(root)
        ramka_akcja.grid(row=3, column=0, sticky="we", **pad)
        ramka_akcja.columnconfigure(1, weight=1)
        self.btn = ttk.Button(ramka_akcja, text="▶  Generuj", command=self._start)
        self.btn.grid(row=0, column=0, sticky="w")
        self.pasek = ttk.Progressbar(ramka_akcja, mode="indeterminate")
        self.pasek.grid(row=0, column=1, sticky="we", padx=10)
        self.btn_otworz = ttk.Button(ramka_akcja, text="Otwórz folder wyniku",
                                     command=self._otworz_folder, state="disabled")
        self.btn_otworz.grid(row=0, column=2, sticky="e")

        # --- 5. Log ---
        ramka_log = ttk.LabelFrame(root, text="Przebieg")
        ramka_log.grid(row=4, column=0, sticky="nsew", **pad)
        root.rowconfigure(4, weight=1)
        ramka_log.rowconfigure(0, weight=1)
        ramka_log.columnconfigure(0, weight=1)
        self.log = tk.Text(ramka_log, height=12, wrap="word", font=("Consolas", 9), state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(ramka_log, orient="vertical", command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)

        self.status = ttk.Label(root, text="Gotowe. Wskaż plik planu DXF i kliknij „Generuj”.",
                                relief="sunken", anchor="w")
        self.status.grid(row=5, column=0, sticky="we")

    # ------------------------------------------------------------- zdarzenia
    def _wybierz_plan(self):
        p = filedialog.askopenfilename(parent=self.root, title="Wybierz plik planu DXF",
                                       filetypes=[("Rysunek DXF", "*.dxf"), ("Wszystkie pliki", "*.*")])
        if p:
            self.plan.set(os.path.normpath(p))

    def _wybierz_katalog(self):
        start = self.katalog.get() or (os.path.dirname(self.plan.get()) if self.plan.get() else "")
        p = filedialog.askdirectory(parent=self.root, title="Katalog zapisu wyników",
                                     initialdir=start or None)
        if p:
            self.katalog.set(os.path.normpath(p))

    def _odswiez_katalog(self):
        if self.plan.get() and not self.katalog.get():
            self.katalog.set(os.path.dirname(os.path.abspath(self.plan.get())))

    def _odswiez_przyciski(self):
        wybrane = any(v.get() for v in self.kroki.values())
        self.btn.configure(state="normal" if (wybrane and not self.pracuje) else "disabled")

    def _pisz(self, tekst: str):
        self.log.configure(state="normal")
        self.log.insert("end", tekst + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------- uruchomienie
    def _start(self):
        plan = self.plan.get().strip()
        if not plan or not os.path.isfile(plan):
            messagebox.showwarning(TYTUL, "Wskaż istniejący plik planu DXF.", parent=self.root)
            return
        kroki = tuple(k for k in pipeline.KROKI if self.kroki[k].get())
        if not kroki:
            messagebox.showwarning(TYTUL, "Zaznacz przynajmniej jedną rzecz do wygenerowania.", parent=self.root)
            return
        katalog = self.katalog.get().strip() or os.path.dirname(os.path.abspath(plan))

        self.pracuje = True
        self.btn.configure(state="disabled")
        self.btn_otworz.configure(state="disabled")
        self.pasek.start(12)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.status.configure(text="Trwa generowanie… (pobieranie nazw ulic z internetu może potrwać do minuty)")
        self._ostatni_katalog = katalog

        opcje = pipeline.Opcje(
            plan=plan, katalog=katalog, kroki=kroki,
            adresy="uug,osm" if self.adresy_on.get() else "brak",
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
        self._odswiez_przyciski()
        self._ostatni_wynik = wynik
        if wynik is None:
            self.status.configure(text="Wystąpił błąd — szczegóły w oknie poniżej.")
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
            self.status.configure(text=f"Gotowe — utworzono {len(udane)} plik(ów).")
            if messagebox.askyesno(TYTUL, f"Gotowe! Utworzono {len(udane)} plik(ów) w:\n{self._ostatni_katalog}"
                                          "\n\nOtworzyć folder z wynikami?", parent=self.root):
                self._otworz_folder()
        else:
            self.status.configure(text=f"Zakończono z problemami: {len(udane)} OK, {len(nieudane)} błędów.")
            messagebox.showwarning(TYTUL, f"Część kroków się nie powiodła ({len(nieudane)}). "
                                          "Szczegóły w oknie „Przebieg”.", parent=self.root)

    def _otworz_folder(self):
        folder = getattr(self, "_ostatni_katalog", "") or self.katalog.get()
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
