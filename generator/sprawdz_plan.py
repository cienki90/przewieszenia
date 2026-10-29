"""„Sprawdź plan” - szybka kontrola planu DXF przed uruchomieniem modułów.

Sprawdza to samo, czego szukają moduły (warstwy, bloki, opisy, layout-wzorzec) i mówi, czy
dany moduł ma szansę się udać, a jeśli nie - czego brakuje. Dzięki temu błąd typu „brak
layoutu-wzorca a” widać od razu, a nie w połowie generowania.

Tylko odczyt pliku (bez zmian), działa w ułamku sekundy także dla dużych planów.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .dxfio import get, mtext_plain, read_tags, split_entities, split_sections

BLOKI_SLUPOW = ("ZN", "E", "R")
RE_STACJA = re.compile(r"STACJA\s+TRAFO\s*(\d+\s*-\s*\d+|\d{3,4})", re.I)
RE_OBWOD = re.compile(r"obw\.?\s*nr\s*\d+", re.I)
RE_SLUP = re.compile(r"s[łl]up\s*nN", re.I)

OK, UWAGA, BLAD = "OK", "UWAGA", "BŁĄD"
ZNAK = {OK: "✓", UWAGA: "!", BLAD: "✗"}


@dataclass
class Raport:
    plik: str
    fakty: list = field(default_factory=list)       # [(poziom, tekst)]
    moduly: list = field(default_factory=list)      # [(moduł, gotowy, [braki])]

    @property
    def bledy(self):
        return sum(1 for p, _ in self.fakty if p == BLAD)

    def tekst(self) -> str:
        linie = [f"SPRAWDZENIE PLANU: {self.plik}"]
        linie += [f"  {ZNAK[p]} {t}" for p, t in self.fakty]
        linie.append("GOTOWOŚĆ MODUŁÓW:")
        for nazwa, gotowy, braki in self.moduly:
            linie.append(f"  {'✓' if gotowy else '✗'} {nazwa}" + ("" if gotowy else " — brakuje: " + "; ".join(braki)))
        return "\n".join(linie)


def _tekst(t, d):
    if t == "MULTILEADER":
        return mtext_plain(get(d, 304) or "")
    if t == "MTEXT":
        return mtext_plain("".join(v for c, v in d if c in (3, 1)))
    return get(d, 1) or ""


def _norm(s):
    return re.sub(r"\s+", "", s or "").lstrip("0") or "0"


def sprawdz(sciezka: str) -> Raport:
    secs = dict(split_sections(read_tags(sciezka)))
    ents = [(t, d) for t, d in split_entities(secs.get("ENTITIES", [])) if (get(d, 67) or "0").strip() != "1"]
    bloki = split_entities(secs.get("BLOCKS", []))

    # bloki zawierające symbol słupa (słupy bywają zagnieżdżone, np. blok „q” = ZN + opis)
    ze_slupem, biezacy = set(BLOKI_SLUPOW), None
    for t, d in bloki:
        if t == "BLOCK":
            biezacy = (get(d, 2) or "").strip()
        elif t == "INSERT" and biezacy and (get(d, 2) or "").strip() in BLOKI_SLUPOW:
            ze_slupem.add(biezacy)

    trasy = zasiegi = otwarte = slupy = opisy_slupow = numery = obwody = przewieszenia = wymiary = 0
    znaczniki = set()
    stacje_odn, stacje_zas = set(), set()
    for t, d in ents:
        w = (get(d, 8) or "").strip()
        wl = w.lower()
        if t in ("LWPOLYLINE", "POLYLINE", "LINE") and wl.startswith("!tele"):
            trasy += 1
        if t in ("LWPOLYLINE", "POLYLINE") and (wl == "!trafo" or wl.startswith("!trafo_")):
            zasiegi += 1
            xs = [float(v) for c, v in d if c == 10]
            ys = [float(v) for c, v in d if c == 20]
            domkniety = len(xs) > 2 and abs(xs[0] - xs[-1]) < 0.01 and abs(ys[0] - ys[-1]) < 0.01
            if not (int(get(d, 70) or 0) & 1) and not domkniety:
                otwarte += 1
            if wl.startswith("!trafo_"):
                stacje_zas.add(_norm(w[len("!trafo_"):].split("-")[-1]))
        if t == "INSERT" and (get(d, 2) or "").strip() in ze_slupem:
            slupy += 1
        if t == "DIMENSION":
            wymiary += 1
        if wl == "_przewieszenia":
            przewieszenia += 1
        if t in ("TEXT", "MTEXT") and wl.startswith("_numery"):
            numery += 1
            if wl == "_numery" and _tekst(t, d).strip() in ("1", "2"):
                znaczniki.add(_tekst(t, d).strip())
        if t in ("MULTILEADER", "MTEXT", "TEXT"):
            tx = _tekst(t, d)
            m = RE_STACJA.search(tx)
            if m:
                stacje_odn.add(_norm(m.group(1).split("-")[-1]))
            if RE_OBWOD.search(tx):
                obwody += 1
            if RE_SLUP.search(tx):
                opisy_slupow += 1

    layouty = []
    for t, d in split_entities(secs.get("OBJECTS", [])):
        if t == "LAYOUT":
            nazwy = [v.strip() for c, v in d if c == 1]
            if nazwy:
                layouty.append(nazwy[-1])
    wzorzec_a = any(n.lower() == "a" for n in layouty)

    r = Raport(sciezka)
    f = r.fakty.append
    f((OK, f"Trasa !tele: {trasy} elem.") if trasy else (BLAD, "Brak trasy na warstwie !tele"))
    f((OK, f"Słupy (bloki {', '.join(BLOKI_SLUPOW)}): {slupy}") if slupy else (BLAD, "Brak bloków słupów ZN/E/R"))
    f((OK, f"Opisy słupów „słup nN / typ”: {opisy_slupow}") if opisy_slupow
      else (UWAGA, "Brak opisów „słup nN / typ” - typy słupów będą nieznane"))
    if zasiegi:
        f((OK, f"Zasięgi stacji (!trafo): {zasiegi}") if not otwarte
          else (UWAGA, f"Zasięgi stacji (!trafo): {zasiegi}, w tym {otwarte} niezamkniętych"))
    else:
        f((UWAGA, "Brak zasięgów stacji (!trafo) - stacje tylko z odnośników i drzewa sieci"))
    f((OK, f"Odnośniki „STACJA TRAFO”: {len(stacje_odn)}") if stacje_odn
      else (UWAGA if stacje_zas else BLAD, "Brak odnośników „STACJA TRAFO <nr>”"))
    bez_zasiegu = sorted(stacje_odn - stacje_zas) if stacje_zas else []
    bez_odn = sorted(stacje_zas - stacje_odn)
    if bez_zasiegu:
        f((UWAGA, f"Stacje bez zasięgu !trafo_<nr>: {', '.join(bez_zasiegu)}"))
    if bez_odn:
        f((UWAGA, f"Zasięgi bez odnośnika STACJA TRAFO: {', '.join(bez_odn)}"))
    f((OK, f"Numery słupów (_numery*): {numery}") if numery else (UWAGA, "Brak numerów słupów (_numery*)"))
    f((OK, f"Opisy „obw. nr X”: {obwody}") if obwody else (UWAGA, "Brak opisów „obw. nr X”"))
    f((OK, f"Zaznaczenia przewieszeń (_PRZEWIESZENIA): {przewieszenia}") if przewieszenia
      else (UWAGA, "Brak zaznaczeń na warstwie _PRZEWIESZENIA"))
    f((OK, f"Wymiary przęseł: {wymiary}") if wymiary else (UWAGA, "Brak wymiarów - długości przęseł z trasy"))
    f((OK, "Layout-wzorzec „a” (PZT) jest") if wzorzec_a
      else (UWAGA, "Brak layoutu-wzorca „a” - do PZT wskaż osobny plik wzorca"))

    stacje = bool(stacje_odn or stacje_zas)

    def modul(nazwa, warunki):
        braki = [opis for ok, opis in warunki if not ok]
        r.moduly.append((nazwa, not braki, braki))

    modul("Numeracja słupów", [(trasy, "trasy !tele"), (slupy, "słupów"),
                               ({"1", "2"} <= znaczniki, "znaczników „1” i „2” na warstwie _numery"),
                               (obwody, "opisów „obw. nr X”")])
    modul("Zestawienie / Obliczenia", [(trasy, "trasy !tele"), (slupy, "słupów"), (numery, "numerów słupów"),
                                       (stacje, "stacji trafo")])
    modul("Przewieszenia", [(trasy, "trasy !tele"), (slupy, "słupów"),
                            (przewieszenia, "zaznaczeń _PRZEWIESZENIA")])
    modul("Arkusze PZT", [(trasy, "trasy !tele"), (zasiegi, "zasięgów !trafo"),
                          (wzorzec_a, "layoutu „a” (albo wskaż plik wzorca)")])
    modul("Rysunki stałe (jako plik PZT)", [(zasiegi, "zasięgów !trafo"), (stacje, "stacji trafo")])
    return r
