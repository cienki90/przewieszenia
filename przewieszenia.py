#!/usr/bin/env python3
"""Generator rysunków przewieszeń (zwisów) linii nN z projektowanym światłowodem.

Użycie:
    python przewieszenia.py "przewieszenia plan.dxf" -o "przewieszenia wynik.dxf"
            [--baza "przewieszenia baza.dxf"] [--opisy opisy.csv]

1. Z planu odczytywane są okręgi z warstwy _PRZEWIESZENIA - każdy okrąg wskazuje przęsło.
2. Dla przęsła ustalane są: słupy (numery z warstwy _numery, typy z opisów "słup nN"),
   rozpiętość (długość trasy !TELE), obwód i stacja (opisy "obw. nr" i "STACJA TRAFO").
3. Wysokości zawieszenia i zwisy pobierane są z bazy gotowych rysunków.
4. Plik CSV z opisami (miejscowość, ulica, stacja, obwód, ...) jest tworzony/uzupełniany
   automatycznie - można go edytować i uruchomić program ponownie.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import plan as plan_mod
from baza import Baza
from plan import Plan
from rysunek import Dane, SKALA_X, zbuduj
from zapis import Wyjscie

POLA = ["nr", "x", "y", "slup_l", "typ_l", "slup_p", "typ_p", "rozpietosc",
        "stacja", "obwod", "stacja2", "obwod2", "miejscowosc", "ulica"]


def wczytaj_opisy(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    return {(round(float(r["x"].replace(",", ".")), 2), round(float(r["y"].replace(",", ".")), 2)): r
            for r in rows if r.get("x") and r.get("y")}


def zapisz_opisy(path, wiersze):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=POLA, delimiter=";")
        w.writeheader()
        w.writerows(wiersze)


def main(argv=None):
    tu = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Generator rysunków przewieszeń (zwisów) z pliku planu DXF.")
    ap.add_argument("plan", help="plik DXF planu z okręgami na warstwie _PRZEWIESZENIA")
    ap.add_argument("-o", "--wynik", default=None, help="plik wynikowy DXF")
    ap.add_argument("--baza", default=os.path.join(tu, "przewieszenia baza.dxf"),
                    help="plik DXF bazy (gotowe rysunki) - parametry zwisów oraz szablon DXF")
    ap.add_argument("--szablon", default=None, help="plik DXF szablonu (domyślnie = baza)")
    ap.add_argument("--opisy", default=None,
                    help="plik CSV z opisami (domyślnie <plan>_opisy.csv); tworzony gdy nie istnieje")
    ap.add_argument("--warstwa", default=plan_mod.WARSTWA_PRZEWIESZEN, help="warstwa z okręgami")
    ap.add_argument("--warstwa-trasy", default=plan_mod.WARSTWA_TRASY, help="warstwa trasy światłowodu")
    ap.add_argument("--obrot-od", type=float, default=50.0,
                    help="przęsła dłuższe niż ta wartość [m] rysowane są pionowo (obrót 90°); 0 = nigdy")
    ap.add_argument("--rozstaw", type=float, default=100.0, help="odstęp kolumn rysunków [j]")
    a = ap.parse_args(argv)

    wynik = a.wynik or os.path.splitext(a.plan)[0] + " wynik.dxf"
    opisy_path = a.opisy or os.path.splitext(a.plan)[0] + "_opisy.csv"
    plan_mod.WARSTWA_PRZEWIESZEN = a.warstwa
    plan_mod.WARSTWA_TRASY = a.warstwa_trasy

    P = Plan(a.plan)
    lista = P.przewieszenia()
    if not lista:
        print(f"Brak okręgów na warstwie {a.warstwa} w pliku {a.plan}", file=sys.stderr)
        return 1
    B = Baza(a.baza if os.path.exists(a.baza) else None)
    if not B.rysunki:
        print("Uwaga: brak bazy - użyto domyślnych reguł zwisów.", file=sys.stderr)
    opisy = wczytaj_opisy(opisy_path)

    W = Wyjscie(a.szablon or a.baza)
    wiersze = []
    kol, wiersz_kol = 0, 0     # pozycja w siatce: kolumna, 0 = górny / 1 = dolny rząd
    Y_GORA, Y_DOL = 17.88, 0.0
    for z in lista:
        auto = dict(nr=z.nr, x=f"{z.x:.2f}", y=f"{z.y:.2f}",
                    slup_l=z.slup_l.numer or "?", typ_l=z.slup_l.typ or "",
                    slup_p=z.slup_p.numer or "?", typ_p=z.slup_p.typ or "",
                    rozpietosc=str(int(round(z.dlugosc))),
                    stacja=z.obwody[0][0] if z.obwody else "", obwod=z.obwody[0][1] if z.obwody else "",
                    stacja2=z.obwody[1][0] if len(z.obwody) > 1 else "",
                    obwod2=z.obwody[1][1] if len(z.obwody) > 1 else "",
                    miejscowosc="", ulica="")
        r = opisy.get((round(z.x, 2), round(z.y, 2)))
        if r:  # wartości z CSV mają pierwszeństwo (puste pole = wartość automatyczna, poza opisami)
            for k in POLA[3:]:
                if k in ("miejscowosc", "ulica") or (r.get(k) or "").strip():
                    auto[k] = (r.get(k) or "").strip()
        wiersze.append(auto)

        L = int(auto["rozpietosc"])
        obw = [(auto["stacja"], auto["obwod"])]
        if auto["stacja2"] or auto["obwod2"]:
            obw.append((auto["stacja2"], auto["obwod2"]))
        obw = [o for o in obw if any(o)]
        hs, zs = B.swiatlowod(L)
        drut_l, slup_l = B.linia_nn(auto["typ_l"])
        drut_p, slup_p = B.linia_nn(auto["typ_p"])
        d = Dane(auto["slup_l"], auto["typ_l"], auto["slup_p"], auto["typ_p"], L, obw,
                 auto["miejscowosc"], auto["ulica"],
                 h_swiatl=(hs, hs), zwis_swiatl=zs, h_nn=(drut_l, drut_p), zwis_nn=B.zwis_nn(L, drut_l, drut_p),
                 h_slup=(slup_l, slup_p))
        R = zbuduj(d)

        pionowo = a.obrot_od > 0 and L > a.obrot_od
        if pionowo:
            if wiersz_kol == 1:
                kol, wiersz_kol = kol + 1, 0
            x0 = kol * a.rozstaw + 10.0
            y0 = Y_DOL - 3.0 + max(0.0, (Y_GORA + 13.0 - L * SKALA_X) / 2)
            W.dodaj(R, x0, y0, rot=90)
            kol += 1
        else:
            x0 = kol * a.rozstaw
            y0 = Y_GORA if wiersz_kol == 0 else Y_DOL
            W.dodaj(R, x0, y0, rot=0)
            if wiersz_kol == 0:
                wiersz_kol = 1
            else:
                kol, wiersz_kol = kol + 1, 0

    W.zapisz(wynik)
    zapisz_opisy(opisy_path, wiersze)

    print(f"Utworzono {len(lista)} rysunków przewieszeń -> {wynik}")
    print(f"Opisy (do edycji): {opisy_path}")
    for w in wiersze:
        obw = f"{w['stacja']} {w['obwod']}" + (f" + {w['stacja2']} {w['obwod2']}" if w["stacja2"] else "")
        print(f"  {w['nr']:>3}. Słup {w['slup_l']} ({w['typ_l']}) - Słup {w['slup_p']} ({w['typ_p']}), "
              f"{w['rozpietosc']} m, {obw}  {w['miejscowosc']} {w['ulica']}".rstrip())
    for o in P.ostrzezenia:
        print("Uwaga:", o, file=sys.stderr)
    braki = [w["nr"] for w in wiersze if "?" in (w["stacja"] + w["stacja2"])]
    if braki:
        print(f"Uwaga: nie ustalono stacji dla przewieszeń {braki} - uzupełnij w {opisy_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
