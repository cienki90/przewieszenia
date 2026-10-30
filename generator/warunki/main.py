"""Generator WT - uruchomienie z wiersza poleceń (dla automatyzacji).

Zwykle program uruchamia się oknem:  python uruchom.pyw
Wiersz poleceń:
    python -m generator_wt.main projekt.dxf --operator InterWan --rejon "Rejon ..." --tak
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import dwg, slowniki
from .config import Config
from .pismo import adres_slupa
from .projekt import Projekt


def _znajdz(lista, nazwa):
    for poz in lista:
        if poz.get("Nazwa", "").casefold() == nazwa.casefold():
            return poz
    raise SystemExit(f"Nie ma pozycji '{nazwa}'. Dostępne: "
                     + ", ".join(p.get("Nazwa", "") for p in lista))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Numeracja słupów warstwy !tele i zestawienia")
    ap.add_argument("dxf", metavar="rysunek", help="projekt DWG albo DXF")
    ap.add_argument("--katalog", help="folder wyników (domyślnie folder projektu)")
    ap.add_argument("--format", choices=["dwg", "dxf"], default="dwg",
                    help="format rysunków wynikowych (DWG wymaga ODA File Converter)")
    ap.add_argument("--oda", help="ścieżka do ODAFileConverter.exe (domyślnie szukana sama)")
    ap.add_argument("--zestawienie", nargs="+", default=["wszystkie"],
                    choices=["rozbudowana", "uproszczona", "projektowa", "oba", "wszystkie",
                             "brak"],
                    help="rodzaje zestawień (można podać kilka)")
    ap.add_argument("--wgs84", action="store_true",
                    help="współrzędne w zestawieniach i piśmie w WGS 84 zamiast PL-2000")
    ap.add_argument("--operator")
    ap.add_argument("--rejon", help="rejon domyślny dla gmin spoza listy")
    ap.add_argument("--od")
    ap.add_argument("--do", default="-")
    ap.add_argument("--prefiks", default="")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--tolerancja", type=float, default=5.0,
                    help="odległość scalania wierzchołków w jeden słup [m]")
    ap.add_argument("--opracowal")
    ap.add_argument("--data-rysunku")
    ap.add_argument("--bez-arkuszy", action="store_true")
    ap.add_argument("--pdf", action="store_true",
                    help="dodatkowo zapisz arkusze numeracji (i plan orientacyjny) jako PDF")
    ap.add_argument("--orientacja", type=int, choices=[10000, 25000],
                    help="utwórz plan orientacyjny w podanej skali")
    ap.add_argument("--szarosc", action="store_true", help="podkład w odcieniach szarości")
    ap.add_argument("--podklad", choices=["osm", "gugik"], default="osm")
    ap.add_argument("--popraw-ulice", action="store_true",
                    help="niezgodne ulice zastąp nazwą najbliższej drogi (OSM)")
    ap.add_argument("--bez-geokodowania", action="store_true")
    ap.add_argument("--tak", action="store_true", help="nie pytaj o potwierdzenie")
    a = ap.parse_args(argv)

    cfg = Config(prefiks=a.prefiks, numer_startowy=a.start, tolerancja_slupa=a.tolerancja,
                 wgs84=a.wgs84, format_rysunkow=a.format, oda_sciezka=a.oda or "")
    p = Projekt(cfg)
    if (a.format == "dwg" or dwg.jest_dwg(a.dxf)) and not p.oda_dostepny():
        raise SystemExit(dwg.KOMUNIKAT_BRAK_ODA + " (albo użyj --format dxf z projektem DXF)")
    p.wczytaj(a.dxf)
    print(f"Słupów: {len(p.slupy)}, stref trafo: {len(p.stacje)}, "
          f"błędnych klików: {len(p.bledne_kliki)}")
    for b in p.bledne_kliki:
        print(f"  scalono {b.liczba} wierzchołki (rozrzut {b.max_odleglosc} m) "
              f"X={b.y:.2f} Y={b.x:.2f}")
    for o in p.ostrzezenia:
        print("  UWAGA:", o)
    if not a.bez_geokodowania:
        bl = p.geokoduj(lambda i, n: print(f"\r  adresy: {i}/{n}", end="", file=sys.stderr))
        print(file=sys.stderr)
        if bl:
            print(f"  {bl} słupów bez adresu (błąd usługi)")
        try:
            p.sprawdz_ulice()
        except RuntimeError as e:
            print("  Sprawdzanie ulic pominięte:", e)
    p.zastosuj_stan()
    if p.poprawek_zastosowanych:
        print(f"  Ręczne poprawki z {p.plik_stanu.name}: {p.poprawek_zastosowanych} słupów")
    if p.poprawek_niedopasowanych:
        print("  UWAGA:", p.ostrzezenia[-1])
    p.planuj()
    if p.ulice_sprawdzone:
        nz = p.niezgodne_ulice()
        print(f"\nSprawdzenie ulic (drogi OSM do {cfg.odl_ulicy:g} m): niezgodnych {len(nz)}")
        for w in nz:
            print(f"  słup {w.etykieta}: adres '{w.ulica or '-'}', droga '{w.ulica_droga}'")
        if nz and a.popraw_ulice:
            print(f"  poprawiono: {p.przyjmij_ulice_z_drog()}")

    if not cfg.plik_slownikow.exists():
        slowniki.utworz_szablon(cfg.plik_slownikow)
    operatorzy = slowniki.wczytaj_liste(cfg.plik_slownikow, slowniki.ARKUSZ_OPERATORZY)
    rejony = slowniki.wczytaj_liste(cfg.plik_slownikow, slowniki.ARKUSZ_REJONY)
    operator = _znajdz(operatorzy, a.operator) if a.operator else (operatorzy or [None])[0]
    rejon = _znajdz(rejony, a.rejon) if a.rejon else (rejony or [None])[0]
    bez = p.przypisz_rejony(rejony, rejon)
    if bez:
        print(f"Gminy spoza listy (rejon domyślny {rejon and rejon['Nazwa']}): {', '.join(bez)}")

    p.planuj_arkusze()
    print(f"Arkuszy 1:{cfg.skala_arkuszy}: {len(p.arkusze)}")
    dlugie = p.przesla()
    if dlugie:
        print(f"\nPrzęsła dłuższe niż {cfg.przeslo_ostrzezenie:g} m: {len(dlugie)}")
        for d, s1, s2 in dlugie:
            znak = "!!" if d > cfg.przeslo_blad else "  "
            print(f"  {znak} {s1.etykieta}–{s2.etykieta}: {d:.2f} m")

    print("\nPlan numeracji:")
    for x in p.opis_planu():
        print("  -", x)
    print(f"  początek: {p.plan[0].etykieta} ({adres_slupa(p.plan[0])}), "
          f"koniec: {p.plan[-1].etykieta} ({adres_slupa(p.plan[-1])})")
    if not a.tak and input("\nCzy wykonać numerację? [t/N]: ").strip().lower() not in ("t", "tak"):
        print("Przerwano - nic nie zapisano.")
        return 0

    kat = Path(a.katalog) if a.katalog else p.plik.parent
    kat.mkdir(parents=True, exist_ok=True)
    rys = p.format_rysunkow  # dwg / dxf
    zad = [(f"numeracja.{rys}", lambda f: p.zapisz_dxf(f, not a.bez_arkuszy, operator,
                                                       a.opracowal, a.data_rysunku)),
           ("pismo.docx", lambda f: p.zapisz_pismo(f, operator, a.od, a.do))]
    z = set(a.zestawienie)
    if z & {"rozbudowana", "oba", "wszystkie"}:
        zad.append(("rozbudowana.xlsx", p.zapisz_rozbudowana))
    if z & {"uproszczona", "oba", "wszystkie"}:
        zad.append(("uproszczona.xls", p.zapisz_uproszczona))
    if z & {"projektowa", "wszystkie"}:
        zad.append(("tabela_projektowa.xlsx", p.zapisz_projektowa))
    if a.pdf and not a.bez_arkuszy:
        zad.append(("numeracja.pdf", lambda f: p.zapisz_numeracje_pdf(f)))
    if a.orientacja:
        zad.append((f"orientacja.{rys}", lambda f: p.zapisz_orientacje(
            f, a.orientacja, a.szarosc, operator, a.opracowal, a.data_rysunku, a.podklad)))
        if a.pdf:
            zad.append(("orientacja.pdf", lambda f: p.zapisz_orientacje_pdf(f)))
    for przyr, f in zad:
        cel = p.sciezka(kat, przyr)
        f(cel)
        print("Zapisano:", cel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
