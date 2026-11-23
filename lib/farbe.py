"""Farbe fuer die Konsole - aber nur, wenn ein Mensch zuschaut.

Wird die Ausgabe in eine Datei oder durch eine Pipe geleitet, bleiben die
Steuerzeichen weg. Sonst stehen sie spaeter im Bericht.
"""

import os
import sys

_CODES = {
    "gruen": "32", "hellgruen": "92", "gelb": "33", "rot": "31",
    "hellrot": "91", "grau": "90", "blau": "34", "fett": "1",
}


def moeglich():
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


def faerben(text, *stile):
    if not stile or not moeglich():
        return str(text)
    codes = ";".join(_CODES[s] for s in stile if s in _CODES)
    return f"\033[{codes}m{text}\033[0m" if codes else str(text)


# -- Bedeutung statt Farbe: die Aufrufer sagen, was es ist --------------

def gut(text):        return faerben(text, "gruen")
def brauchbar(text):  return faerben(text, "gelb")
def schlecht(text):   return faerben(text, "rot")
def kritisch(text):   return faerben(text, "hellrot", "fett")
def leise(text):      return faerben(text, "grau")
def betont(text):     return faerben(text, "fett")


def nach_bewertung(text, bewertung):
    """Faerbt nach den Urteilen, die das Werkzeug vergibt."""
    return {
        "sehr gut": gut, "gut": gut,
        "brauchbar": brauchbar, "grenzwertig": brauchbar,
        "schlecht": schlecht, "kritisch": schlecht,
        "unbrauchbar": kritisch,
    }.get(bewertung, str)(text)


def nach_signal(text, rssi):
    """Faerbt eine Signalstaerke nach denselben Schwellen wie die Heatmap."""
    if rssi is None:
        return leise(text)
    if rssi >= -60:
        return gut(text)
    if rssi >= -70:
        return brauchbar(text)
    if rssi >= -78:
        return schlecht(text)
    return kritisch(text)


def nach_gewicht(text, gewicht):
    return {"kritisch": kritisch, "wichtig": schlecht,
            "hinweis": brauchbar}.get(gewicht, leise)(text)


def balken(rssi, breite=12):
    """Kleiner Balken von -90 bis -30 dBm."""
    if rssi is None:
        return " " * breite
    anteil = max(0.0, min(1.0, (rssi + 90) / 60))
    voll = round(anteil * breite)
    return nach_signal("█" * voll + leise("·") * 0, rssi) + leise("·" * (breite - voll))
