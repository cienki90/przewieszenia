#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kontrola przewieszeń: kopia planu z numerami przewieszeń w miejscach zaznaczeń.

Program nie zmienia oryginalnego planu. Tworzy jego KOPIĘ, a w miejscu każdego
zaznaczenia przewieszenia (środek znacznika na warstwie ``_PRZEWIESZENIA``)
wstawia numer tego przewieszenia jako tekst na osobnej, drukowalnej warstwie
``_PRZEWIESZENIA_KONTROLA``. Ten sam numer pojawia się na rysunku wynikowym
przewieszeń, dzięki czemu łatwo sprawdzić, który rysunek odpowiada któremu
zaznaczeniu na planie.

Działa na poziomie znaczników DXF (bez zewnętrznych bibliotek), więc kopia
zachowuje wszystkie pozostałe obiekty, style i ustawienia oryginału.
"""
from __future__ import annotations

try:
    from .dxfio import fmt, get, read_tags, split_entities, split_sections, write_tags, join_entities
    from .rysunek import KOLOR_KONTROLI, WARSTWA_KONTROLI
except ImportError:
    from dxfio import fmt, get, read_tags, split_entities, split_sections, write_tags, join_entities
    from rysunek import KOLOR_KONTROLI, WARSTWA_KONTROLI

# wysokość tekstu numeru na planie [jednostki rysunku planu].
# Numery słupów na warstwie _numery mają ~2.5 - używamy nieco większej, by numer
# przewieszenia był dobrze widoczny i odróżniał się od numeru słupa.
WYS_TEKSTU = 3.5


def _max_handle(secs) -> int:
    """Największy uchwyt (handle, kod 5/105) w pliku - do nadawania nowych."""
    mx = 0
    for nazwa, tags in secs.items():
        if nazwa == "HEADER":
            continue
        for c, v in tags:
            if c in (5, 105):
                try:
                    mx = max(mx, int(v, 16))
                except ValueError:
                    pass
    return mx


def _owner_modelu(entities) -> str:
    """Uchwyt właściciela encji przestrzeni modelu (kod 330 z istniejącej encji)."""
    for t, d in entities:
        w = get(d, 330)
        if w:
            return w
    return "1F"  # typowy uchwyt *Model_Space w plikach AutoCAD


def _ma_warstwe(tables_ents, nazwa: str) -> bool:
    return any(t == "LAYER" and get(d, 2) == nazwa for t, d in tables_ents)


def _rekord_warstwy(handle: str, nazwa: str, kolor: int) -> list:
    """Tagi nowej warstwy (drukowalnej, linia Continuous)."""
    return [
        (0, "LAYER"), (5, handle), (330, "2"),
        (100, "AcDbSymbolTableRecord"), (100, "AcDbLayerTableRecord"),
        (2, nazwa), (70, "     0"), (62, f"{kolor:>6}"),
        (6, "Continuous"), (370, "    25"), (390, "F"),
    ]


def _text_entity(handle: str, owner: str, x: float, y: float, wys: float,
                 tekst: str, warstwa: str, kolor: int) -> list:
    """Tagi encji TEXT (numer przewieszenia) wyśrodkowanej w punkcie (x, y)."""
    return [
        (0, "TEXT"), (5, handle), (330, owner),
        (100, "AcDbEntity"), (8, warstwa), (62, f"{kolor:>6}"),
        (100, "AcDbText"),
        (10, fmt(x)), (20, fmt(y)), (30, "0.0"),
        (40, fmt(wys)), (1, tekst),
        (72, "     1"), (73, "     2"),              # wyrównanie: poziomo środek, pionowo środek
        (11, fmt(x)), (21, fmt(y)), (31, "0.0"),
        (100, "AcDbText"),
    ]


def dodaj_numery(plan_path: str, wyjscie_path: str, pozycje) -> int:
    """Tworzy kopię planu z numerami przewieszeń.

    pozycje - iterowalne par (nr, x, y): numer przewieszenia i miejsce zaznaczenia.
    Zwraca liczbę wstawionych numerów.
    """
    pozycje = list(pozycje)
    secs_list = split_sections(read_tags(plan_path))
    secs = dict(secs_list)
    kolejnosc = [n for n, _ in secs_list]

    nast = _max_handle(secs) + 1

    def nowy_handle() -> str:
        nonlocal nast
        h = format(nast, "X")
        nast += 1
        return h

    # --- warstwa kontrolna w tabeli LAYER (gdy jej nie ma) ---
    tables = split_entities(secs["TABLES"]) if "TABLES" in secs else []
    if tables and not _ma_warstwe(tables, WARSTWA_KONTROLI):
        rekord = _rekord_warstwy(nowy_handle(), WARSTWA_KONTROLI, KOLOR_KONTROLI)
        # wstaw rekord warstwy tuż przed ENDTAB tabeli LAYER
        nowe, w_layer = [], False
        for t, d in tables:
            if t == "TABLE" and get(d, 2) == "LAYER":
                w_layer = True
            if t == "ENDTAB" and w_layer:
                nowe.extend(split_entities(rekord))
                w_layer = False
            nowe.append((t, d))
        tables = nowe
        secs["TABLES"] = join_entities(tables)

    # --- encje TEXT w przestrzeni modelu ---
    entities = split_entities(secs["ENTITIES"])
    owner = _owner_modelu(entities)
    dodane = []
    for nr, x, y in pozycje:
        tagi = _text_entity(nowy_handle(), owner, float(x), float(y), WYS_TEKSTU,
                            str(nr), WARSTWA_KONTROLI, KOLOR_KONTROLI)
        dodane.extend(split_entities(tagi))
    secs["ENTITIES"] = secs["ENTITIES"] + join_entities(dodane)

    # --- aktualizacja $HANDSEED ---
    hdr = list(secs["HEADER"])
    for i, (c, v) in enumerate(hdr):
        if c == 9 and v == "$HANDSEED":
            hdr[i + 1] = (5, format(nast, "X"))
            break
    secs["HEADER"] = hdr

    # --- złożenie pliku ---
    tags = []
    for name in kolejnosc:
        tags += [(0, "SECTION"), (2, name)] + secs[name] + [(0, "ENDSEC")]
    tags.append((0, "EOF"))
    write_tags(wyjscie_path, tags)
    return len(dodane)
