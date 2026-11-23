"""Misst, was fuer Videoanrufe wirklich zaehlt: Laufzeit, Schwankung, Verlust."""

import re
import statistics
import subprocess
from concurrent.futures import ThreadPoolExecutor

# Richtwerte von Microsoft fuer Teams (Hin- und Rueckweg).
GRENZEN = {
    "laufzeit_ms": (100, 150),   # gut bis, noch brauchbar bis
    "schwankung_ms": (20, 30),   # macOS laesst das WLAN im Leerlauf schlafen,
                                 # das erzeugt harmlose Ausschlaege
    "verlust_prozent": (0.5, 1.0),
}

ZEIT_MUSTER = re.compile(r"time[=<]([\d.]+)\s*ms")
VERLUST_MUSTER = re.compile(r"([\d.]+)% packet loss")


def _ping(ziel, dauer_s, abstand_s=0.2):
    anzahl = max(5, int(dauer_s / abstand_s))
    ergebnis = subprocess.run(
        ["ping", "-c", str(anzahl), "-i", str(abstand_s), "-W", "1000", ziel],
        capture_output=True,
        text=True,
        timeout=dauer_s + 20,
    )
    ausgabe = ergebnis.stdout
    zeiten = [float(t) for t in ZEIT_MUSTER.findall(ausgabe)]
    verlust_treffer = VERLUST_MUSTER.search(ausgabe)
    verlust = float(verlust_treffer.group(1)) if verlust_treffer else 100.0

    if not zeiten:
        return {
            "ziel": ziel,
            "erreichbar": False,
            "verlust_prozent": 100.0,
            "pakete": anzahl,
        }

    # Schwankung als mittlere Aenderung zwischen aufeinanderfolgenden Paketen.
    abweichungen = [abs(b - a) for a, b in zip(zeiten, zeiten[1:])]
    return {
        "ziel": ziel,
        "erreichbar": True,
        "pakete": anzahl,
        "antworten": len(zeiten),
        "verlust_prozent": round(verlust, 2),
        "laufzeit_ms": round(statistics.mean(zeiten), 1),
        "laufzeit_max_ms": round(max(zeiten), 1),
        "schwankung_ms": round(statistics.mean(abweichungen), 1) if abweichungen else 0.0,
        # Ausreisser zaehlen: Pakete, die mehr als 150 ms brauchten
        "ausreisser": sum(1 for t in zeiten if t > 150),
    }


def messen(router_host="fritz.box", internet_host="1.1.1.1", dauer_s=15):
    """Misst Router- und Internetstrecke gleichzeitig."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        router = pool.submit(_ping, router_host, dauer_s)
        internet = pool.submit(_ping, internet_host, dauer_s)
        return {"funkstrecke": router.result(), "internet": internet.result()}


def bewerten(messwert):
    """'gut' / 'brauchbar' / 'kritisch' anhand der Teams-Richtwerte."""
    if not messwert.get("erreichbar"):
        return "kritisch"
    stufen = []
    for feld, (gut, grenze) in GRENZEN.items():
        wert = messwert.get(feld)
        if wert is None:
            continue
        stufen.append(0 if wert <= gut else 1 if wert <= grenze else 2)
    return ["gut", "brauchbar", "kritisch"][max(stufen)] if stufen else "unbekannt"


def begruendung(messwert):
    """Welche Kennzahl den Ausschlag gibt."""
    if not messwert.get("erreichbar"):
        return "keine Antwort"
    gruende = []
    for feld, (gut, grenze) in GRENZEN.items():
        wert = messwert.get(feld)
        if wert is None or wert <= gut:
            continue
        name = {
            "laufzeit_ms": "Laufzeit",
            "schwankung_ms": "Schwankung",
            "verlust_prozent": "Paketverlust",
        }[feld]
        einheit = "%" if feld == "verlust_prozent" else " ms"
        gruende.append(f"{name} {wert}{einheit}" + ("" if wert <= grenze else " (zu hoch)"))
    return ", ".join(gruende) if gruende else "alle Werte im gruenen Bereich"
