"""Beobachtet den Repeater ueber die FRITZ!Box und meldet jede Aenderung.

Faengt genau das, was im Protokoll der FRITZ!Box nicht auftaucht: kurze
Ausfaelle des Repeaters, abreissende Kabelverbindungen, Kanalwechsel.
"""

import time
from datetime import datetime

import fritzbox as fb


def zustand_erheben(box):
    """Momentaufnahme: Zugangspunkte, ihre Funkmodule und alle Kabelgeraete."""
    mesh = box.mesh_liste()
    punkte = fb.zugangspunkte(mesh)

    schnittstellen = {}
    for knoten in mesh.get("nodes", []):
        for s in knoten.get("node_interfaces", []):
            schnittstellen[s["uid"]] = (knoten, s)

    zustand = {"zugangspunkte": {}, "kabel": {}}

    for knoten in mesh.get("nodes", []):
        punkt = punkte.get(knoten["uid"])
        if punkt:
            eintrag = {"erreichbar": bool(knoten.get("is_meshed")), "funk": {}}
            for s in knoten.get("node_interfaces", []):
                name = s.get("name") or ""
                if s.get("type") == "WLAN" and name.startswith("AP:"):
                    eintrag["funk"][name] = {
                        "kanal": s.get("current_channel"),
                        "geraete": sum(1 for l in (s.get("node_links") or [])
                                       if l.get("state") == "CONNECTED"),
                    }
            zustand["zugangspunkte"][punkt["name"]] = eintrag

        # Kabelgeraete: jede LAN-Verbindung, benannt nach dem Geraet am anderen Ende
        for s in knoten.get("node_interfaces", []):
            if s.get("type") != "LAN":
                continue
            for l in (s.get("node_links") or []):
                if l.get("state") != "CONNECTED" or l.get("type") != "LAN":
                    continue
                gegen_uid = (l.get("node_interface_1_uid")
                             if l.get("node_interface_2_uid") == s["uid"]
                             else l.get("node_interface_2_uid"))
                gegen = schnittstellen.get(gegen_uid)
                if not gegen:
                    continue
                gegen_knoten, _ = gegen
                # Immer vom Zugangspunkt aus benennen, damit der Eintrag eindeutig ist
                if punkt:
                    name = gegen_knoten.get("device_name") or "<ohne Namen>"
                    buchse = s.get("name")
                else:
                    continue
                zustand["kabel"][name] = {
                    "mbit": round((l.get("cur_data_rate_rx") or 0) / 1000),
                    "buchse": buchse,
                }
    return zustand


def unterschiede(vorher, nachher):
    """Was hat sich gegenueber der letzten Abfrage geaendert?"""
    meldungen = []

    alt_ap, neu_ap = vorher["zugangspunkte"], nachher["zugangspunkte"]
    for name in set(alt_ap) | set(neu_ap):
        alt, neu = alt_ap.get(name), neu_ap.get(name)
        if alt is None:
            meldungen.append(f"{name}: neu im Mesh aufgetaucht")
            continue
        if neu is None:
            meldungen.append(f"{name}: AUS DEM MESH VERSCHWUNDEN")
            continue
        if alt["erreichbar"] != neu["erreichbar"]:
            meldungen.append(
                f"{name}: {'wieder erreichbar' if neu['erreichbar'] else 'NICHT MEHR ERREICHBAR'}"
            )
        for modul, werte in neu["funk"].items():
            altwerte = alt["funk"].get(modul)
            if altwerte is None:
                meldungen.append(f"{name} {modul}: Funkmodul neu")
                continue
            if altwerte["kanal"] != werte["kanal"]:
                meldungen.append(
                    f"{name} {modul}: KANALWECHSEL {altwerte['kanal']} -> {werte['kanal']}"
                )
            if altwerte["geraete"] != werte["geraete"]:
                meldungen.append(
                    f"{name} {modul}: {altwerte['geraete']} -> {werte['geraete']} Geraete"
                )
        for modul in alt["funk"]:
            if modul not in neu["funk"]:
                meldungen.append(f"{name} {modul}: FUNKMODUL VERSCHWUNDEN")

    alt_kabel, neu_kabel = vorher["kabel"], nachher["kabel"]
    for name in set(alt_kabel) | set(neu_kabel):
        alt, neu = alt_kabel.get(name), neu_kabel.get(name)
        if alt is None:
            meldungen.append(f"Kabel {name}: angesteckt ({neu['mbit']} Mbit an {neu['buchse']})")
        elif neu is None:
            meldungen.append(f"Kabel {name}: VERBINDUNG WEG (war an {alt['buchse']})")
        elif alt["mbit"] != neu["mbit"]:
            meldungen.append(f"Kabel {name}: {alt['mbit']} -> {neu['mbit']} Mbit")
    return meldungen


def bewachen(box, dauer_s, abstand_s=5, melden=print, mitschrift=None):
    """Beobachtet bis zum Ablauf der Zeit und gibt das Protokoll zurueck.

    Jedes Ereignis wird sofort in die Mitschrift geschrieben - ein Abbruch
    mit Strg-C oder ein geschlossenes Fenster kostet dann nichts.
    """
    def festhalten(zeitpunkt, meldung):
        protokoll.append((zeitpunkt, meldung))
        melden(f"  {zeitpunkt}  {meldung}")
        if mitschrift is not None:
            with open(mitschrift, 'a', encoding='utf-8') as datei:
                datei.write(f'- `{zeitpunkt}` {meldung}\n')

    protokoll = []
    vorher = None
    fehler_in_folge = 0
    ende = time.time() + dauer_s

    while time.time() < ende:
        zeitpunkt = datetime.now().strftime("%H:%M:%S")
        try:
            jetzt = zustand_erheben(box)
            if fehler_in_folge:
                festhalten(zeitpunkt, f'FRITZ!Box wieder erreichbar (war {fehler_in_folge} Abfragen lang weg)')
                fehler_in_folge = 0
        except fb.FritzboxFehler:
            fehler_in_folge += 1
            if fehler_in_folge == 1:
                festhalten(zeitpunkt, "FRITZ!Box nicht erreichbar")
            time.sleep(abstand_s)
            continue

        if vorher is not None:
            for meldung in unterschiede(vorher, jetzt):
                festhalten(zeitpunkt, meldung)
        vorher = jetzt
        time.sleep(abstand_s)

    return protokoll


def bericht(protokoll, dauer_s, abstand_s):
    z = [f"# Repeater-Wache", ""]
    z.append(f"Beobachtet: {dauer_s / 60:.0f} Minuten, Abfrage alle {abstand_s} Sekunden.")
    z.append("")
    if not protokoll:
        z.append("**Keine Auffälligkeit.** Weder Ausfall noch Kanalwechsel.")
        return "\n".join(z)
    z.append(f"**{len(protokoll)} Ereignisse:**")
    z.append("")
    for zeitpunkt, meldung in protokoll:
        z.append(f"- `{zeitpunkt}` {meldung}")
    return "\n".join(z)
