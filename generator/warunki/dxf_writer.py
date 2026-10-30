"""Zapis numeracji słupów do DXF jako odnośnik (LEADER) z tekstem (MTEXT).

Wygląd odwzorowuje numeracja_leader.dxf:
- warstwa 'makro-numeracja-punktow', kolor 7, grubość 0.30 mm,
- odnośnik bez grota: słup -> załamanie (+3.73, +3.0) -> półka 0.18,
- MTEXT wys. 3.0, styl GeodText (romans.shx), wyrównanie do dolnego lewego rogu.
"""
from __future__ import annotations

import math

from ezdxf.document import Drawing
from ezdxf.entities.leader import acdb_leader
from ezdxf.enums import MTextEntityAlignment

from .config import Config
from .model import Wierzcholek

# ezdxf pomija w zapisie kod 75 (półka), gdy ma wartość domyślną - wymuszamy zapis,
# tak jak w pliku wzorcowym z AutoCAD-a
acdb_leader.attribs["has_hookline"].optional = False

# 4 możliwe kierunki odnośnika: (znak x, znak y)
_KIERUNKI = [(1, 1), (-1, 1), (-1, -1), (1, -1)]


def _zapytanie(cfg: Config) -> str:
    return f'LEADER MTEXT TEXT[layer=="{cfg.warstwa_numeracji}"]i'


def istniejaca_numeracja(doc: Drawing, cfg: Config) -> int:
    return len(doc.modelspace().query(f'MTEXT TEXT[layer=="{cfg.warstwa_numeracji}"]i'))


def usun_numeracje(doc: Drawing, cfg: Config) -> int:
    msp = doc.modelspace()
    stare = list(msp.query(_zapytanie(cfg)))
    for e in stare:
        msp.delete_entity(e)
    return len(stare)


def _przygotuj(doc: Drawing, cfg: Config) -> None:
    if cfg.warstwa_numeracji not in doc.layers:
        doc.layers.add(cfg.warstwa_numeracji, color=cfg.kolor_warstwy)
    if cfg.styl_tekstu not in doc.styles:
        doc.styles.add(cfg.styl_tekstu, font=cfg.czcionka_stylu)


def _najlepszy_kierunek(w: Wierzcholek, slupy: list[Wierzcholek]) -> tuple[int, int]:
    """Kierunek odnośnika najbardziej oddalony kątowo od odcinków linii."""
    katy = [math.atan2(slupy[n].y - w.y, slupy[n].x - w.x) for n in w.sasiedzi]
    if not katy:
        return _KIERUNKI[0]

    def odstep(k):
        a = math.atan2(k[1] * 3.0, k[0] * 3.73)
        return min(abs(math.remainder(a - b, math.tau)) for b in katy)

    # preferencja prawo-góra przy remisie (kolejność w _KIERUNKI)
    return max(_KIERUNKI, key=lambda k: round(odstep(k), 2))


def zapisz_numeracje(doc: Drawing, plan: list[Wierzcholek], wszystkie: list[Wierzcholek],
                     cfg: Config) -> None:
    _przygotuj(doc, cfg)
    msp = doc.modelspace()
    atr = {"layer": cfg.warstwa_numeracji, "lineweight": cfg.grubosc_linii}
    for w in plan:
        sx, sy = _najlepszy_kierunek(w, wszystkie) if cfg.inteligentny_kierunek else (1, 1)
        zalamanie = (w.x + sx * cfg.odsuniecie_x, w.y + sy * cfg.odsuniecie_y)
        koniec = (zalamanie[0] + sx * cfg.polka, zalamanie[1])
        tekst_xy = (koniec[0] + sx * cfg.odstep_tekstu, zalamanie[1])

        mt = msp.add_mtext(w.etykieta, dxfattribs={
            **atr, "style": cfg.styl_tekstu, "char_height": cfg.wysokosc_tekstu,
            "line_spacing_factor": 0.8})
        mt.set_location(tekst_xy, attachment_point=(
            MTextEntityAlignment.BOTTOM_LEFT if sx > 0 else MTextEntityAlignment.BOTTOM_RIGHT))

        ld = msp.add_leader([(w.x, w.y), zalamanie, koniec], dimstyle="Standard",
                            dxfattribs=atr)
        ld.dxf.has_arrowhead = 0
        ld.dxf.has_hookline = 1
        ld.dxf.annotation_type = 0  # MTEXT
        ld.dxf.annotation_handle = mt.dxf.handle
        ld.dxf.text_height = cfg.wysokosc_tekstu
        ld.dxf.text_width = 0.91 * cfg.wysokosc_tekstu * len(w.etykieta)
        ld.dxf.hookline_direction = 0
        ld.dxf.horizontal_direction = (sx, 0, 0)
        mt.append_reactor_handle(ld.dxf.handle)  # powiązanie tekstu z odnośnikiem
