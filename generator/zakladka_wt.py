"""Zakładka „Warunki techniczne” - natywne (tkinter) okno Generatora WT na rdzeniu generator.warunki.

Odpowiednik okna Qt Generatora WT, krok po kroku:
  1. plik DXF/DWG + ustawienia numeracji -> „Analizuj” (odczyt, adresy GUGiK, sprawdzenie ulic, plan,
     arkusze) - w tle, okno nie zamarza,
  2. „Wykaz słupów” - edycja (podwójne kliknięcie) miejscowości, ulicy, gminy, rodzaju, typu, nr w sieci,
     uwag; wyłączanie słupów z numeracji (kolumna „W num.”); poprawki zapamiętywane przez rdzeń
     w <projekt>.wt.json, więc nie przepadają przy ponownej analizie,
  3. „Kontrola projektu” - plan numeracji, błędne kliki, długie przęsła, ulice, stacje, arkusze…,
  4. zlecenie (operator, rejon, daty) i wybór wyników -> „Numeruj i generuj dokumenty”.
Rdzeń (shapely, pyproj, numpy…) ładowany dopiero przy pierwszym użyciu - reszta programu działa
bez tych bibliotek. Zestawienie uproszczone (.xls) jest podpinane do pola „Warunki techniczne”.
"""
from __future__ import annotations

import datetime
import os
import queue
import shutil
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

KOLUMNY = [  # (nagłówek, atrybut, edytowalna, szerokość) - jak w oknie Qt Generatora WT
    ("W num.", "_wlaczony", False, 55), ("Nr", "etykieta", False, 55), ("Stacja trafo", "stacja_trafo", False, 85),
    ("Nr w sieci", "nr_w_sieci", True, 70), ("Miejscowość", "miejscowosc", True, 120), ("Ulica", "ulica", True, 120),
    ("Droga przy słupie", "ulica_droga", False, 120), ("Gmina", "gmina", True, 100),
    ("Rejon", "rejon_skrot", False, 80), ("Rodzaj", "rodzaj_slupa", True, 55), ("Typ słupa", "typ_slupa", True, 100),
    ("X (2000)", "geo_x", False, 95), ("Y (2000)", "geo_y", False, 95), ("Działka", "dzialka", False, 110),
    ("Uwagi", "uwagi", True, 150),
]
TYPY_DXF = [("Rysunek DXF / DWG", "*.dxf *.dwg"), ("Wszystkie pliki", "*.*")]


def przygotuj_dane(log=print, katalogi_wt=()) -> None:
    """Pierwsze uruchomienie: słowniki operatorów/rejonów i pamięci z dotychczasowego Generatora WT
    (żeby nie wpisywać list od nowa); bez niego - pusty szablon słowników."""
    from .warunki import slowniki
    from .warunki.config import DANE
    DANE.mkdir(parents=True, exist_ok=True)
    cel = DANE / "slowniki.xlsx"
    if cel.exists():
        return
    for k in katalogi_wt:
        if not k:
            continue
        folder = os.path.dirname(k) if k.lower().endswith(".exe") else k
        zrodlo = os.path.join(folder, "dane", "slowniki.xlsx")
        if os.path.isfile(zrodlo):
            shutil.copy2(zrodlo, cel)
            for dodatkowe in ("cache_geokodowania.json",):
                p = os.path.join(folder, "dane", dodatkowe)
                if os.path.isfile(p) and not (DANE / dodatkowe).exists():
                    shutil.copy2(p, DANE / dodatkowe)
            log(f"Warunki techniczne: przeniesiono listy operatorów i rejonów z {folder}")
            return
    slowniki.utworz_szablon(cel)
    log(f"Warunki techniczne: utworzono pusty plik list operatorów i rejonów: {cel}")


class ZakladkaWT:
    def __init__(self, app, ramka):
        self.app = app
        self.root = app.root
        self.f = ramka
        self.projekt = None                # warunki.projekt.Projekt po analizie
        self.cfg = None
        self.operatorzy, self.rejony = [], []
        self._kolejka = queue.Queue()
        self._praca = False
        self._przyciski = []

        self.plik = tk.StringVar()
        self.geo = tk.BooleanVar(value=True)
        self.prefiks = tk.StringVar()
        self.start = tk.StringVar(value="1")
        self.tolerancja = tk.StringVar(value="5.0")
        self.zakladka = tk.StringVar(value="10")
        self.kierunek = tk.BooleanVar(value=True)
        self.operator = tk.StringVar()
        self.rejon = tk.StringVar()
        self.data_od = tk.StringVar(value=datetime.date.today().strftime("%d.%m.%Y"))
        self.data_do = tk.StringVar(value="-")
        self.opracowal = tk.StringVar(value=app.ust.get("wt_opracowal", ""))
        self.data_rys = tk.StringVar(value=datetime.date.today().strftime("%m.%Y"))
        self.wyn = {k: tk.BooleanVar(value=v) for k, v in (
            ("dxf", True), ("arkusze", True), ("pdf_num", False), ("orient", False), ("pismo", True),
            ("rozb", True), ("upr", True), ("proj", True), ("szarosc", False), ("trasa_or", True),
            ("pdf_orient", False))}
        self.skala_or = tk.StringVar(value="10000")
        self.zrodlo_or = tk.StringVar(value="osm")
        self.wgs84 = tk.StringVar(value="pl2000")
        self.katalog = tk.StringVar()
        self._buduj()

    # ------------------------------------------------------------------ UI
    def _sekcja(self, tytul):
        return self.app._sekcja(self.f, tytul)

    def _buduj(self):
        app, f = self.app, self.f
        app._pole_pliku(f, "Plik projektu DXF/DWG:", self.plik, "Rysunek warunków technicznych (DXF/DWG)", TYPY_DXF)
        ttk.Checkbutton(f, text="Pobieraj adresy z GUGiK (miejscowość, ulica, gmina, działka) i sprawdzaj ulice",
                        variable=self.geo).pack(anchor="w", pady=2)
        box = self._sekcja("Numeracja")
        r = ttk.Frame(box)
        r.pack(fill="x", pady=2)
        for etyk, var, szer in (("Prefiks:", self.prefiks, 6), ("Numer startowy:", self.start, 5),
                                ("Scalanie wierzchołków [m]:", self.tolerancja, 5),
                                ("Zakładka arkuszy [m]:", self.zakladka, 5)):
            ttk.Label(r, text=etyk).pack(side="left", padx=(0, 4))
            ttk.Entry(r, textvariable=var, width=szer).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(box, text="Odnośnik po stronie z dala od linii", variable=self.kierunek).pack(anchor="w")
        b = ttk.Button(f, text="▶  Analizuj", command=self.analizuj, style="Accent.TButton")
        b.pack(anchor="w", pady=(10, 4))
        self._przyciski.append(b)
        self.info = ttk.Label(f, text="", wraplength=720, justify="left")
        self.info.pack(anchor="w")

        # wykaz słupów
        box = self._sekcja("Wykaz słupów (podwójne kliknięcie - popraw; kolumna „W num.” - wyłącz/włącz słup)")
        ramka = ttk.Frame(box)
        ramka.pack(fill="both", expand=True)
        self.tab = ttk.Treeview(ramka, columns=[k[1] for k in KOLUMNY], show="headings", height=10)
        for nagl, atr, edyt, szer in KOLUMNY:
            self.tab.heading(atr, text=nagl + (" ✎" if edyt else ""))
            self.tab.column(atr, width=szer, stretch=False, anchor="center" if atr == "_wlaczony" else "w")
        sy = ttk.Scrollbar(ramka, orient="vertical", command=self.tab.yview)
        sx = ttk.Scrollbar(ramka, orient="horizontal", command=self.tab.xview)
        self.tab.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tab.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="we")
        ramka.columnconfigure(0, weight=1)
        self.tab.tag_configure("wykl", foreground="#9AA3AE")
        self.tab.tag_configure("ulica", background="#FFE2C2")
        self.tab.bind("<Double-1>", self._edytuj_komorke)
        self.b_ulice = ttk.Button(box, text="Przyjmij ulice z dróg", command=self.przyjmij_ulice, state="disabled")
        self.b_ulice.pack(anchor="w", pady=(4, 0))

        # kontrola projektu
        box = self._sekcja("Kontrola projektu")
        self.kontrola = ttk.Treeview(box, columns=("opis",), height=9)
        self.kontrola.heading("#0", text="Element")
        self.kontrola.heading("opis", text="Wynik")
        self.kontrola.column("#0", width=300)
        self.kontrola.column("opis", width=440)
        self.kontrola.tag_configure("blad", foreground="#C62828")
        self.kontrola.tag_configure("uwaga", foreground="#B35C00")
        self.kontrola.pack(fill="x")

        # zlecenie
        box = self._sekcja("Zlecenie")
        self._wiersz_combo(box, "Operator:", self.operator)
        self._wiersz_combo(box, "Rejon domyślny:", self.rejon)
        r = ttk.Frame(box)
        r.pack(fill="x", pady=2)
        for etyk, var, szer in (("Umowa od:", self.data_od, 11), ("do:", self.data_do, 11),
                                ("Opracował:", self.opracowal, 22), ("Data rysunku:", self.data_rys, 8)):
            ttk.Label(r, text=etyk).pack(side="left", padx=(0, 4))
            ttk.Entry(r, textvariable=var, width=szer).pack(side="left", padx=(0, 12))
        r = ttk.Frame(box)
        r.pack(fill="x", pady=(4, 0))
        ttk.Button(r, text="Edytuj listy (Excel)", command=self.edytuj_listy).pack(side="left")
        ttk.Button(r, text="Odśwież listy", command=self.wczytaj_listy).pack(side="left", padx=6)

        # wyniki
        box = self._sekcja("Wyniki")
        for klucz, tekst in (("dxf", "Rysunek z numeracją (*_numeracja.dwg/.dxf)"),
                             ("arkusze", "    + arkusze 1:1000 (układy 1, 2, 3…)"),
                             ("pdf_num", "    + arkusze jako PDF (*_numeracja.pdf)"),
                             ("pismo", "Pismo – zapytanie o dostęp (*_pismo.docx)"),
                             ("rozb", "Zestawienie rozbudowane (*_rozbudowana.xlsx)"),
                             ("upr", "Zestawienie uproszczone (*_uproszczona.xls)"),
                             ("proj", "Tabela projektowa (*_tabela_projektowa.xlsx)"),
                             ("orient", "Plan orientacyjny (*_orientacja.dwg/.dxf + jpg)")):
            ttk.Checkbutton(box, text=tekst, variable=self.wyn[klucz]).pack(anchor="w")
        r = ttk.Frame(box)
        r.pack(fill="x", padx=(24, 0), pady=2)
        ttk.Label(r, text="skala 1:").pack(side="left")
        ttk.Combobox(r, textvariable=self.skala_or, values=("10000", "25000"), width=7, state="readonly").pack(side="left")
        ttk.Label(r, text="  podkład:").pack(side="left")
        ttk.Combobox(r, textvariable=self.zrodlo_or, values=("osm", "gugik"), width=7, state="readonly").pack(side="left")
        for klucz, tekst in (("szarosc", "szarość"), ("trasa_or", "trasa na planie"), ("pdf_orient", "też PDF")):
            ttk.Checkbutton(r, text=tekst, variable=self.wyn[klucz]).pack(side="left", padx=(10, 0))
        r = ttk.Frame(box)
        r.pack(fill="x", pady=(6, 2))
        ttk.Label(r, text="Współrzędne w piśmie i zestawieniach:").pack(side="left")
        ttk.Radiobutton(r, text="PL-2000", variable=self.wgs84, value="pl2000").pack(side="left", padx=(8, 0))
        ttk.Radiobutton(r, text="WGS 84", variable=self.wgs84, value="wgs84").pack(side="left", padx=(8, 0))
        app._pole_folderu(box, "Folder wyników:", self.katalog, "Folder wyników warunków technicznych")
        app._podpowiedz(box, "(puste = folder pliku projektu)")
        self.b_gen = ttk.Button(f, text="▶  Numeruj i generuj dokumenty", command=self.generuj,
                                style="Accent.TButton", state="disabled")
        self.b_gen.pack(anchor="w", pady=(12, 6))
        self.wczytaj_listy(cicho=True)

    def _wiersz_combo(self, ramka, etykieta, var):
        r = ttk.Frame(ramka)
        r.pack(fill="x", pady=2)
        ttk.Label(r, text=etykieta, width=24).pack(side="left")
        cb = ttk.Combobox(r, textvariable=var, state="readonly", width=60)
        cb.pack(side="left", padx=6)
        if var is self.operator:
            self.cb_operator = cb
        else:
            self.cb_rejon = cb

    # ------------------------------------------------------------------ listy operatorów / rejonów
    def wczytaj_listy(self, cicho=False):
        try:
            from .warunki import slowniki
            from .warunki.config import Config
            przygotuj_dane(self._log_bezpieczny, [self.app.wt_program.get()])
            plik = Config().plik_slownikow
            self.operatorzy = slowniki.wczytaj_liste(plik, slowniki.ARKUSZ_OPERATORZY)
            self.rejony = slowniki.wczytaj_liste(plik, slowniki.ARKUSZ_REJONY)
        except ImportError as ex:
            if not cicho:
                messagebox.showwarning("Warunki techniczne", f"Brak bibliotek modułu WT: {ex}", parent=self.root)
            return
        except Exception as ex:  # noqa: BLE001
            if not cicho:
                messagebox.showwarning("Warunki techniczne", f"Nie można wczytać list (plik otwarty w Excelu?):\n{ex}",
                                       parent=self.root)
            return
        self.cb_operator.configure(values=[o.get("Nazwa", "") for o in self.operatorzy])
        self.cb_rejon.configure(values=[r.get("Nazwa", "") for r in self.rejony])
        if self.operatorzy and self.operator.get() not in self.cb_operator.cget("values"):
            self.operator.set(self.app.ust.get("wt_operator") or self.operatorzy[0].get("Nazwa", ""))
        if self.rejony and self.rejon.get() not in self.cb_rejon.cget("values"):
            self.rejon.set(self.app.ust.get("wt_rejon") or self.rejony[0].get("Nazwa", ""))

    def _log_bezpieczny(self, tekst):
        """Wpis do „Przebiegu” - przy budowie okna dziennika jeszcze nie ma, więc wpis czeka chwilę."""
        if hasattr(self.app, "log"):
            self.app._pisz(tekst)
        else:
            self.root.after(500, lambda: self._log_bezpieczny(tekst))

    def _wybrany(self, lista, nazwa):
        return next((x for x in lista if x.get("Nazwa") == nazwa), None)

    def edytuj_listy(self):
        from .warunki.config import Config
        plik = Config().plik_slownikow
        if not plik.exists():
            self.wczytaj_listy()
        try:
            os.startfile(plik)  # noqa: S606
        except OSError as ex:
            messagebox.showinfo("Warunki techniczne", f"Plik list: {plik}\n({ex})", parent=self.root)

    # ------------------------------------------------------------------ praca w tle
    def _w_tle(self, praca, po, opis):
        if self._praca:
            return
        self._praca = True
        for b in self._przyciski + [self.b_gen]:
            b.configure(state="disabled")
        self.app.pasek.start(40)
        self.app.status.configure(text=opis)

        def watek():
            try:
                self._kolejka.put(("koniec", po, praca()))
            except BaseException as ex:  # noqa: BLE001
                self._kolejka.put(("blad", None, f"{ex}\n\n{traceback.format_exc()}"))
        threading.Thread(target=watek, daemon=True).start()
        self.root.after(80, self._odbieraj)

    def _postep(self, tekst):
        self._kolejka.put(("postep", None, tekst))

    def _log(self, tekst):
        self._kolejka.put(("log", None, tekst))

    def _odbieraj(self):
        try:
            while True:
                typ, po, dane = self._kolejka.get_nowait()
                if typ == "postep":
                    self.app.status.configure(text=dane)
                elif typ == "log":
                    self.app._pisz(dane)
                else:
                    self._praca = False
                    self.app.pasek.stop()
                    for b in self._przyciski:
                        b.configure(state="normal")
                    self.b_gen.configure(state="normal" if self.projekt and self.projekt.plan else "disabled")
                    if typ == "blad":
                        self.app._pisz("BŁĄD (warunki techniczne): " + dane)
                        self.app.status.configure(text="Błąd - szczegóły w „Przebiegu”.")
                        messagebox.showerror("Warunki techniczne", dane.split("\n\n")[0], parent=self.root)
                    else:
                        po(dane)
                    return
        except queue.Empty:
            pass
        self.root.after(80, self._odbieraj)

    # ------------------------------------------------------------------ analiza
    def _konfiguracja(self):
        from .warunki.config import Config
        cfg = self.cfg or Config()
        cfg.prefiks = self.prefiks.get().strip()
        try:
            cfg.numer_startowy = int(self.start.get())
            cfg.tolerancja_slupa = float(self.tolerancja.get().replace(",", "."))
            cfg.zakladka = float(self.zakladka.get().replace(",", "."))
        except ValueError:
            raise ValueError("Numer startowy, scalanie i zakładka muszą być liczbami.") from None
        cfg.inteligentny_kierunek = self.kierunek.get()
        cfg.format_rysunkow = "dwg" if self.app.eksport_dwg.get() else "dxf"
        self.cfg = cfg
        return cfg

    def analizuj(self):
        plik = self.plik.get().strip()
        if not plik or not os.path.isfile(plik):
            messagebox.showwarning("Warunki techniczne", "Wskaż plik projektu DXF/DWG.", parent=self.root)
            return
        try:
            from .warunki.projekt import Projekt
            cfg = self._konfiguracja()
        except ImportError as ex:
            messagebox.showerror("Warunki techniczne", f"Brak bibliotek modułu WT ({ex}).\n"
                                 "Zainstaluj: pip install shapely pyproj numpy requests xlrd xlwt", parent=self.root)
            return
        except ValueError as ex:
            messagebox.showwarning("Warunki techniczne", str(ex), parent=self.root)
            return
        self.app._projekt_przy_uruchomieniu(plik)
        projekt, geo = Projekt(cfg), self.geo.get()
        self.app._pisz(f"\nWARUNKI TECHNICZNE - analiza: {plik}")

        def praca():
            self._postep("Odczyt pliku…")
            projekt.wczytaj(plik)
            bledy = 0
            if geo:
                bledy = projekt.geokoduj(lambda i, n: self._postep(f"Pobieranie adresów z GUGiK: {i}/{n}"))
                self._postep("Sprawdzanie ulic (drogi OpenStreetMap)…")
                try:
                    projekt.sprawdz_ulice(log=lambda t: None)
                except Exception as e:  # noqa: BLE001
                    projekt.ostrzezenia.append(f"Sprawdzanie ulic pominięte: {e}")
            projekt.zastosuj_stan()
            projekt.planuj()
            self._postep("Rozmieszczanie arkuszy…")
            projekt.planuj_arkusze()
            return bledy

        self._w_tle(praca, lambda bledy: self._analiza_gotowa(projekt, bledy), "Analiza projektu WT…")

    def _analiza_gotowa(self, p, bledy_geo):
        self.projekt = p
        p.przypisz_rejony(self.rejony, self._wybrany(self.rejony, self.rejon.get()))
        info = (f"Słupów: {len(p.slupy)} · stref trafo: {len(p.stacje)} · błędnych klików: {len(p.bledne_kliki)}"
                + (f" · układ EPSG:{p.epsg}" if p.epsg else "") + f" · arkuszy: {len(p.arkusze)}")
        if bledy_geo:
            info += f"\nBez adresu (błąd usługi): {bledy_geo} – uruchom analizę ponownie."
        if p.poprawek_zastosowanych:
            self.app._pisz(f"Zastosowano zapamiętane poprawki ({p.plik_stanu.name}): {p.poprawek_zastosowanych} słupów")
        self.info.configure(text=info)
        self._wypelnij_tabele()
        self._wypelnij_kontrole()
        self.app._pisz(f"Analiza zakończona: {len(p.slupy)} słupów, {len(p.bledne_kliki)} błędnych klików, "
                       f"{len(p.ostrzezenia)} ostrzeżeń.")
        self.app.status.configure(text="Analiza zakończona - sprawdź wykaz i kontrolę, potem generuj dokumenty.")
        self.b_gen.configure(state="normal" if p.plan else "disabled")

    # ------------------------------------------------------------------ wykaz słupów
    def _wartosc(self, w, atr):
        if atr == "_wlaczony":
            return "✗" if w.wykluczony else "✓"
        v = getattr(w, atr)
        if isinstance(v, float):
            v = f"{v:.{self.cfg.miejsca_po_przecinku}f}"
        return "" if v is None else str(v)

    def _wypelnij_tabele(self):
        p = self.projekt
        self.tab.delete(*self.tab.get_children())
        if not p:
            return
        for w in p.slupy_trasa():
            tagi = (["wykl"] if w.wykluczony else []) + (["ulica"] if w.ulica_zgodna is False else [])
            self.tab.insert("", "end", iid=str(w.id), values=[self._wartosc(w, k[1]) for k in KOLUMNY], tags=tagi)
        self.b_ulice.configure(state="normal" if p.niezgodne_ulice() else "disabled")

    def _edytuj_komorke(self, e):
        p = self.projekt
        if not p or self._praca:
            return
        wiersz = self.tab.identify_row(e.y)
        kol = self.tab.identify_column(e.x)
        if not wiersz or not kol:
            return
        nagl, atr, edyt, _ = KOLUMNY[int(kol[1:]) - 1]
        w = p.slupy[int(wiersz)]
        if atr == "_wlaczony":
            p.ustaw_wykluczenie(w, not w.wykluczony)
            p.planuj()
            p.odswiez_miejscowosci_arkuszy()
            self._wypelnij_tabele()
            self._wypelnij_kontrole()
            return
        if not edyt:
            return
        teraz = getattr(w, atr) or ""
        nowa = simpledialog.askstring("Popraw słup", f"Słup {w.etykieta or '(wyłączony)'} – {nagl}:",
                                      initialvalue=str(teraz), parent=self.root)
        if nowa is None:
            return
        nowa = nowa.strip()
        # poprawka zapamiętywana przez rdzeń w <projekt>.wt.json - nie przepada przy ponownej analizie
        p.ustaw_pole(w, atr, nowa if atr == "uwagi" else (nowa or None))
        if atr == "gmina":
            p.przypisz_rejony(self.rejony, self._wybrany(self.rejony, self.rejon.get()))
        elif atr == "miejscowosc":
            p.planuj()
            p.odswiez_miejscowosci_arkuszy()
        self._wypelnij_tabele()
        self._wypelnij_kontrole()
        self.tab.selection_set(wiersz)
        self.tab.see(wiersz)

    def przyjmij_ulice(self):
        p = self.projekt
        nz = p.niezgodne_ulice() if p else []
        if not nz:
            return
        lista = "\n".join(f"Słup {w.etykieta}: {w.ulica or '–'} → {w.ulica_droga}" for w in nz[:20])
        if not messagebox.askyesno("Poprawa ulic", f"Zmienić ulicę dla {len(nz)} słupów?\n\n{lista}"
                                   + ("\n…" if len(nz) > 20 else ""), parent=self.root):
            return
        self.app._pisz(f"Poprawiono ulice: {p.przyjmij_ulice_z_drog()} słupów")
        self._wypelnij_tabele()
        self._wypelnij_kontrole()

    # ------------------------------------------------------------------ kontrola projektu
    def _wypelnij_kontrole(self):
        from .warunki.pismo import adres_slupa
        p, cfg, k = self.projekt, self.cfg, self.kontrola
        k.delete(*k.get_children())
        if not p:
            return

        def wezel(tekst, opis, dzieci=(), tag=None, otwarty=False):
            n = k.insert("", "end", text=tekst, values=(opis,), open=otwarty, tags=(tag,) if tag else ())
            for t, o, *dt in dzieci:
                k.insert(n, "end", text=t, values=(o,), tags=tuple(dt))
            return n

        plan = [(x.split(": ", 1)[0], x.split(": ", 1)[-1]) for x in p.opis_planu()]
        if p.plan:
            plan += [("Słup początkowy", f"{p.plan[0].etykieta} – {adres_slupa(p.plan[0])}"),
                     ("Słup końcowy", f"{p.plan[-1].etykieta} – {adres_slupa(p.plan[-1])}")]
        wezel("Plan numeracji (ciągła)", f"{len(p.plan)} słupów", plan, otwarty=True)
        mapa = {(round(w.x, 3), round(w.y, 3)): w for w in p.slupy}
        bk = [(f"Słup {getattr(mapa.get((round(b.x, 3), round(b.y, 3))), 'etykieta', '?')}",
               f"{b.liczba} wierzchołki, rozrzut {b.max_odleglosc:.2f} m · X={b.y:.2f} Y={b.x:.2f}") for b in p.bledne_kliki]
        wezel(f"Błędne kliki (wierzchołki < {cfg.tolerancja_slupa:g} m)", f"{len(bk)} – scalone w jeden słup", bk,
              "uwaga" if bk else None, otwarty=bool(bk))
        dlugie = p.przesla()
        bledne = sum(1 for d, _, _ in dlugie if d > cfg.przeslo_blad)
        wezel(f"Przęsła > {cfg.przeslo_ostrzezenie:g} m", f"{len(dlugie)}, w tym {bledne} > {cfg.przeslo_blad:g} m",
              [(f"Słupy {a.etykieta or '(wył.)'} – {b.etykieta or '(wył.)'}", f"{d:.2f} m",
                "blad" if d > cfg.przeslo_blad else "uwaga") for d, a, b in dlugie],
              "blad" if bledne else ("uwaga" if dlugie else None), otwarty=bool(dlugie))
        nz = p.niezgodne_ulice()
        if p.ulice_sprawdzone:
            spr = sum(1 for w in p.plan if w.ulica_zgodna is not None)
            wezel(f"Sprawdzenie ulic (drogi OSM do {cfg.odl_ulicy:g} m)",
                  f"niezgodnych {len(nz)} · sprawdzono {spr} z {len(p.plan)}",
                  [(f"Słup {w.etykieta}", f"adres: {w.ulica or '–'} → droga przy słupie: {w.ulica_droga}", "uwaga")
                   for w in nz], "uwaga" if nz else None, otwarty=bool(nz))
        else:
            wezel("Sprawdzenie ulic", "nie wykonano (włącz pobieranie adresów)")
        wezel(f"Arkusze 1:{cfg.skala_arkuszy}", f"{len(p.arkusze)} (zakładka {cfg.zakladka:g} m)",
              [(f"Arkusz {a.nazwa}", ", ".join(a.miejscowosci) or "–") for a in p.arkusze])
        st = [(s.nazwa, f"{sum(1 for w in p.slupy if w.stacja_trafo == s.nazwa)} słupów w zasięgu") for s in p.stacje]
        poza = sum(1 for w in p.slupy if not w.stacja_trafo)
        if poza:
            st.append(("(poza strefami)", f"{poza} słupów – grupowane wg miejscowości"))
        wezel("Stacje trafo", str(len(p.stacje)), st)
        bez_nr = [w for w in p.plan if not w.nr_w_sieci]
        wezel(f"Numery słupów w sieci ({cfg.prefiks_warstwy_numerow}…)",
              f"przypisano {p.numerow_w_sieci}, bez numeru {len(bez_nr)}",
              [(f"Słup {w.etykieta}", f"{w.stacja_trafo or 'poza strefą'} · X={w.geo_x:.2f} Y={w.geo_y:.2f}")
               for w in bez_nr], "uwaga" if bez_nr else None)
        bez_opisu = [w for w in p.plan if not w.rodzaj_slupa]
        wezel("Słupy bez opisu rodzaju/typu", f"{len(bez_opisu)} (opisano {p.opisanych_slupow})",
              [(f"Słup {w.etykieta}", f"X={w.geo_x:.2f} Y={w.geo_y:.2f}") for w in bez_opisu])
        wykl = [w for w in p.slupy if w.wykluczony]
        wezel("Słupy wyłączone z numeracji", f"{len(wykl)} (nie trafią do pisma ani zestawień)",
              [(w.stacja_trafo or "poza strefą", w.nr_w_sieci and f"nr w sieci {w.nr_w_sieci}"
                or f"X={w.geo_x:.2f} Y={w.geo_y:.2f}") for w in wykl])
        poprawki = [kk for kk, v in p.stan["slupy"].items() if any(a != "wykluczony" for a in v)]
        wezel("Ręczne poprawki słupów", f"{len(poprawki)} · zapamiętane w {p.plik_stanu.name}")
        if p.ostrzezenia:
            wezel("Ostrzeżenia", str(len(p.ostrzezenia)), [("", t, "uwaga") for t in p.ostrzezenia], "uwaga", True)

    # ------------------------------------------------------------------ generowanie
    def generuj(self):
        from pathlib import Path
        p = self.projekt
        if not p or not p.plan or self._praca:
            return
        try:
            cfg = self._konfiguracja()
        except ValueError as ex:
            messagebox.showwarning("Warunki techniczne", str(ex), parent=self.root)
            return
        if abs(cfg.tolerancja_slupa - p.tolerancja_analizy) > 1e-9:
            messagebox.showinfo("Warunki techniczne", "Zmieniono odległość scalania wierzchołków – projekt "
                                "zostanie przeanalizowany ponownie.", parent=self.root)
            self.analizuj()
            return
        p.planuj()
        p.odswiez_miejscowosci_arkuszy()
        kat = Path(self.katalog.get().strip() or Path(self.plik.get()).parent)
        tekst = "Plan numeracji:\n" + "\n".join(f"  • {x}" for x in p.opis_planu())
        stare = p.istniejaca_numeracja()
        if stare:
            tekst += f"\n\nNa warstwie {cfg.warstwa_numeracji} jest już {stare} numerów – zostaną zastąpione."
        if p.bledne_kliki:
            tekst += f"\n\nScalono {len(p.bledne_kliki)} błędnych klików."
        if self.wyn["dxf"].get() and self.wyn["arkusze"].get():
            tekst += f"\n\nArkusze 1:{cfg.skala_arkuszy}: {len(p.arkusze)}."
        tekst += f"\n\nPliki zostaną zapisane w:\n{kat}\n\nCzy wykonać numerację?"
        if not messagebox.askyesno("Potwierdzenie numeracji", tekst, parent=self.root):
            self.app._pisz("Warunki techniczne: przerwano – nic nie zapisano.")
            return
        p.cfg.wgs84 = self.wgs84.get() == "wgs84"
        operator = self._wybrany(self.operatorzy, self.operator.get())
        opracowal = self.opracowal.get().strip() or None
        data_rys = self.data_rys.get().strip() or None
        data_od, data_do = self.data_od.get().strip(), self.data_do.get().strip() or "-"
        self.app.ust.update(wt_opracowal=self.opracowal.get().strip(), wt_operator=self.operator.get(),
                            wt_rejon=self.rejon.get())
        self.app._zaplanuj_zapis()
        p.zapisz_ustawienia({"prefiks": cfg.prefiks, "numer_startowy": cfg.numer_startowy,
                             "tolerancja_slupa": cfg.tolerancja_slupa, "zakladka": cfg.zakladka,
                             "inteligentny_kierunek": cfg.inteligentny_kierunek, "operator": self.operator.get(),
                             "rejon": self.rejon.get(), "umowa_od": data_od, "umowa_do": data_do})
        w = {k: v.get() for k, v in self.wyn.items()}
        skala, zrodlo = int(self.skala_or.get()), self.zrodlo_or.get()
        rys = p.format_rysunkow
        if rys == "dwg" and not p.oda_dostepny():
            rys = "dxf"
            self.app._pisz("Brak programu ODA File Converter – rysunki zostaną zapisane jako DXF.")
        zadania = []
        if w["dxf"]:
            zadania.append((f"numeracja.{rys}", lambda f: p.zapisz_dxf(f, w["arkusze"], operator, opracowal, data_rys)))
            if w["arkusze"] and w["pdf_num"]:
                zadania.append(("numeracja.pdf", lambda f: p.zapisz_numeracje_pdf(f, self._log)))
        if w["pismo"]:
            zadania.append(("pismo.docx", lambda f: p.zapisz_pismo(f, operator, data_od, data_do)))
        if w["rozb"]:
            zadania.append(("rozbudowana.xlsx", p.zapisz_rozbudowana))
        if w["upr"]:
            zadania.append(("uproszczona.xls", p.zapisz_uproszczona))
        if w["proj"]:
            zadania.append(("tabela_projektowa.xlsx", p.zapisz_projektowa))
        if w["orient"]:
            pdf_or = p.sciezka(kat, "orientacja.pdf") if w["pdf_orient"] else None

            def orient(f):
                o = p.zapisz_orientacje(f, skala, w["szarosc"], operator, opracowal, data_rys, zrodlo, w["trasa_or"],
                                        lambda i, n: self._postep(f"Pobieranie podkładu: {i}/{n}"), self._log)
                self._log(f"Plan orientacyjny: arkusze {', '.join(a.nazwa for a in o)}")
                if pdf_or:
                    p.zapisz_orientacje_pdf(pdf_or, self._log)
                    self._log(f"Zapisano: {pdf_or}")
            zadania.append((f"orientacja.{rys}", orient))

        def praca():
            kat.mkdir(parents=True, exist_ok=True)
            zapisane = []
            for przyrostek, funkcja in zadania:
                cel = p.sciezka(kat, przyrostek)
                self._postep(f"Zapis: {cel.name}…")
                funkcja(cel)
                self._log(f"Zapisano: {cel}")
                zapisane.append(str(cel))
            return zapisane

        self._w_tle(praca, self._wygenerowano, "Generowanie dokumentów WT…")

    def _wygenerowano(self, zapisane):
        self.app.status.configure(text=f"Warunki techniczne: zapisano {len(zapisane)} plik(ów).")
        upr = next((z for z in zapisane if z.lower().endswith("_uproszczona.xls")), None)
        if upr:
            v = self.app.wt_plik
            teraz = v.get().strip()
            if not teraz or teraz == self.app._podpiete.get(str(v)):
                v.set(os.path.normpath(upr))
                self.app._podpiete[str(v)] = v.get()
                self.app._pisz("PODPIĘTO: Arkusze PZT / Rysunki stałe / Opisy (warunki techniczne) ← "
                               + os.path.basename(upr))
        self.app._zapisz_projekt()
        if zapisane and messagebox.askyesno("Warunki techniczne", f"Zapisano {len(zapisane)} plik(ów).\n\n"
                                            "Otworzyć folder wyników?", parent=self.root):
            try:
                os.startfile(os.path.dirname(zapisane[0]))  # noqa: S606
            except OSError:
                pass
