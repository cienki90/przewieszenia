"""Okno „Stan projektu”: w jednym miejscu pliki wejściowe wszystkich modułów i wyniki w folderze projektu.

Dla każdego pola z plikiem: czy plik istnieje, czy leży w folderze projektu (plik z innego projektu to
najczęstsza pomyłka - np. plan albo WT poprzedniego zadania) i czy wpisał go program (wynik
wcześniejszego modułu), czy użytkownik. Dla każdego modułu: najnowszy wynik w folderze projektu i jego
data. Podwójne kliknięcie przenosi do strony modułu.
"""
from __future__ import annotations

import datetime
import os
import tkinter as tk
from tkinter import messagebox, ttk

try:
    from . import nazwy_plikow as _np
except ImportError:  # bezpośrednie uruchomienie
    import nazwy_plikow as _np

GLEBOKOSC = 2          # wyniki szukane w folderze projektu i podfolderach do 2 poziomów


def _w_folderze(plik, folder) -> bool:
    try:
        f = os.path.normcase(os.path.abspath(folder))
        return os.path.commonpath([os.path.normcase(os.path.abspath(plik)), f]) == f
    except ValueError:
        return False


# wyniki modułów: klucz strony -> [(opis, warunek(nazwa pliku małymi literami, nazwa folderu małymi))]
WYNIKI = {
    "wt": [("zestawienie uproszczone WT", lambda n, d: n.endswith("_uproszczona.xls"))],
    "numeracja": [("plan ponumerowany", lambda n, d: n.endswith((".dxf", ".dwg")) and (
        n.startswith(_np.PONUMEROWANY.lower() + " ") or n[:-4].endswith(" - ponumerowane")))],
    "przewieszenia": [("rysunek przewieszeń", lambda n, d: n.endswith((".dxf", ".dwg")) and (
        n.startswith(_np.PRZEWIESZENIA.lower() + " ") or n[:-4].endswith(" - przewieszenia")))],
    "zestawienie": [("zestawienie słupów", lambda n, d: n.startswith("zestawienie ") and n.endswith(".xlsx"))],
    "obliczenia": [("obliczenia nośności", lambda n, d: n.startswith("obliczenia - ") and n.endswith(".xlsx"))],
    "pzt": [("arkusze PZT", lambda n, d: _np.czy_pzt(n))],
    "orientacje": [("zestawienie stacji", lambda n, d: n == "zestawienie_stacji.xlsx"),
                   ("rysunki stacji", lambda n, d: d == "rysunki stałe" and n.endswith((".dxf", ".dwg"))
                    and not n.startswith("_"))],
    "opisy": [("opisy techniczne", lambda n, d: d == "opisy" and n.endswith(".docx") and "szablon" not in n)],
    "ppw": [("zbiorczy opis PPW", lambda n, d: n == "ppw.docx"),
            ("plik powykonawczy", lambda n, d: n.endswith((".dxf", ".dwg")) and n.startswith(("!ppw ", "ppw ")))],
    "zakladki": [("zakładki", lambda n, d: n.startswith("zakladki.") and n.endswith((".docx", ".pdf")))],
}


def znajdz_wyniki(folder: str) -> dict:
    """{klucz modułu: [(opis, [ścieżki od najnowszej])]} - wyniki modułów leżące w folderze projektu."""
    pliki = []
    if folder and os.path.isdir(folder):
        for kat, podkat, nazwy in os.walk(folder):
            if kat[len(folder):].count(os.sep) >= GLEBOKOSC:
                podkat[:] = []
            podkat[:] = [p for p in podkat if not p.startswith((".", "_"))]
            d = os.path.basename(kat).lower()
            pliki += [(n.lower(), d, os.path.join(kat, n)) for n in nazwy]
    wynik = {}
    for klucz, rodzaje in WYNIKI.items():
        wynik[klucz] = []
        for opis, warunek in rodzaje:
            trafione = [p for n, d, p in pliki if warunek(n, d)]
            trafione.sort(key=_czas, reverse=True)
            wynik[klucz].append((opis, trafione))
    return wynik


def _czas(p) -> float:
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _data(p) -> str:
    t = _czas(p)
    return datetime.datetime.fromtimestamp(t).strftime("%d.%m.%Y %H:%M") if t else ""


def stan_pola(wartosc: str, folder_projektu: str | None, auto: bool) -> tuple[str, str]:
    """(opis stanu, tag) dla ścieżki z pola: puste / brak pliku / spoza projektu / OK."""
    if not wartosc:
        return "puste", "puste"
    kto = "podpiął program" if auto else "wybrany ręcznie"
    if not os.path.exists(wartosc):
        return f"✗ nie ma takiego pliku ({kto})", "blad"
    if folder_projektu and not _w_folderze(wartosc, folder_projektu):
        return f"⚠ spoza folderu projektu ({kto})", "uwaga"
    return f"✓ {kto}", "ok"


class OknoStanu(tk.Toplevel):
    """Okno stanu projektu. `app` - okno główne (pola, projekt, _podpiete, _pokaz)."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Stan projektu")
        self.geometry("1050x620")
        g = ttk.Frame(self, padding=(12, 10, 12, 4))
        g.pack(fill="x")
        self.naglowek = ttk.Label(g, text="", wraplength=1000, justify="left")
        self.naglowek.pack(side="left", fill="x", expand=True)
        ttk.Button(g, text="Odśwież", command=self.odswiez).pack(side="right")
        ttk.Button(g, text="Otwórz folder projektu", command=self._otworz_folder).pack(side="right", padx=6)
        self.b_wyczysc = ttk.Button(g, text="Wyczyść pola spoza projektu", command=self._wyczysc_obce)
        self.b_wyczysc.pack(side="right")
        ramka = ttk.Frame(self, padding=(12, 4, 12, 4))
        ramka.pack(fill="both", expand=True)
        self.drzewo = ttk.Treeview(ramka, columns=("plik", "stan"), show="tree headings")
        self.drzewo.heading("#0", text="Moduł / pole")
        self.drzewo.heading("plik", text="Plik")
        self.drzewo.heading("stan", text="Stan")
        self.drzewo.column("#0", width=270, stretch=False)
        self.drzewo.column("plik", width=470)
        self.drzewo.column("stan", width=260, stretch=False)
        self.drzewo.tag_configure("blad", foreground="#C62828")
        self.drzewo.tag_configure("uwaga", foreground="#B35C00")
        self.drzewo.tag_configure("puste", foreground="#8A8F98")
        sy = ttk.Scrollbar(ramka, orient="vertical", command=self.drzewo.yview)
        self.drzewo.configure(yscrollcommand=sy.set)
        self.drzewo.pack(side="left", fill="both", expand=True)
        sy.pack(side="left", fill="y")
        self.drzewo.bind("<Double-1>", self._przejdz)
        ttk.Label(self, text="Podwójne kliknięcie - przejście do modułu. Pliki spoza folderu projektu i brakujące "
                             "są wyróżnione.", padding=(12, 2, 12, 8)).pack(fill="x")
        self._klucze = {}
        self.odswiez()

    def odswiez(self):
        app, d = self.app, self.drzewo
        d.delete(*d.get_children())
        self._klucze.clear()
        folder = app.projekt.get().strip() or None
        wyniki = znajdz_wyniki(folder) if folder else {}
        problemy = set()                    # nazwy zmiennych (to samo pole bywa w kilku modułach)
        for klucz, nazwa, pola in app._pola_modulow():
            wezel = d.insert("", "end", text=nazwa, open=True)
            self._klucze[wezel] = klucz
            zle = 0
            for etykieta, var in pola:
                wart = str(var.get()).strip()
                auto = bool(wart) and wart == app._podpiete.get(str(var))
                opis, tag = stan_pola(wart, folder, auto)
                if tag in ("blad", "uwaga"):
                    zle += 1
                    problemy.add(str(var))
                n = d.insert(wezel, "end", text=etykieta, values=(wart or "—", opis), tags=(tag,))
                self._klucze[n] = klucz
            for opis, pliki in wyniki.get(klucz, []):
                if pliki:
                    tekst = os.path.relpath(pliki[0], folder) + (f"  (+{len(pliki) - 1} innych)" if len(pliki) > 1 else "")
                    n = d.insert(wezel, "end", text=f"wynik: {opis}", values=(tekst, f"z {_data(pliki[0])}"))
                else:
                    n = d.insert(wezel, "end", text=f"wynik: {opis}", values=("—", "jeszcze nie ma"), tags=("puste",))
                self._klucze[n] = klucz
            if zle:
                d.item(wezel, tags=("uwaga",), values=("", f"⚠ do sprawdzenia: {zle}"))
        self.b_wyczysc.configure(state="normal" if self._obce() else "disabled")
        if not folder:
            self.naglowek.configure(text="Brak otwartego projektu - widać tylko pola modułów (wyniki są szukane "
                                         "w folderze projektu).")
        else:
            self.naglowek.configure(text=f"Projekt: {folder}\n" + (
                f"Pola do sprawdzenia: {len(problemy)} (plik spoza projektu albo nieistniejący)." if problemy
                else "Wszystkie wskazane pliki istnieją i leżą w folderze projektu."))

    def _obce(self):
        """[(moduł, pole, zmienna)] - pola z plikami spoza folderu projektu (także wybrane ręcznie)."""
        folder = self.app.projekt.get().strip()
        if not folder:
            return []
        wynik, widziane = [], set()
        for _klucz, nazwa, pola in self.app._pola_modulow():
            for etykieta, var in pola:
                wart = str(var.get()).strip()
                if wart and str(var) not in widziane and not _w_folderze(wart, folder):
                    widziane.add(str(var))          # to samo pole bywa w kilku modułach (np. WT)
                    wynik.append((nazwa, etykieta, var))
        return wynik

    def _wyczysc_obce(self):
        obce = self._obce()
        if not obce:
            return
        lista = "\n".join(f"• {m} – {e}: {os.path.basename(str(v.get()))}" for m, e, v in obce)
        if not messagebox.askyesno("Stan projektu", f"Wyczyścić pola z plikami spoza folderu projektu?\n\n{lista}\n\n"
                                   "Pliki na dysku nie są usuwane - pola zostaną puste.", parent=self):
            return
        for _m, _e, var in obce:
            var.set("")
            self.app._podpiete.pop(str(var), None)
        self.app._pisz(f"Stan projektu: wyczyszczono {len(obce)} pól z plikami spoza projektu.")
        self.app._zapisz_projekt()
        self.app._podepnij_pzt_orient()        # Rysunki stałe: plik PZT z tego projektu, jeśli jest
        self.odswiez()

    def _przejdz(self, e):
        wiersz = self.drzewo.identify_row(e.y)
        klucz = self._klucze.get(wiersz)
        if klucz and klucz in self.app._strony:
            self.app._pokaz(klucz)
            self.app.root.lift()

    def _otworz_folder(self):
        folder = self.app.projekt.get().strip()
        if folder and os.path.isdir(folder):
            try:
                os.startfile(folder)  # noqa: S606
            except OSError:
                pass
