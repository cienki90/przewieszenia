"""Wersja przeglądarkowa: serwer przyjmuje pliki, uruchamia moduł i oddaje wyniki."""
import io
import json
import os
import threading
import time
import urllib.error
import urllib.request
import zipfile
from urllib.parse import quote

import pytest

from generator.web import serwer as web

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(KATALOG, "przyklady", "przewieszenia plan.dxf")


@pytest.fixture
def adres(tmp_path):
    s = web.Serwer(("127.0.0.1", 0), str(tmp_path), haslo="", rownolegle=1, dni=0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()
    s.server_close()


def _zapytanie(url, metoda="GET", dane=None, naglowki=None):
    r = urllib.request.Request(url, data=dane, method=metoda, headers=naglowki or {})
    with urllib.request.urlopen(r, timeout=30) as o:
        return o.read()


def test_argumenty_modulow():
    m = web.MODULY_WG_ID
    assert web.argumenty(m["zestawienie"], {}, {"plan": "p.dxf"}) == ["p.dxf", "--tylko", "zestawienie"]
    a = web.argumenty(m["przewieszenia"], {"internet": False, "dxf": True, "obrot": "40,5"}, {"plan": "p.dxf"})
    assert a[:3] == ["p.dxf", "--tylko", "przewieszenia"]
    assert ["--adresy", "brak"] == a[a.index("--adresy"):a.index("--adresy") + 2]
    assert "40.5" in a and "--dxf" in a
    a = web.argumenty(m["orientacje"], {"podklad": False}, {}, zasob_szablonu="szablon.dxf")
    assert a[0] == "szablon.dxf" and "--bez-podkladu" in a
    assert web.argumenty(m["ppw_renumer"], {"dxf": False}, {"plik": "a.dxf"}) == ["-", "--ppw-renumeruj", "a.dxf"]
    with pytest.raises(ValueError):
        web.argumenty(m["zestawienie"], {}, {})
    with pytest.raises(ValueError):
        web.argumenty(m["przewieszenia"], {"obrot": "abc"}, {"plan": "p.dxf"})


def test_bezpieczna_nazwa():
    assert web._bezpieczna_nazwa("..\\..\\x/../plan ą.dxf") == "plan ą.dxf"
    assert web._bezpieczna_nazwa("") == "plik"


def test_zadanie_od_wgrania_do_zip(adres):
    assert b"Generator" in _zapytanie(adres + "/")
    moduly = json.loads(_zapytanie(adres + "/api/moduly"))["moduly"]
    assert any(m["id"] == "zestawienie" for m in moduly)
    zid = json.loads(_zapytanie(adres + "/api/zadanie", "POST"))["id"]
    with open(PLAN, "rb") as f:
        _zapytanie(f"{adres}/api/zadanie/{zid}/plik?pole=plan&nazwa={quote('przewieszenia plan.dxf')}",
                   "PUT", f.read())
    _zapytanie(f"{adres}/api/zadanie/{zid}/start", "POST", json.dumps({"modul": "zestawienie"}).encode(),
               {"Content-Type": "application/json"})
    koniec = time.time() + 180
    while True:
        s = json.loads(_zapytanie(f"{adres}/api/zadanie/{zid}"))
        if s.get("pliki") is not None or time.time() > koniec:
            break
        time.sleep(0.5)
    assert s["stan"] == "gotowe", s
    nazwy = [p["nazwa"] for p in s["pliki"]]
    assert "zestawienie przewieszenia plan.xlsx" in nazwy
    assert "przewieszenia plan.dxf" not in nazwy               # wgrany plik nie jest wynikiem
    z = zipfile.ZipFile(io.BytesIO(_zapytanie(f"{adres}/api/zadanie/{zid}/wyniki.zip")))
    assert "zestawienie przewieszenia plan.xlsx" in z.namelist()
    # uruchomionego zadania nie można zmienić; spoza folderu zadania nic nie wyjdzie
    with pytest.raises(urllib.error.HTTPError) as ex:
        _zapytanie(f"{adres}/api/zadanie/{zid}/plik?pole=plan&nazwa=x.dxf", "PUT", b"x")
    assert ex.value.code == 409
    with pytest.raises(urllib.error.HTTPError) as ex:
        _zapytanie(f"{adres}/api/zadanie/{zid}/plik/..%2F..%2Fstan.json")
    assert ex.value.code == 404


def test_haslo(tmp_path):
    s = web.Serwer(("127.0.0.1", 0), str(tmp_path), haslo="tajne", dni=0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    adres = f"http://127.0.0.1:{s.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _zapytanie(adres + "/api/moduly")
        assert ex.value.code == 401
        import base64
        nagl = {"Authorization": "Basic " + base64.b64encode(b"x:tajne").decode()}
        assert json.loads(_zapytanie(adres + "/api/moduly", naglowki=nagl))["moduly"]
    finally:
        s.shutdown()
        s.server_close()
