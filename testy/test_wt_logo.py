"""Logotypy w prawym górnym rogu arkuszy WT."""
import ezdxf

from generator.warunki import arkusze as ark
from generator.warunki.config import SZABLONY, logotypy


def test_logotypy_dostepne():
    assert {"KPO com4com", "KPO helpful"} <= set(logotypy())


def test_logo_w_prawym_gornym_rogu_ramki():
    szd = ezdxf.readfile(SZABLONY / "arkusze_wt.dxf")
    sz = ark.wczytaj_szablon(szd, "a (2)")
    doc = ezdxf.new()
    uk = doc.layouts.new("1")
    e = ark.dodaj_logo(doc, uk, sz.ramka, logotypy()["KPO com4com"])
    x0, y0 = e.dxf.insert.x, e.dxf.insert.y
    szer, wys = e.dxf.u_pixel.x * e.dxf.image_size.x, e.dxf.v_pixel.y * e.dxf.image_size.y
    assert abs(szer - ark.LOGO_SZER) < 1e-6
    assert abs((x0 + szer) - (sz.ramka[2] - ark.LOGO_ODSTEP)) < 1e-6
    assert abs((y0 + wys) - (sz.ramka[3] - ark.LOGO_ODSTEP)) < 1e-6
    assert x0 > sz.ramka[0] and y0 > sz.ramka[1]


def test_nazwy_plikow_wt():
    from pathlib import Path
    from generator.warunki.projekt import Projekt
    p = Projekt()
    p.plik = Path(r"C:\x\PW Cyganka.dwg")
    assert p.sciezka(Path(r"C:\x"), "numeracja.dwg").name == "WT PW Cyganka.dwg"
    assert p.sciezka(Path(r"C:\x"), "numeracja.pdf").name == "WT PW Cyganka.pdf"
    assert p.sciezka(Path(r"C:\x"), "pismo.docx").name == "PW Cyganka_pismo.docx"


def test_ulica_bez_podwojnego_przedrostka():
    from generator.warunki.pismo import ulica_z_przedrostkiem as u
    assert u("Oknicka") == "ul. Oknicka"
    assert u("ulica Oknicka") == "ul. Oknicka"
    assert u("ul. Oknicka") == "ul. Oknicka"
    assert u("ul.Oknicka") == "ul. Oknicka"
    assert u("aleja Krakowska") == "al. Krakowska"
    assert u("Plac Wolności") == "pl. Wolności"
    assert u("Ulicowa") == "ul. Ulicowa"
