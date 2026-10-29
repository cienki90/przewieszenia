"""Przeciąganie plików z Eksploratora Windows na okno programu (bez dodatkowych bibliotek).

Tkinter nie obsługuje upuszczania plików, więc okno główne rejestrujemy przez Windows API
(DragAcceptFiles + przechwycenie komunikatu WM_DROPFILES). Funkcja ``wlacz`` wywołuje
``obsluga(lista_plikow, x_ekranu, y_ekranu)`` po upuszczeniu. Poza Windows - nic nie robi.
"""
from __future__ import annotations

import sys

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4


def wlacz(root, obsluga) -> bool:
    """Włącza upuszczanie plików na okno ``root``. Zwraca True, gdy się udało."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False
    try:
        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
        ustaw = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        ustaw.restype = ctypes.c_void_p
        ustaw.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.GetParent.restype = wintypes.HWND
        user32.GetParent.argtypes = [wintypes.HWND]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
        shell32.DragQueryPoint.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.POINT)]
        shell32.DragFinish.argtypes = [ctypes.c_void_p]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]

        root.update_idletasks()
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()      # ramka okna Tk
        stara = None

        def procedura(h, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                hdrop = ctypes.c_void_p(wparam)
                pliki = []
                for i in range(shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)):
                    n = shell32.DragQueryFileW(hdrop, i, None, 0) + 1
                    bufor = ctypes.create_unicode_buffer(n)
                    shell32.DragQueryFileW(hdrop, i, bufor, n)
                    pliki.append(bufor.value)
                pkt = wintypes.POINT()
                shell32.DragQueryPoint(hdrop, ctypes.byref(pkt))
                user32.ClientToScreen(h, ctypes.byref(pkt))
                shell32.DragFinish(hdrop)
                # w procedurze okna NIE wolno wołać Tk (Tcl jest w trakcie obsługi komunikatów) -
                # tylko kolejka; odbiera ją cykliczne sprawdzanie po stronie Tk
                kolejka.put((pliki, pkt.x, pkt.y))
                return 0
            return user32.CallWindowProcW(stara, h, msg, wparam, lparam)

        import queue
        kolejka = queue.Queue()

        def odbierz():
            try:
                while True:
                    obsluga(*kolejka.get_nowait())
            except queue.Empty:
                pass
            root.after(150, odbierz)

        nowa = WNDPROC(procedura)
        stara = ustaw(hwnd, GWLP_WNDPROC, ctypes.cast(nowa, ctypes.c_void_p))
        if not stara:
            return False
        root._upusc_procedura = nowa          # referencja - inaczej GC usunie procedurę
        shell32.DragAcceptFiles(hwnd, True)
        root.after(150, odbierz)
        return True
    except Exception:  # noqa: BLE001 - przeciąganie to udogodnienie, nie może zablokować programu
        return False
