#!/usr/bin/env python3
"""Prueft die erzeugten Browser-Seiten auf Syntaxfehler im JavaScript.

Ein kaputtes Skript faellt sonst erst auf, wenn im Browser gar nichts mehr
geht - und dort sieht man den Grund nicht.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import editor
import galerie
import heatmap


def javascript_pruefen(name, html):
    treffer = re.search(r"<script>(.*?)</script>", html, re.S)
    if not treffer:
        return True, "kein JavaScript enthalten"
    if not shutil.which("node"):
        return True, "node fehlt, nicht geprueft"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as datei:
        datei.write(treffer.group(1))
        pfad = datei.name
    ergebnis = subprocess.run(["node", "--check", pfad], capture_output=True, text=True)
    Path(pfad).unlink()
    if ergebnis.returncode:
        return False, ergebnis.stderr.strip().splitlines()[1] if ergebnis.stderr else "Fehler"
    return True, "fehlerfrei"


def main():
    plan = heatmap.plan_laden()
    laeufe, uebersprungen = galerie.laeufe_sammeln()
    seiten = {
        "Editor": editor._seite(plan, [
            {"name": "Beispiel fest", "beweglich": False, "verbunden": True},
            {"name": "Beispiel Handy", "beweglich": True, "verbunden": False},
        ]),
        "Vergleichsseite": Path(
            galerie.bauen(laeufe, Path(tempfile.gettempdir()) / "pruefung.html",
                          uebersprungen)
        ).read_text(encoding="utf-8"),
    }
    alles_gut = True
    for name, html in seiten.items():
        gut, meldung = javascript_pruefen(name, html)
        print(f"  {name:<18s} {'ok ' if gut else 'FEHLER'}  {meldung}")
        alles_gut &= gut
    return 0 if alles_gut else 1


if __name__ == "__main__":
    sys.exit(main())
