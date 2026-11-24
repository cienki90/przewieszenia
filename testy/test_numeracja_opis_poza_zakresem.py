"""Opis STACJA TRAFO tuż za obrysem !trafo: zakres bez opisu dostaje najbliższą stację."""
from generator.numeruj_slupy import model as M


def test_odleglosc_od_wielokata():
    A = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert M._odl_od_wielokata((5, 5), A) == 0.0
    assert abs(M._odl_od_wielokata((15, 5), A) - 5) < 1e-9
    assert abs(M._odl_od_wielokata((13, 14), A) - 5) < 1e-9


def test_zakres_bez_opisu_dostaje_najblizsza_stacje(monkeypatch):
    class Rys:
        uwagi = []
        zakresy = [[(0, 0), (100, 0), (100, 100), (0, 100)]]
        nazwy_zakresow = [None]
        wymiary = []
        sieci = []
        teksty = []
        opisy = [("STACJA TRAFO\n03-0551", (130.0, 50.0)),
                 ("słup nN\nP-10/ZN", (90.0, 50.0)), ("słup nN\nP-10/ZN", (10.0, 50.0))]
    monkeypatch.setattr(M, "graf_sieci", lambda *a: {})
    monkeypatch.setattr(M, "graf_wymiarow", lambda *a: {})
    m = M.Model(Rys())
    assert m.zakres_stacji == {0: "03-0551"}
    assert set(m.stacja_slupa.values()) == {"03-0551"}
