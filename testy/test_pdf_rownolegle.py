"""Rysowanie PDF w kilku procesach: wybór liczby procesów."""
import functools
import operator

from generator import dxf2pdf


def test_lambda_wymusza_rysowanie_po_kolei(tmp_path):
    # lambdy nie da się przekazać do procesu potomnego -> 1 proces (bez czytania pliku)
    assert dxf2pdf._ile_procesow(str(tmp_path / "brak.dxf"), lambda n: True) == 1


def test_brak_pliku_daje_jeden_proces(tmp_path):
    assert dxf2pdf._ile_procesow(str(tmp_path / "brak.dxf"), functools.partial(operator.ne, "a")) == 1


def test_zmienna_srodowiskowa_wylacza(monkeypatch, tmp_path):
    monkeypatch.setenv("PGE_PDF_PROCESY", "1")
    assert dxf2pdf._ile_procesow(str(tmp_path / "x.dxf"), None) == 1
