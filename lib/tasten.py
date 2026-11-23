"""Einzelne Tastendruecke lesen, ohne auf die Eingabetaste zu warten."""

import select
import sys
import termios
import tty
from contextlib import contextmanager


def interaktiv():
    return sys.stdin.isatty() and sys.stdout.isatty()


@contextmanager
def sofortmodus():
    """Schaltet das Terminal um, sodass Tasten direkt ankommen."""
    if not interaktiv():
        yield
        return
    dateinummer = sys.stdin.fileno()
    vorher = termios.tcgetattr(dateinummer)
    try:
        tty.setcbreak(dateinummer)
        yield
    finally:
        termios.tcsetattr(dateinummer, termios.TCSADRAIN, vorher)


def taste(wartezeit_s=0.0):
    """Gibt das gedrueckte Zeichen zurueck oder None."""
    if not interaktiv():
        return None
    bereit, _, _ = select.select([sys.stdin], [], [], wartezeit_s)
    return sys.stdin.read(1) if bereit else None
