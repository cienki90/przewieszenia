"""Nazwa firmy (inwestora) w plikach projektu - sprawdzenie, czy we wszystkich etapach jest ta sama.

Skąd czytana:
  * rysunki DXF/DWG - tabelka: tekst bezpośrednio pod etykietą „INWESTOR” (plan z układem-wzorcem
    „a”, arkusze PZT, szablon i rysunki stałe, arkusze Generatora WT),
  * skoroszyty .xlsx (zestawienia, obliczenia, tabele warunków) - ukryta właściwość dokumentu,
    którą program zapisuje przy tworzeniu pliku (oznacz_xlsx); nie widać jej w arkuszach,
  * dokumenty .docx - akapit po nagłówku „Inwestor:”, „Inwestor i zleceniodawca”, „dla inwestora:”
    (opisy, PPW - także gdy szablon poprawiono tylko w jednym z tych miejsc) albo wiersz „Pełna
    nazwa” (pismo o warunki techniczne).

Porównanie ignoruje wielkość liter, kropki i odstępy („InterWan Sp z.o.o.” = „InterWan sp. z o. o.”).
Typowa pomyłka, którą to łapie: szablon opisu albo rysunków stałych wzięty z projektu innej firmy.
"""
from __future__ import annotations

import math
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass

from .dxfio import get, getf, mtext_plain, read_tags, split_entities, split_sections

_RE_ETYKIETA = re.compile(r"^\s*inwestor\s*:?\s*$", re.I)
# miejsca, w których dokument podaje firmę: „Inwestor:”, „Inwestor i zleceniodawca”, „dla inwestora:”,
# „Pełna nazwa” (pismo o warunki); pozycje spisu treści („2. Inwestor:<tab>3”) zaczynają się od numeru
_POLE = r"(?:inwestor(?:\s+i\s+zleceniodawca)?|dla\s+inwestora|pe[łl]na\s+nazwa)"
_RE_AKAPIT = re.compile(r"^\s*" + _POLE + r"\s*[:\t]\s*(\S.*)$", re.I)
_RE_NAGLOWEK = re.compile(r"^\s*" + _POLE + r"\s*:?\s*$", re.I)
_FORMY = ((r"spolka\s+z\s+ograniczona\s+odpowiedzialnoscia", "sp z o o"), (r"spolka\s+akcyjna", "s a"),
          (r"spolka\s+jawna", "sp j"), (r"spolka\s+komandytowa", "sp k"))
ROZSZERZENIA = (".dxf", ".dwg", ".docx", ".xlsx")
_PAMIEC: dict[tuple, list[str]] = {}            # (ścieżka, mtime, rozmiar) -> nazwy


def klucz(nazwa: str) -> str:
    """Postać do porównań: bez wielkości liter, ogonków, kropek i odstępów; pełne nazwy form
    prawnych sprowadzone do skrótów („Spółka z ograniczoną odpowiedzialnością” = „sp. z o.o.”)."""
    t = unicodedata.normalize("NFKD", (nazwa or "").replace("ł", "l").replace("Ł", "L"))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    for wzor, skrot in _FORMY:
        t = re.sub(wzor, skrot, t)
    return re.sub(r"[\W_]+", "", t)


def _czysta(nazwa: str) -> str | None:
    """Pierwsza linia tekstu jako nazwa firmy; None dla pustych pól i znaczników do uzupełnienia."""
    linia = next((x.strip() for x in (nazwa or "").replace("\r", "\n").split("\n") if x.strip()), "")
    linia = re.sub(r"\s+", " ", linia)
    if len(re.sub(r"[\W\d_]+", "", linia)) < 2:              # „…”, „___”, „xx” itp.
        return None
    return linia


# ---------------------------------------------------------------- rysunki
def nazwy_z_dxf(sciezka: str) -> list[str]:
    """Nazwy firm z tabelek rysunku: teksty leżące bezpośrednio pod etykietami „INWESTOR”."""
    secs = dict(split_sections(read_tags(sciezka)))
    grupy: dict[tuple, list] = {}                # kontener (blok / układ) -> [(x, y, wys, tekst)]
    blok = None
    for sek in ("BLOCKS", "ENTITIES"):
        for t, d in split_entities(secs.get(sek, [])):
            if sek == "BLOCKS" and t == "BLOCK":
                blok = (get(d, 2) or "").strip()
            if t not in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
                continue
            tekst = mtext_plain("".join(v for c, v in d if c in (3, 1)))
            if not tekst.strip():
                continue
            kontener = ("blok", blok) if sek == "BLOCKS" else ("model/papier", (get(d, 67) or "0").strip(),
                                                              (get(d, 330) or "").strip())
            grupy.setdefault(kontener, []).append((getf(d, 10, 0.0), getf(d, 20, 0.0),
                                                   getf(d, 40, 0.0) or 2.0, tekst))
    znalezione = []
    for teksty in grupy.values():
        for ex, ey, eh, etykieta in teksty:
            if not _RE_ETYKIETA.match(etykieta):
                continue
            kandydaci = []
            for x, y, _h, tekst in teksty:
                dx, dy = x - ex, y - ey
                if tekst is etykieta or tekst.strip().endswith(":") or _RE_ETYKIETA.match(tekst):
                    continue
                if -10 * eh <= dy < 0 and abs(dx) <= 6 * eh:           # tuż pod etykietą
                    kandydaci.append((math.hypot(dx, dy), tekst))
            if kandydaci:
                nazwa = _czysta(min(kandydaci)[1])
                if nazwa:
                    znalezione.append(nazwa)
    return _rozne(znalezione)


# ---------------------------------------------------------------- dokumenty
def nazwy_z_docx(sciezka: str) -> list[str]:
    """Nazwy firm z dokumentu Word: po nagłówku „Inwestor:” / w wierszu „Pełna nazwa”."""
    import docx                                   # python-docx jest opcjonalny - ImportError łapie nazwy_z_pliku
    dok = docx.Document(sciezka)
    znalezione = []

    def z_ciagu(teksty):
        teksty = [t.strip() for t in teksty]
        for i, t in enumerate(teksty):
            m = _RE_AKAPIT.match(t)
            if m:
                nazwa = _czysta(m.group(1))
            elif _RE_NAGLOWEK.match(t):
                nazwa = _czysta(next((x for x in teksty[i + 1:] if x), ""))
            else:
                continue
            if nazwa:
                znalezione.append(nazwa)

    z_ciagu([p.text for p in dok.paragraphs])
    for tabela in dok.tables:
        for wiersz in tabela.rows:
            komorki = []
            for c in wiersz.cells:                 # scalone komórki python-docx zwraca wielokrotnie
                if not komorki or c._tc is not komorki[-1]._tc:
                    komorki.append(c)
            z_ciagu([c.text for c in komorki])
            for c in komorki:
                z_ciagu([p.text for p in c.paragraphs])
    return _rozne(znalezione)


def _rozne(nazwy) -> list[str]:
    """Różne nazwy (wg klucza), najczęstsza pierwsza."""
    licz: dict[str, list] = {}
    for n in nazwy:
        licz.setdefault(klucz(n), [0, n])[0] += 1
    return [n for _ile, n in sorted(licz.values(), key=lambda v: -v[0])]


def nazwy_z_pliku(sciezka: str) -> list[str] | None:
    """Nazwy firm z pliku .dxf / .dwg / .docx. Pusta lista = plik nie ma pola inwestora;
    None = pliku nie da się odczytać (brak pliku, konwertera DWG albo biblioteki python-docx)."""
    try:
        st = os.stat(sciezka)
    except OSError:
        return None
    k = (os.path.normcase(os.path.abspath(sciezka)), st.st_mtime_ns, st.st_size)
    if k in _PAMIEC:
        return _PAMIEC[k]
    roz = os.path.splitext(sciezka)[1].lower()
    try:
        if roz == ".docx":
            wynik = nazwy_z_docx(sciezka)
        elif roz == ".xlsx":
            wynik = nazwy_z_xlsx(sciezka)
        elif roz == ".dxf":
            wynik = nazwy_z_dxf(sciezka)
        elif roz == ".dwg":
            from . import dwg as mod_dwg
            with tempfile.TemporaryDirectory() as tmp:
                wynik = nazwy_z_dxf(mod_dwg.dwg_na_dxf(sciezka, os.path.join(tmp, "rysunek.dxf")))
        else:
            return None
    except Exception:  # noqa: BLE001 - nieczytelny plik nie może zatrzymać pracy; zgłaszamy „nie odczytano”
        return None
    _PAMIEC[k] = wynik
    return wynik


# ---------------------------------------------------------------- skoroszyty Excela
# Nazwa firmy w skoroszycie (.xlsx) jest zapisana jako niestandardowa właściwość dokumentu
# (docProps/custom.xml) - nie ma jej w żadnej komórce ani na wydruku; Excel pokazuje ją tylko
# w Plik > Informacje > Właściwości > Zaawansowane > Niestandardowe.
WLASCIWOSC = "GeneratorNN.firma"
_CUSTOM = "docProps/custom.xml"
_TYP_CUSTOM = "application/vnd.openxmlformats-officedocument.custom-properties+xml"
_REL_CUSTOM = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
_RE_WLASC = re.compile(r'<property[^>]*name="' + re.escape(WLASCIWOSC) + r'"[^>]*>\s*<vt:lpwstr>(.*?)</vt:lpwstr>', re.S)


def oznacz_xlsx(sciezka: str, nazwa: str | None) -> bool:
    """Zapisuje w skoroszycie .xlsx ukrytą nazwę firmy (właściwość dokumentu). Zwraca True, gdy
    zapisano. Nie rusza arkuszy; plik bez nazwy / nie-xlsx / otwarty w Excelu zostaje bez zmian."""
    import zipfile
    from xml.sax.saxutils import escape
    nazwa = _czysta(nazwa or "")
    if not nazwa or not str(sciezka).lower().endswith(".xlsx") or not os.path.isfile(sciezka):
        return False
    wlasc = (f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" name="{WLASCIWOSC}">'
             f'<vt:lpwstr>{escape(nazwa)}</vt:lpwstr></property>')
    try:
        with zipfile.ZipFile(sciezka) as z:
            pliki = [(i, z.read(i.filename)) for i in z.infolist()]
        nazwy = {i.filename for i, _ in pliki}
        if _CUSTOM in nazwy and WLASCIWOSC not in dict((i.filename, d) for i, d in pliki)[_CUSTOM].decode("utf-8"):
            return False                              # cudze właściwości niestandardowe - nie mieszamy
        custom = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
                  'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
                  + wlasc + '</Properties>').encode("utf-8")
        tmp = sciezka + ".tmp_firma"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for info, dane in pliki:
                if info.filename == _CUSTOM:
                    continue
                if info.filename == "[Content_Types].xml" and _CUSTOM not in nazwy:
                    dane = dane.replace(b"</Types>", f'<Override PartName="/{_CUSTOM}" ContentType="{_TYP_CUSTOM}"/></Types>'.encode())
                if info.filename == "_rels/.rels" and _CUSTOM not in nazwy:
                    dane = dane.replace(b"</Relationships>", f'<Relationship Id="rIdFirma" Type="{_REL_CUSTOM}" Target="{_CUSTOM}"/></Relationships>'.encode())
                z.writestr(info, dane)
            z.writestr(_CUSTOM, custom)
        os.replace(tmp, sciezka)
        return True
    except (OSError, zipfile.BadZipFile, KeyError):
        try:
            os.remove(sciezka + ".tmp_firma")
        except OSError:
            pass
        return False


def nazwy_z_xlsx(sciezka: str) -> list[str]:
    """Ukryta nazwa firmy zapisana w skoroszycie przez oznacz_xlsx ([] gdy jej nie ma)."""
    import zipfile
    from xml.sax.saxutils import unescape
    with zipfile.ZipFile(sciezka) as z:
        if _CUSTOM not in z.namelist():
            return []
        m = _RE_WLASC.search(z.read(_CUSTOM).decode("utf-8"))
    nazwa = _czysta(unescape(m.group(1))) if m else None
    return [nazwa] if nazwa else []


def firma_z_plikow(*sciezki) -> str | None:
    """Pierwsza nazwa firmy znaleziona w podanych plikach (rysunek, dokument, skoroszyt)."""
    for s in sciezki:
        nazwy = nazwy_z_pliku(s) if s else None
        if nazwy:
            return nazwy[0]
    return None


# ---------------------------------------------------------------- porównanie
@dataclass
class Wpis:
    opis: str                       # gdzie plik jest używany, np. „Opisy techniczne - szablon”
    plik: str
    nazwy: list | None              # None = nie odczytano; [] = brak pola inwestora


def zbierz(pliki) -> list[Wpis]:
    """[(opis, ścieżka)] -> wpisy z nazwami firm; ten sam plik podany kilka razy czytany jest raz."""
    wynik, bylo = [], {}
    for opis, sciezka in pliki:
        if not sciezka or os.path.splitext(sciezka)[1].lower() not in ROZSZERZENIA:
            continue
        k = os.path.normcase(os.path.abspath(sciezka))
        if k in bylo:
            bylo[k].opis += "; " + opis
            continue
        bylo[k] = Wpis(opis, sciezka, nazwy_z_pliku(sciezka))
        wynik.append(bylo[k])
    return wynik


def grupy(wpisy) -> dict[str, tuple[str, list[Wpis]]]:
    """{klucz: (nazwa do pokazania, [wpisy])} - po jednej grupie na każdą różną nazwę firmy."""
    g: dict[str, tuple[str, list[Wpis]]] = {}
    for w in wpisy:
        for n in w.nazwy or []:
            g.setdefault(klucz(n), (n, []))[1].append(w)
    return g


def raport(wpisy) -> tuple[bool, list[str]]:
    """(czy nazwa jest wszędzie ta sama, linie opisu). Pliki bez pola inwestora nie są rozbieżnością."""
    g = grupy(wpisy)
    linie = []
    for _k, (nazwa, lista) in sorted(g.items(), key=lambda kv: -len(kv[1][1])):
        linie.append(f"  „{nazwa}”:")
        for w in lista:
            linie.append(f"      {w.opis}: {os.path.basename(w.plik)}")
    nieodczytane = [w for w in wpisy if w.nazwy is None]
    if nieodczytane:
        linie.append("  nie odczytano: " + ", ".join(os.path.basename(w.plik) for w in nieodczytane))
    return len(g) <= 1, linie
