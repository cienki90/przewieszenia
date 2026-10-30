#!/usr/bin/env python3
"""Okienkowy interfejs zunifikowanego generatora - nowoczesny układ z panelem modułów.

Układ okna:
  * nagłówek     - nazwa programu + przełącznik motywu (jasny / ciemny),
  * panel boczny - lista modułów (każdy moduł uruchamia się osobno, bez łańcucha),
  * strona modułu - opis, pola plików, opcje i wyróżniony przycisk „Generuj”,
  * dół okna     - katalog zapisu, pasek postępu, dziennik przebiegu, pasek stanu.

Wygląd: motyw Sun Valley (biblioteka ``sv_ttk``, styl Windows 11); gdy biblioteki nie ma,
okno używa wbudowanego motywu „clam” z własną kolorystyką - program działa tak samo.

Ustawienia między uruchomieniami (``generator.ustawienia``): ostatnio wpisane numery
warunków technicznych (WT) w każdym module, historia numerów WT (lista rozwijana),
motyw i ostatnio otwarty moduł.

Praca odbywa się w osobnym wątku. Program wymaga tylko Pythona z tkinter
(Pillow - opcjonalnie, tylko do podkładu mapowego w rysunkach stałych).
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

from . import pipeline, projekt, ustawienia
from .wersja import wersja

try:
    import sv_ttk
except ImportError:          # motyw opcjonalny - bez niego okno używa „clam”
    sv_ttk = None

TYTUL = "Generator projektów nN"
PODTYTUL = "przewieszenia · zestawienie · obliczenia · rysunki stałe · PZT · opisy"

PLIK_DZIENNIKA = "dziennik GeneratorNN.txt"        # przebieg uruchomień (w katalogu wyników)

DXF_TYPY = [("Rysunek DXF / DWG", "*.dxf *.dwg"), ("Rysunek DXF", "*.dxf"), ("Rysunek DWG", "*.dwg"),
            ("Wszystkie pliki", "*.*")]
DOCX_TYPY = [("Dokument Word", "*.docx"), ("Wszystkie pliki", "*.*")]
XLSX_TYPY = [("Skoroszyt Excel", "*.xlsx *.xls"), ("Wszystkie pliki", "*.*")]

# moduły z polem numeru WT (klucz w ustawieniach)
MODULY_WT = ("opisy", "ppw", "zakladki")

# kolory zależne od motywu: podpowiedzi, dziennik, nagłówek
KOLORY = {
    "light": dict(hint="#6B6F76", log_bg="#FFFFFF", log_fg="#1F2328", akcent="#005FB8",
                  naglowek_bg="#F3F3F3", panel_bg="#EBEBEB"),
    "dark": dict(hint="#A3A8AF", log_bg="#1C1C1C", log_fg="#E6E6E6", akcent="#60CDFF",
                 naglowek_bg="#202020", panel_bg="#2B2B2B"),
}


def _wybierz_plik(parent, var, tytul, typy=DXF_TYPY):
    p = filedialog.askopenfilename(parent=parent, title=tytul, filetypes=typy)
    if p:
        var.set(os.path.normpath(p))


def _czcionka_ui():
    return "Segoe UI" if sys.platform.startswith("win") else "TkDefaultFont"


class Aplikacja:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"{TYTUL} — wersja {wersja()}")
        root.minsize(1060, 800)

        self.ust = ustawienia.wczytaj()
        self._zapis_id = None                              # opóźniony zapis ustawień (after)

        # wspólne
        self.katalog = tk.StringVar()
        self.adresy_on = tk.BooleanVar(value=True)         # nazwy ulic/miejscowości z internetu
        self.eksport_dwg = tk.BooleanVar(value=bool(self.ust.get("zapis_dwg", True)))
        self.motyw = tk.StringVar(value=self.ust.get("motyw", "light"))
        self.pracuje = False
        self._kolejka: queue.Queue = queue.Queue()
        self._ostatni_wynik = None
        self._ostatni_katalog = ""

        # per-moduł: plik wejściowy
        self.we = {k: tk.StringVar() for k in pipeline.KROKI}

        # opcje przewieszeń
        self.pw_obrot = tk.StringVar(value="50")
        # opcje obliczeń
        self.obl_seed = tk.StringVar()
        self.obl_kabel = tk.StringVar(value=str(pipeline.mod_obliczenia.DOMYSLNY_KABEL))
        self.obl_zestawienie = tk.StringVar()              # własny plik zestawienia (puste = z DXF)
        # opcje rysunków stałych
        self.orient_szablon = tk.StringVar()
        self.orient_zasiegi = tk.StringVar()               # plik PZT: zasięgi stacji + słupy (miejscowości)
        self.orient_podklad = tk.BooleanVar(value=True)
        self.orient_pdf = tk.BooleanVar(value=True)       # osobny PDF dla każdej stacji
        self.pdf_folder = tk.StringVar()                   # folder na PDF (puste = obok rysunków)
        # opcje arkuszy PZT
        self.pzt_wzorzec = tk.StringVar()                  # plik z layoutem-wzorcem "a" (puste = plan)
        self.pzt_zaklad = tk.StringVar(value="50")
        # Warunki Techniczne (WT) - źródło miejscowości słupów (wspólne dla PZT/orientacji/opisów)
        self.wt_plik = tk.StringVar()                      # plik WT (.xls/.xlsx); puste = geokodowanie
        self.wt_program = tk.StringVar(value=self.ust.get("generator_wt", ""))   # folder/exe Generatora WT
        self._wt_proces = None                             # uruchomiony Generator WT
        self._wt_start = 0.0
        # opcje opisów technicznych (.docx)
        self.opisy_szablon = tk.StringVar()                # szablon .docx (puste = dołączony)
        self.opisy_zestawienie = tk.StringVar()            # xlsx (puste = z Rysunków stałych)
        self.opisy_obliczenia = tk.StringVar()             # xlsx obliczeń (puste = bez tabeli nośności)
        # opcje PPW (zbiorczy opis .docx)
        self.ppw_szablon = tk.StringVar()                  # szablon .docx (puste = dołączony)
        self.ppw_zestawienie = tk.StringVar()              # xlsx z modułu „zestawienie”
        self.ppw_zestawienie_stacji = tk.StringVar()       # xlsx z Rysunków stałych (miejscowości)
        self.ppw_renumer_dxf = tk.StringVar()              # DXF do renumeracji numerów rysunku
        # opcje zakładek (strony-przekładki: nr stacji / miejscowość / WT)
        self.zakladki_zestawienie = tk.StringVar()         # xlsx (puste = z Rysunków stałych)
        self.zakladki_format = tk.StringVar(value="docx")  # przełącznik formatu: docx / pdf

        # numery WT (ręcznie) - zapamiętywane między uruchomieniami; pusty moduł dostaje
        # ostatnio użyty numer z historii
        zapisane = self.ust.get("wt", {}) if isinstance(self.ust.get("wt"), dict) else {}
        historia = self._historia_wt()
        self.wt = {}
        for m in MODULY_WT:
            v = tk.StringVar(value=zapisane.get(m) or (historia[0] if historia else ""))
            v.trace_add("write", lambda *_: self._zaplanuj_zapis())
            self.wt[m] = v
        self.opisy_wt, self.ppw_wt, self.zakladki_wt = (self.wt[m] for m in MODULY_WT)

        # pola wypełnione automatycznie wynikami tej sesji: nazwa zmiennej -> wpisana ścieżka
        # (tylko w pamięci - nowa sesja programu zaczyna od pustych pól)
        self._podpiete: dict[str, str] = {}
        self._watek = None                                 # wątek roboczy bieżącego modułu
        self._kroki_biezace = ()                           # moduł(y) bieżącego uruchomienia (do dziennika)

        self.projekt = tk.StringVar()                      # folder bieżącego projektu ("" = brak)

        self._przyciski = []                               # przyciski "Generuj" do blokowania
        self._strony = {}                                  # klucz -> ramka strony modułu
        self._wybrana = tk.StringVar()
        self._ustaw_motyw(self.motyw.get())
        self._buduj()
        root.protocol("WM_DELETE_WINDOW", self._zamknij)
        # ostatni projekt wraca przy starcie - wszystkie zakładki od razu wypełnione
        ostatni = self.ust.get("projekt_ostatni")
        if ostatni and os.path.isfile(projekt.sciezka(ostatni)):
            self._otworz_projekt(ostatni, cicho=True)
        # przeciąganie plików z Eksploratora na okno (Windows)
        from . import upusc
        upusc.wlacz(root, self._upuszczono)

    # ================================================================= przeciąganie plików
    def _upuszczono(self, pliki, x, y):
        """Pliki upuszczone na okno: na pole - do tego pola; gdzie indziej - pole dobrane po typie
        pliku i bieżącej zakładce; plik projektu - otwarcie projektu."""
        zmienne = {str(v): v for v in self._pola_projektu().values()}
        pod = self.root.winfo_containing(x, y)
        try:
            nazwa_zm = str(pod.cget("textvariable")) if pod is not None else ""
        except tk.TclError:
            nazwa_zm = ""
        wskazane = zmienne.get(nazwa_zm)
        for p in pliki:
            p = os.path.normpath(p)
            if os.path.basename(p).lower() == projekt.NAZWA_PLIKU.lower() or (
                    os.path.isdir(p) and os.path.isfile(projekt.sciezka(p))):
                self._otworz_projekt(p)
                continue
            cel = wskazane if (wskazane is not None and len(pliki) == 1) else self._pole_dla(p)
            if cel is None:
                self.status.configure(text=f"Nie wiem, gdzie wpisać „{os.path.basename(p)}” na tej zakładce — "
                                           "upuść plik bezpośrednio na pole.")
                continue
            cel.set(p)
            self._podpiete.pop(str(cel), None)            # wybór użytkownika - nie nadpisuj wynikami
            self.status.configure(text=f"Wpisano: {os.path.basename(p)}")

    def _pole_dla(self, p):
        """Pole dla upuszczonego pliku wg rozszerzenia i bieżącej zakładki (albo None)."""
        strona = self._wybrana.get()
        nazwa = os.path.basename(p).lower()
        ext = os.path.splitext(nazwa)[1]
        if os.path.isdir(p):
            return self.katalog
        if ext in (".dxf", ".dwg"):
            if strona in ("numeracja", "przewieszenia", "zestawienie", "obliczenia", "pzt"):
                return self.we[strona]
            if strona == "orientacje":
                return self.orient_zasiegi if "pzt" in nazwa else self.we["orientacje"]
            if strona == "ppw":
                return self.ppw_renumer_dxf
            if strona == "wt" and hasattr(self, "zakladka_wt"):
                return self.zakladka_wt.plik
        if ext in (".xlsx", ".xls"):
            return {"obliczenia": self.obl_zestawienie,
                    "opisy": self.opisy_obliczenia if nazwa.startswith("obliczenia") else self.opisy_zestawienie,
                    "ppw": self.ppw_zestawienie_stacji if "zestawienie_stacji" in nazwa else self.ppw_zestawienie,
                    "zakladki": self.zakladki_zestawienie,
                    "pzt": self.wt_plik, "orientacje": self.wt_plik, "wt": self.wt_plik}.get(strona)
        if ext == ".docx":
            return {"opisy": self.opisy_szablon, "ppw": self.ppw_szablon}.get(strona)
        return None

    # ================================================================= projekt
    def _pola_projektu(self) -> dict:
        """Pola okna zapisywane w projekcie: klucz -> zmienna tk."""
        pola = {f"plik_{k}": v for k, v in self.we.items()}
        for nazwa in ("katalog", "pw_obrot", "obl_seed", "obl_kabel", "obl_zestawienie", "orient_szablon",
                      "orient_zasiegi", "orient_podklad", "orient_pdf", "pdf_folder", "pzt_wzorzec", "pzt_zaklad", "wt_plik",
                      "opisy_szablon", "opisy_zestawienie", "opisy_obliczenia", "ppw_szablon", "ppw_zestawienie",
                      "ppw_zestawienie_stacji", "ppw_renumer_dxf", "zakladki_zestawienie", "zakladki_format",
                      "adresy_on"):
            pola[nazwa] = getattr(self, nazwa)
        for m, v in self.wt.items():
            pola[f"wt_{m}"] = v
        if hasattr(self, "zakladka_wt"):
            pola["wt_plan"] = self.zakladka_wt.plik        # plan warunków technicznych (moduł nr 1)
        return pola

    def _zapisz_projekt(self):
        folder = self.projekt.get()
        if not folder or not os.path.isdir(folder):
            return
        pola = self._pola_projektu()
        auto = [k for k, v in pola.items() if str(v) in self._podpiete and v.get() == self._podpiete[str(v)]]
        try:
            projekt.zapisz(folder, {k: v.get() for k, v in pola.items()}, auto)
        except OSError:
            pass

    def _ustaw_projekt(self, folder):
        folder = os.path.normpath(folder)
        self.projekt.set(folder)
        self.ust["projekt_ostatni"] = folder
        self.ust["projekty"] = projekt.dopisz_ostatni(self.ust.get("projekty") or [], folder)
        self._odswiez_ostatnie()
        self._zaplanuj_zapis()
        self._sugeruj_folder_pdf()

    def _sugeruj_folder_pdf(self):
        """Podpowiedź folderu na PDF: „<folder projektu>\\PDF” (stała struktura projektów).
        Wpisywana, gdy pole jest puste albo wypełnił je wcześniej program - wybór ręczny zostaje."""
        folder = self.projekt.get()
        if not folder:
            return
        teraz = self.pdf_folder.get().strip()
        if teraz and teraz != self._podpiete.get(str(self.pdf_folder)):
            return
        sugestia = os.path.join(folder, "PDF")
        self.pdf_folder.set(sugestia)
        self._podpiete[str(self.pdf_folder)] = sugestia

    def _otworz_projekt(self, folder_lub_plik, cicho=False):
        dane = projekt.wczytaj(folder_lub_plik)
        if dane is None:
            if not cicho:
                messagebox.showwarning(TYTUL, "Nie udało się wczytać projektu (brak pliku "
                                              f"„{projekt.NAZWA_PLIKU}” albo plik uszkodzony).", parent=self.root)
            return
        if self.projekt.get():
            self._zapisz_projekt()                         # poprzedni projekt nie traci zmian
        pola = self._pola_projektu()
        self._podpiete.clear()
        self.pdf_folder.set("")                          # brak w starszym projekcie -> podpowiedź
        for k, wartosc in (dane.get("pola") or {}).items():
            if k in pola:
                try:
                    pola[k].set(wartosc)
                except (tk.TclError, ValueError):
                    pass
        for k in dane.get("auto") or []:
            if k in pola:
                self._podpiete[str(pola[k])] = pola[k].get()
        self._ustaw_projekt(projekt.folder(projekt.sciezka(folder_lub_plik)))
        if hasattr(self, "log"):
            self._pisz(f"Projekt: {self.projekt.get()}")

    def _wybierz_projekt(self):
        p = filedialog.askopenfilename(parent=self.root, title="Otwórz projekt (plik projektu albo plan w folderze)",
                                       filetypes=[("Projekt GeneratorNN", projekt.NAZWA_PLIKU),
                                                  ("Wszystkie pliki", "*.*")])
        if not p:
            return
        folder = os.path.dirname(p)
        if os.path.isfile(projekt.sciezka(folder)):
            self._otworz_projekt(folder)
        else:                                              # folder bez projektu - nowy projekt w nim
            self._nowy_projekt(folder)

    def _nowy_projekt(self, folder=None):
        if self.projekt.get():
            self._zapisz_projekt()
        # czyszczone są pola plików; opcje i numery WT zostają jak były
        pliki = ("katalog", "obl_zestawienie", "orient_szablon", "orient_zasiegi", "pzt_wzorzec", "wt_plik",
                 "opisy_szablon", "opisy_zestawienie", "opisy_obliczenia", "ppw_szablon", "ppw_zestawienie",
                 "ppw_zestawienie_stacji", "ppw_renumer_dxf", "zakladki_zestawienie", "pdf_folder", "wt_plan")
        for k, v in self._pola_projektu().items():
            if k.startswith("plik_") or k in pliki:
                v.set("")
        self._podpiete.clear()
        if folder:
            self._ustaw_projekt(folder)
            self._zapisz_projekt()
        else:
            self.projekt.set("")
            self.ust["projekt_ostatni"] = ""
            self._zaplanuj_zapis()

    def _odswiez_ostatnie(self):
        if not hasattr(self, "menu_ostatnie"):
            return
        self.menu_ostatnie.delete(0, "end")
        lista = [f for f in (self.ust.get("projekty") or []) if os.path.isfile(projekt.sciezka(f))]
        for f in lista:
            self.menu_ostatnie.add_command(label=f, command=lambda f=f: self._otworz_projekt(f))
        if not lista:
            self.menu_ostatnie.add_command(label="(brak)", state="disabled")

    def _sprawdz_plan(self):
        """Szybka kontrola planu (warstwy, bloki, opisy, layout „a”) i gotowość modułów."""
        if self.pracuje:
            return
        kandydaci = [self.we.get(self._wybrana.get(), tk.StringVar()).get().strip()]
        kandydaci += [self.we[k].get().strip() for k in ("numeracja", "przewieszenia", "zestawienie",
                                                          "obliczenia", "pzt")]
        plan = next((p for p in kandydaci if p and os.path.isfile(p) and p.lower().endswith((".dxf", ".dwg"))),
                    None)
        if not plan:
            plan = filedialog.askopenfilename(parent=self.root, title="Plan DXF/DWG do sprawdzenia",
                                              filetypes=DXF_TYPY)
            if not plan:
                return
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.status.configure(text=f"Sprawdzam plan: {os.path.basename(plan)}…")
        self.root.configure(cursor="watch")

        def praca():
            from . import dwg, sprawdz_plan
            wej = dwg.Wejscia(log=lambda *_: None)
            try:
                raport = sprawdz_plan.sprawdz(wej.dxf(plan))
                raport.plik = plan
                self._kolejka_spr.put(raport)
            except BaseException as ex:  # noqa: BLE001
                self._kolejka_spr.put(ex)
            finally:
                wej.sprzatnij()

        self._kolejka_spr = queue.Queue()
        threading.Thread(target=praca, daemon=True).start()
        self.root.after(80, self._odbierz_sprawdzenie)

    def _odbierz_sprawdzenie(self):
        try:
            wynik = self._kolejka_spr.get_nowait()
        except queue.Empty:
            self.root.after(80, self._odbierz_sprawdzenie)
            return
        self.root.configure(cursor="")
        if isinstance(wynik, BaseException):
            self._pisz(f"BŁĄD sprawdzania planu: {wynik}")
            self.status.configure(text="Nie udało się sprawdzić planu — szczegóły w oknie „Przebieg”.")
            return
        self._pisz(wynik.tekst())
        niegotowe = [n for n, gotowy, _ in wynik.moduly if not gotowy]
        self.status.configure(text=("Plan gotowy dla wszystkich modułów." if not niegotowe else
                                    f"Plan: brakuje danych dla: {', '.join(niegotowe)} — szczegóły w „Przebiegu”."))

    def _projekt_przy_uruchomieniu(self, plik):
        """Brak projektu - zakłada go w folderze planu (pierwszy plik DXF/DWG modułów)."""
        if self.projekt.get():
            return
        for k in ("numeracja", "przewieszenia", "zestawienie", "obliczenia", "pzt"):
            p = self.we[k].get().strip()
            if p and os.path.isfile(p):
                self._ustaw_projekt(os.path.dirname(os.path.abspath(p)))
                return
        if plik and os.path.isfile(plik):
            self._ustaw_projekt(os.path.dirname(os.path.abspath(plik)))

    # ================================================================= ustawienia
    def _historia_wt(self) -> list:
        h = self.ust.get("wt_historia", [])
        return [str(x) for x in h] if isinstance(h, list) else []

    def _zaplanuj_zapis(self):
        """Zapis ustawień z opóźnieniem (nie przy każdym naciśnięciu klawisza)."""
        if self._zapis_id is not None:
            self.root.after_cancel(self._zapis_id)
        self._zapis_id = self.root.after(700, self._zapisz_ustawienia)

    def _zapisz_ustawienia(self, do_historii: str | None = None):
        self._zapis_id = None
        self.ust["wt"] = {m: self.wt[m].get().strip() for m in MODULY_WT}
        if do_historii:
            self.ust["wt_historia"] = ustawienia.dopisz_do_historii(self._historia_wt(), do_historii)
        self.ust["motyw"] = self.motyw.get()
        self.ust["zapis_dwg"] = self.eksport_dwg.get()
        self.ust["modul"] = self._wybrana.get()
        ustawienia.zapisz(self.ust)

    def _zamknij(self):
        if self._zapis_id is not None:
            self.root.after_cancel(self._zapis_id)
        self._zapisz_ustawienia()
        self._zapisz_projekt()
        self.root.destroy()

    # ================================================================= wygląd
    def _ustaw_motyw(self, nazwa: str):
        nazwa = "dark" if nazwa == "dark" else "light"
        k = KOLORY[nazwa]
        st = ttk.Style(self.root)
        if sv_ttk is not None:
            sv_ttk.set_theme(nazwa, self.root)
        else:
            try:
                st.theme_use("clam")
            except tk.TclError:
                pass
            tlo = "#FAFAFA" if nazwa == "light" else "#1F1F1F"
            tekst = "#1F2328" if nazwa == "light" else "#E6E6E6"
            self.root.configure(background=tlo)
            st.configure(".", background=tlo, foreground=tekst)
            st.configure("TEntry", fieldbackground=k["log_bg"], foreground=tekst)
            st.configure("TCombobox", fieldbackground=k["log_bg"], foreground=tekst)
            st.configure("Accent.TButton", background=k["akcent"],
                         foreground="#FFFFFF" if nazwa == "light" else "#000000")
            st.map("Accent.TButton", background=[("active", k["akcent"]), ("disabled", "#9AA0A6")])
        f = _czcionka_ui()
        # style konfiguruje się per motyw - ustawiamy je po każdej zmianie motywu
        st.configure("Hint.TLabel", foreground=k["hint"])
        st.configure("Tytul.TLabel", font=(f, 17, "bold"))
        st.configure("Podtytul.TLabel", foreground=k["hint"], font=(f, 10))
        st.configure("Strona.TLabel", font=(f, 15, "bold"))
        st.configure("Opis.TLabel", foreground=k["hint"], font=(f, 10))
        st.configure("Sekcja.TLabel", font=(f, 10, "bold"))
        st.configure("Nav.Toggle.TButton", anchor="w", padding=(14, 5), font=(f, 10))
        if sv_ttk is None:
            st.map("Nav.Toggle.TButton", background=[("selected", k["akcent"])],
                   foreground=[("selected", "#FFFFFF" if nazwa == "light" else "#000000")])
        st.configure("Accent.TButton", padding=(18, 8))
        if hasattr(self, "log"):
            self.log.configure(background=k["log_bg"], foreground=k["log_fg"],
                               insertbackground=k["log_fg"])
        if hasattr(self, "plotno"):
            self.plotno.configure(background=st.lookup("TFrame", "background") or k["naglowek_bg"])
        if getattr(self, "_logo", None) and hasattr(self, "lbl_logo"):
            self.lbl_logo.configure(image=self._logo[nazwa])
        self.motyw.set(nazwa)

    def _wczytaj_logo(self):
        """Logo MMUI dla obu motywów w rozmiarze pasującym do skalowania ekranu (albo None).

        PNG są wyrenderowane z SVG skryptem narzedzia/renderuj_logo.py - Tk wczytuje je
        bez dodatkowych bibliotek."""
        katalog = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grafika")
        try:
            skala = self.root.winfo_fpixels("1i") / 96 * 100
        except tk.TclError:
            skala = 100
        najblizsza = min((100, 125, 150, 200), key=lambda s: abs(s - skala))
        try:
            return {m: tk.PhotoImage(master=self.root,
                                     file=os.path.join(katalog, f"logo_{nazwa}_{najblizsza}.png"))
                    for m, nazwa in (("light", "jasny"), ("dark", "ciemny"))}
        except tk.TclError:            # brak plików logo - okno działa bez niego
            return None

    def _przelacz_motyw(self):
        self._ustaw_motyw("light" if self.motyw.get() == "dark" else "dark")
        self.btn_motyw.configure(text=self._tekst_motywu())
        self._zaplanuj_zapis()

    def _tekst_motywu(self):
        return "☀  Tryb jasny" if self.motyw.get() == "dark" else "☾  Tryb ciemny"

    # ================================================================= budowa UI
    def _buduj(self):
        root = self.root
        root.columnconfigure(0, weight=1)

        # --- nagłówek
        gora = ttk.Frame(root, padding=(20, 14, 20, 8))
        gora.grid(row=0, column=0, sticky="we")
        gora.columnconfigure(0, weight=1)
        linia = ttk.Frame(gora)
        linia.grid(row=0, column=0, sticky="w")
        ttk.Label(linia, text=TYTUL, style="Tytul.TLabel").pack(side="left")
        ttk.Label(linia, text=f"wersja {wersja()}", style="Podtytul.TLabel").pack(
            side="left", padx=(12, 0), pady=(6, 0))
        ttk.Label(gora, text=PODTYTUL, style="Podtytul.TLabel").grid(row=1, column=0, sticky="w")
        self.btn_motyw = ttk.Button(gora, text=self._tekst_motywu(), command=self._przelacz_motyw)
        self.btn_motyw.grid(row=0, column=1, rowspan=2, sticky="e")
        # logo w prawym górnym rogu (PNG - wersja czarna/biała zależnie od motywu)
        self._logo = self._wczytaj_logo()
        if self._logo:
            self.lbl_logo = ttk.Label(gora, image=self._logo[self.motyw.get()])
            self.lbl_logo.grid(row=0, column=2, rowspan=2, sticky="e", padx=(18, 0))

        # --- pasek projektu: zapamiętane pliki i opcje wszystkich modułów dla jednego zadania
        pasek = ttk.Frame(gora)
        pasek.grid(row=2, column=0, columnspan=3, sticky="we", pady=(10, 0))
        pasek.columnconfigure(1, weight=1)
        ttk.Label(pasek, text="Projekt:", style="Sekcja.TLabel").grid(row=0, column=0, sticky="w")
        self._opis_projektu = tk.StringVar()
        ttk.Label(pasek, textvariable=self._opis_projektu, style="Hint.TLabel").grid(
            row=0, column=1, sticky="w", padx=(8, 8))
        ttk.Button(pasek, text="Otwórz…", command=self._wybierz_projekt).grid(row=0, column=2, padx=2)
        mb = ttk.Menubutton(pasek, text="Ostatnie")
        self.menu_ostatnie = tk.Menu(mb, tearoff=False)
        mb.configure(menu=self.menu_ostatnie)
        mb.grid(row=0, column=3, padx=2)
        ttk.Button(pasek, text="Nowy", command=self._nowy_projekt).grid(row=0, column=4, padx=(2, 0))
        ttk.Button(pasek, text="✔ Sprawdź plan", command=self._sprawdz_plan).grid(row=0, column=5, padx=(12, 0))
        self.projekt.trace_add("write", lambda *_: self._opis_projektu.set(
            self.projekt.get() or "brak — założy się sam w folderze planu przy pierwszym uruchomieniu modułu"))
        self.projekt.set(self.projekt.get())
        self._odswiez_ostatnie()

        # --- panel boczny + strony modułów (przewijane, gdy strona nie mieści się w oknie)
        root.rowconfigure(1, weight=1)
        root.rowconfigure(2, weight=0)
        srodek = ttk.Frame(root, padding=(12, 4, 8, 4))
        srodek.grid(row=1, column=0, sticky="nsew")
        srodek.columnconfigure(2, weight=1)
        srodek.rowconfigure(0, weight=1)

        self.nav = ttk.Frame(srodek, padding=(0, 0, 12, 0))
        self.nav.grid(row=0, column=0, sticky="ns")
        ttk.Label(self.nav, text="MODUŁY", style="Hint.TLabel").pack(anchor="w", padx=14, pady=(2, 6))
        ttk.Separator(srodek, orient="vertical").grid(row=0, column=1, sticky="ns")

        self.plotno = tk.Canvas(srodek, highlightthickness=0, borderwidth=0)
        self.plotno.grid(row=0, column=2, sticky="nsew", padx=(20, 0))
        self.przewijanie = ttk.Scrollbar(srodek, orient="vertical", command=self.plotno.yview)
        self.plotno.configure(yscrollcommand=self.przewijanie.set)
        self.kontener = ttk.Frame(self.plotno)
        self.kontener.columnconfigure(0, weight=1)
        self._okno_kontenera = self.plotno.create_window(0, 0, window=self.kontener, anchor="nw")
        self.kontener.bind("<Configure>", lambda e: self._dopasuj_przewijanie())
        self.plotno.bind("<Configure>", lambda e: (
            self.plotno.itemconfigure(self._okno_kontenera, width=e.width), self._dopasuj_przewijanie()))
        self.plotno.bind_all("<MouseWheel>", self._kolko_myszy, add="+")
        self._srodek = srodek

        self._zakladka_generator_wt()
        self._zakladka_numeracja()
        self._zakladka_zestawienie()
        self._zakladka_obliczenia()
        self._zakladka_pzt()
        self._zakladka_orientacje()
        self._zakladka_opisy()
        self._zakladka_przewieszenia()
        self._zakladka_ppw()
        self._zakladka_zakladki()

        start = self.ust.get("modul")
        self._pokaz(start if start in self._strony else next(iter(self._strony)))

        self._dol(root)
        self._ustaw_motyw(self.motyw.get())               # kolory dziennika (utworzonego w _dol)

    def _strona(self, klucz, tytul_nav, tytul, opis):
        """Nowa strona modułu + pozycja w panelu bocznym. Zwraca ramkę na zawartość."""
        f = ttk.Frame(self.kontener, padding=(0, 0, 12, 8))
        ttk.Label(f, text=tytul, style="Strona.TLabel").pack(anchor="w", pady=(2, 2))
        ttk.Label(f, text=opis, style="Opis.TLabel", wraplength=700,
                  justify="left").pack(anchor="w", pady=(0, 10))
        self._strony[klucz] = f
        ttk.Radiobutton(self.nav, text=tytul_nav, value=klucz, variable=self._wybrana,
                        style="Nav.Toggle.TButton", command=lambda: self._pokaz(klucz)).pack(fill="x", pady=1)
        return f

    def _pokaz(self, klucz):
        """Pokazuje stronę modułu (tylko jedna w kontenerze - przewijanie dopasowane do niej)."""
        self._wybrana.set(klucz)
        for k, f in self._strony.items():
            if k == klucz:
                f.grid(row=0, column=0, sticky="nsew")
            else:
                f.grid_remove()
        self.plotno.yview_moveto(0)
        if self._zapis_id is None and hasattr(self, "log"):
            self._zaplanuj_zapis()

    def _dopasuj_przewijanie(self):
        self.plotno.configure(scrollregion=self.plotno.bbox("all"))
        potrzebne = self.kontener.winfo_reqheight() > self.plotno.winfo_height() > 1
        if potrzebne:
            self.przewijanie.grid(row=0, column=3, sticky="ns")
        else:
            self.przewijanie.grid_remove()
            self.plotno.yview_moveto(0)

    def _kolko_myszy(self, e):
        """Kółko myszy przewija stronę modułu (gdy kursor jest nad nią i strona jest dłuższa niż okno)."""
        try:
            w = self.root.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):    # np. rozwinięta lista Combobox
            return
        while w is not None and w is not self.plotno:
            w = w.master
        if w is self.plotno and self.przewijanie.winfo_ismapped():
            self.plotno.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")

    def _sekcja(self, ramka, tytul):
        ttk.Label(ramka, text=tytul, style="Sekcja.TLabel").pack(anchor="w", pady=(10, 2))
        box = ttk.Frame(ramka)
        box.pack(fill="x")
        return box

    def _podpowiedz(self, ramka, tekst, padx=0):
        ttk.Label(ramka, text=tekst, style="Hint.TLabel", wraplength=700,
                  justify="left").pack(anchor="w", padx=padx, pady=(0, 4))

    def _pole_pliku(self, ramka, etykieta, var, tytul, typy=DXF_TYPY):
        f = ttk.Frame(ramka)
        f.pack(fill="x", pady=4)
        ttk.Label(f, text=etykieta, width=24).pack(side="left")
        ttk.Entry(f, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f, text="Wybierz…",
                   command=lambda: _wybierz_plik(self.root, var, tytul, typy)).pack(side="left")

    def _pole_folderu(self, ramka, etykieta, var, tytul):
        """Pole z wyborem FOLDERU (jak „Katalog zapisu”)."""
        f = ttk.Frame(ramka)
        f.pack(fill="x", pady=4)
        ttk.Label(f, text=etykieta, width=24).pack(side="left")
        ttk.Entry(f, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f, text="Wybierz…", command=lambda: self._wybierz_folder(var, tytul)).pack(side="left")

    def _wybierz_folder(self, var, tytul):
        p = filedialog.askdirectory(parent=self.root, title=tytul, initialdir=var.get() or self.projekt.get() or None)
        if p:
            var.set(os.path.normpath(p))

    def _pole_wt(self, ramka, var, przyklad):
        """Pole numeru WT: lista rozwijana z historią wcześniej użytych numerów."""
        r = ttk.Frame(ramka)
        r.pack(fill="x", pady=4)
        ttk.Label(r, text="Numer warunków (WT):", width=24).pack(side="left")
        cb = ttk.Combobox(r, textvariable=var, width=30, values=self._historia_wt())
        cb.configure(postcommand=lambda: cb.configure(values=self._historia_wt()))
        cb.pack(side="left", padx=6)
        self._podpowiedz(ramka, f"(jeden wspólny numer — np. {przyklad}; zapamiętywany na następne "
                                "uruchomienia, wcześniejsze numery na liście rozwijanej)")

    def _pole_internetu(self, ramka):
        """Przełącznik pobierania nazw z internetu - tylko w modułach, które z niego korzystają
        (Przewieszenia, Arkusze PZT); wspólna zmienna, więc ustawienie jest jedno."""
        ttk.Checkbutton(ramka, text="Nazwy miejscowości i ulic z internetu (GUGiK / OpenStreetMap)",
                        variable=self.adresy_on).pack(anchor="w", pady=(6, 0))
        self._podpowiedz(ramka, "(wyłączone = program działa bez internetu, bez nazw ulic/miejscowości)")

    def _przycisk_generuj(self, ramka, tekst, komenda):
        b = ttk.Button(ramka, text="▶  " + tekst, command=komenda, style="Accent.TButton")
        b.pack(anchor="w", pady=(14, 6))
        self._przyciski.append(b)
        return b

    # ---------------------------------------------------------------- strony modułów
    # ---------------------------------------------------------------- moduł nr 1: Generator WT
    def _zakladka_generator_wt(self):
        from . import generator_wt_start as gwt
        from .zakladka_wt import ZakladkaWT
        f = self._strona("wt", "1. Warunki techniczne", "Warunki techniczne (Generator WT)",
                         "Etap warunków technicznych: analiza planu, numeracja słupów, pismo „Zapytanie o możliwość "
                         "dostępu do słupów”, zestawienia (uproszczone .xls, rozbudowane, tabela projektowa), "
                         "arkusze 1:1000 i plan orientacyjny. Zestawienie uproszczone podpina się do dalszych modułów.")
        if not gwt.czy_generator_wt(self.wt_program.get()):
            znaleziony = gwt.znajdz_generator_wt([self.projekt.get()])
            if znaleziony:
                self.wt_program.set(znaleziony)
        # natywne okno Generatora WT (rdzeń generator.warunki ładowany dopiero przy użyciu)
        self.zakladka_wt = ZakladkaWT(self, f)

        # pełny Generator WT w osobnym oknie - opcjonalnie (wszystkie jego funkcje są już w zakładce)
        box = self._sekcja(f, "Pełny Generator WT (osobne okno)")
        self._podpowiedz(box, "(opcjonalnie - wszystkie funkcje Generatora WT są już w tej zakładce; "
                              "tu można uruchomić dotychczasowy program i podpiąć jego wyniki)")
        r = ttk.Frame(box)
        r.pack(fill="x", pady=4)
        ttk.Label(r, text="Program Generator WT:", width=24).pack(side="left")
        ttk.Entry(r, textvariable=self.wt_program).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r, text="Wskaż…", command=self._wskaz_generator_wt).pack(side="left")
        r = ttk.Frame(box)
        r.pack(fill="x", pady=(4, 2))
        ttk.Button(r, text="Uruchom pełny Generator WT", command=self._uruchom_generator_wt).pack(side="left")
        ttk.Button(r, text="Podepnij wyniki WT z folderu projektu",
                   command=lambda: self._podepnij_wt(0.0)).pack(side="left", padx=6)
        f = box
        self._podpowiedz(f, "(zestawienie uproszczone *_uproszczona.xls trafia do pola „Warunki techniczne” - "
                            "korzystają z niego Arkusze PZT, Rysunki stałe i Opisy; pozostałe wyniki są wypisywane "
                            "w „Przebiegu”)")
        self.wt_stan = ttk.Label(f, text="", style="Hint.TLabel")
        self.wt_stan.pack(anchor="w", pady=(6, 0))

    def _wskaz_generator_wt(self):
        from . import generator_wt_start as gwt
        p = filedialog.askopenfilename(parent=self.root, title="Generator WT: uruchom.pyw albo Generator WT.exe",
                                       filetypes=[("Generator WT", "uruchom.pyw *.exe"), ("Wszystkie pliki", "*.*")])
        if not p:
            return
        sciezka = p if p.lower().endswith(".exe") else os.path.dirname(p)
        if not gwt.czy_generator_wt(os.path.normpath(sciezka)):
            messagebox.showwarning(TYTUL, "To nie wygląda na Generator WT (brak uruchom.pyw i folderu generator_wt).",
                                   parent=self.root)
            return
        self.wt_program.set(os.path.normpath(sciezka))
        self.ust["generator_wt"] = self.wt_program.get()
        self._zaplanuj_zapis()

    def _uruchom_generator_wt(self):
        import time

        from . import generator_wt_start as gwt
        if self._wt_proces is not None and self._wt_proces.poll() is None:
            self.status.configure(text="Generator WT jest już uruchomiony.")
            return
        sciezka = self.wt_program.get().strip()
        if not gwt.czy_generator_wt(sciezka):
            messagebox.showwarning(TYTUL, "Wskaż program Generator WT (przycisk „Wskaż…”).", parent=self.root)
            return
        try:
            self._wt_proces = gwt.uruchom(sciezka)
        except OSError as ex:
            messagebox.showerror(TYTUL, f"Nie udało się uruchomić Generatora WT:\n{ex}", parent=self.root)
            return
        self.ust["generator_wt"] = sciezka
        self._zaplanuj_zapis()
        self._wt_start = time.time() - 2
        self.wt_stan.configure(text="Generator WT działa w osobnym oknie - po jego zamknięciu wyniki zostaną podpięte.")
        self.status.configure(text="Uruchomiono Generator WT.")
        self.root.after(2000, self._czekaj_na_wt)

    def _czekaj_na_wt(self):
        if self._wt_proces is None:
            return
        if self._wt_proces.poll() is None:
            self.root.after(2000, self._czekaj_na_wt)
            return
        self._wt_proces = None
        self.wt_stan.configure(text="Generator WT zamknięty.")
        self._podepnij_wt(self._wt_start)

    def _podepnij_wt(self, od_czasu):
        """Wyniki Generatora WT z folderu projektu: wypis w dzienniku, .xls do pola „Warunki techniczne”."""
        from . import generator_wt_start as gwt
        folder = self.projekt.get()
        if not folder:
            folder = filedialog.askdirectory(parent=self.root, title="Folder projektu (z wynikami Generatora WT)")
            if not folder:
                return
            self._ustaw_projekt(folder)
        wyniki = gwt.znajdz_wyniki(folder, od_czasu)
        if not wyniki:
            self._pisz("Generator WT: brak nowych wyników w folderze projektu." if od_czasu else
                       "Generator WT: w folderze projektu nie ma jego wyników.")
            return
        self._pisz("WYNIKI GENERATORA WT:")
        for przyrostek, opis in gwt.WYNIKI:
            if przyrostek in wyniki:
                self._pisz(f"  {opis}: {wyniki[przyrostek]}")
        xls = wyniki.get("_uproszczona.xls")
        if xls:
            teraz = self.wt_plik.get().strip()
            if not teraz or teraz == self._podpiete.get(str(self.wt_plik)):
                self.wt_plik.set(os.path.normpath(xls))
                self._podpiete[str(self.wt_plik)] = self.wt_plik.get()
                self._pisz(f"  PODPIĘTO: Arkusze PZT / Rysunki stałe / Opisy (warunki techniczne) ← {os.path.basename(xls)}")
            else:
                self._pisz("  (pole „Warunki techniczne” ma plik wybrany ręcznie - nie zmieniono)")
        self._zapisz_projekt()
        self.status.configure(text=f"Generator WT: znaleziono {len(wyniki)} wynik(ów).")

    def _zakladka_numeracja(self):
        f = self._strona("numeracja", "Numeracja słupów", "Numeracja słupów",
                         "Automatyczna numeracja słupów nN. W planie zaznacz ręcznie numery „1” i „2” "
                         "dwóch pierwszych słupów każdego obwodu (warstwa _numery) oraz opis „obw. nr X” "
                         "(grot na pierwszym przęśle). Program ponumeruje resztę i utworzy "
                         "„… - ponumerowane.dxf” z numerami i obrysami kontrolnymi. Wymaga biblioteki ezdxf.")
        self._pole_pliku(f, "Plik planu DXF/DWG:", self.we["numeracja"], "Wybierz plik planu (DXF/DWG)")
        self._przycisk_generuj(f, "Ponumeruj słupy", lambda: self._start_modul("numeracja"))

    def _zakladka_przewieszenia(self):
        f = self._strona("przewieszenia", "Przewieszenia", "Przewieszenia",
                         "Rysunki zwisów przęseł linii nN ze światłowodem. Dodatkowo powstaje kopia planu "
                         "z numerami przewieszeń (kontrola) i sprawdzane jest przypisanie stacji trafo.")
        self._pole_pliku(f, "Plik planu DXF/DWG:", self.we["przewieszenia"], "Wybierz plik planu (DXF/DWG)")
        box = self._sekcja(f, "Opcje")
        r = ttk.Frame(box)
        r.pack(fill="x", pady=4)
        ttk.Label(r, text="Przęsła dłuższe niż [m] rysuj pionowo:").pack(side="left")
        ttk.Entry(r, textvariable=self.pw_obrot, width=6).pack(side="left", padx=6)
        self._podpowiedz(box, "(0 = tylko gdy rysunek nie mieści się poziomo w arkuszu)")
        self._pole_internetu(box)
        self._przycisk_generuj(f, "Utwórz przewieszenia", lambda: self._start_modul("przewieszenia"))

    def _zakladka_zestawienie(self):
        f = self._strona("zestawienie", "Zestawienie", "Zestawienie słupów",
                         "Zestawienie słupów nN w podziale na stacje transformatorowe (osobny arkusz na "
                         "stację, arkusz „kontrola” ze sprawdzeniem). Plik XLSX.")
        self._pole_pliku(f, "Plik planu DXF/DWG:", self.we["zestawienie"], "Wybierz plik planu (DXF/DWG)")
        self._przycisk_generuj(f, "Utwórz zestawienie", lambda: self._start_modul("zestawienie"))

    def _zakladka_obliczenia(self):
        f = self._strona("obliczenia", "Obliczenia", "Obliczenia nośności",
                         "Obliczenia nośności słupów. Podaj plan DXF/DWG (zestawienie powstanie automatycznie) "
                         "ALBO wskaż własny plik zestawienia (.xls/.xlsx) — wtedy plan nie jest potrzebny.")
        self._pole_pliku(f, "Plik planu DXF/DWG:", self.we["obliczenia"], "Wybierz plik planu (DXF/DWG)")
        self._pole_pliku(f, "Własne zestawienie (.xlsx):", self.obl_zestawienie,
                         "Wybierz własny plik zestawienia (.xls/.xlsx)", typy=XLSX_TYPY)
        self._podpowiedz(f, "(opcjonalnie — gdy podasz własne zestawienie, obliczenia liczą się z niego, "
                            "a pole „Plik planu” jest ignorowane; wypełnia się samo po module „Zestawienie”)")
        box = self._sekcja(f, "Opcje")
        r = ttk.Frame(box)
        r.pack(fill="x", pady=4)
        ttk.Label(r, text="Domyślny rodzaj kabla (1-11):").pack(side="left")
        ttk.Entry(r, textvariable=self.obl_kabel, width=5).pack(side="left", padx=6)
        ttk.Label(r, text="Ziarno losowania (powtarzalne kąty):").pack(side="left", padx=(16, 0))
        ttk.Entry(r, textvariable=self.obl_seed, width=8).pack(side="left", padx=6)
        self._przycisk_generuj(f, "Wykonaj obliczenia", self._start_obliczenia)

    def _zakladka_orientacje(self):
        f = self._strona("orientacje", "Rysunki stałe", "Rysunki stałe",
                         "Dla każdej stacji trafo z szablonu DXF/DWG powstaje osobny plan orientacyjny + "
                         "zestawienie. Nazwa miejscowości w tabelce jest ustalana z położenia słupów stacji "
                         "(wg zestawienia).")
        self._pole_pliku(f, "Szablon rysunków stałych:", self.we["orientacje"], "Wybierz szablon (DXF/DWG)")
        self._podpowiedz(f, "(puste = dołączony szablon.dxf)")
        self._pole_pliku(f, "Plik PZT (stacje i słupy):", self.orient_zasiegi,
                         "Wybierz plik PZT (zasięgi stacji !trafo_<nr> + słupy)")
        self._podpowiedz(f, "(zasięgi i odnośniki „STACJA TRAFO” stacji, których nie ma w szablonie, są brane "
                            "z tego pliku — dla każdej stacji powstaje osobny rysunek; słupy z tego pliku służą "
                            "do nazw miejscowości. Może to być też zwykły plan ze słupami. Wypełnia się samo "
                            "po module „Arkusze PZT”; puste = stacje i słupy z samego szablonu)")
        box = self._sekcja(f, "Opcje")
        ttk.Checkbutton(box, text="Pobieraj podkład mapowy (OSM/Geoportal; wymaga internetu i biblioteki Pillow)",
                        variable=self.orient_podklad).pack(anchor="w", pady=4)
        ttk.Checkbutton(box, text="Twórz PDF dla każdej stacji (osobny plik, strona na arkusz)",
                        variable=self.orient_pdf).pack(anchor="w", pady=(0, 4))
        self._pole_folderu(box, "Folder na PDF:", self.pdf_folder, "Folder na pliki PDF")
        self._podpowiedz(box, "(podpowiadany folder „PDF” w folderze projektu — folder powstanie sam; "
                              "puste = PDF obok rysunków; dotyczy też „PDF z gotowych rysunków”)")
        rp = ttk.Frame(box)
        rp.pack(fill="x", pady=(2, 4))
        ttk.Button(rp, text="PDF z gotowych rysunków…", command=self._pdf_z_gotowych).pack(side="left")
        ttk.Label(rp, text="  (wskaż folder z rysunkami DXF/DWG — PDF do „Folderu na PDF” albo obok rysunków)",
                  style="Hint.TLabel").pack(side="left")
        ttk.Button(f, text="Nazwy miejscowości…", command=self._nazwy_miejscowosci).pack(anchor="w", pady=(10, 0))
        self._przycisk_generuj(f, "Utwórz rysunki stałe", lambda: self._start_modul("orientacje"))

    def _zakladka_pzt(self):
        f = self._strona("pzt", "Arkusze PZT", "Arkusze PZT (A3 1:1000)",
                         "Dla każdej stacji trafo powstaje komplet arkuszy A3 1:1000 pokrywających całą trasę "
                         "(warstwa !tele) w zakresie stacji (poligony !trafo), przy minimalnej liczbie arkuszy. "
                         "Każdy arkusz to kopia layoutu-wzorca „a” z pliku.")
        self._pole_pliku(f, "Plik planu DXF/DWG:", self.we["pzt"], "Wybierz plik planu (DXF/DWG)")
        self._pole_pliku(f, "Plik ze wzorcem „a”:", self.pzt_wzorzec,
                         "Wybierz plik (DXF/DWG) z layoutem-wzorcem „a”")
        self._podpowiedz(f, "(puste = wzorzec „a” z pliku planu powyżej)")
        self._pole_pliku(f, "Warunki techniczne (.xls):", self.wt_plik,
                         "Wybierz plik Warunków Technicznych (.xls/.xlsx)", typy=XLSX_TYPY)
        self._podpowiedz(f, "(opcjonalnie — miejscowości słupów wg zasięgu stacji trafo z WT, zamiast "
                            "geokodowania; współrzędne PUWG2000 lub WGS84. To samo źródło zasila też "
                            "Rysunki stałe i Opisy)")
        box = self._sekcja(f, "Opcje")
        r = ttk.Frame(box)
        r.pack(fill="x", pady=4)
        ttk.Label(r, text="Zakład (wspólny odcinek sąsiednich arkuszy) [m]:").pack(side="left")
        ttk.Entry(r, textvariable=self.pzt_zaklad, width=6).pack(side="left", padx=6)
        self._pole_internetu(box)
        podglad = ttk.Frame(box)
        podglad.pack(fill="x", pady=(8, 0))
        ttk.Button(podglad, text="Podgląd i przesuwanie arkuszy…", command=self._podglad_pzt).pack(side="left")
        ttk.Label(podglad, text="  (mapa poglądowa wybranej stacji; zapisany układ jest używany przy generowaniu)",
                  style="Hint.TLabel").pack(side="left")
        ttk.Button(f, text="Nazwy miejscowości…", command=self._nazwy_miejscowosci).pack(anchor="w", pady=(10, 0))
        self._przycisk_generuj(f, "Utwórz arkusze PZT", lambda: self._start_modul("pzt"))

    # ---- ręczne poprawki nazw miejscowości (okno „Nazwy miejscowości…”) ----
    def _plik_nazw(self):
        """„nazwy miejscowości.csv” w folderze projektu (albo planu, gdy projektu jeszcze nie ma)."""
        folder = self.projekt.get()
        if not folder:
            for k in ("pzt", "numeracja", "przewieszenia", "zestawienie", "obliczenia"):
                p = self.we[k].get().strip()
                if p and os.path.isfile(p):
                    folder = os.path.dirname(os.path.abspath(p))
                    break
            folder = folder or (os.path.dirname(os.path.abspath(self.orient_zasiegi.get().strip()))
                                if self.orient_zasiegi.get().strip() else "")
        from . import nazwy
        return os.path.join(folder, nazwy.NAZWA_PLIKU) if folder else None

    def _nazwy_miejscowosci(self):
        csv_nazw = self._plik_nazw()
        if not csv_nazw:
            messagebox.showwarning(TYTUL, "Najpierw wskaż plan (albo otwórz projekt) - poprawki nazw "
                                          "zapisuję w folderze projektu.", parent=self.root)
            return
        self._projekt_przy_uruchomieniu("")
        kandydaci = [self.opisy_zestawienie.get(), self.zakladki_zestawienie.get(), self.ppw_zestawienie_stacji.get()]
        for kat in (self.katalog.get(), os.path.dirname(csv_nazw)):
            if kat:
                kandydaci.append(os.path.join(kat, "rysunki stałe", "zestawienie_stacji.xlsx"))
        zest = next((p.strip() for p in kandydaci if p and os.path.isfile(p.strip())), None)
        from .okno_nazw import OknoNazw
        OknoNazw(self.root, csv_nazw, zest, log=self._pisz)

    def _pdf_z_gotowych(self):
        """PDF z istniejącego folderu rysunków (np. „rysunki stałe”) - bez generowania ich od nowa."""
        start = next((p for p in (os.path.join(self.katalog.get(), "rysunki stałe") if self.katalog.get() else "",
                                  os.path.join(self.projekt.get(), "rysunki stałe") if self.projekt.get() else "",
                                  self.projekt.get()) if p and os.path.isdir(p)), None)
        folder = filedialog.askdirectory(parent=self.root, title="Folder z rysunkami DXF/DWG",
                                         initialdir=start)
        if folder:
            self._uruchom(os.path.normpath(folder), ("pdf",))

    def _podglad_pzt(self):
        """Okno podglądu układu arkuszy - otwierane tylko na żądanie (liczenie rozkładu w tle)."""
        plik = self.we["pzt"].get().strip()
        if not plik or not os.path.isfile(plik):
            messagebox.showwarning(TYTUL, "Wskaż istniejący plan DXF/DWG (pole „Plik planu DXF/DWG”).",
                                   parent=self.root)
            return
        okno = getattr(self, "_okno_podgladu", None)
        if okno is not None and okno.winfo_exists():
            okno.lift()
            return
        from .podglad_pzt import PodgladPZT
        self._okno_podgladu = PodgladPZT(self.root, plik, wzorzec=(self.pzt_wzorzec.get().strip() or None),
                                         zaklad=_float(self.pzt_zaklad.get(), 50.0),
                                         ciemny=self.motyw.get() == "dark")

    def _zakladka_opisy(self):
        f = self._strona("opisy", "Opisy techniczne", "Opisy techniczne (.docx)",
                         "Dla każdej stacji powstaje osobny opis techniczny .docx z szablonu Word. "
                         "Dane (nr stacji + miejscowość) bierzemy z zestawienia — można podpiąć wprost "
                         "plik „zestawienie_stacji.xlsx” z Rysunków stałych. Numer warunków (WT) wpisz ręcznie.")
        self._pole_pliku(f, "Zestawienie (.xlsx):", self.opisy_zestawienie,
                         "Wybierz zestawienie (np. z Rysunków stałych)", typy=XLSX_TYPY)
        self._podpowiedz(f, "(„zestawienie_stacji.xlsx” — wypełnia się samo po module „Rysunki stałe”)")
        self._pole_pliku(f, "Szablon opisu (.docx):", self.opisy_szablon,
                         "Wybierz szablon .docx", typy=DOCX_TYPY)
        self._podpowiedz(f, "(puste = dołączony szablon_opisu.docx; gdy wskażesz własny szablon, "
                            "opisy zapisywane są w JEGO folderze)")
        self._pole_pliku(f, "Obliczenia (.xlsx):", self.opisy_obliczenia,
                         "Wybierz plik obliczeń nośności (.xlsx)", typy=XLSX_TYPY)
        self._podpowiedz(f, "(opcjonalnie — do każdego opisu dołączana jest tabela „Zestawienie zbiorcze "
                            "słupów” z pasującego arkusza obliczeń; puste = bez tabeli nośności)")
        box = self._sekcja(f, "Dane wspólne")
        self._pole_wt(box, self.opisy_wt, "100/RE-5/KŚ/2026")
        self._przycisk_generuj(f, "Utwórz opisy .docx", self._start_opisy)

    def _start_opisy(self):
        zest = self.opisy_zestawienie.get().strip()
        if not zest or not os.path.isfile(zest):
            messagebox.showwarning(TYTUL, "Wskaż plik zestawienia (.xlsx) — np. „zestawienie_stacji.xlsx” "
                                          "z Rysunków stałych.", parent=self.root)
            return
        obl = self.opisy_obliczenia.get().strip()
        if obl and not os.path.isfile(obl):
            messagebox.showwarning(TYTUL, "Wskazany plik obliczeń (.xlsx) nie istnieje.", parent=self.root)
            return
        if not self.opisy_wt.get().strip():
            if not messagebox.askyesno(TYTUL, "Nie podano numeru warunków (WT). Opisy powstaną z pustym WT. "
                                              "Kontynuować?", parent=self.root):
                return
        self._uruchom(zest, ("opisy",), wt=self.opisy_wt.get())

    def _zakladka_ppw(self):
        f = self._strona("ppw", "PPW", "PPW (zbiorczy opis .docx)",
                         "JEDEN zbiorczy opis techniczny .docx dla CAŁEGO projektu (wszystkie stacje w jednym "
                         "pliku), z szablonu Word. Tabela „Zestawienie zbiorcze słupów” powstaje z pliku modułu "
                         "„Zestawienie”, miejscowości z „Rysunków stałych”. Numer WT wpisz ręcznie.")
        self._pole_pliku(f, "Zestawienie (.xlsx):", self.ppw_zestawienie,
                         "Wybierz zestawienie z modułu „Zestawienie”", typy=XLSX_TYPY)
        self._podpowiedz(f, "(plik z modułu „Zestawienie” — wypełnia się sam po jego uruchomieniu)")
        self._pole_pliku(f, "Miejscowości (.xlsx):", self.ppw_zestawienie_stacji,
                         "Wybierz „zestawienie_stacji.xlsx” z Rysunków stałych", typy=XLSX_TYPY)
        self._podpowiedz(f, "(„zestawienie_stacji.xlsx” z Rysunków stałych — wypełnia się samo po tym module)")
        self._pole_pliku(f, "Szablon PPW (.docx):", self.ppw_szablon, "Wybierz szablon .docx", typy=DOCX_TYPY)
        self._podpowiedz(f, "(puste = dołączony „PPW miński szablon.docx”; gdy wskażesz własny, PPW.docx "
                            "zapisze się w JEGO folderze)")
        box = self._sekcja(f, "Dane wspólne")
        self._pole_wt(box, self.ppw_wt, "100/RE-5/KŚ/2026")
        self._przycisk_generuj(f, "Utwórz PPW .docx", self._start_ppw)

        # --- renumeracja numerów rysunku w tabelkach arkuszy (DXF, osobna akcja) ---
        ren = self._sekcja(f, "Renumeracja numerów rysunku (DXF/DWG)")
        self._podpowiedz(ren, "Dla arkuszy STACJA-ARKUSZ (np. 112-1) nadaje numery rysunku w tabelkach "
                              "(112→1, wiele arkuszy → 1.1, 1.2; jeden → bez kropki) i zamienia „Projekt "
                              "wykonawczy” → „Projekt powykonawczy”. Tworzy „PPW <nazwa pliku>.dxf”.")
        self._pole_pliku(ren, "Plik DXF/DWG (PZT/arkusze):", self.ppw_renumer_dxf,
                         "Wybierz plik (DXF/DWG) z arkuszami STACJA-ARKUSZ")
        self._przycisk_generuj(ren, "Renumeruj rysunki", self._start_renumer)

    def _start_renumer(self):
        dxf = self.ppw_renumer_dxf.get().strip()
        if not dxf or not os.path.isfile(dxf):
            messagebox.showwarning(TYTUL, "Wskaż plik DXF/DWG z arkuszami STACJA-ARKUSZ (np. plik PZT).",
                                   parent=self.root)
            return
        self._uruchom(dxf, ("ppw_renumer",))

    def _start_ppw(self):
        zest = self.ppw_zestawienie.get().strip()
        if not zest or not os.path.isfile(zest):
            messagebox.showwarning(TYTUL, "Wskaż plik zestawienia (.xlsx) z modułu „Zestawienie”.",
                                   parent=self.root)
            return
        zs = self.ppw_zestawienie_stacji.get().strip()
        if zs and not os.path.isfile(zs):
            messagebox.showwarning(TYTUL, "Wskazany plik miejscowości (.xlsx) nie istnieje.", parent=self.root)
            return
        if not self.ppw_wt.get().strip():
            if not messagebox.askyesno(TYTUL, "Nie podano numeru warunków (WT). PPW powstanie z pustym WT. "
                                              "Kontynuować?", parent=self.root):
                return
        self._uruchom(zest, ("ppw",), wt=self.ppw_wt.get())

    def _zakladka_zakladki(self):
        f = self._strona("zakladki", "Zakładki", "Zakładki (przekładki)",
                         "Dla każdej stacji trafo powstaje osobna strona-przekładka (zakładka) z trzema "
                         "wyśrodkowanymi liniami: numer stacji, miejscowość i numer warunków (WT). "
                         "Dane bierzemy z zestawienia — można podpiąć wprost „zestawienie_stacji.xlsx” "
                         "z „Rysunków stałych”. Numer WT wpisz ręcznie, gdy zestawienie go nie zawiera.")
        self._pole_pliku(f, "Zestawienie (.xlsx):", self.zakladki_zestawienie,
                         "Wybierz zestawienie (np. z Rysunków stałych)", typy=XLSX_TYPY)
        self._podpowiedz(f, "(„zestawienie_stacji.xlsx” — wypełnia się samo po module „Rysunki stałe”)")
        box = self._sekcja(f, "Opcje")
        rf = ttk.Frame(box)
        rf.pack(fill="x", pady=4)
        ttk.Label(rf, text="Format wyniku:", width=24).pack(side="left")
        ttk.Radiobutton(rf, text="Word (.docx)", variable=self.zakladki_format,
                        value="docx").pack(side="left", padx=(6, 0))
        ttk.Radiobutton(rf, text="PDF (.pdf)", variable=self.zakladki_format,
                        value="pdf").pack(side="left", padx=(12, 0))
        self._podpowiedz(box, "(.docx — edytowalny w Wordzie, wymaga biblioteki python-docx; "
                              ".pdf — gotowy do druku, bez dodatkowych bibliotek)")
        self._pole_wt(box, self.zakladki_wt, "71/RE-5/KŚ/2026")
        self._przycisk_generuj(f, "Utwórz zakładki", self._start_zakladki)

    def _start_zakladki(self):
        zest = self.zakladki_zestawienie.get().strip()
        if not zest or not os.path.isfile(zest):
            messagebox.showwarning(TYTUL, "Wskaż plik zestawienia (.xlsx) — np. „zestawienie_stacji.xlsx” "
                                          "z Rysunków stałych.", parent=self.root)
            return
        if not self.zakladki_wt.get().strip():
            if not messagebox.askyesno(TYTUL, "Nie podano numeru warunków (WT). Zakładki powstaną z pustym WT. "
                                              "Kontynuować?", parent=self.root):
                return
        self._uruchom(zest, ("zakladki",), wt=self.zakladki_wt.get())

    # ---------------------------------------------------------------- dół okna
    def _dol(self, root):
        dol = ttk.Frame(root, padding=(20, 6, 20, 6))
        dol.grid(row=2, column=0, sticky="nsew")
        dol.columnconfigure(0, weight=1)

        ttk.Separator(dol, orient="horizontal").grid(row=0, column=0, sticky="we", pady=(0, 8))

        kat = ttk.Frame(dol)
        kat.grid(row=1, column=0, sticky="we", pady=2)
        kat.columnconfigure(1, weight=1)
        ttk.Label(kat, text="Katalog zapisu:").grid(row=0, column=0, sticky="w")
        ttk.Entry(kat, textvariable=self.katalog).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(kat, text="Zmień…", command=self._wybierz_katalog).grid(row=0, column=2)
        ttk.Label(kat, text="(puste = katalog pliku wejściowego)", style="Hint.TLabel").grid(
            row=1, column=1, columnspan=2, sticky="w", padx=6)
        ttk.Checkbutton(kat, text="Zapisuj rysunki jako DWG (bez ODA File Converter — jako DXF)",
                        variable=self.eksport_dwg).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Button(kat, text="Wskaż ODA…", command=self._wskaz_oda).grid(row=2, column=2)

        akcja = ttk.Frame(dol)
        akcja.grid(row=2, column=0, sticky="we", pady=6)
        akcja.columnconfigure(0, weight=1)
        self.pasek = ttk.Progressbar(akcja, mode="indeterminate")
        self.pasek.grid(row=0, column=0, sticky="we")
        self.btn_otworz = ttk.Button(akcja, text="Otwórz folder wyniku",
                                     command=self._otworz_folder, state="disabled")
        self.btn_otworz.grid(row=0, column=1, padx=(10, 0))
        ttk.Button(akcja, text="Kopiuj dziennik", command=self._kopiuj_dziennik).grid(row=0, column=2, padx=(6, 0))

        box = ttk.Frame(dol)
        box.grid(row=3, column=0, sticky="nsew", pady=(2, 0))
        box.rowconfigure(1, weight=1)
        box.columnconfigure(0, weight=1)
        ttk.Label(box, text="Przebieg", style="Sekcja.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.log = tk.Text(box, height=7, wrap="word", font=("Consolas", 9), state="disabled",
                           relief="flat", borderwidth=0, highlightthickness=1, padx=8, pady=6)
        self.log.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        sb.grid(row=1, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)

        self.status = ttk.Label(root, text="Gotowe. Wybierz moduł, wskaż plik i kliknij „Generuj”.",
                                style="Hint.TLabel", anchor="w", padding=(20, 4, 20, 8))
        self.status.grid(row=3, column=0, sticky="we")

    # ================================================================= logika
    def _wybierz_katalog(self):
        p = filedialog.askdirectory(parent=self.root, title="Katalog zapisu wyników",
                                    initialdir=self.katalog.get() or None)
        if p:
            self.katalog.set(os.path.normpath(p))

    def _wskaz_oda(self):
        """Wybór folderu ODA File Converter (konwersja DWG) - zapamiętywany w ustawieniach."""
        from . import dwg
        teraz = dwg.konwerter()
        p = filedialog.askdirectory(parent=self.root, title="Folder programu ODA File Converter")
        if not p:
            if teraz:
                self._pisz(f"Konwerter DWG: {teraz}")
            return
        plik = dwg.ustaw_oda(os.path.normpath(p))
        if plik:
            self._pisz(f"Konwerter DWG: ODA File Converter ({plik}) - zapamiętano.")
        else:
            messagebox.showwarning(TYTUL, "W tym folderze nie ma pliku ODAFileConverter.exe.",
                                   parent=self.root)

    def _pisz(self, tekst: str):
        self.log.configure(state="normal")
        self.log.insert("end", tekst + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _kopiuj_dziennik(self):
        tekst = self.log.get("1.0", "end").strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(tekst)
        self.status.configure(text="Skopiowano dziennik do schowka." if tekst else "Dziennik jest pusty.")

    def _zapisz_dziennik(self):
        """Dopisuje przebieg uruchomienia do „dziennik GeneratorNN.txt” w katalogu wyników - w wersji
        okienkowej komunikaty modułów nie trafiają nigdzie indziej (ważne przy diagnozie błędów)."""
        katalog = self._ostatni_katalog
        if not katalog or not os.path.isdir(katalog):
            return None
        import datetime
        sciezka = os.path.join(katalog, PLIK_DZIENNIKA)
        naglowek = (f"===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} · {', '.join(self._kroki_biezace)} "
                    f"· wersja {wersja()} =====")
        try:
            with open(sciezka, "a", encoding="utf-8") as f:
                f.write(naglowek + "\n" + self.log.get("1.0", "end").strip() + "\n\n")
            return sciezka
        except OSError:
            return None

    def _domyslny_katalog(self, plik):
        if plik and os.path.isdir(plik):                  # PDF z gotowych rysunków - wyniki w tym folderze
            return plik
        return self.katalog.get().strip() or (os.path.dirname(os.path.abspath(plik)) if plik else "")

    # ---- uruchomienie: pojedynczy moduł z jego zakładki ----
    def _start_modul(self, krok):
        plik = self.we[krok].get().strip()
        if krok != "orientacje" and (not plik or not os.path.isfile(plik)):
            messagebox.showwarning(TYTUL, "Wskaż istniejący plik DXF lub DWG.", parent=self.root)
            return
        if krok == "orientacje" and plik and not os.path.isfile(plik):
            messagebox.showwarning(TYTUL, "Wskazany szablon nie istnieje.", parent=self.root)
            return
        zas = self.orient_zasiegi.get().strip()
        if krok == "orientacje" and zas and not os.path.isfile(zas):
            messagebox.showwarning(TYTUL, "Wskazany plik z zasięgami stacji (PZT) nie istnieje.", parent=self.root)
            return
        # dla orientacji bez pliku: użyj dołączonego szablonu jako wejścia
        wejscie = plik
        orient_szablon = None
        if krok == "orientacje":
            from . import zasoby
            orient_szablon = plik or None
            wejscie = plik or zasoby.szablon_orientacji_dxf()
            if not wejscie:
                messagebox.showwarning(TYTUL, "Brak dołączonego szablonu — wskaż plik szablonu DXF/DWG.",
                                       parent=self.root)
                return
        self._uruchom(wejscie, (krok,), orient_szablon=orient_szablon)

    # ---- uruchomienie: Obliczenia (plik DXF albo własne zestawienie) ----
    def _start_obliczenia(self):
        zest = self.obl_zestawienie.get().strip()
        dxf = self.we["obliczenia"].get().strip()
        if zest:
            if not os.path.isfile(zest):
                messagebox.showwarning(TYTUL, "Wskazane zestawienie (.xlsx) nie istnieje.", parent=self.root)
                return
            # własne zestawienie: plik DXF nie jest potrzebny (pipeline użyje zestawienia jako bazy)
            self._uruchom(dxf or zest, ("obliczenia",))
            return
        if not dxf or not os.path.isfile(dxf):
            messagebox.showwarning(TYTUL, "Wskaż plan DXF/DWG albo własne zestawienie (.xlsx).", parent=self.root)
            return
        self._uruchom(dxf, ("obliczenia",))

    def _uruchom(self, plik, kroki, orient_szablon=None, wt=None):
        if self.pracuje:
            return
        # użyty numer WT trafia do historii (lista rozwijana) i zostaje zapamiętany
        if self._zapis_id is not None:
            self.root.after_cancel(self._zapis_id)
        self._zapisz_ustawienia(do_historii=wt)
        self._projekt_przy_uruchomieniu(plik)
        self._zapisz_projekt()
        katalog = self._domyslny_katalog(plik)
        self._kroki_biezace = tuple(kroki)
        self.pracuje = True
        for b in self._przyciski:
            b.configure(state="disabled")
        self.btn_otworz.configure(state="disabled")
        self.pasek.start(40)                               # co 40 ms - płynnie, bez obciążania CPU
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        z_internetem = (any(k in ("przewieszenia", "pzt") for k in kroki) and self.adresy_on.get()) \
            or ("orientacje" in kroki)
        self.status.configure(text="Trwa generowanie… (pobieranie danych z internetu może chwilę potrwać)"
                              if z_internetem else "Trwa generowanie…")
        self._ostatni_katalog = katalog

        opcje = pipeline.Opcje(
            plan=plik, katalog=katalog, kroki=kroki,
            adresy="uug,osm" if self.adresy_on.get() else "brak",
            obrot_od=_float(self.pw_obrot.get(), 50.0),
            seed=_int_or_none(self.obl_seed.get()),
            kabel=_int(self.obl_kabel.get(), pipeline.mod_obliczenia.DOMYSLNY_KABEL),
            obliczenia_zestawienie=(self.obl_zestawienie.get().strip() or None),
            orient_podklad=self.orient_podklad.get(),
            orient_pdf=self.orient_pdf.get(),
            pdf_folder=(self.pdf_folder.get().strip() or None),
            orient_szablon=orient_szablon or (self.orient_szablon.get().strip() or None),
            orient_zasiegi=(self.orient_zasiegi.get().strip() or None),   # też źródło słupów
            pzt_wzorzec=(self.pzt_wzorzec.get().strip() or None),
            pzt_zaklad=_float(self.pzt_zaklad.get(), 50.0),
            wt_plik=(self.wt_plik.get().strip() or None),
            opisy_szablon=(self.opisy_szablon.get().strip() or None),
            opisy_zestawienie=(self.opisy_zestawienie.get().strip() or None),
            opisy_obliczenia=(self.opisy_obliczenia.get().strip() or None),
            opisy_wt=self.opisy_wt.get().strip(),
            ppw_szablon=(self.ppw_szablon.get().strip() or None),
            ppw_zestawienie=(self.ppw_zestawienie.get().strip() or None),
            ppw_zestawienie_stacji=(self.ppw_zestawienie_stacji.get().strip() or None),
            ppw_wt=self.ppw_wt.get().strip(),
            ppw_renumer_dxf=(self.ppw_renumer_dxf.get().strip() or None),
            zakladki_zestawienie=(self.zakladki_zestawienie.get().strip() or None),
            zakladki_format=(self.zakladki_format.get().strip() or "docx"),
            zakladki_wt=self.zakladki_wt.get().strip(),
            eksport_dwg=self.eksport_dwg.get(),
            nazwy_plik=self._plik_nazw() if os.path.isfile(self._plik_nazw() or "") else None,
            log=lambda t="": self._kolejka.put(("log", t)),
        )
        self._watek = threading.Thread(target=self._praca, args=(opcje,), daemon=True)
        self._watek.start()
        self.root.after(80, self._pompuj)

    def _praca(self, opcje):
        # BaseException: moduły kończą się czasem przez SystemExit (np. „plik otwarty w Excelu”) -
        # bez tego wątek ginął po cichu, a okno czekało w nieskończoność
        try:
            wynik = pipeline.uruchom(opcje)
            self._kolejka.put(("koniec", wynik))
        except BaseException as ex:  # noqa: BLE001
            self._kolejka.put(("log", "\nBŁĄD: " + (str(ex) or type(ex).__name__)))
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
        if self._watek is not None and not self._watek.is_alive() and self._kolejka.empty():
            # zabezpieczenie: wątek zakończył się bez wyniku - nie zostawiaj okna w stanie „trwa”
            self._pisz("\nBŁĄD: moduł zakończył się nieoczekiwanie (bez wyniku).")
            self._zakoncz(None)
            return
        self.root.after(80, self._pompuj)

    # ---- podpinanie wyników tej sesji do kolejnych modułów ----
    def _odbiorcy_wyniku(self, krok, wyjscie):
        """Dla wyniku modułu zwraca (plik, [(moduł, pole, StringVar), ...]) - gdzie go podpiąć."""
        if krok == "numeracja":
            return wyjscie, [("Przewieszenia", "plik planu", self.we["przewieszenia"]),
                             ("Zestawienie", "plik planu", self.we["zestawienie"]),
                             ("Obliczenia", "plik planu", self.we["obliczenia"]),
                             ("Arkusze PZT", "plik planu", self.we["pzt"]),
                             ("Rysunki stałe", "plik stacji i słupów", self.orient_zasiegi)]
        if krok == "zestawienie":
            return wyjscie, [("Obliczenia", "własne zestawienie", self.obl_zestawienie),
                             ("PPW", "zestawienie", self.ppw_zestawienie)]
        if krok == "obliczenia":
            return wyjscie, [("Opisy techniczne", "obliczenia", self.opisy_obliczenia)]
        if krok == "orientacje":
            zest = os.path.join(wyjscie, "zestawienie_stacji.xlsx")
            return zest, [("Opisy techniczne", "zestawienie", self.opisy_zestawienie),
                          ("PPW", "miejscowości", self.ppw_zestawienie_stacji),
                          ("Zakładki", "zestawienie", self.zakladki_zestawienie)]
        if krok == "pzt":
            return wyjscie, [("Rysunki stałe", "plik PZT (stacje i słupy)", self.orient_zasiegi),
                             ("PPW", "plik do renumeracji", self.ppw_renumer_dxf)]
        return None, []

    def _podepnij_wyniki(self, udane):
        """Pliki wygenerowane w tej sesji programu wpisuje do pól modułów, które ich używają.

        Pole jest wypełniane, gdy jest puste albo gdy poprzednio wypełnił je program (nowszy wynik
        zastępuje starszy) - ścieżki wybrane ręcznie przez użytkownika nie są nadpisywane."""
        podpiete = []
        for k in udane:
            plik, odbiorcy = self._odbiorcy_wyniku(k.nazwa, k.wyjscie) if k.wyjscie else (None, [])
            if not plik or not os.path.isfile(plik):
                continue
            plik = os.path.normpath(plik)
            for modul, pole, var in odbiorcy:
                teraz = var.get().strip()
                if teraz and teraz != self._podpiete.get(str(var)):
                    continue                        # wybrane ręcznie - zostaw
                var.set(plik)
                self._podpiete[str(var)] = plik
                podpiete.append(f"  {modul} ({pole}) ← {os.path.basename(plik)}")
        if podpiete:
            self._pisz("\nPODPIĘTO DO KOLEJNYCH MODUŁÓW (wyniki tej sesji):")
            for linia in podpiete:
                self._pisz(linia)

    def _zakoncz(self, wynik):
        self.pracuje = False
        self.pasek.stop()
        for b in self._przyciski:
            b.configure(state="normal")
        self._ostatni_wynik = wynik
        if wynik is None:
            self._zapisz_dziennik()
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
        self._podepnij_wyniki(udane)
        self._zapisz_projekt()                             # podpięte wyniki zostają w projekcie
        dziennik = self._zapisz_dziennik()
        if dziennik:
            self._pisz(f"\nDziennik zapisano: {dziennik}")
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
    if sys.platform.startswith("win"):
        try:                                   # ostre czcionki na ekranach z powiększeniem
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    Aplikacja(root)
    root.mainloop()


if __name__ == "__main__":
    main()
