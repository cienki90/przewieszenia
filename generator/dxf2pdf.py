"""DXF -> PDF bez CAD-a: każdy arkusz (layout papieru, w kolejności zakładek) = jedna strona PDF.

Wierne odtworzenie programu DXF2PDF.exe (odczytanego z jego kodu Pythona 3.12) jako modułu
generatora - np. osobny PDF dla każdej stacji z „Rysunków stałych”:
  * warstwy niedrukowalne i Defpoints są pomijane - jak przy wydruku z CAD-a; rzutnie leżące na
    takich warstwach są najpierw przenoszone na warstwę „0” (inaczej zniknęłaby ich zawartość);
    zmiana tylko w pamięci, plik DXF nie jest zapisywany,
  * obraz podkładu (IMAGEDEF) szukany obok pliku DXF albo folder wyżej,
  * obrazy w PDF zmniejszane do DPI_PODKLADU i zapisywane jako JPG (maska przycięcia bez zmian),
  * współrzędne wektorów skracane do MIEJSCA_PO_PRZECINKU (strumienie z tekstem bez zmian),
  * w odróżnieniu od oryginału rzutnie są przygotowywane do rysowania (_napraw_rzutnie) - w
    rysunkach stałych oryginał dawał puste rzutnie (sama ramka i tabelka, bez mapy i zasięgu).

Wymaga bibliotek ezdxf i pymupdf.
"""
from __future__ import annotations

import os
import pathlib
import re

DPI_PODKLADU = 200          # rozdzielczość obrazów (podkładu) w PDF
JAKOSC_JPG = 75             # jakość kompresji JPG obrazów
MIEJSCA_PO_PRZECINKU = 2    # dokładność współrzędnych wektorów w treści stron
_LICZBA = re.compile(rb"(?<![\w/.])-?\d*\.\d+")
_TEKST = re.compile(rb"\bBT\b")


def _biblioteki():
    try:
        import ezdxf  # noqa: F401
        import pymupdf
        from ezdxf.addons.drawing import pymupdf as _backend  # noqa: F401
    except ImportError as ex:
        raise ImportError("Tworzenie PDF wymaga bibliotek ezdxf i pymupdf "
                          "(pip install ezdxf pymupdf).") from ex
    return pymupdf


def pomin_niedrukowalne(doc) -> list:
    """Ukrywa warstwy z wyłączonym drukowaniem (oraz Defpoints) - tak jak CAD przy wydruku.

    Rzutnie leżące na takich warstwach przenosimy na „0”, żeby nie zniknęła ich zawartość.
    Zmiana dotyczy tylko pamięci, plik DXF nie jest zapisywany. Zwraca nazwy ukrytych warstw."""
    niedrukowalne = {w.dxf.name.lower() for w in doc.layers
                     if w.dxf.get("plot", 1) == 0 or w.dxf.name.lower() == "defpoints"}
    for arkusz in doc.layouts:
        if arkusz.name == "Model":
            continue
        for vp in arkusz.query("VIEWPORT"):
            if vp.dxf.layer.lower() in niedrukowalne:
                vp.dxf.layer = "0"
                vp.dxf.color = 0                    # znacznik: ramki nie drukujemy
    for w in doc.layers:
        if w.dxf.name.lower() in niedrukowalne:
            w.off()
    _ramki_rzutni(doc)
    return sorted(niedrukowalne)


def _ramki_rzutni(doc) -> int:
    """Ramki rzutni - CAD drukuje obrys rzutni leżącej na drukowalnej warstwie, ezdxf go nie rysuje.
    Dodaje prostokąt (w pamięci) na warstwie rzutni; pomija arkusz papieru (status 1 / id 1),
    rzutnie z obrysem z innego obiektu i rzutnie przeniesione z warstw niedrukowalnych."""
    n = 0
    for arkusz in doc.layouts:
        if arkusz.name == "Model":
            continue
        for vp in list(arkusz.query("VIEWPORT")):
            if vp.dxf.get("id", 0) == 1 or vp.dxf.get("color", 256) == 0:
                continue
            if vp.dxf.get("clipping_boundary_handle", "0") not in ("0", "", None):
                continue
            w, h = vp.dxf.width / 2, vp.dxf.height / 2
            if w <= 0 or h <= 0:
                continue
            x, y = vp.dxf.center.x, vp.dxf.center.y
            arkusz.add_lwpolyline([(x - w, y - h), (x + w, y - h), (x + w, y + h), (x - w, y + h)], close=True,
                                  dxfattribs={"layer": vp.dxf.layer})
            n += 1
    return n


def _stany_warstw_odnosnikow(doc) -> int:
    """Po wczytaniu odnośnika jego warstwy nazywają się „<odnośnik>$0$<warstwa>” i mają ustawienia
    z pliku odnośnika; w rysunku głównym ustawienia tych warstw (wyłączona, zamrożona, bez
    wydruku, kolor) zapisane są pod „<odnośnik>|<warstwa>” - przenosimy je na nowe warstwy."""
    stany = {w.dxf.name.lower(): w for w in doc.layers if "|" in w.dxf.name}
    n = 0
    for w in doc.layers:
        nazwa = w.dxf.name
        if "$0$" not in nazwa:
            continue
        odn, _, war = nazwa.partition("$0$")
        wzor = stany.get(f"{odn}|{war}".lower())
        if wzor is None:
            continue
        w.dxf.plot = wzor.dxf.get("plot", 1)
        w.dxf.flags = wzor.dxf.get("flags", 0)
        w.dxf.color = wzor.dxf.get("color", 7)
        n += 1
    return n


def _usun_odnosniki_niedrukowalne(doc) -> int:
    """Wstawienia odnośników zewnętrznych (XREF) leżące na warstwach niedrukowalnych - usuwane
    (w pamięci) przed wczytaniem odnośników, żeby nie trafiły na wydruk."""
    niedrukowalne = {w.dxf.name.lower() for w in doc.layers
                     if w.dxf.get("plot", 1) == 0 or w.dxf.name.lower() == "defpoints"}
    odn = {b.name.lower() for b in doc.blocks if b.block_record.is_xref}
    if not niedrukowalne or not odn:
        return 0
    n = 0
    for blok in list(doc.blocks):
        for e in list(blok.query("INSERT")):
            if e.dxf.name.lower() in odn and e.dxf.layer.lower() in niedrukowalne:
                blok.delete_entity(e)
                n += 1
    return n


def _napraw_rzutnie(doc) -> int:
    """Przygotowuje rzutnie do rysowania przez ezdxf (zmiana tylko w pamięci, ten sam widok co w CAD).

    Dwie rzeczy, przez które rzutnia mapy wychodziła PUSTA (także w oryginalnym DXF2PDF):
      * status: ezdxf traktuje rzutnię ze statusem 1 jako sam arkusz papieru i jej nie rysuje;
        w szablonach rysunków stałych status 1 ma rzutnia MAPY (id 2), a arkusz (id 1) - status 2.
        Arkusz dostaje status 1, pozostałe rzutnie - kolejne numery;
      * punkt celu widoku: środek widoku zapisany jest WZGLĘDEM punktu celu, a ezdxf punkt celu
        pomija. Dla widoku z góry: środek += cel, cel = 0.
    Zwraca liczbę poprawionych rzutni."""
    ile = 0
    for arkusz in doc.layouts:
        if arkusz.name == "Model":
            continue
        rzutnie = list(arkusz.query("VIEWPORT"))
        papier = [vp for vp in rzutnie if vp.dxf.get("id", 0) == 1]
        if papier and papier[0].dxf.get("status", 1) != 1:
            papier[0].dxf.status = 1
            nr = 2
            for vp in sorted((v for v in rzutnie if v is not papier[0] and v.dxf.get("status", 1) > 0),
                             key=lambda v: v.dxf.get("status", 1)):
                vp.dxf.status = nr
                nr += 1
            ile += 1
        for vp in rzutnie:
            cel = vp.dxf.get("view_target_point", (0, 0, 0))
            kier = vp.dxf.get("view_direction_vector", (0, 0, 1))
            if (abs(cel[0]) > 1e-6 or abs(cel[1]) > 1e-6) and abs(kier[0]) < 1e-9 and abs(kier[1]) < 1e-9:
                sr = vp.dxf.view_center_point
                vp.dxf.view_center_point = (sr[0] + cel[0], sr[1] + cel[1])
                vp.dxf.view_target_point = (0, 0, cel[2] if len(cel) > 2 else 0)
                ile += 1
    return ile


def _napraw_obrazy(doc, dxf: str, folder_obrazow: str | None = None) -> None:
    """Obraz podkładu szukany obok pliku DXF albo folder wyżej (ścieżka w rysunku bywa nieaktualna);
    `folder_obrazow` - dodatkowo folder oryginału (DXF tymczasowy zrobiony z DWG leży gdzie indziej)."""
    dxf = pathlib.Path(dxf)
    foldery = ([pathlib.Path(folder_obrazow)] if folder_obrazow else []) + [dxf.parent, dxf.parent.parent]
    for idef in doc.objects.query("IMAGEDEF"):
        nazwa = pathlib.PureWindowsPath(idef.dxf.filename).name
        for kandydat in (f / nazwa for f in foldery):
            if kandydat.exists():
                idef.dxf.filename = str(kandydat)
                break


def obrazy_do_jpg(pdf) -> None:
    """Zapisuje obrazy jako JPG i zmniejsza je do DPI_PODKLADU.

    Maska przycięcia obrazu (SMask) zostaje bez zmian. Obrazy już skompresowane (JPEG/JPEG2000)
    i jednobitowe (maski) są pomijane; zmniejszamy tylko, gdy obraz byłby < 90% oryginału."""
    pymupdf = _biblioteki()
    gotowe = set()
    for strona in pdf:
        for img in strona.get_images(full=True):
            xref, bpc, filtr = img[0], img[4], img[8]
            if xref in gotowe or bpc == 1 or filtr in ("DCTDecode", "JPXDecode"):
                continue
            gotowe.add(xref)
            pix = pymupdf.Pixmap(pdf, xref)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)                  # bez kanału alfa (maska zostaje osobno)
            if pix.n not in (1, 3):
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            ramki = strona.get_image_rects(xref)
            if ramki:
                szer_pt = max(r.width for r in ramki)
                wys_pt = max(r.height for r in ramki)
                skala = max(szer_pt * DPI_PODKLADU / 72 / pix.width, wys_pt * DPI_PODKLADU / 72 / pix.height)
                if skala < 0.9:
                    pix = pymupdf.Pixmap(pix, round(pix.width * skala), round(pix.height * skala), None)
            try:
                jpg = pix.tobytes("jpg", jpg_quality=JAKOSC_JPG)
            except TypeError:                                  # starsze pymupdf
                jpg = pix.pil_tobytes("JPEG", quality=JAKOSC_JPG)
            pdf.update_stream(xref, jpg, compress=False)
            pdf.xref_set_key(xref, "Filter", "/DCTDecode")
            pdf.xref_set_key(xref, "DecodeParms", "null")
            pdf.xref_set_key(xref, "Width", str(pix.width))
            pdf.xref_set_key(xref, "Height", str(pix.height))
            pdf.xref_set_key(xref, "BitsPerComponent", "8")
            pdf.xref_set_key(xref, "ColorSpace", "/DeviceGray" if pix.n == 1 else "/DeviceRGB")


def zaokraglij_wektory(pdf) -> None:
    """Skraca współrzędne w treści stron (ezdxf pisze 5 miejsc po przecinku).
    Strumienie z tekstem (operator BT) zostają bez zmian."""
    def krotsza(m: re.Match) -> bytes:
        s = f"{float(m.group(0)):.{MIEJSCA_PO_PRZECINKU}f}".rstrip("0").rstrip(".")
        return s.encode() if s not in ("", "-", "-0") else b"0"

    gotowe = set()
    for strona in pdf:
        for xref in strona.get_contents():
            if xref in gotowe:
                continue
            gotowe.add(xref)
            tresc = pdf.xref_stream(xref)
            if not tresc or _TEKST.search(tresc):
                continue
            pdf.update_stream(xref, _LICZBA.sub(krotsza, tresc))


def arkusze_do_pdf(dxf: str, folder_obrazow: str | None = None, wybierz=None):
    """Rysuje arkusze (layouty papieru) rysunku do dokumentu PDF w pamięci.
    `wybierz(nazwa) -> bool` - które arkusze (None = wszystkie). Zwraca (dokument pymupdf, [nazwy stron])."""
    pymupdf = _biblioteki()
    from ezdxf import recover
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
    from ezdxf.addons.drawing import pymupdf as backend_pdf

    doc, _audyt = recover.readfile(dxf)
    _wczytaj_odnosniki(doc, dxf, folder_obrazow)
    _napraw_obrazy(doc, dxf, folder_obrazow)
    pomin_niedrukowalne(doc)
    _napraw_rzutnie(doc)
    konf = config.Configuration(image_policy=config.ImagePolicy.DISPLAY)
    # wierzch: białe „tło ekranu” (teksty z tłem w kolorze ekranu są białe, nie czarne); prostokąt tła
    # strony jest potem usuwany, żeby warstwa była przezroczysta
    konf_wierzch = config.Configuration(image_policy=config.ImagePolicy.DISPLAY,
                                        background_policy=config.BackgroundPolicy.WHITE)
    wynik, nazwy = pymupdf.open(), []
    for nazwa in doc.layout_names_in_taborder():
        if nazwa == "Model" or (wybierz is not None and not wybierz(nazwa)):
            continue
        arkusz = doc.paperspace(nazwa)
        strona = layout.Page.from_dxf_layout(arkusz)
        # papier 1:1 (bez dopasowania do strony) - obie warstwy muszą leżeć dokładnie na sobie
        ustaw = layout.Settings(fit_page=False, scale=arkusz.get_plot_unit_scale_factor())
        backend = backend_pdf.PyMuPdfBackend()
        Frontend(RenderContext(doc), backend, config=konf).draw_layout(arkusz)
        obrys = backend.player().bbox()                # obszar całego arkusza - wspólny dla obu warstw
        jedna = pymupdf.open("pdf", backend.get_pdf_bytes(strona, settings=ustaw, render_box=obrys))
        # elementy arkusza (ramka, tabelka i legenda z białym tłem) jeszcze raz NAD zawartością rzutni - jak
        # w CAD-zie, gdzie tabelka zasłania rysunek; rysowanie ezdxf kładzie rzutnię na wierzchu
        papier = [e for e in arkusz if e.dxftype() != "VIEWPORT"]
        if papier and any(e.dxftype() == "VIEWPORT" for e in arkusz):
            be = backend_pdf.PyMuPdfBackend()
            ctx = RenderContext(doc)
            ctx.set_current_layout(arkusz)            # biały papier: kolor 7 = czarny, jak przy całym arkuszu
            front = Frontend(ctx, be, config=konf_wierzch)
            front.draw_entities(papier)
            with pymupdf.open("pdf", be.get_pdf_bytes(strona, settings=ustaw, render_box=obrys)) as wierzch:
                _usun_tlo_strony(wierzch)
                jedna[0].show_pdf_page(jedna[0].rect, wierzch, 0)
        wynik.insert_pdf(jedna)
        jedna.close()
        nazwy.append(nazwa)
    return wynik, nazwy


# czarny/biały prostokąt tła strony, który backend PyMuPDF kładzie na początku strumienia
_TLO_STRONY = re.compile(rb"q\s+0 0 [\d.]+ [\d.]+ re\s+h\s+[\d.]+ [\d.]+ [\d.]+ rg f\s+Q")


def _usun_tlo_strony(pdf) -> None:
    """Warstwa wierzchnia ma być przezroczysta - bez prostokąta tła strony."""
    strona = pdf[0]
    for xref in strona.get_contents():
        raw = pdf.xref_stream(xref)
        nowy = _TLO_STRONY.sub(b"", raw, count=1)
        if nowy != raw:
            pdf.update_stream(xref, nowy)
            return


def _wczytaj_odnosniki(doc, dxf: str, folder: str | None = None, log=None) -> list:
    """Wczytuje do rysunku odnośniki zewnętrzne (XREF) - np. podkład mapowy dołączony jako osobny DWG.
    Ścieżki względne szukane w folderze oryginału (folder) i rysunku; DWG zamieniane na DXF (ODA).
    Zwraca listę nazw odnośników, których nie udało się wczytać (rysunek bez nich, jak dotąd)."""
    import tempfile

    import ezdxf
    from ezdxf import xref as ezxref
    from . import dwg as mod_dwg

    bledy = []
    _usun_odnosniki_niedrukowalne(doc)
    tmp = tempfile.mkdtemp(prefix="xref_")

    def wczytaj(sciezka):
        sciezka = str(sciezka)
        if sciezka.lower().endswith(".dwg"):
            sciezka = mod_dwg.dwg_na_dxf(sciezka, os.path.join(tmp, f"x{len(os.listdir(tmp))}.dxf"))
        from ezdxf import recover
        d, _ = recover.readfile(sciezka)
        return d

    foldery = [f for f in (folder, os.path.dirname(os.path.abspath(dxf))) if f]
    try:
        for _proba in range(3):                       # odnośniki zagnieżdżone - kilka przebiegów
            odn = [b for b in doc.blocks if b.block_record.is_xref]
            if not odn:
                break
            for blok in odn:
                sciezka = (blok.block.dxf.get("xref_path", "") or "").strip()
                nazwa_pliku = os.path.basename(sciezka.replace("\\", "/"))
                kand = [sciezka] if os.path.isabs(sciezka) else []
                kand += [os.path.normpath(os.path.join(f, sciezka)) for f in foldery]
                kand += [os.path.join(f, nazwa_pliku) for f in foldery]
                plik = next((k for k in kand if k and os.path.isfile(k)), None)
                try:
                    if plik is None:
                        raise FileNotFoundError(sciezka)
                    ezxref.embed(blok, load_fn=lambda _p, plik=plik: wczytaj(plik),
                                 search_paths=[os.path.dirname(plik)])
                except Exception as ex:  # noqa: BLE001 - brak odnośnika nie zatrzymuje PDF-u
                    bledy.append(f"{blok.name} ({ex})")
                    blok.block.dxf.flags &= ~0x0C          # dalej zwykły (pusty) blok, nie odnośnik
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    _stany_warstw_odnosnikow(doc)
    if bledy and log:
        log("Nie wczytano odnośników zewnętrznych: " + "; ".join(bledy))
    return bledy


def dxf_do_pdf(dxf: str, pdf_wyj: str | None = None, folder_obrazow: str | None = None) -> tuple[str, int]:
    """Jeden plik DXF -> PDF (strona na każdy arkusz). Zwraca (ścieżka PDF, liczba stron).
    `folder_obrazow` - gdzie jeszcze szukać obrazu podkładu (np. folder oryginalnego DWG)."""
    pdf_wyj = pdf_wyj or os.path.splitext(dxf)[0] + ".pdf"
    wynik, _nazwy = arkusze_do_pdf(dxf, folder_obrazow)
    if wynik.page_count == 0:
        raise ValueError("rysunek nie ma arkuszy (layoutów papieru)")
    obrazy_do_jpg(wynik)
    zaokraglij_wektory(wynik)
    stron = wynik.page_count
    wynik.save(pdf_wyj, garbage=3, deflate=True, deflate_images=True, deflate_fonts=True)
    wynik.close()
    return pdf_wyj, stron


def konwertuj_pliki(pliki, folder_wyj: str | None = None, log=print) -> tuple[list, list]:
    """Lista plików DXF -> PDF (w `folder_wyj` albo obok DXF). Zwraca (udane PDF, błędy)."""
    udane, bledy = [], []
    pliki = list(pliki)
    for n, dxf in enumerate(pliki, 1):
        nazwa = os.path.splitext(os.path.basename(dxf))[0] + ".pdf"
        pdf = os.path.join(folder_wyj or os.path.dirname(dxf), nazwa)
        try:
            _, stron = dxf_do_pdf(dxf, pdf)
            mb = os.path.getsize(pdf) / 1024 / 1024
            log(f"  [{n}/{len(pliki)}] OK   {nazwa}  ({stron} ark., {mb:.1f} MB)")
            udane.append(pdf)
        except Exception as ex:  # noqa: BLE001 - jeden zły plik nie przerywa reszty
            log(f"  [{n}/{len(pliki)}] BŁĄD {os.path.basename(dxf)}: {ex}")
            bledy.append((dxf, str(ex)))
    return udane, bledy
