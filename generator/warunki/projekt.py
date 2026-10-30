"""Wspólna logika programu (używana przez GUI i wiersz poleceń).

Kolejność pracy:
    p = Projekt(cfg)
    p.wczytaj("projekt.dxf")        # słupy, błędne kliki, strefy trafo, opisy słupów
    p.geokoduj(postep)              # miejscowość/ulica/gmina z GUGiK
    p.zastosuj_stan()               # ręczne poprawki i wykluczenia z <projekt>.wt.json
    p.planuj()                      # grupy i numery (bez zapisu)
    p.przypisz_rejony(rejony, domyslny)
    p.zapisz_dxf(...), p.zapisz_pismo(...), p.zapisz_rozbudowana(...), p.zapisz_uproszczona(...)
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

from ezdxf.document import Drawing

import string

import ezdxf
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from . import arkusze as ark
from . import dwg, dxf_writer, export, geocoder, numbering, pismo, podklad, reader, slowniki
from . import stan, ulice
from .config import Config
from .model import BlednyKlik, StacjaTrafo, Wierzcholek


class Projekt:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.plik: Path | None = None
        self.doc: Drawing | None = None
        self.slupy: list[Wierzcholek] = []
        self.bledne_kliki: list[BlednyKlik] = []
        self.stacje: list[StacjaTrafo] = []
        self.ostrzezenia: list[str] = []
        self.grupy: list[numbering.Grupa] = []
        self.plan: list[Wierzcholek] = []
        self.epsg: int | None = None
        self.opisanych_slupow = 0
        self.numerow_w_sieci = 0
        self.ulice_sprawdzone = False
        self.tolerancja_analizy = self.cfg.tolerancja_slupa
        self.arkusze: list[ark.Arkusz] = []
        self._szablon_doc = None
        # ostatnio wygenerowany plan orientacyjny (do eksportu PDF z podkładem)
        self._orient_doc: Drawing | None = None
        self._orient_podklady: list = []
        self._orient_podklad_arkusza: dict = {}
        # ręczne poprawki i ustawienia zapisywane w <projekt>.wt.json (patrz stan.py)
        self.stan: dict = stan.pusty()
        self.poprawek_zastosowanych = 0
        self.poprawek_niedopasowanych: list[str] = []
        self.blad_stanu: str | None = None

    # ------------------------------------------------------------ analiza
    def wczytaj(self, plik: str | Path) -> None:
        self.plik = Path(plik)
        self.stan = stan.wczytaj(self.plik_stanu)
        self.tolerancja_analizy = self.cfg.tolerancja_slupa
        self.doc = dwg.wczytaj(self.plik, self.cfg.oda_sciezka or None)  # DWG albo DXF
        self.slupy, self.bledne_kliki = reader.wczytaj_slupy(self.doc, self.cfg)
        if not self.slupy:
            raise ValueError(f"Brak polilinii na warstwie '{self.cfg.warstwa_tele}'.")
        self.stacje, self.ostrzezenia = reader.wczytaj_stacje_trafo(self.doc, self.cfg)
        self.opisanych_slupow = reader.przypisz_opisy_slupow(self.doc, self.slupy, self.cfg)
        self.numerow_w_sieci, o = reader.przypisz_numery_slupow(self.doc, self.slupy, self.cfg)
        self.ostrzezenia += o
        try:
            self.epsg = geocoder.wykryj_epsg(self.slupy[0].x)
        except ValueError as e:
            self.epsg = None
            self.ostrzezenia.append(str(e))

    def geokoduj(self, postep=None) -> int:
        if self.epsg is None:
            return len(self.slupy)
        g = geocoder.Geokoder(self.epsg, self.cfg.promien_adresu,
                              plik_cache=self.cfg.plik_slownikow.parent / "cache_geokodowania.json")
        return geocoder.uzupelnij(self.slupy, g, postep=postep)

    def sprawdz_ulice(self, log=print) -> list[ulice.WynikUlicy]:
        """Porównuje ulicę z adresu z nazwaną drogą (OSM) przy słupie."""
        if self.epsg is None:
            return []
        wyniki = ulice.sprawdz(self.slupy, self.epsg, self.cfg.odl_ulicy,
                               self.cfg.plik_slownikow.parent / "cache_drog", log)
        for r in wyniki:
            r.slup.ulica_droga = r.ulica_droga
            r.slup.ulica_zgodna = r.zgodna
        self.ulice_sprawdzone = True
        return wyniki

    def niezgodne_ulice(self) -> list[Wierzcholek]:
        return [w for w in self.plan if w.ulica_zgodna is False]

    def przyjmij_ulice_z_drog(self, slupy: list[Wierzcholek] | None = None) -> int:
        n = 0
        for w in (slupy if slupy is not None else self.niezgodne_ulice()):
            if w.ulica_droga:
                self.ustaw_pole(w, "ulica", w.ulica_droga, zapisz=False)
                n += 1
        if n:
            self.zapisz_stan()
        return n

    # ------------------------------------------------------------ stan projektu (.wt.json)
    @property
    def plik_stanu(self) -> Path:
        return stan.plik_stanu(self.plik)

    def _wpis_stanu(self, w: Wierzcholek) -> dict:
        return self.stan["slupy"].setdefault(stan.klucz(w.x, w.y), {})

    def ustaw_pole(self, w: Wierzcholek, atr: str, wartosc, zapisz: bool = True) -> None:
        """Ręczna poprawka pola słupa - ustawiana i zapamiętywana w pliku stanu."""
        if atr not in stan.POLA_RECZNE:
            raise ValueError(f"Pola '{atr}' nie można poprawiać ręcznie.")
        setattr(w, atr, wartosc)
        if atr == "ulica" and w.ulica_droga:
            # zgodna, gdy równa drodze; inaczej uznajemy decyzję użytkownika (None = nie zgłaszaj)
            w.ulica_zgodna = True if ulice.norm(w.ulica) == ulice.norm(w.ulica_droga) else None
        elif atr == "nr_w_sieci":
            reader.ustaw_id_slupow(self.slupy)
        self._wpis_stanu(w)[atr] = wartosc
        if zapisz:
            self.zapisz_stan()

    def zastosuj_stan(self) -> None:
        """Nakłada zapamiętane poprawki i wykluczenia na słupy (po odczycie i geokodowaniu).
        Poprawki słupów, których nie ma już w rysunku, zostają w pliku."""
        dopasowane, self.poprawek_niedopasowanych = stan.dopasuj(self.stan["slupy"], self.slupy)
        przeklucz = {}
        for idx, (k, wpis) in dopasowane.items():
            w = self.slupy[idx]
            for atr in stan.POLA_RECZNE:
                if atr in wpis:
                    setattr(w, atr, wpis[atr])
            if "ulica" in wpis and w.ulica_droga:
                w.ulica_zgodna = (True if ulice.norm(w.ulica) == ulice.norm(w.ulica_droga)
                                  else None)
            w.wykluczony = bool(wpis.get("wykluczony"))
            nowy = stan.klucz(w.x, w.y)
            if nowy != k:  # słup lekko przesunięty w rysunku - zapamiętaj nowe położenie
                przeklucz[k] = nowy
        for k, nowy in przeklucz.items():
            self.stan["slupy"][nowy] = self.stan["slupy"].pop(k)
        reader.ustaw_id_slupow(self.slupy)
        self.poprawek_zastosowanych = len(dopasowane)
        if self.poprawek_niedopasowanych:
            self.ostrzezenia.append(
                f"{len(self.poprawek_niedopasowanych)} zapamiętanych poprawek "
                f"({self.plik_stanu.name}) nie pasuje do żadnego słupa – rysunek się zmienił.")

    def migawka(self) -> dict:
        """Ręcznie zmieniane dane słupów (poprawki, wykluczenia) - do cofania zmian."""
        pola = (*stan.POLA_RECZNE, "wykluczony", "ulica_zgodna")
        return {"slupy": [{a: getattr(w, a) for a in pola} for w in self.slupy],
                "stan": copy.deepcopy(self.stan["slupy"])}

    def przywroc(self, m: dict) -> None:
        """Przywraca migawkę i zapisuje plik stanu. Potem trzeba przypisać rejony."""
        for w, wart in zip(self.slupy, m["slupy"]):
            for a, v in wart.items():
                setattr(w, a, v)
        self.stan["slupy"] = copy.deepcopy(m["stan"])
        self.planuj()
        self.odswiez_miejscowosci_arkuszy()
        self.zapisz_stan()

    def ustawienia_stanu(self) -> dict:
        return dict(self.stan.get("ustawienia") or {})

    def zapisz_ustawienia(self, ustawienia: dict) -> None:
        self.stan["ustawienia"] = dict(ustawienia)
        self.zapisz_stan()

    def zapisz_stan(self) -> bool:
        """Zapisuje plik stanu obok DXF. Błąd zapisu (np. folder tylko do odczytu) nie
        przerywa pracy - komunikat jest w self.blad_stanu."""
        if self.plik is None:
            return False
        # puste wpisy (np. słup włączony z powrotem) nie są zapisywane
        self.stan["slupy"] = {k: v for k, v in self.stan["slupy"].items() if v}
        try:
            stan.zapisz(self.plik_stanu, self.stan)
            self.blad_stanu = None
            return True
        except OSError as e:
            self.blad_stanu = f"Nie można zapisać {self.plik_stanu.name}: {e}"
            return False

    def przelicz_wgs84(self) -> None:
        """Współrzędne słupów w WGS 84 (EPSG:4326)."""
        if self.epsg is None:
            raise ValueError("Nie rozpoznano układu współrzędnych projektu.")
        from pyproj import Transformer
        t = Transformer.from_crs(self.epsg, 4326, always_xy=True)
        for w in self.slupy:
            w.lon, w.lat = t.transform(w.x, w.y)

    def planuj(self) -> None:
        self.grupy = numbering.utworz_grupy(self.slupy, self.stacje, self.cfg)
        reader.ustaw_id_slupow(self.slupy)
        self.plan = numbering.zaplanuj_numeracje(self.slupy, self.grupy, self.cfg)

    def slupy_trasa(self) -> list[Wierzcholek]:
        """Wszystkie słupy (również wykluczone) w kolejności wzdłuż trasy -
        do wykazu i mapy. Numerowane słupy idą zgodnie z planem."""
        kol = numbering.kolejnosc_trasy(self.slupy)
        return [self.slupy[i] for i in kol]

    def ustaw_wykluczenie(self, slup: Wierzcholek, wykluczony: bool) -> None:
        """Wyłącza/włącza słup w numeracji. Wykluczony słup zostaje w trasie
        (sąsiedztwo i arkusze bez zmian), ale nie dostaje numeru i nie trafia
        do planu, czyli znika z numeracji DXF, pisma i zestawień.
        Po zmianie trzeba wywołać planuj()."""
        slup.wykluczony = wykluczony
        wpis = self._wpis_stanu(slup)
        if wykluczony:
            wpis["wykluczony"] = True
        else:
            wpis.pop("wykluczony", None)
        self.zapisz_stan()

    def przypisz_rejony(self, rejony: list[dict], domyslny: dict | None) -> list[str]:
        """Rejon wg gminy ze słownika; gminy nieprzypisane -> rejon domyślny.
        Zwraca listę gmin, które dostały rejon domyślny."""
        bez = set()
        for w in self.slupy:
            r = slowniki.rejon_dla_gminy(rejony, w.gmina)
            if r is None:
                bez.add(w.gmina or "(brak gminy)")
                r = domyslny
            w.rejon = r.get("Nazwa") if r else None
            w.rejon_skrot = slowniki.nazwa_skrocona(r)
        return sorted(bez)

    # ------------------------------------------------------------ podsumowania
    def opis_planu(self) -> list[str]:
        p = self.cfg.prefiks
        wynik = []
        for g in self.grupy:
            nry = sorted(w.nr for w in g.wierzcholki)
            rodzaj = "strefa trafo" if g.stacja else "miejscowość"
            wynik.append(f"{g.nazwa} [{rodzaj}]: {len(nry)} słupów, {p}{nry[0]}–{p}{nry[-1]}")
        return wynik

    def przesla(self, prog: float | None = None) -> list[tuple[float, Wierzcholek, Wierzcholek]]:
        """Odległości między połączonymi linią słupami, dłuższe niż próg (malejąco)."""
        prog = self.cfg.przeslo_ostrzezenie if prog is None else prog
        wynik = []
        for a in self.slupy:
            for i in a.sasiedzi:
                b = self.slupy[i]
                if a.id < b.id:
                    d = math.hypot(a.x - b.x, a.y - b.y)
                    if d > prog:
                        para = sorted((a, b), key=lambda w: w.nr or 0)
                        wynik.append((d, para[0], para[1]))
        return sorted(wynik, key=lambda t: -t[0])

    def istniejaca_numeracja(self) -> int:
        return dxf_writer.istniejaca_numeracja(self.doc, self.cfg) if self.doc else 0

    def sciezka(self, katalog: Path, przyrostek: str) -> Path:
        return Path(katalog) / f"{self.plik.stem}_{przyrostek}"

    @property
    def format_rysunkow(self) -> str:
        """'dwg' albo 'dxf' - rozszerzenie rysunków wynikowych (numeracja, orientacja)."""
        return "dxf" if self.cfg.format_rysunkow.lower() == "dxf" else "dwg"

    def oda_dostepny(self) -> bool:
        return dwg.dostepny(self.cfg.oda_sciezka or None)

    # ------------------------------------------------------------ arkusze
    def szablon_doc(self):
        if self._szablon_doc is None:
            self._szablon_doc = ezdxf.readfile(str(self.cfg.szablon_arkuszy))
        return self._szablon_doc

    def planuj_arkusze(self) -> list[ark.Arkusz]:
        """Rozmieszcza arkusze trasy (skala cfg.skala_arkuszy) wzdłuż linii."""
        sz = ark.wczytaj_szablon(self.szablon_doc(), self.cfg.uklad_trasy)
        k = self.cfg.skala_arkuszy / 1000  # m terenu na mm papieru
        W, H = sz.vp_rozmiar[0] * k, sz.vp_rozmiar[1] * k
        zak = tuple(v * k for v in sz.zakazane)
        linie = ark.lancuchy_trasy(self.slupy)
        polozenia = ark.rozmiesc(linie, W, H, zak, self.cfg.margines_mm * k, self.cfg.zakladka)
        self.arkusze = []
        for i, (x0, y0) in enumerate(polozenia, start=1):
            a = ark.Arkusz(str(i), x0, y0, W, H)
            a.miejscowosci = ark.miejscowosci_na_arkuszu(a, self.slupy)
            self.arkusze.append(a)
        return self.arkusze

    def odswiez_miejscowosci_arkuszy(self) -> None:
        for a in self.arkusze:
            a.miejscowosci = ark.miejscowosci_na_arkuszu(a, self.slupy)

    @staticmethod
    def tekst_inwestora(operator: dict | None) -> str | None:
        if not operator:
            return None
        adres = ", ".join(x for x in (operator.get("Adres (siedziba)"),
                                      operator.get("Kod pocztowy")) if x)
        return "\n".join(x for x in (operator.get("Pełna nazwa") or operator.get("Nazwa"),
                                     adres) if x)

    # ------------------------------------------------------------ zapis
    def zapisz_dxf(self, wyjscie: Path, arkusze: bool = False, operator: dict | None = None,
                   opracowal: str | None = None, data: str | None = None) -> None:
        dxf_writer.usun_numeracje(self.doc, self.cfg)
        dxf_writer.zapisz_numeracje(self.doc, self.plan, self.slupy, self.cfg)
        if arkusze:
            if not self.arkusze:
                self.planuj_arkusze()
            ark.usun_arkusze(self.doc, [n for n in self.doc.layouts.names() if n.isdigit()])
            sz = ark.wczytaj_szablon(self.szablon_doc(), self.cfg.uklad_trasy)
            ark.dodaj_uklady(self.doc, self.szablon_doc(), sz, self.arkusze,
                             self.cfg.skala_arkuszy, None, self.tekst_inwestora(operator),
                             opracowal, data, zamrozone=[self.cfg.warstwa_obrysow],
                             wysokosc_branzy=self.cfg.wysokosc_branzy)
            ark.rysuj_obrysy(self.doc, self.arkusze, self.cfg.warstwa_obrysow,
                             drukowalna=False, wys_tekstu=20.0)
        dwg.zapisz(self.doc, wyjscie, self.cfg.oda_sciezka or None)  # DWG albo DXF

    def zapisz_orientacje(self, wyjscie: Path, mianownik: int, szarosc: bool,
                          operator: dict | None, opracowal: str | None, data: str | None,
                          zrodlo: str = "osm", trasa: bool = True, postep=None,
                          log=print) -> list[ark.Arkusz]:
        """Oddzielny plik DXF z planem orientacyjnym: podkład, obrysy arkuszy z numerami,
        (opcjonalnie) trasa i układy papieru 0.A, 0.B, ... w skali 1:mianownik (A3)."""
        if not self.arkusze:
            self.planuj_arkusze()
        szd = self.szablon_doc()
        sz = ark.wczytaj_szablon(szd, self.cfg.uklad_orientacji)
        k = mianownik / 1000
        W, H = sz.vp_rozmiar[0] * k, sz.vp_rozmiar[1] * k
        zak = tuple(v * k for v in sz.zakazane)
        # krawędzie obrysów jako osobne odcinki (zamknięty pierścień ma t_początku == t_końca)
        linie = [LineString([c[i], c[i + 1]]) for a in self.arkusze
                 for c in [list(a.prostokat.exterior.coords)] for i in range(4)]
        linie += ark.lancuchy_trasy(self.slupy)
        polozenia = ark.rozmiesc(linie, W, H, zak, self.cfg.margines_orientacji_mm * k,
                                 zakladka=0.0, krok=max(20.0, W / 80), gestosc=max(5.0, k))
        litery = string.ascii_uppercase
        orient = []
        for i, (x0, y0) in enumerate(polozenia):
            nazwa = "0." + (litery[i] if i < 26 else litery[i // 26 - 1] + litery[i % 26])
            a = ark.Arkusz(nazwa, x0, y0, W, H)
            a.miejscowosci = ark.miejscowosci_na_arkuszu(a, self.slupy)
            orient.append(a)

        doc = ezdxf.new(szd.dxfversion, setup=True)
        doc.header["$INSUNITS"] = 6
        msp = doc.modelspace()

        # podkład tylko w widokach arkuszy (+ zapas); arkusze, których obszary się
        # łączą -> jeden obraz, rozłączne -> osobne obrazy
        zapas = self.cfg.zapas_podkladu_mm * k
        obszary = [box(a.x0 - zapas, a.y0 - zapas, a.x0 + a.szer + zapas, a.y0 + a.wys + zapas)
                   for a in orient]
        grupy: list[list[int]] = []
        for i, o in enumerate(obszary):
            laczy = [g for g in grupy if any(obszary[j].intersects(o) for j in g)]
            nowa = [i] + [j for g in laczy for j in g]
            grupy = [g for g in grupy if g not in laczy] + [sorted(nowa)]
        grupy.sort()
        doc.layers.add(self.cfg.warstwa_podkladu, color=7)
        zrodla = []
        podklady = []
        podklad_arkusza: dict[str, object] = {}  # nazwa arkusza -> jego podkład (do PDF)
        for n, g in enumerate(grupy, start=1):
            obszar = unary_union([obszary[j] for j in g])
            przyr = "" if len(grupy) == 1 else f"_{n}"
            plik_jpg = Path(wyjscie).with_name(Path(wyjscie).stem + przyr + ".jpg")
            if len(grupy) > 1:
                log(f"Podkład {n}/{len(grupy)} (arkusze {', '.join(orient[j].nazwa for j in g)})")
            pk = podklad.pobierz(obszar.bounds, self.epsg, mianownik, plik_jpg, szarosc, zrodlo,
                                 self.cfg.katalog_kafli, postep, log, obszar=obszar)
            zrodla.append(pk.zrodlo)
            podklady.append(pk)
            for j in g:
                podklad_arkusza[orient[j].nazwa] = pk
            idef = doc.add_image_def(filename=plik_jpg.name, size_in_pixel=pk.piks)
            msp.add_image(idef, insert=(pk.x0, pk.y0), size_in_units=(pk.szer_m, pk.wys_m),
                          dxfattribs={"layer": self.cfg.warstwa_podkladu})
        doc.set_raster_variables(frame=0, quality=1, units="m")

        if trasa:
            doc.layers.add(self.cfg.warstwa_trasy_orientacji, color=1)
            for ls in ark.lancuchy_trasy(self.slupy):
                msp.add_lwpolyline(list(ls.coords), dxfattribs={
                    "layer": self.cfg.warstwa_trasy_orientacji, "lineweight": 50})
        ark.rysuj_obrysy(doc, self.arkusze, self.cfg.warstwa_obrysow, drukowalna=True,
                         wys_tekstu=4.0 * k, kolor=5)
        for e in msp.query(f'LWPOLYLINE[layer=="{self.cfg.warstwa_obrysow}"]'):
            e.dxf.lineweight = 35

        domyslne = [n for n in doc.layouts.names() if n != "Model"]
        ark.dodaj_uklady(doc, szd, sz, orient, mianownik, self.cfg.nazwa_orientacji,
                         self.tekst_inwestora(operator), opracowal, data,
                         dodatkowe_teksty=[podklad.ATRYBUCJA[z] for z in dict.fromkeys(zrodla)],
                         wysokosc_branzy=self.cfg.wysokosc_branzy)
        for n in domyslne:  # pusty układ 'Layout1' tworzony przez ezdxf
            doc.layouts.delete(n)
        dwg.zapisz(doc, wyjscie, self.cfg.oda_sciezka or None)  # DWG albo DXF
        self._orient_doc = doc
        self._orient_podklady = podklady
        self._orient_podklad_arkusza = podklad_arkusza
        self._orient_arkusze = orient
        return orient

    # ------------------------------------------------------------ eksport PDF
    def zapisz_numeracje_pdf(self, wyjscie: Path, log=print) -> int:
        """Zapisuje arkusze trasy (układy '1', '2', …) z pliku numeracji do PDF.

        Wymaga wcześniejszego wywołania zapisz_dxf(..., arkusze=True), bo układy
        papieru są tworzone razem z numeracją. Zwraca liczbę stron."""
        from . import pdf as _pdf
        if self.doc is None:
            raise ValueError("Najpierw wczytaj projekt i zapisz numerację DXF.")
        nazwy = sorted((n for n in self.doc.layouts.names() if n.isdigit()), key=int)
        if not nazwy:
            raise ValueError("Plik numeracji nie ma arkuszy 1:1000 - włącz arkusze przy "
                             "zapisie DXF.")
        return _pdf.eksportuj_uklady(self.doc, wyjscie, nazwy,
                                     warstwa_numeracji=self.cfg.warstwa_numeracji, log=log)

    def zapisz_orientacje_pdf(self, wyjscie: Path, log=print) -> int:
        """Zapisuje plan orientacyjny do PDF (po jednym arkuszu 0.A, 0.B, … na stronę).

        Podkład rastrowy jest wklejany z plików JPG wprost na strony. Wymaga
        wcześniejszego wywołania zapisz_orientacje(...). Zwraca liczbę stron."""
        from . import pdf as _pdf
        if self._orient_doc is None:
            raise ValueError("Najpierw utwórz plan orientacyjny (zapisz_orientacje).")
        doc = self._orient_doc
        nazwy = [n for n in doc.layouts.names() if n != "Model"]
        nazwy.sort(key=lambda n: (len(n), n))  # 0.A, 0.B, …, 0.AA
        obrazy_tla = {}
        for nazwa in nazwy:
            psp = doc.paperspace(nazwa)
            pk = self._orient_podklad_arkusza.get(nazwa)
            obrazy = [(pk.plik, pk.x0, pk.y0, pk.szer_m, pk.wys_m)] if pk else []
            obrazy_tla[nazwa] = _pdf.tla_z_rzutni(psp, obrazy)
        return _pdf.eksportuj_uklady(doc, wyjscie, nazwy, obrazy_tla=obrazy_tla, log=log)

    def _wgs_jesli_trzeba(self, zawsze: bool = False) -> None:
        if (self.cfg.wgs84 or zawsze) and any(w.lat is None for w in self.slupy):
            self.przelicz_wgs84()

    def zapisz_pismo(self, wyjscie: Path, operator: dict | None, data_od: str | None,
                     data_do: str = "-") -> None:
        self._wgs_jesli_trzeba()
        pismo.generuj_pismo(self.cfg.szablon_pisma, wyjscie, self.plan, operator,
                            data_od, data_do, self.cfg)

    def zapisz_rozbudowana(self, wyjscie: Path) -> None:
        self._wgs_jesli_trzeba()
        export.zapisz_rozbudowane(self.plan, wyjscie, self.cfg, self.epsg)

    def zapisz_uproszczona(self, wyjscie: Path) -> None:
        self._wgs_jesli_trzeba()
        export.zapisz_uproszczone(self.plan, wyjscie, self.cfg, self.epsg)

    def zapisz_projektowa(self, wyjscie: Path) -> None:
        self._wgs_jesli_trzeba(zawsze=True)  # kolumna "Współrzędne GPS" - zawsze WGS 84
        export.zapisz_projektowa(self.plan, wyjscie, self.cfg)
