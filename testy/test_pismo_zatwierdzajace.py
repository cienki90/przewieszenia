"""Pismo zatwierdzające: dane z folderu projektu, zapamiętanie numeru WT, Word z szablonem i bez."""
import datetime
import json
import os

import docx
import openpyxl

from generator import pismo_zatwierdzajace as P


def _projekt(tmp_path, wt_w_opisie="65/RE-5/KŚ/2026"):
    f = tmp_path / "Stojadła"
    (f / "rysunki stałe" / "rysunki stałe").mkdir(parents=True)
    (f / "opisy").mkdir()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "zestawienie"
    for r in (("stacja", "ilość", "długość", "kontrola"), ("05-1570", 20, 800, "OK"),
              ("05-0068", 19, 700, "OK"), ("RAZEM", 39, 1500, "")):
        ws.append(r)
    wb.save(f / "zestawienie plan.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(("Lp.", "Oznaczenie stacji", "Nr stacji", "Miejscowość", "Gmina"))
    ws.append((1, "05-1570", 1570, "Stojadła", '"Mińsk Mazowiecki"'))
    ws.append((2, "05-0068", 68, "Mińsk Mazowiecki, Stojadła", '"Mińsk Mazowiecki"'))
    ws.append((3, "05-9999", 9999, "Inna", "Inna"))             # stacja spoza zestawienia - pomijana
    wb.save(f / "rysunki stałe" / "rysunki stałe" / "zestawienie_stacji.xlsx")
    d = docx.Document()
    d.add_paragraph(f"Warunki techniczne nr {wt_w_opisie} z dnia ...")
    d.save(f / "opisy" / "1570.docx")
    (f / "plan.wt.json").write_text(json.dumps({"ustawienia": {"rejon": "Rejon Energetyczny Mińsk Mazowiecki"}}),
                                    encoding="utf-8")
    return str(f)


def test_dane_z_projektu_i_zapamietany_wt(tmp_path):
    f = _projekt(tmp_path)
    p = P.wczytaj_projekt(f)
    assert p.stacje == ["05-1570", "05-0068"] and p.slupy == 39
    assert p.miejscowosci == "Stojadła, Mińsk Mazowiecki gm. Mińsk Mazowiecki"
    assert p.wt == "65/RE-5/KŚ/2026" and p.rejon == "Mińsk Mazowiecki" and not p.uwagi
    assert P.wt_zapisany(f) == "65/RE-5/KŚ/2026"              # zapisany w „projekt GeneratorNN.json”
    P.zapamietaj_wt(f, "70/RE-5/KŚ/2026")                     # poprawka ręczna wygrywa z opisem
    assert P.wczytaj_projekt(f).wt == "70/RE-5/KŚ/2026"


def test_word_bez_szablonu(tmp_path):
    p = P.wczytaj_projekt(_projekt(tmp_path))
    out = P.generuj([p], str(tmp_path / "pismo.docx"), miejscowosc="Mińsk Mazowiecki",
                    data=datetime.date(2026, 7, 24), log=lambda *a: None)
    tekst = "\n".join(x.text for x in docx.Document(out).paragraphs)
    assert "Mińsk Mazowiecki, 24 lipca 2026 r." in tekst
    assert "Rejon Energetyczny Mińsk Mazowiecki w miejscowościach Stojadła, Mińsk Mazowiecki gm. Mińsk Mazowiecki." in tekst
    assert "nr 05‑1570, 05‑0068 na 39 stanowiskach słupowych" in tekst
    assert "nr 65/RE-5/KŚ/2026." in tekst


def test_word_z_szablonu(tmp_path):
    p = P.wczytaj_projekt(_projekt(tmp_path))
    sz = docx.Document()
    sz.add_paragraph("Nagłówek *data*")
    sz.add_paragraph("*projekty*")
    sz.add_paragraph("Razem *razem* słupów, RE *rejon*.")
    sz.save(tmp_path / "szablon.docx")
    out = P.generuj([p, p], str(tmp_path / "pismo.docx"), szablon=str(tmp_path / "szablon.docx"),
                    data=datetime.date(2026, 7, 24), log=lambda *a: None)
    teksty = [x.text for x in docx.Document(out).paragraphs]
    assert teksty[0] == "Nagłówek 24 lipca 2026 r."
    assert sum(t.startswith("- Podwieszenie") for t in teksty) == 2 and "*projekty*" not in teksty
    assert teksty[-1] == "Razem 78 słupów, RE Mińsk Mazowiecki."
