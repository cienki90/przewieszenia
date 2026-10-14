#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui - proste okno (tkinter) do wskazania pliku DXF i uruchomienia numeracji.

Okno: wybór pliku DXF, (opcjonalnie) miejsca zapisu, przycisk "Ponumeruj słupy"
i pole logu z raportem (liczba obwodów, słupów, uwagi).
"""
import os


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext

    from numeruj import przetworz

    okno = tk.Tk()
    okno.title('Numeracja słupów nN z DXF (beta)')
    okno.resizable(True, True)
    wej = tk.StringVar()
    wyj = tk.StringVar()

    def domyslne_wyjscie(dxf):
        baza, _ = os.path.splitext(os.path.abspath(dxf))
        return baza + ' - ponumerowane.dxf'

    def wybierz_dxf():
        p = filedialog.askopenfilename(parent=okno, title='Wskaż plik DXF',
                                       filetypes=[('Rysunki DXF', '*.dxf'),
                                                  ('Wszystkie pliki', '*.*')])
        if p:
            wej.set(os.path.normpath(p))
            wyj.set(os.path.normpath(domyslne_wyjscie(p)))

    def wybierz_wyjscie():
        start = wyj.get() or (domyslne_wyjscie(wej.get()) if wej.get() else '')
        p = filedialog.asksaveasfilename(
            parent=okno, title='Gdzie zapisać wynik', defaultextension='.dxf',
            initialdir=os.path.dirname(start) if start else None,
            initialfile=os.path.basename(start) if start else 'ponumerowane.dxf',
            filetypes=[('Rysunek DXF', '*.dxf')])
        if p:
            wyj.set(os.path.normpath(p))

    def log(t):
        pole.configure(state='normal')
        pole.insert('end', t + '\n')
        pole.see('end')
        pole.configure(state='disabled')

    def uruchom():
        dxf, out = wej.get().strip(), wyj.get().strip()
        if not dxf or not os.path.isfile(dxf):
            messagebox.showwarning('Brak pliku', 'Wskaż istniejący plik DXF.', parent=okno)
            return
        if out and not out.lower().endswith('.dxf'):
            out += '.dxf'
            wyj.set(out)
        okno.config(cursor='watch')
        okno.update()
        try:
            wynik, raport = przetworz(dxf, out or None)
            log(raport)
            log('')
            log('Gotowe. Zapisano: %s' % wynik)
            log('-' * 60)
            messagebox.showinfo('Gotowe', 'Zapisano wynik:\n%s' % wynik, parent=okno)
        except Exception as e:
            log('BŁĄD: %s' % e)
            messagebox.showerror('Błąd', str(e), parent=okno)
        finally:
            okno.config(cursor='')

    pad = {'padx': 6, 'pady': 4}
    ramka = tk.Frame(okno)
    ramka.pack(fill='x', **pad)
    tk.Label(ramka, text='Plik DXF:').grid(row=0, column=0, sticky='w')
    tk.Entry(ramka, textvariable=wej, width=60).grid(row=0, column=1, sticky='we', **pad)
    tk.Button(ramka, text='Wskaż…', command=wybierz_dxf).grid(row=0, column=2, **pad)
    tk.Label(ramka, text='Zapisz do:').grid(row=1, column=0, sticky='w')
    tk.Entry(ramka, textvariable=wyj, width=60).grid(row=1, column=1, sticky='we', **pad)
    tk.Button(ramka, text='Zmień…', command=wybierz_wyjscie).grid(row=1, column=2, **pad)
    ramka.columnconfigure(1, weight=1)

    tk.Button(okno, text='Ponumeruj słupy', command=uruchom,
              height=2).pack(fill='x', **pad)

    tk.Label(okno, text='Jak przygotować rysunek: w każdym obwodzie wpisz ręcznie numer '
             '"1" i "2" przy dwóch pierwszych słupach\n(kierunek 1→2 = magistrala) oraz '
             'opis "obw. nr X" z grotem na pierwsze przęsło.',
             justify='left', fg='#444').pack(anchor='w', **pad)

    pole = scrolledtext.ScrolledText(okno, height=16, width=90, state='disabled')
    pole.pack(fill='both', expand=True, **pad)

    okno.mainloop()


if __name__ == '__main__':
    gui()
