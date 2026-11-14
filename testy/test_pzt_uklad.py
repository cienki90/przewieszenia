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
