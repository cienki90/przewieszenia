"""Start okna programu BEZ okna terminala (uruchamiany przez pythonw / uruchom.bat).

Bez konsoli nie widać komunikatów o błędach, więc błąd przy starcie jest pokazywany w okienku
i zapisywany do pliku „blad uruchomienia.txt” obok programu.
"""
import os
import sys
import traceback

if __name__ == "__main__":
    tu = os.path.dirname(os.path.abspath(__file__))
    os.chdir(tu)
    if tu not in sys.path:
        sys.path.insert(0, tu)
    try:
        from generator.gui import main
        main()
    except Exception:  # noqa: BLE001 - jedyne miejsce, w którym użytkownik zobaczy błąd startu
        tekst = traceback.format_exc()
        try:
            with open(os.path.join(tu, "blad uruchomienia.txt"), "w", encoding="utf-8") as f:
                f.write(tekst)
        except OSError:
            pass
        try:
            import tkinter
            from tkinter import messagebox
            okno = tkinter.Tk()
            okno.withdraw()
            messagebox.showerror("Generator projektów nN", "Program nie uruchomił się:\n\n" + tekst[-1500:]
                                 + "\n\nCzy biblioteki są zainstalowane? Uruchom setup.bat.")
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
