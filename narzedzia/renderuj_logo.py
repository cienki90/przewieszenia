#!/usr/bin/env python3
"""Zamiana logo SVG (generator/grafika/mmui-logo.svg) na pliki PNG dla okna programu.

Tk nie wyświetla SVG, ale PNG wczytuje bez dodatkowych bibliotek - dlatego logo jest
renderowane raz (tym skryptem), a gotowe PNG trafiają do repozytorium:
  generator/grafika/logo_jasny_<skala>.png  - logo czarne (motyw jasny),
  generator/grafika/logo_ciemny_<skala>.png - logo białe (motyw ciemny),
gdzie <skala> to skalowanie ekranu Windows w % (100, 125, 150, 200).

Logo składa się wyłącznie z wypełnionych ścieżek (komendy M, L, Q, Z), więc renderujemy je
własnym prostym parserem: krzywe Q przybliżane odcinkami, każda podścieżka rysowana jako
wielokąt w trybie XOR (daje poprawne „dziury” - wnętrza liter i wycięte „M” w kwadracie).
Wygładzanie krawędzi: rysunek 4× większy, potem zmniejszenie filtrem LANCZOS.
Wymaga Pillow (tylko do uruchomienia tego skryptu, nie do działania programu).

Użycie:  python narzedzia/renderuj_logo.py [--wysokosc 40]
"""
from __future__ import annotations

import argparse
import os
import re
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops, ImageDraw

TU = os.path.dirname(os.path.abspath(__file__))
GRAFIKA = os.path.join(os.path.dirname(TU), "generator", "grafika")
SVG = os.path.join(GRAFIKA, "mmui-logo.svg")
NADPROBKOWANIE = 4
KROKI_KRZYWEJ = 16


def _podsciezki(d: str):
    """Ścieżka SVG (M/L/Q/Z, współrzędne bezwzględne) -> lista wielokątów [(x, y), ...]."""
    tokeny = re.findall(r"[MLQZmlqz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    wynik, biezaca, i, kom, pkt = [], [], 0, None, (0.0, 0.0)
    while i < len(tokeny):
        t = tokeny[i]
        if t.isalpha():
            kom = t.upper()
            if t.islower():
                raise ValueError("obsługiwane są tylko współrzędne bezwzględne (wielkie litery)")
            i += 1
            if kom == "Z":
                if biezaca:
                    wynik.append(biezaca)
                biezaca = []
            continue
        if kom == "M":
            if biezaca:
                wynik.append(biezaca)
            pkt = (float(tokeny[i]), float(tokeny[i + 1]))
            biezaca = [pkt]
            i += 2
            kom = "L"                                   # kolejne pary po M to odcinki
        elif kom == "L":
            pkt = (float(tokeny[i]), float(tokeny[i + 1]))
            biezaca.append(pkt)
            i += 2
        elif kom == "Q":
            cx, cy, x, y = (float(v) for v in tokeny[i:i + 4])
            x0, y0 = pkt
            for k in range(1, KROKI_KRZYWEJ + 1):
                s = k / KROKI_KRZYWEJ
                biezaca.append(((1 - s) ** 2 * x0 + 2 * (1 - s) * s * cx + s * s * x,
                                (1 - s) ** 2 * y0 + 2 * (1 - s) * s * cy + s * s * y))
            pkt = (x, y)
            i += 4
        else:
            raise ValueError(f"nieobsługiwana komenda ścieżki: {kom}")
    if biezaca:
        wynik.append(biezaca)
    return wynik


def renderuj(wysokosc: int, kolor: tuple) -> Image.Image:
    korzen = ET.parse(SVG).getroot()
    vb = [float(v) for v in korzen.get("viewBox").split()]
    skala = wysokosc * NADPROBKOWANIE / vb[3]
    w, h = round(vb[2] * skala), round(vb[3] * skala)
    maska = Image.new("L", (w, h), 0)
    for el in korzen.iter():
        if not el.tag.endswith("path"):
            continue
        for wielokat in _podsciezki(el.get("d")):
            if len(wielokat) < 3:
                continue
            warstwa = Image.new("L", (w, h), 0)
            ImageDraw.Draw(warstwa).polygon([((x - vb[0]) * skala, (y - vb[1]) * skala)
                                             for x, y in wielokat], fill=255)
            maska = ImageChops.logical_xor(maska.convert("1"), warstwa.convert("1")).convert("L")
    maska = maska.resize((round(w / NADPROBKOWANIE), wysokosc), Image.LANCZOS)
    obraz = Image.new("RGBA", maska.size, kolor + (0,))
    obraz.putalpha(maska)
    return obraz


# skalowanie ekranu Windows [%] -> osobny plik, żeby logo było ostre i w tej samej wielkości
SKALE = (100, 125, 150, 200)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Renderuje logo SVG do PNG dla okna programu.")
    ap.add_argument("--wysokosc", type=int, default=40,
                    help="wysokość logo w pikselach przy skalowaniu 100%% (domyślnie 40)")
    a = ap.parse_args(argv)
    for motyw, kolor in (("jasny", (0, 0, 0)), ("ciemny", (255, 255, 255))):
        for skala in SKALE:
            sciezka = os.path.join(GRAFIKA, f"logo_{motyw}_{skala}.png")
            renderuj(round(a.wysokosc * skala / 100), kolor).save(sciezka, optimize=True)
            print("zapisano:", sciezka)


if __name__ == "__main__":
    main()
