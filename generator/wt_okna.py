"""Okna pomocnicze zakładki „Warunki techniczne” (natywne odpowiedniki okien Generatora WT):

- OknoMapy      - mapa słupów z numeracją: klik = zaznacz (i pokaż w wykazie), podwójny klik = wyłącz/włącz
                  słup w numeracji, kółko = zoom, przeciąganie = przesuń; opcjonalny podkład mapy
                  zasadniczej z Geoportalu (pobierany w tle dla widocznego obszaru),
- OknoArkuszy   - podgląd ułożenia arkuszy 1:1000 na trasie; arkusz można przeciągnąć myszą
                  (ręczne położenie zapamiętywane w <projekt>.wt.json), „Ułóż automatycznie” przywraca rozkład,
- DialogOperatora - dodanie/aktualizacja operatora po NIP (GUS albo biała lista MF + rejestr RPT UKE).

Okna otwierane na żądanie (przyciski w zakładce) - nie obciążają programu, gdy nie są potrzebne.
"""
from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

KOLORY = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
          "#17becf", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22")


def _w_tle(root, praca, gotowe, blad):
    """praca() w osobnym wątku; gotowe(wynik)/blad(tekst) wywoływane w wątku okna."""
    q = queue.Queue()

    def watek():
        try:
            q.put((True, praca()))
        except Exception as ex:  # noqa: BLE001
            q.put((False, str(ex)))
    threading.Thread(target=watek, daemon=True).start()

    def odbierz():
        try:
            ok, w = q.get_nowait()
        except queue.Empty:
            root.after(100, odbierz)
            return
        (gotowe if ok else blad)(w)
    root.after(100, odbierz)


class _Widok:
    """Wspólne przeliczanie świat <-> ekran: ekran = (ox + s*x, oy - s*y), zoom kółkiem."""

    def _init_widok(self, canvas):
        self.cv = canvas
        self.s, self.ox, self.oy = 1.0, 0.0, 0.0
        self._dopasowano = False
        canvas.bind("<MouseWheel>", self._kolko)
        canvas.bind("<Button-4>", lambda e: self._zoom(e.x, e.y, 1.2))   # Linux
        canvas.bind("<Button-5>", lambda e: self._zoom(e.x, e.y, 1 / 1.2))
        canvas.bind("<Configure>", lambda e: self._dopasuj() if not self._dopasowano else self.rysuj())

    def ekran(self, x, y):
        return self.ox + self.s * x, self.oy - self.s * y

    def swiat(self, px, py):
        return (px - self.ox) / self.s, (self.oy - py) / self.s

    def _dopasuj_do(self, x0, x1, y0, y1, m=40):
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        if w < 10 or h < 10:
            return False
        self.s = min((w - 2 * m) / max(x1 - x0, 1e-6), (h - 2 * m) / max(y1 - y0, 1e-6))
        self.ox = w / 2 - self.s * (x0 + x1) / 2
        self.oy = h / 2 + self.s * (y0 + y1) / 2
        self._dopasowano = True
        return True

    def _kolko(self, e):
        self._zoom(e.x, e.y, 1.2 if e.delta > 0 else 1 / 1.2)

    def _zoom(self, px, py, k):
        gx, gy = self.swiat(px, py)
        self.s *= k
        self.ox = px - self.s * gx
        self.oy = py + self.s * gy
        self._dopasowano = True
        self._po_zmianie_widoku()
        self.rysuj()

    def _po_zmianie_widoku(self):
        pass


# ====================================================================== mapa słupów
class OknoMapy(tk.Toplevel, _Widok):
    MAX_M_NA_PIKSEL = 2.5    # powyżej tej skali usługi EGiB/GESUT zwracają pusty obraz

    def __init__(self, zakladka):
        super().__init__(zakladka.root)
        self.z = zakladka
        self.title("Warunki techniczne – mapa słupów")
        self.geometry("1000x720")
        self.zaznaczony = None
        self._pkt = None
        self._przeciaganie = False
        self.podklad = tk.BooleanVar(value=False)
        self._podklad_img = None      # PIL.Image
        self._podklad_bbox = None
        self._podklad_tk = None       # ImageTk.PhotoImage (trzymany, żeby nie zniknął)
        self._pobieranie = False
        self._oczekuje = False
        self._zwloka = None

        pasek = ttk.Frame(self, padding=(8, 6, 8, 0))
        pasek.pack(fill="x")
        self.b_wyklucz = ttk.Button(pasek, text="Wyłącz zaznaczony z numeracji", state="disabled",
                                    command=lambda: self.zaznaczony is not None and self.z.przelacz_slup(self.zaznaczony))
        self.b_wyklucz.pack(side="left")
        ttk.Button(pasek, text="Dopasuj widok", command=self._dopasuj).pack(side="left", padx=6)
        ttk.Checkbutton(pasek, text="Mapa zasadnicza (Geoportal)", variable=self.podklad,
                        command=self._przelacz_podklad).pack(side="left", padx=6)
        ttk.Label(self, text="Klik = zaznacz słup (też w wykazie) · podwójny klik = wyłącz/włącz w numeracji · "
                             "kółko = zoom · przeciąganie = przesuń", padding=(8, 2)).pack(fill="x")
        cv = tk.Canvas(self, background="white", highlightthickness=0, cursor="crosshair")
        cv.pack(fill="both", expand=True)
        self.stan = ttk.Label(self, text="", padding=(8, 2))
        self.stan.pack(fill="x")
        self._init_widok(cv)
        cv.bind("<ButtonPress-1>", self._klik)
        cv.bind("<B1-Motion>", self._ruch)
        cv.bind("<ButtonRelease-1>", self._puszczenie)
        cv.bind("<Double-1>", self._podwojny)

    @property
    def slupy(self):
        p = self.z.projekt
        return p.slupy if p else []

    def _dopasuj(self):
        if self.slupy:
            xs, ys = [w.x for w in self.slupy], [w.y for w in self.slupy]
            if self._dopasuj_do(min(xs), max(xs), min(ys), max(ys)):
                self._po_zmianie_widoku()
        self.rysuj()

    def odswiez(self, dopasuj=False):
        if dopasuj:
            self._dopasowano = False
            self._podklad_img = None
            self._dopasuj()
        else:
            self.rysuj()

    def zaznacz(self, slup_id):
        self.zaznaczony = slup_id
        w = self.slupy[slup_id] if slup_id is not None and slup_id < len(self.slupy) else None
        self.b_wyklucz.configure(state="normal" if w is not None else "disabled",
                                 text="Włącz zaznaczony do numeracji" if w is not None and w.wykluczony
                                 else "Wyłącz zaznaczony z numeracji")
        self.rysuj()

    def _slup_przy(self, px, py, prog=12):
        najbl, najd = None, prog
        for w in self.slupy:
            ex, ey = self.ekran(w.x, w.y)
            d = math.hypot(ex - px, ey - py)
            if d <= najd:
                najd, najbl = d, w.id
        return najbl

    def _klik(self, e):
        self._pkt, self._przeciaganie = (e.x, e.y), False
        i = self._slup_przy(e.x, e.y)
        if i is not None:
            self.zaznacz(i)
            self.z.pokaz_w_wykazie(i)

    def _ruch(self, e):
        if self._pkt is None:
            return
        dx, dy = e.x - self._pkt[0], e.y - self._pkt[1]
        if self._przeciaganie or abs(dx) + abs(dy) > 3:
            self._przeciaganie = True
            self.ox += dx
            self.oy += dy
            self._pkt = (e.x, e.y)
            self._dopasowano = True
            self.rysuj()

    def _puszczenie(self, _e):
        if self._przeciaganie:
            self._po_zmianie_widoku()
        self._przeciaganie, self._pkt = False, None

    def _podwojny(self, e):
        i = self._slup_przy(e.x, e.y)
        if i is not None:
            self.z.przelacz_slup(i)

    # -------------------------------------------------- podkład mapy zasadniczej
    def _przelacz_podklad(self):
        p = self.z.projekt
        if self.podklad.get() and (not p or p.epsg is None):
            self.podklad.set(False)
            messagebox.showwarning("Mapa zasadnicza", "Nie rozpoznano układu współrzędnych projektu (PL-2000) – "
                                   "nie można pobrać podkładu z Geoportalu.", parent=self)
            return
        if not self.podklad.get():
            self._podklad_img = self._podklad_tk = None
            self.stan.configure(text="Mapa zasadnicza: wyłączona")
            self.rysuj()
        else:
            self._pobierz_podklad()

    def _po_zmianie_widoku(self):
        if self.podklad.get():
            if self._zwloka:
                self.after_cancel(self._zwloka)
            self._zwloka = self.after(400, self._pobierz_podklad)

    def _pobierz_podklad(self):
        self._zwloka = None
        p = self.z.projekt
        if not p or p.epsg is None or not self.podklad.get():
            return
        if self._pobieranie:
            self._oczekuje = True
            return
        if 1 / self.s > self.MAX_M_NA_PIKSEL:  # Geoportal nie rysuje działek w tak małej skali (pusty obraz)
            self._podklad_img = None
            self.stan.configure(text="Mapa zasadnicza: przybliż widok (kółko myszy), żeby zobaczyć działki "
                                     "i sieci – w tej skali Geoportal ich nie rysuje.")
            self.rysuj()
            return
        self._pobieranie, self._oczekuje = True, False
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        x0, y1 = self.swiat(0, 0)
        x1, y0 = self.swiat(w, h)
        mx, my = (x1 - x0) * 0.1, (y1 - y0) * 0.1
        bbox = (x0 - mx, y0 - my, x1 + mx, y1 + my)
        szer = min(int(w * 1.2), 2200)
        wys = max(1, int(szer * (bbox[3] - bbox[1]) / max(bbox[2] - bbox[0], 1e-6)))
        epsg = p.epsg
        self.stan.configure(text="Pobieranie mapy zasadniczej z Geoportalu…")

        def praca():
            from .warunki import podklad
            return podklad.pobierz_mape_zasadnicza(bbox, epsg, szer, wys, sieci=True), bbox

        def gotowe(wynik):
            self._pobieranie = False
            if not self.winfo_exists():
                return
            if self.podklad.get():
                self._podklad_img, self._podklad_bbox = wynik
                self.stan.configure(text="Mapa zasadnicza: pobrana (działki, budynki, sieci GESUT)")
                self.rysuj()
            if self._oczekuje:
                self._pobierz_podklad()

        def blad(tekst):
            self._pobieranie = False
            if self.winfo_exists():
                self.stan.configure(text="Mapa zasadnicza: błąd pobierania (sprawdź internet)")
                self.z.app._pisz("Mapa zasadnicza – błąd pobierania: " + tekst)
        _w_tle(self, praca, gotowe, blad)

    def _rysuj_podklad(self):
        """Wycina z pobranego obrazu widoczny fragment i skaluje do ekranu (PIL)."""
        if self._podklad_img is None:
            return
        from PIL import ImageTk
        img, (bx0, by0, bx1, by1) = self._podklad_img, self._podklad_bbox
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        vx0, vy1 = self.swiat(0, 0)
        vx1, vy0 = self.swiat(w, h)
        ix0, iy0, ix1, iy1 = max(bx0, vx0), max(by0, vy0), min(bx1, vx1), min(by1, vy1)
        if ix1 <= ix0 or iy1 <= iy0:
            return
        kx, ky = img.width / (bx1 - bx0), img.height / (by1 - by0)
        ramka = (int((ix0 - bx0) * kx), int((by1 - iy1) * ky), int(math.ceil((ix1 - bx0) * kx)),
                 int(math.ceil((by1 - iy0) * ky)))
        ex0, ey0 = self.ekran(ix0, iy1)
        ex1, ey1 = self.ekran(ix1, iy0)
        rw, rh = max(1, int(ex1 - ex0)), max(1, int(ey1 - ey0))
        if rw > 6000 or rh > 6000:
            return
        self._podklad_tk = ImageTk.PhotoImage(img.crop(ramka).resize((rw, rh)), master=self.cv)
        self.cv.create_image(ex0, ey0, image=self._podklad_tk, anchor="nw")

    # -------------------------------------------------- rysowanie
    def rysuj(self):
        cv = self.cv
        cv.delete("all")
        sl = self.slupy
        if not sl:
            cv.create_text(cv.winfo_width() / 2, cv.winfo_height() / 2, text="Brak projektu – przeanalizuj plik DXF.")
            return
        try:
            self._rysuj_podklad()
        except Exception:  # noqa: BLE001 - podkład jest tylko tłem
            pass
        narysowane = set()
        for w in sl:
            ax, ay = self.ekran(w.x, w.y)
            for n in w.sasiedzi:
                if (w.id, n) in narysowane:
                    continue
                narysowane |= {(w.id, n), (n, w.id)}
                bx, by = self.ekran(sl[n].x, sl[n].y)
                cv.create_line(ax, ay, bx, by, fill="#555555", width=1.4)
        for w in sl:
            x, y = self.ekran(w.x, w.y)
            wybrany = w.id == self.zaznaczony
            kol = "#9aa3ae" if w.wykluczony else ("#d62728" if wybrany else "#1d4e89")
            r = 6 if wybrany else 4
            cv.create_oval(x - r, y - r, x + r, y + r, outline=kol, width=2 if wybrany else 1,
                           fill="white" if w.wykluczony else kol)
            if w.wykluczony:
                cv.create_line(x - r, y - r, x + r, y + r, fill="#c62828", width=1.5)
                cv.create_line(x - r, y + r, x + r, y - r, fill="#c62828", width=1.5)
            etyk = "—" if w.wykluczony else (w.etykieta or "")
            if etyk:
                cv.create_text(x + 7, y - 9, text=etyk, anchor="w", fill=kol, font=("Segoe UI", 9, "bold"))
        wykl = sum(1 for w in sl if w.wykluczony)
        if not self._pobieranie and not self.podklad.get():
            self.stan.configure(text=f"Słupów: {len(sl)} · w numeracji: {len(sl) - wykl} · wyłączonych: {wykl}")


# ====================================================================== podgląd arkuszy
class OknoArkuszy(tk.Toplevel, _Widok):
    def __init__(self, zakladka):
        super().__init__(zakladka.root)
        self.z = zakladka
        self.title("Warunki techniczne – układ arkuszy")
        self.geometry("1000x720")
        self.linie, self.zakazane = [], None
        self._chwyt = None        # (arkusz, dx, dy) przy przeciąganiu arkusza
        self._pan = None

        pasek = ttk.Frame(self, padding=(8, 6))
        pasek.pack(fill="x")
        ttk.Label(pasek, text="Przeciągnij arkusz lewym przyciskiem · prawy przycisk = przesuń widok · "
                              "kółko = zoom").pack(side="left")
        ttk.Button(pasek, text="Dopasuj widok", command=self._dopasuj).pack(side="right")
        ttk.Button(pasek, text="Ułóż automatycznie", command=self._uloz).pack(side="right", padx=6)
        cv = tk.Canvas(self, background="white", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        self.stan = ttk.Label(self, text="", padding=(8, 2))
        self.stan.pack(fill="x")
        self._init_widok(cv)
        cv.bind("<ButtonPress-1>", self._chwyc)
        cv.bind("<B1-Motion>", self._przeciagaj)
        cv.bind("<ButtonRelease-1>", self._upusc)
        cv.bind("<ButtonPress-3>", lambda e: setattr(self, "_pan", (e.x, e.y)))
        cv.bind("<B3-Motion>", self._przesun_widok)
        self.odswiez(dopasuj=True)

    @property
    def arkusze(self):
        p = self.z.projekt
        return p.arkusze if p else []

    def odswiez(self, dopasuj=False):
        from .warunki import arkusze as ark
        p = self.z.projekt
        self.linie, self.zakazane = [], None
        if p and p.arkusze:
            sz = ark.wczytaj_szablon(p.szablon_doc(), p.cfg.uklad_trasy)
            k = p.cfg.skala_arkuszy / 1000
            self.linie = ark.lancuchy_trasy(p.slupy)
            self.zakazane = tuple(v * k for v in sz.zakazane)
        if dopasuj:
            self._dopasowano = False
            self._dopasuj()
        else:
            self.rysuj()

    def _dopasuj(self):
        a = self.arkusze
        if a:
            self._dopasuj_do(min(x.x0 for x in a), max(x.x0 + x.szer for x in a),
                             min(x.y0 for x in a), max(x.y0 + x.wys for x in a), m=20)
        self.rysuj()

    def _arkusz_przy(self, px, py):
        x, y = self.swiat(px, py)
        for a in reversed(self.arkusze):
            if a.x0 <= x <= a.x0 + a.szer and a.y0 <= y <= a.y0 + a.wys:
                return a
        return None

    def _chwyc(self, e):
        a = self._arkusz_przy(e.x, e.y)
        if a is not None and not self.z._praca:
            x, y = self.swiat(e.x, e.y)
            self._chwyt = (a, x - a.x0, y - a.y0)
            self.cv.configure(cursor="fleur")

    def _przeciagaj(self, e):
        if not self._chwyt:
            return
        a, dx, dy = self._chwyt
        x, y = self.swiat(e.x, e.y)
        a.x0, a.y0 = x - dx, y - dy
        self.rysuj()

    def _upusc(self, _e):
        if self._chwyt:
            self._chwyt = None
            self.cv.configure(cursor="")
            self.z.arkusze_przesuniete()
            self.rysuj()

    def _przesun_widok(self, e):
        if self._pan:
            self.ox += e.x - self._pan[0]
            self.oy += e.y - self._pan[1]
            self._pan = (e.x, e.y)
            self._dopasowano = True
            self.rysuj()

    def _uloz(self):
        if self.z._praca or not self.z.projekt:
            return
        if messagebox.askyesno("Arkusze", "Ułożyć arkusze automatycznie? Ręczne przesunięcia zostaną usunięte.",
                               parent=self):
            self.z.arkusze_automatycznie()
            self.odswiez(dopasuj=True)

    def _poza_arkuszami(self):
        """Słupy w numeracji, które nie leżą w obszarze rysunku żadnego arkusza (poza tabelką)."""
        p = self.z.projekt
        zx0, zy0, zx1, zy1 = self.zakazane or (0, 0, 0, 0)
        wynik = []
        for w in (p.plan if p else []):
            ok = False
            for a in self.arkusze:
                rx, ry = w.x - a.x0, w.y - a.y0
                if 0 <= rx <= a.szer and 0 <= ry <= a.wys and not (zx0 <= rx <= zx1 and zy0 <= ry <= zy1):
                    ok = True
                    break
            if not ok:
                wynik.append(w)
        return wynik

    def rysuj(self):
        cv = self.cv
        cv.delete("all")
        ark = self.arkusze
        if not ark:
            cv.create_text(cv.winfo_width() / 2, cv.winfo_height() / 2, text="Brak arkuszy – przeanalizuj projekt.")
            self.stan.configure(text="")
            return
        for i, a in enumerate(ark):
            k = KOLORY[i % len(KOLORY)]
            if self.zakazane:
                zx0, zy0, zx1, zy1 = self.zakazane
                x0, y0 = self.ekran(a.x0 + zx0, a.y0 + zy1)
                x1, y1 = self.ekran(a.x0 + zx1, a.y0 + zy0)
                cv.create_rectangle(x0, y0, x1, y1, outline="", fill=k, stipple="gray25")
            x0, y0 = self.ekran(a.x0, a.y0 + a.wys)
            x1, y1 = self.ekran(a.x0 + a.szer, a.y0)
            cv.create_rectangle(x0, y0, x1, y1, outline=k, width=3 if self._chwyt and self._chwyt[0] is a else 1.6)
        for ls in self.linie:
            pkt = [c for xy in ls.coords for c in self.ekran(*xy)]
            if len(pkt) >= 4:
                cv.create_line(*pkt, fill="#222222", width=1.8)
        poza = self._poza_arkuszami()
        for w in poza:
            x, y = self.ekran(w.x, w.y)
            cv.create_oval(x - 6, y - 6, x + 6, y + 6, outline="#c62828", width=2)
        for i, a in enumerate(ark):
            x, y = self.ekran(a.x0 + a.szer / 2, a.y0 + a.wys / 2)
            cv.create_text(x, y, text=a.nazwa, fill=KOLORY[i % len(KOLORY)], font=("Segoe UI", 13, "bold"))
        p = self.z.projekt
        tekst = f"Arkuszy: {len(ark)} (1:{p.cfg.skala_arkuszy})"
        if self.z.arkusze_reczne():
            tekst += " · położenie ręczne (zapamiętane w projekcie)"
        tekst += (f" · UWAGA: słupy poza arkuszami: {', '.join(w.etykieta for w in poza[:15])}"
                  + ("…" if len(poza) > 15 else "") if poza else " · wszystkie słupy na arkuszach")
        self.stan.configure(text=tekst, foreground="#C62828" if poza else "")


# ====================================================================== operator po NIP
class DialogOperatora(tk.Toplevel):
    POLA_REJESTRU = ("Pełna nazwa", "Adres (siedziba)", "Kod pocztowy", "Regon", "Numer wpisu do RPT")

    def __init__(self, zakladka):
        from .warunki import slowniki
        super().__init__(zakladka.root)
        self.z = zakladka
        self.title("Dodaj operatora po NIP")
        self.transient(zakladka.root)
        self.resizable(True, False)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        r = ttk.Frame(f)
        r.pack(fill="x")
        ttk.Label(r, text="NIP:").pack(side="left")
        self.nip = tk.StringVar()
        e = ttk.Entry(r, textvariable=self.nip, width=22)
        e.pack(side="left", padx=6)
        e.bind("<Return>", lambda _e: self.pobierz())
        e.focus_set()
        self.b_pobierz = ttk.Button(r, text="Pobierz z rejestrów", style="Accent.TButton", command=self.pobierz)
        self.b_pobierz.pack(side="left")
        self.info = ttk.Label(f, text="Dane adresowe: GUS (gdy podano klucz) albo biała lista MF; numer RPT: rejestr UKE.",
                              wraplength=520, justify="left")
        self.info.pack(anchor="w", pady=(6, 6))
        g = ttk.LabelFrame(f, text="Dane operatora (możesz poprawić przed zapisem)", padding=8)
        g.pack(fill="x")
        self.pola = {}
        for i, k in enumerate(slowniki.KOLUMNY_OPERATORA):
            ttk.Label(g, text=k + ":").grid(row=i, column=0, sticky="w", pady=1)
            v = tk.StringVar()
            ttk.Entry(g, textvariable=v, width=56).grid(row=i, column=1, sticky="we", padx=(6, 0), pady=1)
            self.pola[k] = v
        g.columnconfigure(1, weight=1)
        g2 = ttk.LabelFrame(f, text="Klucz GUS (opcjonalnie – bez klucza dane z białej listy MF)", padding=8)
        g2.pack(fill="x", pady=(8, 0))
        self.klucz = tk.StringVar(value=zakladka.app.ust.get("wt_klucz_gus", ""))
        ttk.Entry(g2, textvariable=self.klucz).pack(fill="x")
        r = ttk.Frame(f)
        r.pack(fill="x", pady=(10, 0))
        ttk.Button(r, text="Anuluj", command=self.destroy).pack(side="right")
        ttk.Button(r, text="Zapisz na liście", style="Accent.TButton", command=self.zapisz).pack(side="right", padx=6)
        self.grab_set()

    def _istniejacy(self, nip):
        import re
        return next((o for o in self.z.operatorzy if re.sub(r"\D", "", o.get("NIP", "")) == nip), None)

    def pobierz(self):
        from .warunki import rejestry
        klucz = self.klucz.get().strip()
        self.z.app.ust["wt_klucz_gus"] = klucz
        self.z.app._zaplanuj_zapis()
        nip = self.nip.get()
        self.b_pobierz.configure(state="disabled")
        self.info.configure(text="Pobieranie danych z rejestrów…")
        self.configure(cursor="watch")

        def gotowe(w):
            if not self.winfo_exists():
                return
            self.b_pobierz.configure(state="normal")
            self.configure(cursor="")
            info = list(w.pop("_info", []))
            stary = self._istniejacy(w["NIP"])
            if stary:  # zachowaj pola wpisane ręcznie, podmień tylko dane z rejestrów
                nowy = dict(stary)
                for k in self.POLA_REJESTRU + ("NIP",):
                    if w.get(k):
                        nowy[k] = w[k]
                zmiany = [k for k in self.POLA_REJESTRU if stary.get(k, "") != nowy.get(k, "")]
                info.insert(0, f"Operator „{stary.get('Nazwa')}” jest już na liście – zapis zaktualizuje dane "
                               "z rejestrów." + (f" Zmienione: {', '.join(zmiany)}." if zmiany else " Bez zmian."))
                w = nowy
            for k, v in self.pola.items():
                v.set(w.get(k, ""))
            self.info.configure(text="\n".join(info))

        def blad(tekst):
            if not self.winfo_exists():
                return
            self.b_pobierz.configure(state="normal")
            self.configure(cursor="")
            self.info.configure(text="")
            messagebox.showwarning("NIP", tekst, parent=self)
        _w_tle(self, lambda: rejestry.operator_po_nip(nip, klucz or None), gotowe, blad)

    def zapisz(self):
        from .warunki import rejestry, slowniki
        from .warunki.config import Config
        if not self.pola["Nazwa"].get().strip() or not self.pola["NIP"].get().strip():
            messagebox.showwarning("Operator", "Uzupełnij co najmniej nazwę i NIP.", parent=self)
            return
        try:
            nip = rejestry.oczysc_nip(self.pola["NIP"].get())
        except rejestry.BladRejestru as ex:
            messagebox.showwarning("Operator", str(ex), parent=self)
            return
        wpis = {k: v.get().strip() for k, v in self.pola.items()}
        wpis["NIP"] = nip
        plik = Config().plik_slownikow
        try:
            stan = slowniki.zapisz_operatora(plik, wpis)
        except PermissionError:
            messagebox.showwarning("Operator", "Plik list jest otwarty w Excelu – zamknij go i spróbuj ponownie.",
                                   parent=self)
            return
        self.z.app._pisz(f"Operator {wpis['Nazwa']}: {stan} w {plik.name}")
        self.z.operator.set(wpis["Nazwa"])
        self.z.app.ust["wt_operator"] = wpis["Nazwa"]
        self.z.app._zaplanuj_zapis()
        self.destroy()
        self.z.wczytaj_listy()
