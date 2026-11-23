"""Liest die WLAN-Werte des Macs ueber den kleinen Swift-Helfer aus."""

import json
import subprocess
import tempfile
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "tools" / "wifi_sample.swift"

# macOS vergibt die Ortungsfreigabe nur an Programme mit App-Huelle und
# eigener Kennung. Ein nacktes Kommandozeilenprogramm bekommt sie nie,
# deshalb steckt der Helfer in einem minimalen .app-Buendel.
BUENDEL = WURZEL / "bin" / "WLAN-Messung.app"
HELFER = BUENDEL / "Contents" / "MacOS" / "wifi-sample"
KENNUNG = "de.wifioptimizer.wlanmessung"

INFO_PLIST = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>{KENNUNG}</string>
  <key>CFBundleName</key><string>WLAN-Messung</string>
  <key>CFBundleExecutable</key><string>wifi-sample</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
  <key>NSLocationWhenInUseUsageDescription</key>
  <string>Zum Auslesen des verbundenen WLAN-Zugangspunkts. macOS gibt dessen
  Kennung nur an Programme mit Ortungsfreigabe heraus.</string>
</dict>
</plist>
"""


class WlanFehler(Exception):
    pass


def helfer_bereitstellen():
    """Baut den Helfer samt App-Huelle, falls er fehlt oder veraltet ist."""
    if HELFER.exists() and HELFER.stat().st_mtime >= QUELLE.stat().st_mtime:
        return HELFER

    HELFER.parent.mkdir(parents=True, exist_ok=True)
    ergebnis = subprocess.run(
        ["swiftc", "-O", "-o", str(HELFER), str(QUELLE)],
        capture_output=True,
        text=True,
    )
    if ergebnis.returncode != 0:
        raise WlanFehler(
            "Der WLAN-Helfer liess sich nicht uebersetzen. Sind die Xcode-"
            f"Befehlszeilenwerkzeuge installiert?\n{ergebnis.stderr.strip()}"
        )

    (BUENDEL / "Contents" / "Info.plist").write_text(INFO_PLIST, encoding="utf-8")

    # Ohne gueltige Signatur ueber das ganze Buendel vergibt macOS keine Rechte.
    signiert = subprocess.run(
        ["codesign", "--force", "--sign", "-", str(BUENDEL)],
        capture_output=True,
        text=True,
    )
    if signiert.returncode != 0:
        raise WlanFehler(f"Signieren fehlgeschlagen:\n{signiert.stderr.strip()}")
    return HELFER


# macOS rechnet ein direkt gestartetes Programm dem Terminal zu, nicht dem
# App-Buendel - dann bleiben SSID und BSSID ausgeblendet. Ueber den Finder
# gestartet greift die Freigabe. Das kostet rund 0,2 s mehr pro Abfrage.
_ueber_finder = True
_fehlschlaege = 0
AUFGEBEN_NACH = 5          # erst nach so vielen Fehlversuchen in Folge umschalten


def _probe_direkt():
    ergebnis = subprocess.run(
        [str(helfer_bereitstellen())], capture_output=True, text=True, timeout=15
    )
    if ergebnis.returncode != 0 or not ergebnis.stdout.strip():
        raise WlanFehler(f"WLAN-Abfrage fehlgeschlagen: {ergebnis.stderr.strip()}")
    return json.loads(ergebnis.stdout)


def _probe_ueber_finder(frist_s=3.0):
    helfer_bereitstellen()
    with tempfile.TemporaryDirectory() as ordner:
        ziel = Path(ordner) / "probe.json"
        subprocess.run(
            ["open", "-a", str(BUENDEL), "--args", "--out", str(ziel)],
            capture_output=True,
            timeout=10,
        )
        frist = time.time() + frist_s
        while time.time() < frist:
            if ziel.exists() and ziel.stat().st_size:
                return json.loads(ziel.read_text(encoding="utf-8"))
            time.sleep(0.03)
    return None


def probe():
    """Eine Momentaufnahme der WLAN-Verbindung."""
    global _ueber_finder, _fehlschlaege

    daten = None
    if _ueber_finder:
        try:
            daten = _probe_ueber_finder()
        except (subprocess.SubprocessError, OSError, ValueError):
            daten = None

        if daten is not None and not daten.get("bssid"):
            # Der Weg funktioniert, liefert aber keine Kennung: Es fehlt die
            # Ortungsfreigabe. Weitere Versuche kosten nur Zeit.
            _ueber_finder = False
            daten = None
        elif daten is None:
            # Nur eine Zeitueberschreitung - diesmal den schnellen Weg nehmen,
            # beim naechsten Mal aber wieder den genauen versuchen.
            _fehlschlaege += 1
            if _fehlschlaege >= AUFGEBEN_NACH:
                _ueber_finder = False
        else:
            _fehlschlaege = 0

    if daten is None:
        daten = _probe_direkt()
    if "error" in daten:
        raise WlanFehler(daten["error"])
    return daten


def standortfreigabe_anfordern(wartezeit_s=60):
    """Fordert die Ortungsfreigabe an.

    Der Helfer wird ueber den Finder-Mechanismus gestartet, weil ein aus dem
    Terminal gestarteter Prozess keinen Systemdialog zeigen darf. Die Antwort
    kommt deshalb ueber eine Datei zurueck statt ueber die Standardausgabe.
    """
    helfer_bereitstellen()
    with tempfile.TemporaryDirectory() as ordner:
        ziel = Path(ordner) / "antwort.json"
        subprocess.run(
            ["open", "-a", str(BUENDEL), "--args", "--authorize", "--out", str(ziel)],
            capture_output=True,
            text=True,
            check=False,
        )
        frist = time.time() + wartezeit_s
        while time.time() < frist:
            if ziel.exists() and ziel.stat().st_size:
                return json.loads(ziel.read_text(encoding="utf-8"))
            time.sleep(0.5)
    raise WlanFehler(
        "Keine Antwort auf die Freigabe-Anfrage. Wurde der Dialog weggeklickt?"
    )


# -- Bewertung ---------------------------------------------------------

def rssi_bewertung(rssi):
    if rssi is None:
        return "unbekannt"
    if rssi >= -55:
        return "sehr gut"
    if rssi >= -65:
        return "gut"
    if rssi >= -72:
        return "grenzwertig"
    if rssi >= -80:
        return "schlecht"
    return "unbrauchbar"


def snr_bewertung(snr):
    if snr is None:
        return "unbekannt"
    if snr >= 30:
        return "sehr gut"
    if snr >= 22:
        return "gut"
    if snr >= 15:
        return "grenzwertig"
    return "schlecht"


def ampel(bewertung):
    return {
        "sehr gut": "++",
        "gut": "+ ",
        "grenzwertig": "o ",
        "schlecht": "- ",
        "unbrauchbar": "--",
    }.get(bewertung, "? ")
