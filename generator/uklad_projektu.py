"""Układ folderu projektu - gdzie leżą pliki wejściowe modułów (wg przykładowego projektu
„Cyganka, Brzóze, Żuków”):

    <projekt>\\                        plan „PW ….dwg”, „!ponumerowany …”, „!PZT …”, „!Przewieszenia …”,
                                       „!PPW …”, „zestawienie ….xlsx”, „Obliczenia - zestawienie ….xlsx”,
                                       tabele warunków „…_uproszczona.xls / _rozbudowana.xlsx”
    <projekt>\\PDF\\                    PDF-y
    <projekt>\\opisy\\                  szablon opisu „szablon.docx”, „PPW miński szablon.docx”
    <projekt>\\opisy\\opisy\\            wygenerowane opisy i PPW.docx
    <projekt>\\rysunki stałe\\          szablon rysunków stałych „szablon.dwg/.dxf”
    <projekt>\\rysunki stałe\\rysunki stałe\\  rysunki stałe i „zestawienie_stacji.xlsx”

Dla każdego pola z plikiem: folder, w którym okno wyboru ma się otworzyć, i plik, który program
podpina sam, gdy pole jest puste (najnowszy pasujący; najpierw w miejscu z układu, potem w całym
projekcie do 2 poziomów w głąb).
"""
from __future__ import annotations

import os

try:
    from . import nazwy_plikow as _np
except ImportError:  # bezpośrednie uruchomienie
    import nazwy_plikow as _np

RYSUNKI = (".dwg", ".dxf")
POMIJANE_PLANY = ("danewektorowe", "warunki ", "szablon")     # podkłady geodezyjne, rysunki WT, szablony


def _rysunek(n):
    return n.endswith(RYSUNKI)


def _plan_surowy(n):
    """Plan do numeracji: rysunek w folderze projektu, nie wynik programu i nie podkład."""
    return (_rysunek(n) and not n.startswith(("!", "~")) and not n.startswith(POMIJANE_PLANY)
            and not n[:-4].endswith((" - kontrola", " - ponumerowane", " - przewieszenia", " - pzt",
                                     "_numeracja", "_orientacja", " - powykonawczy"))
            and " - ponumerowane - " not in n)


def _plan_ponumerowany(n):
    return _rysunek(n) and (n.startswith(_np.PONUMEROWANY.lower() + " ") or n[:-4].endswith(" - ponumerowane"))


def _wt(n):
    return n.endswith(("_uproszczona.xls", "_uproszczona.xlsx", "_rozbudowana.xlsx", "_tabela_projektowa.xlsx"))


def _zestawienie(n):
    return n.startswith("zestawienie ") and n.endswith(".xlsx")


# pole -> (podfolder z układu, [warunki w kolejności preferencji]); warunek(nazwa małymi literami)
UKLAD = {
    "plik_numeracja": ("", [_plan_surowy]),
    "plik_przewieszenia": ("", [_plan_ponumerowany, _plan_surowy]),
    "plik_zestawienie": ("", [_plan_ponumerowany, _plan_surowy]),
    "plik_obliczenia": ("", [_plan_ponumerowany, _plan_surowy]),
    "plik_pzt": ("", [_plan_ponumerowany, _plan_surowy]),
    "plik_orientacje": ("rysunki stałe", [lambda n: _rysunek(n) and n.startswith("szablon")]),
    "orient_zasiegi": ("", [lambda n: _np.czy_pzt(n) and _rysunek(n)]),
    "wt_plik": ("", [lambda n: n.endswith(("_uproszczona.xls", "_uproszczona.xlsx")),
                     lambda n: n.endswith("_rozbudowana.xlsx"), lambda n: n.endswith("_tabela_projektowa.xlsx")]),
    "obl_zestawienie": ("", [_zestawienie]),
    "opisy_zestawienie": ("rysunki stałe/rysunki stałe", [lambda n: n == "zestawienie_stacji.xlsx"]),
    "opisy_szablon": ("opisy", [lambda n: n.endswith(".docx") and n.startswith("szablon")]),
    "opisy_obliczenia": ("", [lambda n: n.startswith("obliczenia - ") and n.endswith(".xlsx")]),
    "ppw_zestawienie": ("", [_zestawienie]),
    "ppw_zestawienie_stacji": ("rysunki stałe/rysunki stałe", [lambda n: n == "zestawienie_stacji.xlsx"]),
    "ppw_szablon": ("opisy", [lambda n: n.endswith(".docx") and "ppw" in n and "szablon" in n]),
    "ppw_renumer_dxf": ("", [lambda n: _np.czy_pzt(n) and _rysunek(n)]),
    "zakladki_zestawienie": ("rysunki stałe/rysunki stałe", [lambda n: n == "zestawienie_stacji.xlsx"]),
    "pzt_wzorzec": ("", []),             # puste = wzorzec z planu - nie podpinamy
    "final_pzt": ("", [lambda n: _np.czy_pzt(n) and _rysunek(n)]),
    "final_przewieszenia": ("", [lambda n: _rysunek(n) and n.startswith(_np.PRZEWIESZENIA.lower() + " ")]),
}
# pola z FOLDEREM: pole -> podfolder z układu (wpisywany, gdy istnieje)
FOLDERY = {
    "final_opisy": "opisy/opisy",
    "final_rysunki": "rysunki stałe/rysunki stałe",
}


def znajdz_folder(projekt: str, pole: str) -> str | None:
    if not projekt or pole not in FOLDERY:
        return None
    f = os.path.join(projekt, *FOLDERY[pole].split("/"))
    return f if os.path.isdir(f) else None
GLEBOKOSC = 2


def folder_pola(projekt: str, pole: str) -> str | None:
    """Folder, w którym okno wyboru pliku ma się otworzyć (istniejący; inaczej folder projektu)."""
    if not projekt or not os.path.isdir(projekt):
        return None
    pod = UKLAD.get(pole, ("", []))[0]
    kandydat = os.path.join(projekt, *pod.split("/")) if pod else projekt
    return kandydat if os.path.isdir(kandydat) else projekt


def _pliki(folder, rekurencyjnie):
    if not os.path.isdir(folder):
        return []
    if not rekurencyjnie:
        return [(n.lower(), os.path.join(folder, n)) for n in os.listdir(folder)
                if os.path.isfile(os.path.join(folder, n))]
    wynik = []
    for kat, podkat, nazwy in os.walk(folder):
        if kat[len(folder):].count(os.sep) >= GLEBOKOSC:
            podkat[:] = []
        podkat[:] = [p for p in podkat if not p.startswith((".", "_"))]
        wynik += [(n.lower(), os.path.join(kat, n)) for n in nazwy]
    return wynik


def _czas(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def znajdz(projekt: str, pole: str) -> str | None:
    """Plik dla pola wg układu projektu: najpierw w podfolderze z układu, potem w całym projekcie;
    przy kilku pasujących - wg kolejności warunków, a w obrębie warunku najnowszy. DWG ma
    pierwszeństwo przed DXF o tej samej nazwie (DXF bywa pomocniczą kopią)."""
    if not projekt or not os.path.isdir(projekt) or pole not in UKLAD:
        return None
    pod, warunki = UKLAD[pole]
    miejsce = os.path.join(projekt, *pod.split("/")) if pod else projekt
    for pliki in (_pliki(miejsce, False), _pliki(projekt, True)):
        for warunek in warunki:
            trafione = [p for n, p in pliki if not n.startswith("~$") and warunek(n)]
            if trafione:
                trafione.sort(key=lambda p: (_czas(p), p.lower().endswith(".dwg")), reverse=True)
                najnowszy = trafione[0]
                dwg = os.path.splitext(najnowszy)[0] + ".dwg"
                return dwg if os.path.isfile(dwg) else najnowszy
    return None
