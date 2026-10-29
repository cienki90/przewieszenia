"""Podgląd i ręczne przesuwanie arkuszy PZT na mapie poglądowej wybranej stacji trafo.

Okno otwierane na żądanie z zakładki „Arkusze PZT”. Pokazuje dla wybranej stacji:
zasięg stacji, trasę !tele, arkusze (prostokąty okna rzutni A3 1:1000 z numerami i strefą
tabelki) oraz NIEPOKRYTE odcinki trasy (na czerwono). Arkusze przeciąga się myszą.

Obciążenie: plik wczytywany raz przy otwarciu, rozkład automatyczny liczony w tle dopiero
po wybraniu stacji (i zapamiętywany) - okno programu się nie blokuje.

Zapisany układ trafia do „<plan> - arkusze PZT.json” (pzt.zapisz_uklad) - generowanie PZT
używa go zamiast rozkładu automatycznego dla zapisanych stacji.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import pzt

KOLORY = {
    False: dict(tlo="#FFFFFF", zasieg="#E8F1FB", zasieg_obrys="#5B8FD0", trasa="#1F2328",
                arkusz="#005FB8", tabelka="#9AA0A6", luka="#D93025", tekst="#1F2328", siatka="#EEEEEE"),
    True: dict(tlo="#1C1C1C", zasieg="#1E2A38", zasieg_obrys="#4C7FBF", trasa="#E6E6E6",
               arkusz="#60CDFF", tabelka="#6B6F76", luka="#FF6B5E", tekst="#E6E6E6", siatka="#2A2A2A"),
}


class PodgladPZT(tk.Toplevel):
    def __init__(self, master, dxf: str, wzorzec: str | None = None, zaklad: float = pzt.ZAKLAD,
                 ciemny: bool = False):
        super().__init__(master)
        self.title(f"Podgląd arkuszy PZT — {os.path.basename(dxf)}")
        self.geometry("1200x800")
        self.minsize(900, 600)
        self.dxf, self.wzorzec, self.zaklad = dxf, wzorzec, zaklad
        self.k = KOLORY[bool(ciemny)]
        self.plik_ukladu = pzt.sciezka_ukladu(dxf)

        self.we = None                 # pzt.Wejscie
        self.stacje = {}               # nr -> pzt.DaneStacji
        self.zapisany = {}             # nr -> [(x0, y0)] z pliku układu
        self.auto = {}                 # nr -> [(x0, y0)] rozkład automatyczny (liczony na żądanie)
        self.biezacy = {}              # nr -> [[x0, y0]] układ w edycji
        self.zmiany = False            # niezapisane zmiany
        self.nr = None                 # wybrana stacja
        self._kolejka = queue.Queue()
        self._drag = None              # (indeks arkusza, ostatnie x, y ekranu)
        self._przesuniety = False      # czy podczas przeciągania arkusz się ruszył
        self.zaznaczony = None         # indeks zaznaczonego arkusza (do usunięcia)
        self._pan = None
        self.s, self.cx, self.cy = 1.0, 0.0, 0.0      # skala [px/m] i środek widoku [m]

        self._buduj()
        self.protocol("WM_DELETE_WINDOW", self._zamknij)
        self._w_tle(self._wczytaj, self._po_wczytaniu, "Wczytuję plik…")

    # ------------------------------------------------------------------ UI
    def _buduj(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        panel = ttk.Frame(self, padding=12)
        panel.grid(row=0, column=0, sticky="ns")
        ttk.Label(panel, text="Stacja trafo:").pack(anchor="w")
        self.wybor = tk.StringVar()
        self.cb = ttk.Combobox(panel, textvariable=self.wybor, state="readonly", width=22)
        self.cb.pack(anchor="w", pady=(2, 10))
        self.cb.bind("<<ComboboxSelected>>", lambda e: self._wybierz(self._nr_z_listy()))
        self.info = ttk.Label(panel, text="", justify="left", wraplength=240)
        self.info.pack(anchor="w", pady=(0, 10))
        self.btn_dziury = ttk.Button(panel, text="Domknij dziury", command=self._domknij_dziury)
        self.btn_dziury.pack(fill="x", pady=2)
        self.btn_usun = ttk.Button(panel, text="Usuń zaznaczony arkusz", command=self._usun)
        self.btn_usun.pack(fill="x", pady=2)
        self.btn_auto = ttk.Button(panel, text="Przywróć automatyczny", command=self._przywroc)
        self.btn_auto.pack(fill="x", pady=2)
        self.btn_dopasuj = ttk.Button(panel, text="Dopasuj widok", command=self._dopasuj)
        self.btn_dopasuj.pack(fill="x", pady=2)
        self.btn_zapisz = ttk.Button(panel, text="Zapisz układ", command=self._zapisz, style="Accent.TButton")
        self.btn_zapisz.pack(fill="x", pady=(12, 2))
        ttk.Button(panel, text="Zamknij", command=self._zamknij).pack(fill="x", pady=2)
        ttk.Label(panel, justify="left", wraplength=240, text=(
            "Przeciągnij arkusz lewym przyciskiem myszy (kliknięty arkusz jest zaznaczony).\n"
            "Podwójne kliknięcie — nowy arkusz w tym miejscu; Delete — usuń zaznaczony.\n"
            "Kółko — przybliżenie, prawy przycisk — przesuwanie widoku.\n\n"
            "Czerwone odcinki trasy nie mieszczą się w żadnym arkuszu (z marginesem, poza tabelką).\n\n"
            "Zapisany układ jest używany przy generowaniu „Arkuszy PZT” dla tego planu."),
            style="Hint.TLabel").pack(anchor="w", pady=(16, 0))

        self.plotno = tk.Canvas(self, background=self.k["tlo"], highlightthickness=0, cursor="crosshair")
        self.plotno.grid(row=0, column=1, sticky="nsew")
        self.plotno.bind("<Configure>", lambda e: self._rysuj())
        self.plotno.bind("<ButtonPress-1>", self._chwyc)
        self.plotno.bind("<B1-Motion>", self._ciagnij)
        self.plotno.bind("<ButtonRelease-1>", self._pusc)
        self.plotno.bind("<ButtonPress-3>", lambda e: setattr(self, "_pan", (e.x, e.y)))
        self.plotno.bind("<B3-Motion>", self._przesun_widok)
        self.plotno.bind("<MouseWheel>", self._kolko)
        self.plotno.bind("<Double-Button-1>", self._dodaj_w_punkcie)
        self.bind("<Delete>", lambda e: self._usun())
        self.status = ttk.Label(self, text="", anchor="w", padding=(12, 4))
        self.status.grid(row=1, column=0, columnspan=2, sticky="we")
        self._ustaw_przyciski(False)

    def _ustaw_przyciski(self, aktywne: bool):
        for b in (self.btn_auto, self.btn_dopasuj, self.btn_zapisz, self.btn_dziury, self.btn_usun):
            b.configure(state="normal" if aktywne else "disabled")

    # ------------------------------------------------------------------ praca w tle
    def _w_tle(self, funkcja, po, komunikat):
        self.status.configure(text=komunikat)
        self.configure(cursor="watch")

        def praca():
            try:
                self._kolejka.put((po, funkcja(), None))
            except BaseException as ex:  # noqa: BLE001 - błąd pokazujemy w oknie
                self._kolejka.put((po, None, ex))
        threading.Thread(target=praca, daemon=True).start()
        self.after(60, self._odbierz)

    def _odbierz(self):
        try:
            po, wynik, blad = self._kolejka.get_nowait()
        except queue.Empty:
            self.after(60, self._odbierz)
            return
        self.configure(cursor="")
        if blad is not None:
            self.status.configure(text=f"Błąd: {blad}")
            messagebox.showerror("Podgląd arkuszy PZT", str(blad), parent=self)
            return
        po(wynik)

    def _wczytaj(self):
        # plan/wzorzec w DWG - konwersja do tymczasowego DXF (plik układu i tak leży obok oryginału)
        from . import dwg
        self._dwg = dwg.Wejscia(log=lambda *_: None)
        we = pzt.wczytaj(self._dwg.dxf(self.dxf), self._dwg.dxf(self.wzorzec) if self.wzorzec else None)
        stacje, _ = pzt.dane_stacji(we)
        return we, stacje, pzt.wczytaj_uklad(self.plik_ukladu, we.wzor_okno, log=lambda *_: None)

    def _po_wczytaniu(self, wynik):
        self.we, stacje, self.zapisany = wynik
        self.stacje = {s.nr: s for s in stacje if s.linie}
        if not self.stacje:
            self.status.configure(text="W pliku nie ma stacji z trasą !tele w zasięgu.")
            return
        self.cb.configure(values=[self._etykieta(nr) for nr in self.stacje])
        self.status.configure(text=f"Stacji: {len(self.stacje)}. Wybierz stację z listy.")
        self._wybierz(next(iter(self.stacje)))

    def _etykieta(self, nr):
        return f"{self.stacje[nr].oznaczenie}" + ("  (układ ręczny)" if nr in self.zapisany else "")

    def _nr_z_listy(self):
        i = self.cb.current()
        return list(self.stacje)[i] if i >= 0 else None

    # ------------------------------------------------------------------ stacja
    def _wybierz(self, nr):
        if nr is None:
            return
        self.nr = nr
        self.zaznaczony = None
        self.cb.current(list(self.stacje).index(nr))
        if nr in self.auto:
            self._pokaz_stacje()
            return
        self._ustaw_przyciski(False)
        st = self.stacje[nr]
        W, H = self.we.wzor_okno

        def licz():
            return pzt.rozmiesc(st.linie, W, H, self.we.wzor_zakazane, zaklad=self.zaklad)

        def po(narozniki):
            self.auto[nr] = narozniki
            if nr == self.nr:
                self._pokaz_stacje()
        self._w_tle(licz, po, f"Liczę rozkład arkuszy stacji {st.oznaczenie}…")

    def _pokaz_stacje(self):
        nr = self.nr
        if nr not in self.biezacy:
            zrodlo = self.zapisany.get(nr) or self.auto[nr]
            self.biezacy[nr] = [list(p) for p in zrodlo]
        self._ustaw_przyciski(True)
        self._dopasuj()

    def _przywroc(self):
        if self.nr in self.auto:
            self.biezacy[self.nr] = [list(p) for p in self.auto[self.nr]]
            self.zaznaczony = None
            self.zmiany = True
            self._rysuj()

    # ------------------------------------------------------------------ dodawanie / usuwanie
    def _dodaj(self, x0, y0):
        self.biezacy[self.nr].append([x0, y0])
        self.zaznaczony = len(self.biezacy[self.nr]) - 1
        self.zmiany = True
        self._rysuj()

    def _dodaj_w_punkcie(self, e):
        if self.nr not in self.biezacy:
            return
        W, H = self.we.wzor_okno
        x, y = self._swiat(e.x, e.y)
        self._dodaj(x - W / 2, y - H / 2)                 # arkusz wyśrodkowany w klikniętym miejscu

    def _usun(self):
        if self.nr not in self.biezacy or self.zaznaczony is None:
            self.status.configure(text="Kliknij arkusz, aby go zaznaczyć, potem usuń.")
            return
        if len(self.biezacy[self.nr]) <= 1:
            self.status.configure(text="Stacja musi mieć przynajmniej jeden arkusz.")
            return
        del self.biezacy[self.nr][self.zaznaczony]
        self.zaznaczony = None
        self.zmiany = True
        self._rysuj()

    def _domknij_dziury(self):
        """Dokłada arkusze na niepokrytych odcinkach trasy - każdy nowy arkusz w położeniu, które
        pokrywa najwięcej niepokrytych próbek (kandydaci wokół pierwszej niepokrytej próbki)."""
        if self.nr not in self.biezacy:
            return
        st = self.stacje[self.nr]
        W, H = self.we.wzor_okno
        zak, m = self.we.wzor_zakazane, pzt.MARGINES_MM
        zx0, zy1 = zak[0] - m, zak[3] + m
        dodane = 0
        for _ in range(30):                                # zabezpieczenie przed zapętleniem
            luki = pzt.niepokryte(st.linie, [tuple(p) for p in self.biezacy[self.nr]], W, H, zak)
            if not luki:
                break
            px, py = luki[0]
            najlepszy, ile_najl = None, 0
            kx, ky = W / 8, H / 8
            for i in range(-4, 5):
                for j in range(-4, 5):
                    x0, y0 = px - W / 2 + i * kx, py - H / 2 + j * ky
                    if not pzt._w_uzyt(px - x0, py - y0, W, H, m, zx0, zy1):
                        continue
                    ile = sum(1 for x, y in luki if pzt._w_uzyt(x - x0, y - y0, W, H, m, zx0, zy1))
                    if ile > ile_najl:
                        najlepszy, ile_najl = (x0, y0), ile
            if najlepszy is None:
                break
            self.biezacy[self.nr].append(list(najlepszy))
            dodane += 1
        if dodane:
            self.zmiany = True
            self.zaznaczony = None
        self._rysuj()
        self.status.configure(text=f"Domknięto dziury: dodano {dodane} ark." if dodane else "Brak dziur do domknięcia.")

    def _uporzadkuj(self, nr):
        """Kolejność arkuszy wzdłuż trasy (jak w rozkładzie automatycznym) - numeracja nr-1, nr-2…"""
        st = self.stacje[nr]
        W, H = self.we.wzor_okno
        zak, m = self.we.wzor_zakazane, pzt.MARGINES_MM
        zx0, zy1 = zak[0] - m, zak[3] + m
        probki = pzt._probkuj(st.linie, pzt.GESTOSC)

        def pierwsza(p):
            for i, (x, y, _c, _t) in enumerate(probki):
                if pzt._w_uzyt(x - p[0], y - p[1], W, H, m, zx0, zy1):
                    return i
            return len(probki)
        self.biezacy[nr].sort(key=pierwsza)

    # ------------------------------------------------------------------ geometria widoku
    def _ekran(self, x, y):
        w, h = self.plotno.winfo_width(), self.plotno.winfo_height()
        return (x - self.cx) * self.s + w / 2, h / 2 - (y - self.cy) * self.s

    def _swiat(self, sx, sy):
        w, h = self.plotno.winfo_width(), self.plotno.winfo_height()
        return (sx - w / 2) / self.s + self.cx, (h / 2 - sy) / self.s + self.cy

    def _dopasuj(self):
        if self.nr not in self.biezacy:
            return
        st = self.stacje[self.nr]
        W, H = self.we.wzor_okno
        pts = [p for poly in st.poligony for p in poly] + [p for ln in st.linie for p in ln]
        for x0, y0 in self.biezacy[self.nr]:
            pts += [(x0, y0), (x0 + W, y0 + H)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w, h = max(self.plotno.winfo_width(), 100), max(self.plotno.winfo_height(), 100)
        self.cx, self.cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        self.s = 0.92 * min(w / max(max(xs) - min(xs), 1), h / max(max(ys) - min(ys), 1))
        self._rysuj()

    # ------------------------------------------------------------------ rysowanie
    def _rysuj(self):
        c, k = self.plotno, self.k
        c.delete("all")
        if self.nr not in self.biezacy:
            return
        st = self.stacje[self.nr]
        W, H = self.we.wzor_okno
        zak = self.we.wzor_zakazane
        m = pzt.MARGINES_MM
        for poly in st.poligony:
            c.create_polygon([v for p in poly for v in self._ekran(*p)], fill=k["zasieg"],
                             outline=k["zasieg_obrys"], dash=(6, 4), width=1.5)
        for ln in st.linie:
            c.create_line([v for p in ln for v in self._ekran(*p)], fill=k["trasa"], width=2)
        for i, (x0, y0) in enumerate(self.biezacy[self.nr]):
            tag = ("ark", f"ark{i}")
            c.create_rectangle(*self._ekran(x0, y0 + H), *self._ekran(x0 + W, y0), outline=k["arkusz"],
                               width=4 if i == self.zaznaczony else 2, fill=k["arkusz"], stipple="gray12",
                               tags=tag)
            c.create_rectangle(*self._ekran(x0 + m, y0 + H - m), *self._ekran(x0 + W - m, y0 + m),
                               outline=k["arkusz"], dash=(3, 3), tags=tag)
            c.create_rectangle(*self._ekran(x0 + zak[0], y0 + zak[3]), *self._ekran(x0 + W, y0 + zak[1]),
                               outline=k["tabelka"], fill=k["tabelka"], stipple="gray50", tags=tag)
            tx, ty = self._ekran(x0, y0 + H)
            c.create_text(tx + 6, ty + 4, anchor="nw", text=f"{self.nr}-{i + 1}", fill=k["arkusz"],
                          font=("Segoe UI", 11, "bold"), tags=tag)
        self._rysuj_luki()

    def _rysuj_luki(self):
        c, k = self.plotno, self.k
        c.delete("luka")
        st = self.stacje[self.nr]
        W, H = self.we.wzor_okno
        luki = pzt.niepokryte(st.linie, [tuple(p) for p in self.biezacy[self.nr]], W, H, self.we.wzor_zakazane)
        r = 3
        for x, y in luki:
            sx, sy = self._ekran(x, y)
            c.create_oval(sx - r, sy - r, sx + r, sy + r, fill=k["luka"], outline=k["luka"], tags="luka")
        n = len(self.biezacy[self.nr])
        reczny = self.biezacy[self.nr] != [list(p) for p in self.auto.get(self.nr, [])]
        opis = [f"Stacja {st.oznaczenie}", f"Arkuszy: {n}",
                ("Niepokryta trasa: ok. %.0f m" % (len(luki) * pzt.GESTOSC)) if luki else "Cała trasa pokryta ✓",
                "Układ: ręczny" if reczny else "Układ: automatyczny"]
        self.info.configure(text="\n".join(opis), foreground=k["luka"] if luki else "")
        self.status.configure(text=("Niezapisane zmiany. " if self.zmiany else "") +
                              f"Plik układu: {os.path.basename(self.plik_ukladu)}")

    # ------------------------------------------------------------------ mysz
    def _chwyc(self, e):
        bliskie = self.plotno.find_overlapping(e.x - 2, e.y - 2, e.x + 2, e.y + 2)
        for item in reversed(bliskie):                    # najwyżej leżący arkusz
            for t in self.plotno.gettags(item):
                if t.startswith("ark") and t != "ark":
                    self._drag = (int(t[3:]), e.x, e.y)
                    self._przesuniety = False
                    if self.zaznaczony != int(t[3:]):
                        self.zaznaczony = int(t[3:])
                        self._rysuj()
                    self.plotno.tag_raise(t)
                    self.plotno.configure(cursor="fleur")
                    return

    def _ciagnij(self, e):
        if not self._drag:
            return
        i, lx, ly = self._drag
        self.plotno.move(f"ark{i}", e.x - lx, e.y - ly)
        p = self.biezacy[self.nr][i]
        p[0] += (e.x - lx) / self.s
        p[1] -= (e.y - ly) / self.s
        self._drag = (i, e.x, e.y)
        self._przesuniety = True

    def _pusc(self, _e):
        if self._drag:
            self._drag = None
            self.plotno.configure(cursor="crosshair")
            if self._przesuniety:
                self.zmiany = True
                self._rysuj_luki()

    def _przesun_widok(self, e):
        if self._pan:
            self.cx -= (e.x - self._pan[0]) / self.s
            self.cy += (e.y - self._pan[1]) / self.s
            self._pan = (e.x, e.y)
            self._rysuj()

    def _kolko(self, e):
        wx, wy = self._swiat(e.x, e.y)
        f = 1.2 if e.delta > 0 else 1 / 1.2
        self.s *= f
        # punkt pod kursorem zostaje w miejscu
        self.cx = wx - (wx - self.cx) / f
        self.cy = wy - (wy - self.cy) / f
        self._rysuj()

    # ------------------------------------------------------------------ zapis / zamknięcie
    def _zapisz(self):
        wynik = dict(self.zapisany)
        for nr in self.biezacy:
            self._uporzadkuj(nr)                           # numeracja arkuszy wzdłuż trasy
        self.zaznaczony = None
        self._rysuj()
        for nr, pts in self.biezacy.items():
            if [list(p) for p in self.auto.get(nr, [])] == pts:
                wynik.pop(nr, None)                       # równe automatycznemu - nie trzeba zapisywać
            else:
                wynik[nr] = [tuple(p) for p in pts]
        try:
            pzt.zapisz_uklad(self.plik_ukladu, self.we.wzor_okno, wynik)
        except OSError as ex:
            messagebox.showerror("Podgląd arkuszy PZT", f"Nie udało się zapisać układu:\n{ex}", parent=self)
            return False
        self.zapisany = wynik
        self.zmiany = False
        self.cb.configure(values=[self._etykieta(nr) for nr in self.stacje])
        self.cb.current(list(self.stacje).index(self.nr))
        self._rysuj_luki()
        self.status.configure(text=(f"Zapisano układ ({len(wynik)} stacji z ręcznym układem) - "
                                    f"„Arkusze PZT” użyją go przy generowaniu.") if wynik else
                              "Wszystkie stacje mają układ automatyczny - plik układu usunięty.")
        return True

    def _zamknij(self):
        if self.zmiany:
            odp = messagebox.askyesnocancel("Podgląd arkuszy PZT", "Zapisać zmiany w układzie arkuszy?",
                                            parent=self)
            if odp is None or (odp and not self._zapisz()):
                return
        if getattr(self, "_dwg", None) is not None:
            self._dwg.sprzatnij()
        self.destroy()
