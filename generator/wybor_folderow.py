"""Okno wyboru KILKU folderów naraz - systemowe okno Windows „Wybierz folder” z zaznaczaniem
Ctrl / Shift.

tkinter ma tylko wybór jednego folderu (askdirectory). Tu wołamy IFileOpenDialog z opcjami
FOS_PICKFOLDERS | FOS_ALLOWMULTISELECT przez ctypes - bez dodatkowych bibliotek, działa też w exe.
Poza Windows albo przy błędzie COM funkcja zwraca None - wtedy wołający używa askdirectory.
"""
from __future__ import annotations

import ctypes
import os
import sys
import uuid
from ctypes import POINTER, byref, c_long, c_ulong, c_void_p

if sys.platform == "win32":
    from ctypes import wintypes

FOS_NOCHANGEDIR = 0x8
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_ALLOWMULTISELECT = 0x200
FOS_PATHMUSTEXIST = 0x800
SIGDN_FILESYSPATH = 0x80058000
HR_ANULOWANO = -2147023673            # HRESULT_FROM_WIN32(ERROR_CANCELLED) = 0x800704C7
CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 2

CLSID_FILE_OPEN_DIALOG = "{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}"
IID_IFILE_OPEN_DIALOG = "{d57c7288-d4ad-4768-be02-9d969532d960}"
IID_ISHELL_ITEM = "{43826d1e-e718-42ee-bc55-a1e261c37bfe}"

# indeksy metod w tablicy wirtualnej (vtable) interfejsów COM
_RELEASE = 2
_SHOW, _SET_OPTIONS, _GET_OPTIONS, _SET_FOLDER, _SET_TITLE, _SET_OK_LABEL, _GET_RESULTS = 3, 9, 10, 12, 17, 18, 27
_TABLICA_ILE, _TABLICA_ELEMENT = 7, 8          # IShellItemArray::GetCount, GetItemAt
_ELEMENT_NAZWA = 5                             # IShellItem::GetDisplayName


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def z(cls, tekst: str) -> "_GUID":
        u = uuid.UUID(tekst)
        return cls(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


def _metoda(obj, indeks, *argtypes):
    """Metoda interfejsu COM o danym indeksie w vtable (zwraca HRESULT jako liczbę)."""
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtbl[indeks])
    return lambda *a: fn(obj, *a)


def _zwolnij(obj) -> None:
    if obj:
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtbl[_RELEASE])(obj)


def _uchwyt_okna(okno):
    """HWND okna głównego programu (okno wyboru jest wtedy modalne względem niego)."""
    if okno is None:
        return None
    try:
        rodzic = ctypes.WINFUNCTYPE(wintypes.HWND, wintypes.HWND, wintypes.UINT)(
            ("GetAncestor", ctypes.windll.user32))
        return rodzic(okno.winfo_id(), 2) or None          # GA_ROOT
    except Exception:  # noqa: BLE001 - bez właściciela okno też działa
        return None


def wybierz_foldery(okno=None, tytul: str = "", start: str | None = None,
                    przycisk: str = "") -> list[str] | None:
    """Foldery zaznaczone w systemowym oknie wyboru ([] = anulowano) albo None, gdy okna
    systemowego nie da się użyć (inny system, błąd COM) - wtedy trzeba wybrać zwykłym askdirectory."""
    if sys.platform != "win32":
        return None
    try:
        return _wybierz(okno, tytul, start, przycisk)
    except (OSError, AttributeError, ValueError, TypeError):
        return None


def _wybierz(okno, tytul, start, przycisk):
    ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32
    hr_init = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    dlg = c_void_p()
    try:
        hr = ole32.CoCreateInstance(byref(_GUID.z(CLSID_FILE_OPEN_DIALOG)), None, CLSCTX_INPROC_SERVER,
                                    byref(_GUID.z(IID_IFILE_OPEN_DIALOG)), byref(dlg))
        if hr < 0 or not dlg:
            return None
        opcje = wintypes.DWORD()
        if _metoda(dlg, _GET_OPTIONS, POINTER(wintypes.DWORD))(byref(opcje)) < 0:
            return None
        nowe = (opcje.value | FOS_NOCHANGEDIR | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM
                | FOS_ALLOWMULTISELECT | FOS_PATHMUSTEXIST)
        if _metoda(dlg, _SET_OPTIONS, wintypes.DWORD)(nowe) < 0:
            return None
        if tytul:
            _metoda(dlg, _SET_TITLE, wintypes.LPCWSTR)(tytul)
        if przycisk:
            _metoda(dlg, _SET_OK_LABEL, wintypes.LPCWSTR)(przycisk)
        if start and os.path.isdir(start):
            folder = c_void_p()
            if shell32.SHCreateItemFromParsingName(ctypes.c_wchar_p(os.path.abspath(start)), None,
                                                   byref(_GUID.z(IID_ISHELL_ITEM)), byref(folder)) >= 0:
                _metoda(dlg, _SET_FOLDER, c_void_p)(folder)
                _zwolnij(folder)
        hr = _metoda(dlg, _SHOW, wintypes.HWND)(_uchwyt_okna(okno))
        if hr == HR_ANULOWANO:
            return []
        if hr < 0:
            return None
        tablica = c_void_p()
        if _metoda(dlg, _GET_RESULTS, POINTER(c_void_p))(byref(tablica)) < 0 or not tablica:
            return []
        try:
            ile = wintypes.DWORD()
            _metoda(tablica, _TABLICA_ILE, POINTER(wintypes.DWORD))(byref(ile))
            wynik = []
            for i in range(ile.value):
                element = c_void_p()
                if _metoda(tablica, _TABLICA_ELEMENT, wintypes.DWORD, POINTER(c_void_p))(i, byref(element)) < 0:
                    continue
                try:
                    tekst = c_void_p()
                    if (_metoda(element, _ELEMENT_NAZWA, wintypes.DWORD, POINTER(c_void_p))(
                            SIGDN_FILESYSPATH, byref(tekst)) >= 0 and tekst):
                        wynik.append(os.path.normpath(ctypes.wstring_at(tekst.value)))
                        ole32.CoTaskMemFree(tekst)
                finally:
                    _zwolnij(element)
            return wynik
        finally:
            _zwolnij(tablica)
    finally:
        _zwolnij(dlg)
        if hr_init in (0, 1):                  # S_OK / S_FALSE - zainicjowane tutaj, zwalniamy
            ole32.CoUninitialize()
