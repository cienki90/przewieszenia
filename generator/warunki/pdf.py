"""Eksport rysunków DXF do PDF (wektorowo), przez dodatek rysujący ezdxf + PyMuPDF.

Każdy układ papieru DXF (A3) staje się osobną stroną wielostronicowego PDF-u,
odwzorowaną 1:1 (bez skalowania do strony).

Trzy sprawy wymagają osobnego potraktowania, bo inaczej PDF różni się od wydruku z CAD-a:

1. Kolejność rysowania (białe tło tabelki). Dodatek rysujący rysuje zawartość rzutni
   (model: trasa, strefy trafo) PO encjach przestrzeni papieru, więc rysunek z modelu
   przebijałby przez tabelkę i legendę. Rysujemy więc stronę w dwóch warstwach: model
   na spodzie, a encje przestrzeni papieru (ramka, tabelka z białym tłem, legenda)
   nakładamy na wierzchu - jak w CAD-zie, gdzie tabelka przykrywa okno rzutni.
   Warstwa wierzchnia ma usunięte czarne tło strony, żeby była przezroczysta.

2. Grubość numeracji. Numery słupów są pisane czcionką kreskową SHX (romans.shx),
   którą dodatek rysujący renderuje cienko i nieczytelnie. Na czas eksportu PDF
   przestawiamy styl tekstu numeracji na pogrubioną czcionkę TrueType (bez zmiany
   zapisanego pliku DXF).

3. Podkład rastrowy planu orientacyjnego. Dodatek rysujący osadza obraz
   nieskompresowany (plik PDF rośnie do kilkudziesięciu MB). Dlatego obrazy IMAGE
   są pomijane w renderze, a pliki JPG podkładu wklejamy wprost na strony pod rysunek
   wektorowy; pozycja wynika z ustawień rzutni i georeferencji obrazu.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing import pymupdf as ezpdf
from ezdxf.addons.drawing.config import (BackgroundPolicy, Configuration, ImagePolicy,
                                         LineweightPolicy)
from ezdxf.document import Drawing

# Styl tekstu i czcionka numeracji na potrzeby PDF (pogrubiona, czytelna).
# Arial Bold jest w każdym Windowsie; gdy go brak, ezdxf użyje czcionki zastępczej.
STYL_NUMEROW_PDF = "WT_PDF_NUMERY"
CZCIONKA_NUMEROW_PDF = "arialbd.ttf"

# Pogrubienie linii modelu na wydruku (numeracja i trasa mają w DXF jawny
# lineweight, więc grubieją; opisy słupów mają domyślny, więc nie). W 1/100 mm skalowane.
SKALA_GRUBOSCI = 1.6
# Grubość linii ramki, tabelki i legendy na wydruku [1/100 mm] = 0,25 mm.
GRUBOSC_RAMKI = 25

# Wzorzec bloku białego/czarnego tła strony na początku strumienia PDF warstwy papieru.
_TLO_STRONY = re.compile(rb"q\s+0 0 [\d.]+ [\d.]+ re\s+h\s+0 0 0 rg f\s+Q")


def _nazwy_ukladow(doc: Drawing, nazwy=None) -> list[str]:
    if nazwy is not None:
        return [n for n in nazwy if n in doc.layouts.names()]
    return [n for n in doc.layouts.names() if n != "Model"]


def _strona_ukladu(psp):
    """Strona PDF i ustawienia wiernego odwzorowania papieru układu (bez skalowania)."""
    page = layout.Page.from_dxf_layout(psp)
    ustaw = layout.Settings(fit_page=False, scale=psp.get_plot_unit_scale_factor())
    return page, ustaw


def _konfig(tlo: BackgroundPolicy, skala: float = SKALA_GRUBOSCI) -> Configuration:
    return Configuration(
        background_policy=tlo,
        image_policy=ImagePolicy.IGNORE,          # obrazy wklejamy ręcznie (patrz niżej)
        lineweight_policy=LineweightPolicy.ABSOLUTE,
        lineweight_scaling=skala,
    )


class _StaleGruboscLinii:
    """Na czas renderu warstwy papieru ustawia liniom i poliliniom stałą grubość
    (ramka, tabelka, legenda = 0,25 mm) i przywraca stan po zakończeniu."""

    def __init__(self, encje, grubosc: int = GRUBOSC_RAMKI):
        self.encje = encje
        self.grubosc = grubosc
        self.pierwotne: list = []

    def __enter__(self):
        for e in self.encje:
            if e.dxftype() in ("LINE", "LWPOLYLINE", "POLYLINE"):
                self.pierwotne.append((e, e.dxf.get("lineweight", None)))
                e.dxf.lineweight = self.grubosc
        return self

    def __exit__(self, *a):
        for e, lw in self.pierwotne:
            if lw is None:
                e.dxf.discard("lineweight")
            else:
                e.dxf.lineweight = lw


class _PogrubioneNumery:
    """Na czas eksportu PDF przestawia styl tekstu numeracji na pogrubioną czcionkę
    TrueType i przywraca stan po zakończeniu (nie zmienia zapisanego pliku DXF)."""

    def __init__(self, doc: Drawing, warstwa_numeracji: str):
        self.doc = doc
        self.warstwa = warstwa_numeracji
        self.pierwotne: list = []

    def __enter__(self):
        if STYL_NUMEROW_PDF not in self.doc.styles:
            self.doc.styles.add(STYL_NUMEROW_PDF, font=CZCIONKA_NUMEROW_PDF)
        for e in self.doc.modelspace().query(f'MTEXT TEXT[layer=="{self.warstwa}"]i'):
            self.pierwotne.append((e, e.dxf.style))
            e.dxf.style = STYL_NUMEROW_PDF
        return self

    def __exit__(self, *a):
        for e, styl in self.pierwotne:
            e.dxf.style = styl


def _rysuj_strone(doc: Drawing, psp, ctx, obrazy_tla, pymupdf):
    """Buduje jedną stronę PDF danego układu papieru.

    Warstwy od spodu: (1) podkład rastrowy (JPG, tylko orientacja), (2) zawartość
    rzutni (model: trasa, obrysy arkuszy, numeracja), (3) encje przestrzeni papieru
    (ramka, tabelka z białym tłem, legenda). Warstwy 2 i 3 mają przezroczyste tło,
    żeby podkład był widoczny, a tabelka zasłaniała rysunek z modelu."""
    page, ustaw = _strona_ukladu(psp)
    na_pt = 72.0 / 25.4

    if obrazy_tla:
        # pusta biała strona, na niej podkład (spód), potem model i papier.
        # podkład przycinamy do prostokąta rzutni, żeby nie wychodził poza ramkę.
        strona = pymupdf.open()
        strona.new_page(width=page.width * na_pt, height=page.height * na_pt)
        clip = _prostokat_rzutni_pt(psp, page, na_pt, pymupdf)
        for t in obrazy_tla:
            if t.plik.exists():
                _wklej_podklad(strona[0], t, clip, na_pt, pymupdf)
        be_model = ezpdf.PyMuPdfBackend()
        Frontend(ctx, be_model, config=_konfig(BackgroundPolicy.OFF)).draw_layout(psp)
        model = pymupdf.open("pdf", be_model.get_pdf_bytes(page, settings=ustaw))
        _usun_tlo_strony(model)
        strona[0].show_pdf_page(strona[0].rect, model, 0)
        model.close()
    else:
        # bez podkładu: model od razu jako strona (białe tło)
        be_model = ezpdf.PyMuPdfBackend()
        Frontend(ctx, be_model, config=_konfig(BackgroundPolicy.WHITE)).draw_layout(psp)
        strona = pymupdf.open("pdf", be_model.get_pdf_bytes(page, settings=ustaw))

    # --- warstwa przestrzeni papieru (bez rzutni) na wierzchu, przezroczyste tło;
    # linie ramki, tabelki i legendy renderowane w stałej grubości 0,25 mm
    pap = [e for e in psp if e.dxftype() != "VIEWPORT"]
    if pap:
        be_pap = ezpdf.PyMuPdfBackend()
        with _StaleGruboscLinii(pap):
            Frontend(ctx, be_pap, config=_konfig(BackgroundPolicy.OFF, skala=1.0)
                     ).draw_entities(pap)
        wierzch = pymupdf.open("pdf", be_pap.get_pdf_bytes(page, settings=ustaw))
        _usun_tlo_strony(wierzch)
        strona[0].show_pdf_page(strona[0].rect, wierzch, 0)
        wierzch.close()
    return strona


def _prostokat_rzutni_pt(psp, page, na_pt, pymupdf):
    """Prostokąt rzutni na stronie PDF [pt, od lewego górnego rogu] - do przycięcia podkładu."""
    vp = _rzutnia(psp)
    if vp is None:
        return None
    w, h = vp.dxf.width, vp.dxf.height
    x0 = vp.dxf.center.x - w / 2
    y0 = vp.dxf.center.y - h / 2  # od lewego dolnego rogu arkusza
    gora = page.height - (y0 + h)  # oś Y: DXF w górę, PDF w dół
    return pymupdf.Rect(x0 * na_pt, gora * na_pt, (x0 + w) * na_pt, (gora + h) * na_pt)


def _wklej_podklad(strona, t, clip, na_pt, pymupdf) -> None:
    """Wkleja podkład 't' na stronę, przycięty do prostokąta rzutni 'clip'.

    insert_image nie przycina obrazu, więc fragment poza rzutnią wycinamy z pliku
    (Pillow) i wstawiamy tylko część widoczną."""
    prost = pymupdf.Rect(t.x * na_pt, t.y * na_pt,
                         (t.x + t.szer) * na_pt, (t.y + t.wys) * na_pt)
    widoczny = (prost & clip) if clip else prost
    if widoczny.is_empty:
        return
    if clip is None or widoczny.contains(prost):
        strona.insert_image(prost, filename=str(t.plik), keep_proportion=False)
        return
    from PIL import Image
    with Image.open(t.plik) as img:
        W, H = img.size
        fx0 = (widoczny.x0 - prost.x0) / prost.width
        fy0 = (widoczny.y0 - prost.y0) / prost.height
        fx1 = (widoczny.x1 - prost.x0) / prost.width
        fy1 = (widoczny.y1 - prost.y0) / prost.height
        wyciety = img.crop((int(fx0 * W), int(fy0 * H),
                            max(int(fx0 * W) + 1, int(fx1 * W)),
                            max(int(fy0 * H) + 1, int(fy1 * H))))
        import io
        buf = io.BytesIO()
        wyciety.convert("RGB").save(buf, "JPEG", quality=88)
    strona.insert_image(widoczny, stream=buf.getvalue(), keep_proportion=False)


def _usun_tlo_strony(pdf) -> None:
    """Usuwa z warstwy wierzchniej czarny prostokąt tła strony, żeby była przezroczysta."""
    strona = pdf[0]
    xref = strona.get_contents()[0]
    raw = pdf.xref_stream(xref)
    nowy = _TLO_STRONY.sub(b"", raw, count=1)
    if nowy != raw:
        pdf.update_stream(xref, nowy)


# Rysowanie stron w kilku procesach: strona to ~1 s czystego Pythona na jednym rdzeniu, a strony są
# od siebie niezależne. Od tylu stron się to opłaca (start procesu i wczytanie rysunku ~2-3 s):
MIN_STRON_ROWNOLEGLE = 4
MAKS_PROCESOW = 6
CZAS_PROCESU_S = 900


def liczba_procesow(stron: int, procesy: int | None = None) -> int:
    """Ile procesów pomocniczych użyć do narysowania 'stron' (1 = rysuj po kolei w tym procesie).
    W programie spakowanym do .exe zawsze 1 - nie ma tam interpretera do uruchomienia pomocników."""
    if procesy is not None:
        return max(1, min(int(procesy), stron))
    if getattr(sys, "frozen", False) or stron < MIN_STRON_ROWNOLEGLE:
        return 1
    return max(1, min((os.cpu_count() or 1) - 1, MAKS_PROCESOW, (stron + 1) // 2))


def _strony_w_procesach(doc: Drawing, nazwy, obrazy_tla, warstwa_numeracji, procesy: int, log) -> list[bytes]:
    """Rysuje strony w 'procesy' procesach pomocniczych; zwraca strony PDF (bajty) w kolejności 'nazwy'.

    Pomocnik to osobno uruchomiony interpreter z modułem tego pliku (python -m …pdf zadanie.json),
    a nie multiprocessing - tamten wczytuje ponownie plik startowy programu, a uruchom.pyw otwiera
    okno przy samym wczytaniu. Każdy pomocnik dostaje kopię rysunku w pliku tymczasowym."""
    modul = __spec__.name if __spec__ else __name__
    korzen = Path(__file__).resolve().parents[len(modul.split(".")) - 1]
    with tempfile.TemporaryDirectory(prefix="wt_pdf_") as tmp:
        tmp = Path(tmp)
        rysunek = tmp / "arkusze.dxf"
        stara_nazwa = doc.filename
        try:
            doc.saveas(rysunek)
        finally:
            doc.filename = stara_nazwa               # saveas przestawia nazwę dokumentu - przywróć
        # ezdxf przy zapisie dopisuje stylom wymiarowania wartości domyślne (np. dimlwd = -2), a wtedy
        # po wczytaniu odnośnik LEADER bierze grubość ze stylu zamiast własnej. Pomocnik dostaje listę
        # ustawień faktycznie obecnych w stylach i resztę usuwa - rysuje jak z dokumentu w pamięci.
        style_wym = {s.dxf.name: sorted(s.dxfattribs()) for s in doc.dimstyles}
        zadania = []
        for i in range(procesy):
            czesc = list(enumerate(nazwy))[i::procesy]
            if not czesc:
                continue
            plik = tmp / f"zadanie_{i}.json"
            plik.write_text(json.dumps({
                "dxf": str(rysunek), "katalog": str(tmp), "warstwa_numeracji": warstwa_numeracji,
                "style_wymiarowania": style_wym,
                "strony": [[nr, nazwa] for nr, nazwa in czesc],
                "tla": {nazwa: [[str(t.plik), t.x, t.y, t.szer, t.wys] for t in (obrazy_tla or {}).get(nazwa) or []]
                        for _nr, nazwa in czesc}}), encoding="utf-8")
            flagi = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            # komunikaty pomocnika do pliku (nie do potoku - pełny potok zatrzymałby proces)
            bledy_plik = tmp / f"bledy_{i}.txt"
            with open(bledy_plik, "wb") as f_err:
                proces = subprocess.Popen([sys.executable, "-m", modul, str(plik)], cwd=str(korzen),
                                          stdout=subprocess.DEVNULL, stderr=f_err, **flagi)
            zadania.append((czesc, proces, bledy_plik))
        bledy = []
        for czesc, proces, bledy_plik in zadania:
            try:
                proces.wait(timeout=CZAS_PROCESU_S)
            except subprocess.TimeoutExpired:
                proces.kill()
                proces.wait()
                bledy.append("przekroczony czas")
                continue
            if proces.returncode != 0:
                linie = bledy_plik.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                bledy.append(linie[-1] if linie else f"kod {proces.returncode}")
            elif log:
                for _nr, nazwa in czesc:
                    log(f"PDF: strona {nazwa}")
        if bledy:
            raise RuntimeError("proces pomocniczy: " + "; ".join(bledy))
        return [(tmp / f"strona_{nr}.pdf").read_bytes() for nr in range(len(nazwy))]


def _proces_pomocniczy(plik_zadania: str) -> int:
    """(python -m …pdf zadanie.json) Rysuje strony z zadania do plików strona_<nr>.pdf."""
    import ezdxf
    import pymupdf
    z = json.loads(Path(plik_zadania).read_text(encoding="utf-8"))
    doc = ezdxf.readfile(z["dxf"])
    for styl in doc.dimstyles:                       # stan stylów jak w dokumencie nadrzędnym
        obecne = z.get("style_wymiarowania", {}).get(styl.dxf.name)
        if obecne is not None:
            for atr in list(styl.dxfattribs()):
                if atr not in obecne:
                    styl.dxf.discard(atr)
    pogrub = _PogrubioneNumery(doc, z["warstwa_numeracji"]) if z.get("warstwa_numeracji") else _bez_zmian()
    with pogrub:
        ctx = RenderContext(doc)        # po dodaniu stylu numerów - inaczej kontekst go nie zna
        for nr, nazwa in z["strony"]:
            tla = [RysunekTla(*t) for t in z["tla"].get(nazwa) or []]
            strona = _rysuj_strone(doc, doc.paperspace(nazwa), ctx, tla, pymupdf)
            strona.save(str(Path(z["katalog"]) / f"strona_{nr}.pdf"))
            strona.close()
    return 0


def eksportuj_uklady(doc: Drawing, wyjscie: Path, nazwy=None, obrazy_tla=None,
                     warstwa_numeracji: str | None = None, log=None, procesy: int | None = None) -> int:
    """Zapisuje układy papieru 'doc' do jednego wielostronicowego PDF-u.

    nazwy             - lista nazw układów (kolejność stron); None = wszystkie poza 'Model'.
    obrazy_tla        - opcjonalny słownik {nazwa_układu: [RysunekTla, ...]} (podkład).
    warstwa_numeracji - gdy podana, numery na tej warstwie są pogrubiane w PDF.
    procesy           - liczba procesów rysujących strony; None = dobierz (patrz liczba_procesow),
                        1 = po kolei w tym procesie. Gdy pomocnik zawiedzie, strony rysowane są po kolei.
    Zwraca liczbę zapisanych stron.
    """
    import pymupdf

    nazwy = _nazwy_ukladow(doc, nazwy)
    if not nazwy:
        raise ValueError("Dokument nie ma układów papieru do zapisania w PDF.")
    pdf = pymupdf.open()
    try:
        gotowe = None
        ile = liczba_procesow(len(nazwy), procesy)
        if ile > 1:
            try:
                gotowe = _strony_w_procesach(doc, nazwy, obrazy_tla, warstwa_numeracji, ile, log)
            except Exception as ex:  # noqa: BLE001 - każdy kłopot z pomocnikami = rysuj po kolei
                if log:
                    log(f"PDF: rysowanie w {ile} procesach nie powiodło się ({ex}) - rysuję po kolei.")
        if gotowe is not None:
            for bajty in gotowe:
                strona = pymupdf.open("pdf", bajty)
                pdf.insert_pdf(strona)
                strona.close()
        else:
            pogrub = (_PogrubioneNumery(doc, warstwa_numeracji) if warstwa_numeracji
                      else _bez_zmian())
            with pogrub:
                # kontekst po dodaniu pogrubionego stylu numerów: utworzony wcześniej nie znał go
                # i przy pierwszym eksporcie część numerów rysowała się inną czcionką
                ctx = RenderContext(doc)
                for nazwa in nazwy:
                    psp = doc.paperspace(nazwa)
                    tla = (obrazy_tla or {}).get(nazwa) or []
                    strona = _rysuj_strone(doc, psp, ctx, tla, pymupdf)
                    pdf.insert_pdf(strona)
                    strona.close()
                    if log:
                        log(f"PDF: strona {nazwa}")
        Path(wyjscie).parent.mkdir(parents=True, exist_ok=True)
        # garbage+deflate+clean: usuwa duplikaty i kompresuje strumienie (mały plik)
        pdf.save(str(wyjscie), garbage=4, deflate=True, clean=True)
        return pdf.page_count
    finally:
        pdf.close()


class _bez_zmian:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class RysunekTla:
    """Obraz podkładu do wklejenia na stronę PDF, z pozycją w mm papieru.

    x, y - lewy górny róg obrazu [mm od lewego górnego rogu strony],
    szer, wys - rozmiar obrazu na papierze [mm].
    """

    __slots__ = ("plik", "x", "y", "szer", "wys")

    def __init__(self, plik: Path, x: float, y: float, szer: float, wys: float):
        self.plik = Path(plik)
        self.x, self.y, self.szer, self.wys = x, y, szer, wys


# --------------------------------------------------------- geometria rzutni orientacji

def tla_z_rzutni(psp, obrazy) -> list[RysunekTla]:
    """Dla układu orientacji: przelicza obrazy IMAGE (model) na pozycje w mm papieru.

    psp     - przestrzeń papieru układu (zawiera rzutnię z widokiem modelu),
    obrazy  - lista krotek (plik_jpg, x0_m, y0_m, szer_m, wys_m) = lewy dolny róg
              obrazu w terenie i jego rozmiar w metrach (z obiektu Podklad).
    Zwraca listę RysunekTla (mm papieru, od lewego górnego rogu strony).
    """
    vp = _rzutnia(psp)
    if vp is None:
        return []
    cx_mm, cy_mm = vp.dxf.center.x, vp.dxf.center.y  # środek rzutni na papierze [mm]
    w_mm, h_mm = vp.dxf.width, vp.dxf.height
    vcx, vcy = vp.dxf.view_center_point.x, vp.dxf.view_center_point.y  # środek widoku [m]
    view_h = vp.dxf.view_height
    view_w = view_h * (w_mm / h_mm) if h_mm else view_h
    if not view_w or not view_h:
        return []
    skala_x = w_mm / view_w   # mm papieru na metr terenu
    skala_y = h_mm / view_h
    strona_h_mm = _wysokosc_strony_mm(psp)

    def na_papier(mx, my):  # metr terenu -> mm od lewego dolnego rogu arkusza
        return cx_mm + (mx - vcx) * skala_x, cy_mm + (my - vcy) * skala_y

    wynik = []
    for plik, x0_m, y0_m, szer_m, wys_m in obrazy:
        lx_mm, gy_mm = na_papier(x0_m, y0_m + wys_m)  # lewy górny róg obrazu
        # oś Y: DXF rośnie w górę, PDF w dół -> licz od góry strony
        wynik.append(RysunekTla(plik, lx_mm, strona_h_mm - gy_mm,
                                szer_m * skala_x, wys_m * skala_y))
    return wynik


def _rzutnia(psp):
    vps = [e for e in psp if e.dxftype() == "VIEWPORT" and e.dxf.id != 1]
    return max(vps, key=lambda v: v.dxf.width * v.dxf.height) if vps else None


def _wysokosc_strony_mm(psp) -> float:
    h = psp.dxf_layout.dxfattribs().get("paper_height")
    return float(h) if h else layout.Page.from_dxf_layout(psp).height


if __name__ == "__main__":          # proces pomocniczy rysowania stron (patrz _strony_w_procesach)
    sys.exit(_proces_pomocniczy(sys.argv[1]))
