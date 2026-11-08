"""Publikacja gotowych kopii programu: kopia z innej gałęzi bez przełączania i osobna kopia
dla każdej gałęzi w hookach gita (tymczasowe repozytorium - prawdziwe hooki nie są ruszane)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KORZEN, "narzedzia"))

import publikuj_gotowy as pg  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                           "-c", "commit.gpgsign=false", *args], capture_output=True, check=True, text=True).stdout


def _plik(repo, sciezka, tresc):
    p = os.path.join(repo, *sciezka.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(tresc)


@unittest.skipIf(shutil.which("git") is None, "brak gita")
class TestPublikacja(unittest.TestCase):
    def setUp(self):
        self.kat = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.kat, True)
        self.repo = os.path.join(self.kat, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q", "-b", "glowna")
        _plik(self.repo, "generator/__init__.py", '__version__ = "2.0"\n')
        _plik(self.repo, "uruchom.bat", "@echo off\n")
        _plik(self.repo, "przyklady/plan.dxf", "0\nEOF\n")              # nie trafia do kopii
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "baza")
        _git(self.repo, "checkout", "-q", "-b", "scalenie")
        _plik(self.repo, "generator/warunki/reader.py", "# WT\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "WT")
        _git(self.repo, "checkout", "-q", "glowna")

    def test_kopia_z_innej_galezi_bez_przelaczania(self):
        cel = os.path.join(self.kat, "PGE MAKER + WT")
        pg.publikuj(self.repo, cel, "scalenie")
        self.assertTrue(os.path.isfile(os.path.join(cel, "generator", "warunki", "reader.py")))
        self.assertFalse(os.path.exists(os.path.join(cel, "przyklady")))
        with open(os.path.join(cel, "generator", "_wersja.txt"), encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("2.0.2 ("))
        with open(os.path.join(cel, "INSTRUKCJA.txt"), encoding="utf-8") as f:
            self.assertIn("gałąź scalenie", f.read())
        self.assertEqual(_git(self.repo, "rev-parse", "--abbrev-ref", "HEAD").strip(), "glowna")
        # kopia głównej gałęzi (HEAD) nie ma modułu WT
        cel2 = os.path.join(self.kat, "PGE MAKER")
        pg.publikuj(self.repo, cel2)
        self.assertFalse(os.path.exists(os.path.join(cel2, "generator", "warunki")))

    def test_hook_dla_dwoch_galezi_i_stary_format(self):
        hooki = os.path.join(self.repo, ".git", "hooks")
        os.makedirs(hooki, exist_ok=True)
        stary = ('#!/bin/sh\n[ "$(git rev-parse --abbrev-ref HEAD)" = "glowna" ] || exit 0\n'
                 "CEL='D:\\GOTOWE\\PGE MAKER'\nexit 0\n")
        with open(os.path.join(hooki, "post-commit"), "w", encoding="utf-8") as f:
            f.write(stary)
        self.assertEqual(pg.kopie_z_hooka(stary), {"glowna": "D:\\GOTOWE\\PGE MAKER"})
        pg.zainstaluj_hook(self.repo, "D:\\GOTOWE\\PGE MAKER + WT", "scalenie")
        for nazwa in pg.HOOKI:
            with open(os.path.join(hooki, nazwa), encoding="utf-8") as f:
                tresc = f.read()
            self.assertEqual(pg.kopie_z_hooka(tresc), {"glowna": "D:\\GOTOWE\\PGE MAKER",
                                                       "scalenie": "D:\\GOTOWE\\PGE MAKER + WT"})
            self.assertIn("  'scalenie') CEL='D:\\GOTOWE\\PGE MAKER + WT' ;;", tresc)
        # ponowna instalacja tej samej gałęzi zmienia tylko jej katalog
        pg.zainstaluj_hook(self.repo, "D:\\INNY", "glowna")
        with open(os.path.join(hooki, "post-merge"), encoding="utf-8") as f:
            self.assertEqual(pg.kopie_z_hooka(f.read()), {"glowna": "D:\\INNY", "scalenie": "D:\\GOTOWE\\PGE MAKER + WT"})

    @unittest.skipIf(shutil.which("sh") is None, "brak powłoki sh")
    def test_hook_wybiera_katalog_wg_galezi(self):
        """Uruchomiony hook publikuje do katalogu bieżącej gałęzi, a dla innych gałęzi nic nie robi."""
        hooki = os.path.join(self.repo, ".git", "hooks")
        _plik(self.repo, "narzedzia/publikuj_gotowy.py", "")              # hook wywołuje skrypt z repo
        shutil.copy2(pg.__file__, os.path.join(self.repo, "narzedzia", "publikuj_gotowy.py"))
        cel_g, cel_s = os.path.join(self.kat, "G"), os.path.join(self.kat, "S")
        pg.zainstaluj_hook(self.repo, cel_g, "glowna")
        pg.zainstaluj_hook(self.repo, cel_s, "scalenie")
        hook = os.path.join(hooki, "post-commit").replace("\\", "/")
        env = dict(os.environ, PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
        _git(self.repo, "checkout", "-q", "scalenie")
        subprocess.run(["sh", hook], cwd=self.repo, check=True, capture_output=True, env=env)
        self.assertTrue(os.path.isfile(os.path.join(cel_s, "generator", "warunki", "reader.py")))
        self.assertFalse(os.path.exists(cel_g))
        _git(self.repo, "checkout", "-q", "-b", "inna")
        subprocess.run(["sh", hook], cwd=self.repo, check=True, capture_output=True, env=env)
        self.assertFalse(os.path.exists(cel_g))


if __name__ == "__main__":
    unittest.main()
