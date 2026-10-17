#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Moduł „Zakładki” - komplet stron-przekładek (zakładek) dla całego projektu.

Dla każdej stacji trafo z zestawienia powstaje jedna strona z trzema wyśrodkowanymi
liniami (dużą czcionką):

    ST 05-0112
    Kiczki Pierwsze
    71/RE-5/KŚ/2026

tzn.:
    1. numer stacji trafo (z prefiksem „ST ”),
    2. miejscowość,
    3. numer warunków technicznych (WT).

Dane pobierane są z pliku zestawienia - najczęściej z „zestawienie_stacji.xlsx”
generowanego przez moduł „Rysunki stałe” (orientacje). Rozpoznawanie kolumn jest
wspólne z modułem „Opisy” (ten sam parser wczytaj_zestawienie z opisy.py), więc
działa też z zestawieniem w formacie „domtel” (Plik | trafo | miejscowosc | | wt).
Numer WT - jeden wspólny - można podać ręcznie, gdy zestawienie go nie zawiera.

Wynik powstaje w JEDNYM z dwóch formatów (przełącznik):
  * DOCX - jeden dokument .docx, każda stacja na osobnej stronie (wymaga python-docx),
  * PDF  - jeden plik .pdf, każda stacja na osobnej stronie (czysty Python, bez bibliotek).

Użycie (CLI):
    python -m generator.zakladki "zestawienie_stacji.xlsx" --wt 71/RE-5/KŚ/2026
    python -m generator.zakladki "zestawienie_stacji.xlsx" --format pdf -o zakladki.pdf
"""
from __future__ import annotations

import argparse
import os
import sys

try:  # część pakietu (python -m generator.zakladki / okno)
    from . import opisy as _opisy
except ImportError:  # bezpośrednie uruchomienie: python generator/zakladki.py
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import opisy as _opisy

FORMATY = ("docx", "pdf")


# ---------------------------------------------------------------------------
# Przygotowanie danych
# ---------------------------------------------------------------------------
def _norm_stacja(trafo: str) -> str:
    """Numer stacji z prefiksem „ST ” (bez podwajania, gdy już jest)."""
    s = (trafo or "").strip()
    if not s:
        return ""
    if s.upper().startswith("ST "):
        return "ST " + s[3:].strip()
    return "ST " + s


def przygotuj_strony(zestawienie: str, arkusz: str = "Arkusz1", wt: str = ""):
    """Zwraca listę krotek (nr_stacji, miejscowosc, wt) - po jednej na stację.

    Dane czytane są przez wspólny parser z modułu „Opisy” (rozpoznaje kolumny po
    nagłówkach - format „domtel” i „Orientacje”). WT bez wartości w zestawieniu
    uzupełniany jest wartością `wt` (ręcznie wpisany numer wspólny)."""
    _opisy._wymagaj_bibliotek()  # potrzebny openpyxl do odczytu .xlsx
    wiersze = _opisy.wczytaj_zestawienie(zestawienie, arkusz, wt_domyslne=wt)
    strony = []
    for w in wiersze:
        strony.append((_norm_stacja(w.get("trafo") or w.get("plik") or ""),
                       (w.get("miejscowosc") or "").strip(),
                       (w.get("wt") or "").strip()))
    return strony


# ---------------------------------------------------------------------------
# Rozmiar strony zakładki (koperta/przekładka Com-10): 104.7 x 241.3 mm.
# Tekst jest wyrównany do GÓRY strony, wyśrodkowany poziomo, czcionką pogrubioną 12 pt.
# ---------------------------------------------------------------------------
_COM10_W_MM = 104.7
_COM10_H_MM = 241.3
_MARGINES_GORA_MM = 10.0          # tekst zaczyna się ~1 cm od górnej krawędzi
_ROZMIAR_PT = 12                  # pogrubiona czcionka 12 pt


# ---------------------------------------------------------------------------
# Wynik: DOCX
# ---------------------------------------------------------------------------
def _zapisz_docx(strony, wyjscie: str, rozmiar_pt: int = _ROZMIAR_PT):
    """Jeden .docx: każda stacja na osobnej stronie (Com-10), 3 wyśrodkowane linie
    pogrubioną czcionką, wyrównane do góry strony."""
    try:
        import docx
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Mm, Pt
    except ImportError as ex:
        raise ImportError("Format DOCX wymaga biblioteki python-docx "
                          "(pip install python-docx)") from ex

    doc = docx.Document()
    sek = doc.sections[0]
    # rozmiar strony Com-10 (104.7 x 241.3 mm) + wąskie marginesy, tekst przy górze
    sek.page_width = Mm(_COM10_W_MM)
    sek.page_height = Mm(_COM10_H_MM)
    sek.top_margin = Mm(_MARGINES_GORA_MM)
    sek.bottom_margin = Mm(5)
    sek.left_margin = Mm(5)
    sek.right_margin = Mm(5)

    for i, (stacja, miejscowosc, wt) in enumerate(strony):
        if i > 0:
            doc.add_page_break()
        for tekst in (stacja, miejscowosc, wt):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pf = p.paragraph_format
            pf.space_before = Pt(0)
            pf.space_after = Pt(0)
            run = p.add_run(tekst)
            run.bold = True
            run.font.size = Pt(rozmiar_pt)
    doc.save(wyjscie)
    return wyjscie


# ---------------------------------------------------------------------------
# Wynik: PDF (czysty Python - bez bibliotek zewnętrznych)
# ---------------------------------------------------------------------------
# Minimalny generator PDF: strony A4, tekst czcionką bazową Helvetica-Bold.
#
# WAŻNE o polskich znakach: standardowe WinAnsiEncoding (cp1252) NIE zawiera
# większości polskich diakrytyków (ą ć ę ł ń ś ź ż …) - zostałyby zamienione na „?”.
# Dlatego budujemy WŁASNE kodowanie (Encoding z tablicą /Differences): każdemu
# polskiemu znakowi przypisujemy nazwę glifu Adobe (aogonek, eogonek, lslash, sacute,
# zdotaccent, …). Font Helvetica ma te glify - trzeba je tylko „podpiąć” pod kody bajtów.
#
# Strona zakładki ma rozmiar Com-10 (104.7 x 241.3 mm), tekst wyrównany do GÓRY.
_MM_PT = 72.0 / 25.4                        # mm -> punkty PDF
_STR_W = _COM10_W_MM * _MM_PT               # szerokość strony [pt]
_STR_H = _COM10_H_MM * _MM_PT               # wysokość strony [pt]
_GORA_PT = _MARGINES_GORA_MM * _MM_PT       # margines górny [pt]

# polski znak -> nazwa glifu Adobe (dla tablicy /Differences)
_GLIFY_PL = {
    "ą": "aogonek", "ć": "cacute", "ę": "eogonek", "ł": "lslash", "ń": "nacute",
    "ó": "oacute", "ś": "sacute", "ź": "zacute", "ż": "zdotaccent",
    "Ą": "Aogonek", "Ć": "Cacute", "Ę": "Eogonek", "Ł": "Lslash", "Ń": "Nacute",
    "Ó": "Oacute", "Ś": "Sacute", "Ź": "Zacute", "Ż": "Zdotaccent",
}
# polskim znakom przydzielamy wolne kody bajtów 0x80..0x91 (poza zakresem ASCII)
_KOD_PL = {ch: 0x80 + i for i, ch in enumerate(_GLIFY_PL)}


def _roznice_encoding() -> bytes:
    """Tablica /Differences: kod bajtu -> nazwa glifu (dla polskich znaków)."""
    czesci = []
    for ch, kod in sorted(_KOD_PL.items(), key=lambda kv: kv[1]):
        czesci.append(b"%d /%s" % (kod, _GLIFY_PL[ch].encode("ascii")))
    return b" ".join(czesci)


def _escape_pdf(s: str) -> bytes:
    """Treść tekstu PDF: ASCII + polskie znaki wg własnego kodowania + ucieczki ( ) \\."""
    out = bytearray()
    for ch in s:
        if ch in _KOD_PL:                      # polski znak -> własny kod bajtu (z /Differences)
            kod = _KOD_PL[ch]
        else:
            try:
                b = ch.encode("latin-1")       # ASCII i część znaków łacińskich
                kod = b[0]
            except UnicodeEncodeError:
                kod = ord("?")                 # znak nieobsługiwany - zastąp (bardzo rzadkie)
        if kod in (0x28, 0x29, 0x5C):          # '(' ')' '\'
            out.append(0x5C)
        out.append(kod)
    return bytes(out)


# Szerokości glifów Helvetica-Bold (AFM, w 1/1000 em) - realne metryki czcionki bazowej.
# Dzięki nim centrujemy dokładnie i - co ważne - rysujemy tekst operatorem TJ z JAWNYM
# przesuwaniem po każdym znaku, więc akcent nad polskim glifem (np. Ś) nie „zachodzi” na
# następny znak w czytnikach, które źle liczą advance akcentowanych glifów z /Differences.
_SZER_HB = {
    " ": 278, "!": 333, '"': 474, "#": 556, "$": 556, "%": 889, "&": 722, "'": 238,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556, "7": 556,
    "8": 556, "9": 556, ":": 333, ";": 333, "<": 584, "=": 584, ">": 584, "?": 611,
    "@": 975, "A": 722, "B": 722, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
    "H": 722, "I": 278, "J": 556, "K": 722, "L": 611, "M": 833, "N": 722, "O": 778,
    "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944,
    "X": 667, "Y": 667, "Z": 611, "[": 333, "\\": 278, "]": 333, "^": 584, "_": 556,
    "`": 333, "a": 556, "b": 611, "c": 556, "d": 611, "e": 556, "f": 333, "g": 611,
    "h": 611, "i": 278, "j": 278, "k": 556, "l": 278, "m": 889, "n": 611, "o": 611,
    "p": 611, "q": 611, "r": 389, "s": 556, "t": 333, "u": 611, "v": 556, "w": 778,
    "x": 556, "y": 556, "z": 500, "{": 389, "|": 280, "}": 389, "~": 584,
}
# polskie znaki - szerokość jak odpowiadającej im litery bazowej (akcent nie zmienia advance)
_SZER_PL = {
    "ą": 556, "ć": 556, "ę": 556, "ł": 278, "ń": 611, "ó": 611, "ś": 556, "ź": 556, "ż": 500,
    "Ą": 722, "Ć": 722, "Ę": 667, "Ł": 611, "Ń": 722, "Ó": 778, "Ś": 667, "Ź": 611, "Ż": 611,
}


def _szer_glifu(ch: str) -> int:
    """Szerokość glifu Helvetica-Bold w 1/1000 em (domyślnie 'o', gdy znak nieznany)."""
    if ch in _SZER_PL:
        return _SZER_PL[ch]
    return _SZER_HB.get(ch, 611)


def _szerokosc_helvetica_bold(tekst: str, rozmiar: float) -> float:
    """Szerokość tekstu Helvetica-Bold [pt] wg realnych metryk AFM (do wyśrodkowania)."""
    return sum(_szer_glifu(c) for c in tekst) / 1000.0 * rozmiar


def _strumien_strony(stacja: str, miejscowosc: str, wt: str, rozmiar: float = _ROZMIAR_PT) -> bytes:
    """Strumień rysujący 3 wyśrodkowane linie przy GÓRZE strony Com-10.

    Tekst rysujemy operatorem Tj (jedna linia = jeden napis), a wyśrodkowanie liczymy
    z realnych szerokości glifów Helvetica-Bold (AFM). Zachowujemy spójny advance
    czcionki, więc tekst pozostaje kopiowalny i wyszukiwalny."""
    linie = [stacja, miejscowosc, wt]
    interlinia = rozmiar * 1.2                       # ciasna interlinia (jak we wzorcu)
    y0 = _STR_H - _GORA_PT - rozmiar                 # pierwsza linia tuż pod górnym marginesem
    polecenia = bytearray(b"BT\n")
    for i, tekst in enumerate(linie):
        szer = _szerokosc_helvetica_bold(tekst, rozmiar)
        x = (_STR_W - szer) / 2
        y = y0 - i * interlinia
        polecenia += b"/F1 %d Tf\n" % int(rozmiar)
        polecenia += b"1 0 0 1 %.2f %.2f Tm\n" % (x, y)
        polecenia += b"(" + _escape_pdf(tekst) + b") Tj\n"
    polecenia += b"ET\n"
    return bytes(polecenia)


def _zapisz_pdf(strony, wyjscie: str, rozmiar_pt: float = _ROZMIAR_PT):
    """Jeden .pdf: każda stacja na osobnej stronie Com-10 (czysty Python)."""
    if not strony:
        raise ValueError("Brak danych do zapisania w PDF.")

    obiekty = []                         # treść każdego obiektu (bez numeru i nagłówka 'n 0 obj')
    n_stron = len(strony)
    # stałe obiekty: 1 katalog, 2 drzewo stron, 3 kodowanie, 4 czcionka.
    # strony i ich treści dalej: 5,6 (strona 1), 7,8 (strona 2), ...
    kids_num = [5 + 2 * i for i in range(n_stron)]

    obiekty.append(b"<< /Type /Catalog /Pages 2 0 R >>")                 # 1
    kids = b" ".join(b"%d 0 R" % k for k in kids_num)
    obiekty.append(b"<< /Type /Pages /Count %d /Kids [%s] >>" % (n_stron, kids))  # 2
    # 3: kodowanie bazujące na WinAnsi + /Differences z polskimi glifami
    obiekty.append(b"<< /Type /Encoding /BaseEncoding /WinAnsiEncoding "
                   b"/Differences [%s] >>" % _roznice_encoding())        # 3
    # 4: czcionka Helvetica-Bold korzystająca z własnego kodowania (obiekt 3)
    obiekty.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                   b"/Encoding 3 0 R >>")                                # 4

    for i, (stacja, miejscowosc, wt) in enumerate(strony):
        tresc = _strumien_strony(stacja, miejscowosc, wt, rozmiar_pt)
        obj_strona = kids_num[i]
        obj_tresc = obj_strona + 1
        strona = (b"<< /Type /Page /Parent 2 0 R "
                  b"/MediaBox [0 0 %.2f %.2f] "
                  b"/Resources << /Font << /F1 4 0 R >> >> "
                  b"/Contents %d 0 R >>" % (_STR_W, _STR_H, obj_tresc))
        obiekty.append(strona)
        obiekty.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(tresc), tresc))

    # złożenie pliku z tablicą xref
    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsety = [0] * (len(obiekty) + 1)
    for idx, body in enumerate(obiekty, start=1):
        offsety[idx] = len(buf)
        buf += b"%d 0 obj\n" % idx + body + b"\nendobj\n"
    xref_pos = len(buf)
    buf += b"xref\n0 %d\n" % (len(obiekty) + 1)
    buf += b"0000000000 65535 f \n"
    for idx in range(1, len(obiekty) + 1):
        buf += b"%010d 00000 n \n" % offsety[idx]
    buf += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(obiekty) + 1, xref_pos))

    with open(wyjscie, "wb") as f:
        f.write(buf)
    return wyjscie


# ---------------------------------------------------------------------------
# Funkcja generująca (wywoływalna z CLI i z pipeline/GUI)
# ---------------------------------------------------------------------------
def generuj(zestawienie, wyjscie=None, format="docx", arkusz="Arkusz1", wt="", log=None):
    """Tworzy plik zakładek (DOCX albo PDF) z zestawienia.

    Parametry:
        zestawienie - ścieżka do .xlsx (np. „zestawienie_stacji.xlsx” z Rysunków stałych),
        wyjscie     - plik wynikowy; gdy None, obok zestawienia (zakladki.docx/.pdf),
        format      - „docx” albo „pdf” (przełącznik formatu wyniku),
        arkusz      - nazwa arkusza z danymi (domyślnie „Arkusz1”),
        wt          - numer warunków (WT) wspólny, gdy zestawienie go nie zawiera,
        log         - funkcja log(msg) (domyślnie print).

    Zwraca ścieżkę utworzonego pliku."""
    if log is None:
        log = print
    fmt = (format or "docx").strip().lower()
    if fmt not in FORMATY:
        raise ValueError(f"Nieznany format „{format}” - dozwolone: {', '.join(FORMATY)}.")
    if not os.path.isfile(zestawienie):
        raise FileNotFoundError(f"Nie znaleziono zestawienia: {zestawienie}")

    strony = przygotuj_strony(zestawienie, arkusz, wt=wt)
    if not strony:
        raise ValueError("Zestawienie nie zawiera danych (żadnej stacji).")

    if wyjscie is None:
        baza = os.path.join(os.path.dirname(os.path.abspath(zestawienie)), "zakladki")
        wyjscie = baza + "." + fmt
    else:
        # dopilnuj rozszerzenia zgodnego z formatem
        rdzen, ext = os.path.splitext(wyjscie)
        if ext.lower() != "." + fmt:
            wyjscie = rdzen + "." + fmt
    os.makedirs(os.path.dirname(os.path.abspath(wyjscie)), exist_ok=True)

    braki_wt = [s[0] for s in strony if not s[2]]
    if braki_wt:
        log(f"Uwaga: brak numeru WT dla {len(braki_wt)} stacji (np. {braki_wt[:3]}) - "
            f"podaj numer warunków (--wt) lub uzupełnij kolumnę „wt” w zestawieniu.")

    log(f"Znaleziono {len(strony)} stacji w zestawieniu. Format: {fmt.upper()}.")
    if fmt == "docx":
        _zapisz_docx(strony, wyjscie)
    else:
        _zapisz_pdf(strony, wyjscie)
    for stacja, miejscowosc, w in strony:
        log(f"  [OK] {stacja:12s} {miejscowosc:20s} WT={w}")
    log(f"Gotowe: {wyjscie}")
    return wyjscie


# ---------------------------------------------------------------------------
# Main (CLI)
# ---------------------------------------------------------------------------
def main(argv=None):
    for strumien in (sys.stdout, sys.stderr):  # polskie znaki w konsoli Windows
        try:
            strumien.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(
        description="Zakładki (przekładki): dla każdej stacji trafo z zestawienia osobna strona "
                    "(nr stacji / miejscowość / WT). Wynik .docx albo .pdf.")
    ap.add_argument("zestawienie", help="plik .xlsx z danymi (np. „zestawienie_stacji.xlsx” z Rysunków stałych)")
    ap.add_argument("-o", "--wyjscie", default=None,
                    help="plik wynikowy (domyślnie zakladki.<format> obok zestawienia)")
    ap.add_argument("--format", choices=FORMATY, default="docx",
                    help="format wyniku: docx (domyślnie) albo pdf")
    ap.add_argument("--arkusz", default="Arkusz1", help="nazwa arkusza z danymi (domyślnie Arkusz1)")
    ap.add_argument("--wt", default="",
                    help="numer warunków technicznych (WT) - jeden wspólny, gdy zestawienie go nie zawiera")
    a = ap.parse_args(argv)
    try:
        generuj(a.zestawienie, a.wyjscie, format=a.format, arkusz=a.arkusz, wt=a.wt)
    except Exception as ex:  # noqa: BLE001
        sys.exit(str(ex))
    return 0


if __name__ == "__main__":
    sys.exit(main())
