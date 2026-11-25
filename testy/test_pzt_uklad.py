"""Układ arkuszy PZT: najmniejsza liczba arkuszy, prawdziwy zakład, numeracja od stacji."""
from generator import pzt

W, H = 394.47, 286.31
ZAK = (311.47, 0.0, 394.47, 62.99)


def _wspolne(linie, r, m=pzt.MARGINES_MM):
    zx0, zy1 = ZAK[0] - m, ZAK[3] + m
    P = pzt._probkuj(linie, pzt.GESTOSC)
    mk = [[pzt._w_uzyt(x - x0, y - y0, W, H, m, zx0, zy1) for x, y, _c, _t in P] for x0, y0 in r]
    return [sum(a and b for a, b in zip(mk[i], mk[i + 1])) * pzt.GESTOSC for i in range(len(r) - 1)]


def test_prosta_trasa_minimalna_liczba_arkuszy_i_zaklad():
    linie = [[(0.0, 0.0), (950.0, 0.0)]]
    r = pzt.rozmiesc(linie, W, H, ZAK, start=(0.0, 0.0))
    assert len(r) == 3                                  # dawniej 4 (zakład liczony podwójnie)
    assert not pzt.niepokryte(linie, r, W, H, ZAK)
    assert all(w >= pzt.ZAKLAD - pzt.GESTOSC for w in _wspolne(linie, r))
    assert [x for x, _ in r] == sorted(x for x, _ in r)   # numeracja od stacji


def test_minimalnie_nie_gorzej_niz_zachlannie():
    maski = [[1, 1, 1, 1, 0, 0], [1, 1, 1, 0, 0, 0], [0, 0, 0, 1, 1, 1], [0, 0, 1, 1, 1, 1], [1, 0, 0, 0, 0, 1]]
    maski = [[bool(v) for v in m] for m in maski]
    w = pzt._wybierz_minimalnie(maski, 6)
    assert len(w) == 2
    assert all(any(maski[j][i] for j in w) for i in range(6))


def test_numeracja_od_stacji_galeziami():
    # stacja w środku: najpierw arkusz ze stacją, potem jedna gałąź do końca, potem druga
    linie = [[(0.0, 0.0), (-900.0, 0.0)], [(0.0, 0.0), (900.0, 0.0)]]
    r = pzt.rozmiesc(linie, W, H, ZAK, start=(0.0, 0.0))
    sr = [x + W / 2 for x, _ in r]
    assert abs(sr[0]) == min(abs(s) for s in sr)
    znaki = [s > 0 for s in sr[1:]]
    assert znaki == sorted(znaki) or znaki == sorted(znaki, reverse=True)


def test_strefa_zakazana_obejmuje_cala_legende(tmp_path):
    """Legenda wstawiona punktem po PRAWEJ stronie (rysunek w lewo od punktu) - strefa liczona
    z geometrii bloku, nie z punktu wstawienia."""
    import ezdxf
    doc = ezdxf.new()
    leg = doc.blocks.new("legenda")
    leg.add_lwpolyline([(-50, 0), (0, 0), (0, 58), (-50, 58)], close=True)
    tab = doc.blocks.new("tabelka")
    tab.add_lwpolyline([(-83, 0), (0, 0), (0, 65), (-83, 65)], close=True)
    lay = doc.layouts.new("a")
    lay.add_viewport(center=(197.5, 143.5), size=(395, 287), view_center_point=(0, 0), view_height=287)
    lay.add_blockref("tabelka", (395, 0))
    lay.add_blockref("legenda", (312, 0))
    plik = tmp_path / "w.dxf"
    doc.saveas(plik)
    W, H, zak = pzt._wczytaj_wzorzec(str(plik))
    assert abs(zak[0] - 262) < 1.0
    assert abs(zak[3] - 65) < 1.0


def test_jeden_arkusz_to_sam_numer_2():
    from generator.pzt import numer_rysunku
    assert numer_rysunku(1, 1) == "2"
    assert [numer_rysunku(i, 3) for i in (1, 2, 3)] == ["2.1", "2.2", "2.3"]
