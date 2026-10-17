# -*- coding: utf-8 -*-
"""
Generator opisów technicznych (.docx) dla Domtel Telecom.

Na podstawie:
  - szablonu .docx (domyślnie "szablon.docx")
  - zestawienia .xlsx (domyślnie "zestawienie domtel.xlsx", arkusz "Arkusz1")

tworzy dla każdego wiersza zestawienia osobny plik .docx z podstawionymi danymi:
  - miejscowość
  - numer stacji trafo
  - numer warunków technicznych (WT)

Zestawienie (Arkusz1) ma kolumny:
    Plik | trafo | miejscowosc | (pusta) | wt
np.
    433  | 05-0433 | Osęka    |  | 100/RE-5/KŚ/2026

Nazwa pliku wynikowego pochodzi z kolumny "Plik" (np. 433.docx).

Użycie:
    python generator.py
    python generator.py --szablon szablon.docx --zestawienie "zestawienie domtel.xlsx" --out wynik
"""

import argparse
import copy
import os
import sys

# Biblioteki openpyxl / python-docx są OPCJONALNE i potrzebne tylko dla modułu
# „Opisy techniczne”. Importujemy je LENIWIE (patrz _wymagaj_bibliotek), żeby sam
# import tego modułu nie wywracał całego programu, gdy bibliotek brak - pozostałe
# kroki łańcucha (przewieszenia/zestawienie/obliczenia) działają bez nich.
openpyxl = None
docx = None
OxmlElement = None
qn = None


def _wymagaj_bibliotek():
    """Ładuje openpyxl i python-docx. Zgłasza ImportError z czytelnym komunikatem,
    gdy którejś brak - łapie to pipeline i pomija jedynie krok „opisy”."""
    global openpyxl, docx, OxmlElement, qn
    if openpyxl is None:
        try:
            import openpyxl as _openpyxl
        except ImportError as ex:
            raise ImportError("Brak biblioteki openpyxl. Zainstaluj: pip install openpyxl") from ex
        openpyxl = _openpyxl
    if docx is None:
        try:
            import docx as _docx
            from docx.oxml import OxmlElement as _OxmlElement
            from docx.oxml.ns import qn as _qn
        except ImportError as ex:
            raise ImportError("Brak biblioteki python-docx. Zainstaluj: pip install python-docx") from ex
        docx, OxmlElement, qn = _docx, _OxmlElement, _qn


# ---------------------------------------------------------------------------
# Wczytanie danych z zestawienia
# ---------------------------------------------------------------------------
def _ascii(s):
    tr = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    return str(s or "").translate(tr).strip().lower()


# nagłówki rozpoznawane dla każdego pola (po zamianie na ascii/małe litery)
_NAGLOWKI = {
    "plik":        ("plik", "nr stacji", "numer", "nr"),
    "trafo":       ("trafo", "oznaczenie stacji", "nr trafo", "stacja", "nr stacji trafo"),
    "miejscowosc": ("miejscowosc", "miejscowość", "miejscowosci"),
    "wt":          ("wt", "nr wt", "numer warunkow", "numer warunkow technicznych", "warunki"),
}


def wczytaj_zestawienie(sciezka, arkusz="Arkusz1", wt_domyslne=""):
    """Zwraca listę słowników: {plik, trafo, miejscowosc, wt}.

    Rozpoznaje kolumny PO NAGŁÓWKACH, więc działa zarówno z zestawieniem „domtel”
    (Plik | trafo | miejscowosc | | wt) jak i z zestawieniem z modułu Orientacje
    (Lp. | Oznaczenie stacji | Nr stacji | Miejscowość | ...). Gdy nagłówków nie ma -
    przyjmuje stary układ domtel (A=plik, B=trafo, C=miejscowosc, E=wt).

    wt_domyslne - numer warunków wstawiany, gdy w zestawieniu nie ma kolumny „wt”
    (tak jest w zestawieniu z Orientacji - WT podaje się ręcznie)."""
    wb = openpyxl.load_workbook(sciezka, data_only=True)
    if arkusz not in wb.sheetnames:
        arkusz = wb.sheetnames[0]
    ws = wb[arkusz]

    rows = [[("" if c is None else str(c).strip()) for c in r] for r in ws.iter_rows(values_only=True)]
    if not rows:
        return []

    # rozpoznanie kolumn po nagłówku (pierwszy wiersz)
    naglowek = [_ascii(v) for v in rows[0]]
    kol = {}
    for idx, h in enumerate(naglowek):
        for pole, nazwy in _NAGLOWKI.items():
            if pole not in kol and h in nazwy:
                kol[pole] = idx
    # Orientacje: "nr stacji" trafia zarówno do plik jak i (gdy brak oznaczenia) do trafo
    ma_naglowek = bool(kol)
    if not ma_naglowek:
        kol = {"plik": 0, "trafo": 1, "miejscowosc": 2, "wt": 4}   # stary układ domtel

    def pole(vals, nazwa):
        i = kol.get(nazwa)
        return vals[i] if i is not None and i < len(vals) else ""

    wiersze = []
    for i, vals in enumerate(rows):
        if ma_naglowek and i == 0:
            continue
        if not any(vals):
            continue
        plik = pole(vals, "plik")
        trafo = pole(vals, "trafo") or plik
        if not plik and trafo:
            plik = trafo.split("-")[-1].lstrip("0") or trafo
        miejscowosc = pole(vals, "miejscowosc")
        wt = pole(vals, "wt") or wt_domyslne
        if not plik:
            continue
        wiersze.append({
            "plik": plik,
            "trafo": trafo,
            "miejscowosc": miejscowosc,
            "wt": wt,
        })
    return wiersze


# ---------------------------------------------------------------------------
# Narzędzia do operacji na runach akapitu
# ---------------------------------------------------------------------------
def tekst_akapitu(par):
    return "".join(r.text for r in par.runs)


def wstaw_po_runie_z_fraza(par, fraza, wstawka, dopisz_na_koniec_runu=True):
    """
    Znajduje pierwszy run którego tekst kończy się daną frazą (lub ją zawiera)
    i dopisuje 'wstawka' bezpośrednio po tym fragmencie, zachowując formatowanie
    tego runu. Zwraca True gdy się udało.
    """
    for r in par.runs:
        if fraza in r.text:
            idx = r.text.rfind(fraza) + len(fraza)
            r.text = r.text[:idx] + wstawka + r.text[idx:]
            return True
    return False


def wstaw_przed_fraza(par, fraza, wstawka):
    """Dopisuje 'wstawka' bezpośrednio PRZED frazą w pierwszym runie który ją zawiera."""
    for r in par.runs:
        if fraza in r.text:
            idx = r.text.find(fraza)
            r.text = r.text[:idx] + wstawka + r.text[idx:]
            return True
    return False


def dopisz_do_runu_z_fraza(par, fraza, wstawka):
    """Dopisuje 'wstawka' na koniec tekstu pierwszego runu zawierającego frazę."""
    for r in par.runs:
        if fraza in r.text:
            r.text = r.text + wstawka
            return True
    return False


def dopisz_do_runu_po_kotwicy(par, kotwica, wartosc_runu, wstawka):
    """
    Znajduje run zawierający 'kotwica', a następnie pierwszy KOLEJNY run którego
    tekst jest dokładnie równy 'wartosc_runu' i dopisuje do niego 'wstawka'.
    """
    po_kotwicy = False
    for r in par.runs:
        if not po_kotwicy:
            if kotwica in r.text:
                po_kotwicy = True
            continue
        if r.text == wartosc_runu:
            r.text = r.text + wstawka
            return True
    return False


def unikalne_komorki(row):
    """Zwraca komórki wiersza bez duplikatów powstałych ze scalenia (ten sam _tc)."""
    widziane = set()
    wynik = []
    for c in row.cells:
        key = id(c._tc)
        if key not in widziane:
            widziane.add(key)
            wynik.append(c)
    return wynik


# ---------------------------------------------------------------------------
# Podstawienie danych w dokumencie
# ---------------------------------------------------------------------------
def wypelnij_dokument(doc, dane):
    """
    Wypełnia dokument danymi projektu.

    Szablon korzysta z kontrolek zawartości (Content Controls / SDT) oznaczonych
    tagami 'miejscowosc', 'wt' i 'trafo'. Każda taka kontrolka pokazuje placeholder
    "Kliknij lub naciśnij tutaj, aby wprowadzić tekst." – wstawiamy do niej właściwą
    wartość i usuwamy status placeholdera.

    Dla ewentualnych starszych szablonów bez kontrolek SDT działa też podstawianie
    po frazach-kotwicach (fallback).
    """
    miejscowosc = dane["miejscowosc"]
    trafo = dane["trafo"]
    wt = dane["wt"]
    mapowanie = {"miejscowosc": miejscowosc, "wt": wt, "trafo": trafo}

    uzupelnione = {"miejscowosc": 0, "trafo": 0, "wt": 0}

    # 1) Wypełnianie kontrolek zawartości (SDT) po tagu/aliasie
    sdt_lista = _wszystkie_sdt(doc)
    for sdt in sdt_lista:
        klucz = _sdt_klucz(sdt)
        if klucz in mapowanie:
            if _wypelnij_sdt(sdt, mapowanie[klucz]):
                uzupelnione[klucz] += 1

    # 2) Fallback dla szablonów bez SDT (podstawianie po frazach)
    if sum(uzupelnione.values()) == 0:
        _wypelnij_po_frazach(doc, dane, uzupelnione)

    # 3) "Spłaszczenie" wypełnionych kontrolek do zwykłego tekstu
    #    (plik wygląda i zachowuje się jak gotowe pliki referencyjne – bez pól).
    for sdt in _wszystkie_sdt(doc):
        if _sdt_klucz(sdt) in mapowanie:
            _splaszcz_sdt(sdt)

    return uzupelnione


# ---- Obsługa kontrolek zawartości (SDT) ----
def _wszystkie_sdt(doc):
    """Zwraca wszystkie elementy <w:sdt> w treści dokumentu."""
    return doc.element.body.findall(".//" + qn("w:sdt"))


def _sdt_klucz(sdt):
    """Zwraca tag lub alias kontrolki (małymi literami), albo None."""
    pr = sdt.find(qn("w:sdtPr"))
    if pr is None:
        return None
    for nazwa in ("w:tag", "w:alias"):
        el = pr.find(qn(nazwa))
        if el is not None:
            v = el.get(qn("w:val"))
            if v:
                return v.strip().lower()
    return None


def _wypelnij_sdt(sdt, wartosc):
    """
    Wstawia 'wartosc' do zawartości kontrolki SDT, zachowując formatowanie
    zdefiniowane w sdtPr/rPr, oraz usuwa status placeholdera.
    Zwraca True gdy wypełniono.
    """
    pr = sdt.find(qn("w:sdtPr"))
    content = sdt.find(qn("w:sdtContent"))
    if content is None:
        return False

    # formatowanie runu wartości – z sdtPr/rPr jeśli jest
    rpr_wzor = None
    if pr is not None:
        rpr = pr.find(qn("w:rPr"))
        if rpr is not None:
            rpr_wzor = copy.deepcopy(rpr)

    # usuń status placeholdera (żeby to nie był już "Kliknij lub naciśnij...")
    if pr is not None:
        for tag in ("w:showingPlcHdr", "w:temporary"):
            el = pr.find(qn(tag))
            if el is not None:
                pr.remove(el)

    # znajdź pierwszy akapit w content; jeśli brak – pracujemy bezpośrednio na runach
    p = content.find(qn("w:p"))
    kontener = p if p is not None else content

    # usuń dotychczasowe runy (placeholder)
    for r in kontener.findall(qn("w:r")):
        kontener.remove(r)

    # zbuduj nowy run z wartością
    r = OxmlElement("w:r")
    if rpr_wzor is not None:
        r.append(rpr_wzor)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = wartosc
    r.append(t)
    kontener.append(r)
    return True


def _splaszcz_sdt(sdt):
    """
    Zamienia kontrolkę <w:sdt> na jej zawartość – przenosi dzieci <w:sdtContent>
    w miejsce kontrolki i usuwa samą kontrolkę. Dzięki temu wynik nie zawiera już
    pól (content controls), tylko zwykły tekst, tak jak w gotowych plikach.

    Obsługuje zarówno SDT na poziomie akapitu (sdtContent zawiera <w:p>),
    jak i inline (sdtContent zawiera <w:r>).
    """
    content = sdt.find(qn("w:sdtContent"))
    rodzic = sdt.getparent()
    if content is None or rodzic is None:
        return
    idx = list(rodzic).index(sdt)
    # przenosimy dzieci sdtContent (w odwrotnej kolejności wstawiając pod tym samym idx)
    dzieci = list(content)
    for i, child in enumerate(dzieci):
        rodzic.insert(idx + i, child)
    rodzic.remove(sdt)


# ---- Fallback: podstawianie po frazach (szablony bez SDT) ----
def _wypelnij_po_frazach(doc, dane, uzupelnione):
    miejscowosc = dane["miejscowosc"]
    trafo = dane["trafo"]
    wt = dane["wt"]

    for par in doc.paragraphs:
        txt = tekst_akapitu(par)

        if "Tematem dokumentacji jest lini" in txt and " telekomunikacyjnej światłowodowej" in txt \
                and "w miejscowości" in txt and "słupach" in txt \
                and "jest linii" not in txt:
            if dopisz_do_runu_po_kotwicy(par, "iejscowości", " ", miejscowosc):
                uzupelnione["miejscowosc"] += 1
            else:
                wstaw_po_runie_z_fraza(par, "iejscowości", miejscowosc)
                uzupelnione["miejscowosc"] += 1
            if par.runs and par.runs[-1].text == ".":
                par.runs[-1].text = wt + "."
                uzupelnione["wt"] += 1
            continue

        if txt.startswith("Pismo PGE Dystrybucja") and txt.rstrip().endswith("nr"):
            if par.runs:
                par.runs[-1].text = par.runs[-1].text + wt
                uzupelnione["wt"] += 1
            continue

        if txt.startswith("Podwieszenie proj. światłowodu na") and "w m." in txt:
            if dopisz_do_runu_z_fraza(par, "m. ", miejscowosc):
                uzupelnione["miejscowosc"] += 1
            continue

        if txt.startswith("Na terenie miejscowości") and "napowietrzna sieć elektroenergetyczna" in txt:
            wstawiono = False
            for i, r in enumerate(par.runs):
                if r.text == "miejscowości " and i > 0:
                    r.text = r.text + miejscowosc
                    wstawiono = True
                    break
            if not wstawiono:
                wstaw_po_runie_z_fraza(par, "miejscowości ", miejscowosc)
                wstawiono = True
            if wstawiono:
                uzupelnione["miejscowosc"] += 1
            continue

        if "Sieć napowietrzna nN jest zasilona ze stacji" in txt and "SN/nN" in txt:
            if par.runs:
                par.runs[-1].text = par.runs[-1].text + trafo
                uzupelnione["trafo"] += 1
            continue

        if "Tematem dokumentacji jest linii telekomunikacyjnej" in txt \
                and "w miejscowości" in txt:
            if dopisz_do_runu_z_fraza(par, "w miejscowości", miejscowosc):
                uzupelnione["miejscowosc"] += 1
            if par.runs and par.runs[-1].text == ".":
                par.runs[-1].text = wt + "."
                uzupelnione["wt"] += 1
            continue

        if txt.startswith("Projekt linii telekomunikacyjnej światłowodowej") \
                and "zasilanej ze stacji transformatorowej" in txt:
            if dopisz_do_runu_z_fraza(par, "w miejscowości", miejscowosc):
                uzupelnione["miejscowosc"] += 1
            if dopisz_do_runu_po_kotwicy(par, "nr ", " ", trafo):
                uzupelnione["trafo"] += 1
            for r in par.runs:
                if r.text.endswith("z warunkami nr "):
                    r.text = r.text + wt
                    uzupelnione["wt"] += 1
                    break
            continue

    if doc.tables:
        t = doc.tables[0]
        for row in t.rows:
            for cell in unikalne_komorki(row):
                for par in cell.paragraphs:
                    txt = tekst_akapitu(par)
                    if "sieci elektroenergetycznej nN 0,4kV w miejscowości" in txt \
                            and not txt.strip().endswith(miejscowosc or "\0"):
                        if par.runs and "miejscowości" in txt:
                            par.runs[-1].text = par.runs[-1].text + miejscowosc
                            uzupelnione["miejscowosc"] += 1
                    elif txt.strip().startswith("Numer warunków:"):
                        if par.runs:
                            par.runs[-1].text = par.runs[-1].text + wt
                            uzupelnione["wt"] += 1
                    elif txt.strip().startswith("Nr stacji trafo:"):
                        if par.runs:
                            par.runs[-1].text = par.runs[-1].text + trafo
                            uzupelnione["trafo"] += 1


# ---------------------------------------------------------------------------
# Funkcja generująca (wywoływalna z CLI i z GUI)
# ---------------------------------------------------------------------------
def generuj(szablon, zestawienie, out=".", arkusz="Arkusz1",
            obliczenia=None, wt="", log=None):
    """
    Generuje pliki .docx dla wszystkich pozycji z zestawienia.

    Parametry:
        szablon      – ścieżka do szablonu .docx
        zestawienie  – ścieżka do pliku .xlsx z danymi
        out          – katalog wyjściowy
        arkusz       – nazwa arkusza z danymi (domyślnie 'Arkusz1')
        obliczenia   – (opcjonalnie) ścieżka do pliku .xlsx z obliczeniami
                       nośności słupów. Jeśli podana, dla każdego projektu, dla
                       którego istnieje arkusz o nazwie = numer pliku, zostanie
                       wstawiona tabela "Zestawienie zbiorcze słupów".
        log          – (opcjonalnie) funkcja log(msg) do raportowania postępu
                       (np. do GUI). Domyślnie print.

    Zwraca listę nazw utworzonych plików.
    """
    if log is None:
        log = print

    _wymagaj_bibliotek()

    if not os.path.isfile(szablon):
        raise FileNotFoundError(f"Nie znaleziono szablonu: {szablon}")
    if not os.path.isfile(zestawienie):
        raise FileNotFoundError(f"Nie znaleziono zestawienia: {zestawienie}")

    os.makedirs(out, exist_ok=True)

    wiersze = wczytaj_zestawienie(zestawienie, arkusz, wt_domyslne=wt)
    if not wiersze:
        raise ValueError("Zestawienie nie zawiera danych.")
    if wt and not any(w["wt"] for w in wiersze):
        pass  # żaden wiersz nie miał WT - użyto wartości domyślnej (ręcznie wpisany numer WT)
    braki_wt = [w["plik"] for w in wiersze if not w["wt"]]
    if braki_wt:
        log(f"Uwaga: brak numeru WT dla {len(braki_wt)} pozycji (np. {braki_wt[:3]}) - "
            f"podaj numer warunków (--wt) lub uzupełnij kolumnę „wt” w zestawieniu.")

    # Przygotowanie modułu obliczeń (opcjonalnie)
    wb_obl = None
    wzorce = None
    if obliczenia:
        if not os.path.isfile(obliczenia):
            raise FileNotFoundError(f"Nie znaleziono pliku obliczeń: {obliczenia}")
        import openpyxl as _opx
        try:
            from . import obliczenia2word as o2w
        except ImportError:
            import obliczenia2word as o2w
        wb_obl = _opx.load_workbook(obliczenia, data_only=True)
        wzorce = o2w.WzorceWierszy()
        log(f"Dołączam obliczenia z: {os.path.basename(obliczenia)}")

    log(f"Znaleziono {len(wiersze)} pozycji w zestawieniu.")

    utworzone = []
    for dane in wiersze:
        doc = docx.Document(szablon)
        info = wypelnij_dokument(doc, dane)

        nazwa = dane["plik"]
        if not nazwa.lower().endswith(".docx"):
            nazwa += ".docx"
        baza = nazwa[:-5]  # bez .docx

        # dołączenie tabeli obliczeń, jeśli jest odpowiedni arkusz
        obl_info = ""
        if wb_obl is not None:
            try:
                from . import obliczenia2word as o2w
            except ImportError:
                import obliczenia2word as o2w
            arkusz_obl = _dopasuj_arkusz_obliczen(wb_obl, baza, dane.get("trafo", ""))
            if arkusz_obl is not None:
                n = o2w.wstaw_tabele_obliczen(doc, wb_obl[arkusz_obl], wzorce)
                obl_info = f"  + obliczenia (arkusz '{arkusz_obl}', {n} wierszy)"
            else:
                obl_info = "  (brak arkusza obliczeń)"

        sciezka = os.path.join(out, nazwa)
        doc.save(sciezka)
        utworzone.append(nazwa)
        log(f"  [OK] {nazwa:14s} miejscowość={dane['miejscowosc']:12s} "
            f"trafo={dane['trafo']:9s} WT={dane['wt']}{obl_info}")

    log("Gotowe.")
    return utworzone


def _dopasuj_arkusz_obliczen(wb, baza, trafo):
    """
    Dopasowuje arkusz obliczeń do projektu. Próbuje po:
      - dokładnej nazwie = numer pliku (np. '112'),
      - numerze trafo bez prefiksu '05-' (np. '0112' lub '112').
    """
    nazwy = set(wb.sheetnames)
    if baza in nazwy:
        return baza
    # z numeru trafo np. '05-0112' -> '112', '0112'
    kand = []
    if trafo:
        ogon = trafo.split("-")[-1].strip()
        kand.append(ogon)                 # '0112'
        kand.append(ogon.lstrip("0"))     # '112'
    kand.append(baza.lstrip("0"))
    for k in kand:
        if k in nazwy:
            return k
    return None


# ---------------------------------------------------------------------------
# Main (CLI)
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Generator opisów technicznych .docx na podstawie szablonu i zestawienia."
    )
    ap.add_argument("--szablon", default="szablon.docx", help="Plik szablonu .docx")
    ap.add_argument("--zestawienie", default="zestawienie domtel.xlsx",
                    help="Plik zestawienia .xlsx")
    ap.add_argument("--arkusz", default="Arkusz1", help="Nazwa arkusza z danymi")
    ap.add_argument("--obliczenia", default=None,
                    help="(opcjonalnie) plik .xlsx z obliczeniami nośności słupów")
    ap.add_argument("--wt", default="",
                    help="numer warunków technicznych (WT) wstawiany, gdy zestawienie nie ma kolumny „wt” "
                         "(np. zestawienie z Orientacji); jeden wspólny numer dla całości")
    ap.add_argument("--out", default=None,
                    help="Katalog wyjściowy (domyślnie folder szablonu opisu)")
    args = ap.parse_args()

    try:
        _wymagaj_bibliotek()
        # domyślnie zapisuj opisy w folderze szablonu
        out = args.out or os.path.dirname(os.path.abspath(args.szablon))
        generuj(args.szablon, args.zestawienie, out=out,
                arkusz=args.arkusz, obliczenia=args.obliczenia, wt=args.wt)
    except Exception as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
