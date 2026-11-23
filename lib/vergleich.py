"""Vergleicht zwei Messungen Punkt fuer Punkt: Was hat sich wie geaendert?"""

import json
import statistics

import farbe
from datetime import datetime
from pathlib import Path


def laden(ordner):
    return json.loads((Path(ordner) / "messung.json").read_text(encoding="utf-8"))


def _schluessel(punkt):
    """Erkennt denselben Messpunkt in beiden Laeufen wieder."""
    if punkt.get("raum"):
        return f"{punkt['raum']}|{punkt.get('wo', '')}"
    return punkt.get("name", "")


def _punkte(lauf):
    """Die Messpunkte eines Laufs, egal in welchem Modus er entstand."""
    if lauf.get("messwerte"):
        return [
            {
                "schluessel": _schluessel(m),
                "raum": m.get("raum"),
                "wo": m.get("wo"),
                "rssi": m.get("rssi"),
                "rssi_min": m.get("rssi_min"),
                "zugangspunkt": m.get("zugangspunkt"),
                "bewertung": m.get("bewertung"),
                "verlust": ((m.get("messung") or {}).get("internet") or {})
                           .get("verlust_prozent"),
            }
            for m in lauf["messwerte"]
        ]
    return [
        {
            "schluessel": _schluessel(p),
            "raum": p.get("name"),
            "wo": "",
            "rssi": p.get("rssi_mittel"),
            "rssi_min": p.get("rssi_min"),
            "zugangspunkt": p.get("zugangspunkt"),
            "bewertung": p.get("bewertung"),
            "verlust": (p.get("internet") or {}).get("verlust_prozent"),
        }
        for p in lauf.get("punkte", [])
    ]


def vergleichen(vorher, nachher):
    """Paart die Punkte beider Laeufe und berechnet die Veraenderung."""
    alt = {p["schluessel"]: p for p in _punkte(vorher)}
    neu = {p["schluessel"]: p for p in _punkte(nachher)}

    paare = []
    for schluessel, n in neu.items():
        a = alt.get(schluessel)
        if not a or a["rssi"] is None or n["rssi"] is None:
            continue
        paare.append({
            "raum": n["raum"],
            "wo": n["wo"],
            "vorher": a["rssi"],
            "nachher": n["rssi"],
            "delta": n["rssi"] - a["rssi"],
            "vorher_min": a.get("rssi_min"),
            "nachher_min": n.get("rssi_min"),
            "ap_vorher": a.get("zugangspunkt"),
            "ap_nachher": n.get("zugangspunkt"),
            "verlust_vorher": a.get("verlust"),
            "verlust_nachher": n.get("verlust"),
        })
    paare.sort(key=lambda p: p["delta"])
    return paare


def zusammenfassung(paare):
    if not paare:
        return {}
    deltas = [p["delta"] for p in paare]
    return {
        "punkte": len(paare),
        "mittel": round(statistics.mean(deltas), 1),
        "besser": sum(1 for d in deltas if d >= 3),
        "gleich": sum(1 for d in deltas if -3 < d < 3),
        "schlechter": sum(1 for d in deltas if d <= -3),
        "groesster_gewinn": max(deltas),
        "groesster_verlust": min(deltas),
        "wechsel": sum(1 for p in paare if p["ap_vorher"] != p["ap_nachher"]),
    }


def _pfeil(delta):
    if delta >= 3:
        return "++" if delta >= 8 else "+ "
    if delta <= -3:
        return "--" if delta <= -8 else "- "
    return "  "


def text(paare, zus, vorher_zeit, nachher_zeit):
    z = []
    z.append(f"  Vorher:  {vorher_zeit}")
    z.append(f"  Nachher: {nachher_zeit}")
    z.append("")
    if not paare:
        z.append("  Keine gemeinsamen Messpunkte gefunden.")
        return "\n".join(z)

    z.append(f"  {'Punkt':<34s} {'vorher':>8s} {'nachher':>8s} {'Delta':>7s}   Zugangspunkt")
    z.append("  " + "-" * 86)
    for p in paare:
        ort = f"{p['raum']} {p['wo']}".strip()[:33]
        wechsel = ""
        if p["ap_vorher"] != p["ap_nachher"]:
            kurz = (p["ap_nachher"] or "?").split(" (")[0]
            wechsel = f"  -> {kurz}"
        delta = f"{p['delta']:>+5d} dB {_pfeil(p['delta'])}"
        if p["delta"] >= 3:
            delta = farbe.gut(delta)
        elif p["delta"] <= -3:
            delta = farbe.schlecht(delta)
        else:
            delta = farbe.leise(delta)
        z.append(
            f"  {ort:<34s} {p['vorher']:>5d} dBm {p['nachher']:>5d} dBm "
            f"{delta}{farbe.leise(wechsel)}"
        )
    z.append("")
    mittel = f"{zus['mittel']:+.1f} dB"
    mittel = (farbe.gut(mittel) if zus["mittel"] >= 3 else
              farbe.schlecht(mittel) if zus["mittel"] <= -3 else farbe.leise(mittel))
    z.append(f"  Im Mittel {mittel} ueber {zus['punkte']} Punkte.")
    z.append(f"  Besser: {zus['besser']}   unveraendert: {zus['gleich']}   "
             f"schlechter: {zus['schlechter']}   (ab 3 dB gezaehlt)")
    z.append(f"  Groesster Gewinn {zus['groesster_gewinn']:+d} dB, "
             f"groesster Verlust {zus['groesster_verlust']:+d} dB.")
    if zus["wechsel"]:
        z.append(f"  An {zus['wechsel']} Punkten haengt das Geraet jetzt an einem "
                 f"anderen Zugangspunkt.")
    return "\n".join(z)


def markdown(paare, zus, vorher_zeit, nachher_zeit):
    z = [f"# Vergleich zweier Messungen", ""]
    z.append(f"- **Vorher:** {vorher_zeit}")
    z.append(f"- **Nachher:** {nachher_zeit}")
    z.append("")
    if not paare:
        z.append("Keine gemeinsamen Messpunkte gefunden.")
        return "\n".join(z)
    z.append(f"Im Mittel **{zus['mittel']:+.1f} dB** über {zus['punkte']} Punkte. "
             f"Besser an {zus['besser']}, schlechter an {zus['schlechter']} Punkten "
             f"(ab 3 dB gezählt).")
    z.append("")
    z.append("| Punkt | vorher | nachher | Veränderung | Zugangspunkt vorher | Zugangspunkt nachher |")
    z.append("|---|---|---|---|---|---|")
    for p in paare:
        ort = f"{p['raum']} {p['wo']}".strip()
        z.append(
            f"| {ort} | {p['vorher']} dBm | {p['nachher']} dBm | "
            f"**{p['delta']:+d} dB** | {p['ap_vorher'] or '?'} | {p['ap_nachher'] or '?'} |"
        )
    return "\n".join(z)


def zeit(lauf):
    roh = lauf.get("gestartet")
    try:
        return datetime.fromisoformat(roh).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return roh or "unbekannt"
