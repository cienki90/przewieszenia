"""Wersja okienkowa (dla pliku .exe): pyta o plik planu i miejsce zapisu, potem generuje przewieszenia."""
from __future__ import annotations

import contextlib
import io
import os
import sys
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import przewieszenia

TYTUL = "Przewieszenia - generator rysunków zwisów"


def uruchom(plan: str, wynik: str):
    """Uruchamia generator; zwraca (kod, tekst raportu)."""
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            kod = przewieszenia.main([plan, "-o", wynik])
    except SystemExit as ex:
        kod = ex.code if isinstance(ex.code, int) else 1
    except Exception:
        out.write("\nBłąd programu:\n" + traceback.format_exc())
        kod = 1
    return kod, out.getvalue()


def okno_raportu(root, tytul, tekst):
    win = tk.Toplevel(root)
    win.title(tytul)
    win.geometry("900x500")
    t = tk.Text(win, wrap="none", font=("Consolas", 9))
    sy = ttk.Scrollbar(win, orient="vertical", command=t.yview)
    t.configure(yscrollcommand=sy.set)
    sy.pack(side="right", fill="y")
    t.pack(fill="both", expand=True)
    t.insert("1.0", tekst)
    t.configure(state="disabled")
    ttk.Button(win, text="Zamknij", command=root.destroy).pack(pady=6)
    win.protocol("WM_DELETE_WINDOW", root.destroy)


def main():
    root = tk.Tk()
    root.withdraw()
    root.title(TYTUL)

    plan = filedialog.askopenfilename(
        title="Wybierz plik planu, z którego mają powstać przewieszenia",
        filetypes=[("Rysunek DXF", "*.dxf"), ("Wszystkie pliki", "*.*")])
    if not plan:
        return
    domyslna = os.path.splitext(os.path.basename(plan))[0] + " - przewieszenia.dxf"
    wynik = filedialog.asksaveasfilename(
        title="Gdzie zapisać przewieszenia?",
        initialdir=os.path.dirname(plan), initialfile=domyslna, defaultextension=".dxf",
        filetypes=[("Rysunek DXF", "*.dxf")])
    if not wynik:
        return
    if os.path.abspath(wynik) == os.path.abspath(plan):
        messagebox.showerror(TYTUL, "Plik wynikowy nie może być tym samym plikiem co plan.")
        return

    # okno "proszę czekać"
    czekaj = tk.Toplevel(root)
    czekaj.title(TYTUL)
    czekaj.resizable(False, False)
    ttk.Label(czekaj, text="Trwa tworzenie przewieszeń...\n(pobieranie nazw ulic z internetu może potrwać "
                           "do minuty)", padding=20, justify="center").pack()
    pasek = ttk.Progressbar(czekaj, mode="indeterminate", length=300)
    pasek.pack(padx=20, pady=(0, 20))
    pasek.start(12)

    wynik_pracy = {}

    def praca():
        wynik_pracy["r"] = uruchom(plan, wynik)

    th = threading.Thread(target=praca, daemon=True)
    th.start()

    def sprawdz():
        if th.is_alive():
            root.after(200, sprawdz)
            return
        czekaj.destroy()
        kod, raport = wynik_pracy["r"]
        if kod == 0:
            if messagebox.askyesno(TYTUL, f"Gotowe!\n\nZapisano: {wynik}\n\n"
                                          "Opisy (miejscowość, ulica, stacja) można poprawić w pliku CSV obok "
                                          "planu i uruchomić program ponownie.\n\nOtworzyć folder z wynikiem?"):
                try:
                    os.startfile(os.path.dirname(os.path.abspath(wynik)))  # Windows
                except Exception:
                    pass
            okno_raportu(root, "Raport", raport)
        else:
            okno_raportu(root, "Wystąpił problem", raport or "Nieznany błąd.")

    root.after(200, sprawdz)
    root.mainloop()


if __name__ == "__main__":
    main()
