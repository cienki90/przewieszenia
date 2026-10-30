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

import re
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


def eksportuj_uklady(doc: Drawing, wyjscie: Path, nazwy=None, obrazy_tla=None,
                     warstwa_numeracji: str | None = None, log=None) -> int:
    """Zapisuje układy papieru 'doc' do jednego wielostronicowego PDF-u.

    nazwy             - lista nazw układów (kolejność stron); None = wszystkie poza 'Model'.
    obrazy_tla        - opcjonalny słownik {nazwa_układu: [RysunekTla, ...]} (podkład).
    warstwa_numeracji - gdy podana, numery na tej warstwie są pogrubiane w PDF.
    Zwraca liczbę zapisanych stron.
    """
    import pymupdf

    nazwy = _nazwy_ukladow(doc, nazwy)
    if not nazwy:
        raise ValueError("Dokument nie ma układów papieru do zapisania w PDF.")
    ctx = RenderContext(doc)
    pdf = pymupdf.open()
    pogrub = (_PogrubioneNumery(doc, warstwa_numeracji) if warstwa_numeracji
              else _bez_zmian())
    try:
        with pogrub:
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
