"""Minimalna obsługa plików DXF (ASCII) bez zewnętrznych bibliotek.

Odczyt: plik -> lista par (kod, wartość) -> sekcje -> encje.
Zapis: lista par -> tekst DXF.
"""
from __future__ import annotations

import math
import os
import re

# pamięć podręczna odczytanych plików: ścieżka -> ((mtime_ns, rozmiar), krotka tagów).
# Ten sam plik czytany kilka razy w jednym uruchomieniu (np. plan: przewieszenia + kontrola)
# jest parsowany tylko raz; zmiana pliku na dysku (mtime/rozmiar) unieważnia wpis.
_CACHE: dict[str, tuple[tuple[int, int], tuple]] = {}
_CACHE_MAX = 2


def read_tags(path: str) -> list[tuple[int, str]]:
    klucz = os.path.abspath(path)
    st = os.stat(klucz)
    stempel = (st.st_mtime_ns, st.st_size)
    wpis = _CACHE.get(klucz)
    if wpis is not None and wpis[0] == stempel:
        return list(wpis[1])     # kopia listy - wywołujący mogą ją modyfikować
    with open(klucz, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1250", errors="replace")
    if "\r" in text:
        text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if len(lines) % 2:           # niesparowana ostatnia linia (zwykle pusta po EOF) - pomiń
        lines.pop()
    tags = [(int(c), v) for c, v in zip(lines[0::2], lines[1::2]) if c.strip()]
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[klucz] = (stempel, tuple(tags))
    return tags


def split_sections(tags):
    """Zwraca listę (nazwa, tagi_wewnątrz) w kolejności z pliku."""
    out = []
    i = 0
    n = len(tags)
    while i < n:
        if tags[i] == (0, "SECTION"):
            name = tags[i + 1][1]
            j = i + 2
            while tags[j] != (0, "ENDSEC"):
                j += 1
            out.append((name, tags[i + 2 : j]))
            i = j
        i += 1
    return out


def split_entities(tags):
    """Dzieli tagi na encje: lista (typ, [(kod, wartość), ...])."""
    out = []
    cur = None
    for c, v in tags:
        if c == 0:
            cur = (v, [])
            out.append(cur)
        elif cur is not None:
            cur[1].append((c, v))
    return out


def join_entities(ents):
    tags = []
    for t, d in ents:
        tags.append((0, t))
        tags.extend(d)
    return tags


def get(d, code, default=None):
    for c, v in d:
        if c == code:
            return v
    return default


def getf(d, code, default=None):
    v = get(d, code)
    return float(v) if v is not None else default


def write_tags(path: str, tags) -> None:
    out = []
    for c, v in tags:
        out.append(f"{c:>3}\n{v}\n")
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("".join(out))


def mtext_plain(s: str) -> str:
    """Usuwa podstawowe kody formatujące MTEXT."""
    s = re.sub(r"\\[pACcFfHhQqTtWw][^;]*;", "", s)
    s = s.replace("\\P", "\n").replace("{", "").replace("}", "")
    return s.strip()


def fmt(x: float) -> str:
    if abs(x) < 1e-12:
        x = 0.0
    return repr(float(x))


def seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.dist(p, (ax + t * dx, ay + t * dy))
