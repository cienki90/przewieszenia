"""Dane operatora po numerze NIP z rejestrów publicznych.

- GUS (BIR 1.1, REGON)  - nazwa, adres, REGON. Wymaga klucza użytkownika
  (bezpłatny, wydaje GUS: https://api.stat.gov.pl/Home/RegonApi).
- Biała lista podatników VAT (Ministerstwo Finansów) - nazwa, adres, REGON;
  bez klucza; używana, gdy nie podano klucza GUS albo GUS nie odpowiada.
- Rejestr przedsiębiorców telekomunikacyjnych UKE (rejestry.uke.gov.pl/rejestr_rpt)
  - numer wpisu do RPT.
"""
from __future__ import annotations

import html
import re
from datetime import date

import requests

USER_AGENT = "GeneratorWT/1.0 (projektowanie sieci telekomunikacyjnych)"
GUS_URL = "https://wyszukiwarkaregon.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc"
GUS_URL_TEST = "https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc"
GUS_KLUCZ_TEST = "abcde12345abcde12345"
MF_URL = "https://wl-api.mf.gov.pl/api/search/nip/{nip}"
RPT_URL = "https://rejestry.uke.gov.pl/rejestr_rpt"


class BladRejestru(Exception):
    pass


def oczysc_nip(nip: str) -> str:
    n = re.sub(r"\D", "", nip or "")
    if len(n) != 10:
        raise BladRejestru("NIP musi mieć 10 cyfr.")
    wagi = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    if sum(int(c) * w for c, w in zip(n, wagi)) % 11 != int(n[9]):
        raise BladRejestru(f"Nieprawidłowy NIP {n} (błędna cyfra kontrolna).")
    return n


# ---------------------------------------------------------------- formatowanie

_MALE = {"sp.", "z", "o.o.", "s.a.", "s.c.", "sp.k.", "i", "w", "na", "ul.", "al."}
_FORMY = [  # pełne nazwy form prawnych -> skróty używane w pismach
    (r"SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ SPÓŁKA KOMANDYTOWA", "Sp. z o.o. Sp.k."),
    (r"SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ", "Sp. z o.o."),
    (r"SPÓŁKA AKCYJNA", "S.A."),
    (r"SPÓŁKA KOMANDYTOWA", "Sp.k."),
    (r"SPÓŁKA JAWNA", "Sp.j."),
    (r"SPÓŁKA CYWILNA", "s.c."),
]


def ladna_nazwa(nazwa: str) -> str:
    """'INTERWAN SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ' -> 'Interwan Sp. z o.o.'
    Słowa pisane wielkimi literami, krótkie (do 4 znaków, np. 'ISP', 'IT'), zostają."""
    t = " ".join((nazwa or "").split())
    forma = ""
    for wzor, skrot in _FORMY:
        if re.search(wzor + r"\s*$", t, re.I):
            t = re.sub(wzor + r"\s*$", "", t, flags=re.I).strip()
            forma = skrot
            break
    slowa = []
    for s in t.split():
        if s.isupper() and len(s) <= 4 and s.isalpha() and len(t.split()) > 1:
            slowa.append(s)  # skróty, np. ISP, IT
        elif s.lower() in _MALE:
            slowa.append(s.lower())
        else:
            slowa.append("-".join(x[:1].upper() + x[1:].lower() for x in s.split("-")))
    if t.isupper() and len(t.split()) == 1:  # jedno słowo, np. "KOWALSKI-NOWAK"
        slowa = ["-".join(x[:1].upper() + x[1:].lower() for x in t.split("-"))]
    return (" ".join(slowa) + (" " + forma if forma else "")).strip()


def ladna_miejscowosc(t: str) -> str:
    return " ".join("-".join(x[:1].upper() + x[1:].lower() for x in s.split("-"))
                    for s in (t or "").split())


def ladna_ulica(t: str) -> str:
    t = ladna_miejscowosc(t)
    if t and not re.match(r"(?i)^(ul\.|al\.|pl\.|os\.|aleja\b|aleje\b|plac\b|osiedle\b|rondo\b|skwer\b)", t):
        t = "ul. " + t
    return re.sub(r"(?i)^(ul|al|pl|os)\.", lambda m: m.group(1).lower() + ".", t)


# ---------------------------------------------------------------- GUS BIR 1.1

def _soap(url, akcja, cialo):
    return (f'<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
            f'xmlns:ns="http://CIS/BIR/PUBL/2014/07" '
            f'xmlns:dat="http://CIS/BIR/PUBL/2014/07/DataContract">'
            f'<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">'
            f'<wsa:To>{url}</wsa:To><wsa:Action>http://CIS/BIR/PUBL/2014/07/'
            f'IUslugaBIRzewnPubl/{akcja}</wsa:Action></soap:Header>'
            f'<soap:Body>{cialo}</soap:Body></soap:Envelope>').encode("utf-8")


def _pole(xml, nazwa):
    m = re.search(rf"<{nazwa}>(.*?)</{nazwa}>", xml, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def gus(nip: str, klucz: str, timeout: int = 30) -> dict:
    test = klucz.strip() == GUS_KLUCZ_TEST
    url = GUS_URL_TEST if test else GUS_URL
    h = {"Content-Type": "application/soap+xml; charset=utf-8", "User-Agent": USER_AGENT}
    s = requests.Session()
    r = s.post(url, data=_soap(url, "Zaloguj", f"<ns:Zaloguj><ns:pKluczUzytkownika>"
                                               f"{klucz.strip()}</ns:pKluczUzytkownika>"
                                               f"</ns:Zaloguj>"), headers=h, timeout=timeout)
    sid = _pole(r.text, "ZalogujResult")
    if not sid:
        raise BladRejestru("GUS: nieprawidłowy klucz użytkownika.")
    h["sid"] = sid
    try:
        r = s.post(url, data=_soap(url, "DaneSzukajPodmioty",
                                   f"<ns:DaneSzukajPodmioty><ns:pParametryWyszukiwania>"
                                   f"<dat:Nip>{nip}</dat:Nip></ns:pParametryWyszukiwania>"
                                   f"</ns:DaneSzukajPodmioty>"), headers=h, timeout=timeout)
        wynik = html.unescape(_pole(r.text, "DaneSzukajPodmiotyResult"))
    finally:
        s.post(url, data=_soap(url, "Wyloguj", f"<ns:Wyloguj><ns:pIdentyfikatorSesji>{sid}"
                                               f"</ns:pIdentyfikatorSesji></ns:Wyloguj>"),
               headers=h, timeout=timeout)
    if not wynik or _pole(wynik, "ErrorCode"):
        raise BladRejestru("GUS: " + (_pole(wynik, "ErrorMessagePl") or "brak danych."))
    nr = _pole(wynik, "NrNieruchomosci")
    lok = _pole(wynik, "NrLokalu")
    return {"nazwa": _pole(wynik, "Nazwa"), "regon": _pole(wynik, "Regon"),
            "ulica": _pole(wynik, "Ulica"), "nr": nr + (f"/{lok}" if lok else ""),
            "kod": _pole(wynik, "KodPocztowy"), "miejscowosc": _pole(wynik, "Miejscowosc"),
            "zrodlo": "GUS" + (" (środowisko testowe)" if test else "")}


# ---------------------------------------------------------------- Biała lista MF

def biala_lista(nip: str, timeout: int = 30) -> dict:
    r = requests.get(MF_URL.format(nip=nip), params={"date": date.today().isoformat()},
                     headers={"User-Agent": USER_AGENT}, timeout=timeout)
    if r.status_code != 200:
        raise BladRejestru(f"Biała lista MF: HTTP {r.status_code}")
    p = (r.json().get("result") or {}).get("subject")
    if not p:
        raise BladRejestru("Biała lista MF: nie znaleziono podmiotu.")
    adres = p.get("workingAddress") or p.get("residenceAddress") or ""
    # "LAZUROWA 1, 05-311 DĘBE WIELKIE" / "UL. X 5/2, 00-001 MIASTO"
    m = re.match(r"^(.*?)[,\s]+(\d{2}-\d{3})\s+(.+)$", adres)
    ul_nr, kod, miasto = (m.group(1), m.group(2), m.group(3)) if m else (adres, "", "")
    m2 = re.match(r"^(.*?)\s+(\d+\w*(?:/\d+\w*)?)$", ul_nr.strip())
    ulica, nr = (m2.group(1), m2.group(2)) if m2 else (ul_nr, "")
    return {"nazwa": p.get("name", ""), "regon": p.get("regon") or "", "ulica": ulica,
            "nr": nr, "kod": kod, "miejscowosc": miasto, "zrodlo": "Biała lista MF"}


# ---------------------------------------------------------------- RPT UKE

def rpt(nip: str, timeout: int = 30) -> dict | None:
    r = requests.get(RPT_URL, params={"nip": nip}, headers={"User-Agent": USER_AGENT},
                     timeout=timeout)
    r.raise_for_status()
    s = r.text
    i = s.find("<table")
    if i < 0:
        return None
    tabela = re.sub(r"\s+", " ", s[i:s.find("</table>", i)])
    wiersze = []
    for w in re.findall(r"<tr.*?</tr>", tabela):
        wiersze.append([html.unescape(re.sub("<[^>]+>", "", c)).strip()
                        for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", w)])
    if len(wiersze) < 2:
        return None
    nagl = wiersze[0]
    rek = [dict(zip(nagl, w)) for w in wiersze[1:] if len(w) == len(nagl)]
    rek = [x for x in rek if re.sub(r"\D", "", x.get("NIP", "")) == nip]
    if not rek:
        return None
    aktywne = [x for x in rek if not x.get("Data wykreślenia z rejestru")]
    x = (aktywne or rek)[0]
    nr = x.get("Nr domu", "") + (f"/{x['Nr lokalu']}" if x.get("Nr lokalu") else "")
    return {"nr_rpt": x.get("Nr PT", ""), "nazwa": x.get("Nazwa PT", ""),
            "wykreslony": not aktywne, "ulica": x.get("Ulica", ""), "nr": nr,
            "kod": x.get("Kod pocztowy", ""), "miejscowosc": x.get("Miejscowość", "")}


# ---------------------------------------------------------------- całość

def operator_po_nip(nip: str, klucz_gus: str | None = None, log=None) -> dict:
    """Zwraca wpis do arkusza 'Operatorzy' (kolumny jak w słowniku) + klucz '_info'."""
    nip = oczysc_nip(nip)
    info, dane = [], None
    if klucz_gus:
        try:
            dane = gus(nip, klucz_gus)
        except (BladRejestru, requests.RequestException) as e:
            info.append(f"{e} – używam białej listy MF.")
    if dane is None:
        try:
            dane = biala_lista(nip)
        except (BladRejestru, requests.RequestException, ValueError) as e:
            info.append(str(e))
    try:
        r = rpt(nip)
    except requests.RequestException as e:
        r = None
        info.append(f"Rejestr RPT niedostępny: {e}")
    if r is None:
        info.append("Brak wpisu w rejestrze przedsiębiorców telekomunikacyjnych (RPT).")
    elif r["wykreslony"]:
        info.append(f"Uwaga: wpis RPT nr {r['nr_rpt']} jest wykreślony z rejestru.")
    if dane is None and r is not None:  # adres z RPT, gdy inne źródła zawiodły
        dane = {**r, "regon": "", "zrodlo": "RPT UKE"}
    if dane is None:
        raise BladRejestru("Nie znaleziono podmiotu o NIP " + nip + ". " + " ".join(info))

    pelna = ladna_nazwa(dane["nazwa"])
    ulica = ladna_ulica(dane["ulica"])
    adres = f"{ulica} {dane['nr']}".strip() if ulica else \
        f"{ladna_miejscowosc(dane['miejscowosc'])} {dane['nr']}".strip()
    wpis = {
        "Nazwa": pelna.replace(" Sp. z o.o.", "").replace(" S.A.", "").strip() or pelna,
        "Numer Umowy Ramowej": "",
        "Pełna nazwa": pelna,
        "Adres (siedziba)": adres,
        "Kod pocztowy": f"{dane['kod']} {ladna_miejscowosc(dane['miejscowosc'])}".strip(),
        "NIP": nip,
        "Regon": dane.get("regon", ""),
        "Numer wpisu do RPT": r["nr_rpt"] if r else "",
        "Dane kontaktowe": "",
        "_info": [f"Dane adresowe: {dane['zrodlo']}."]
                 + ([f"RPT: nr {r['nr_rpt']}."] if r else []) + info,
    }
    if log:
        for t in wpis["_info"]:
            log(t)
    return wpis
