"""Uebersicht aller Geraete im Netz - wer funkt wo, wie schnell, wie sparsam.

Entscheidend fuer ein ruhiges WLAN ist nicht die Datenmenge, sondern die
Sendezeit: Ein langsames Geraet belegt den Funkkanal fuer dieselbe Datenmenge
um ein Vielfaches laenger als ein schnelles.
"""

import fritzbox as fb


def _streams(schnittstelle):
    """Welche Kanalbreiten und wie viele Datenstroeme kann das Geraet?"""
    eintraege = schnittstelle.get("supported_streams_tx") or []
    koennen = {breite: anzahl for breite, anzahl in eintraege if anzahl}
    if not koennen:
        return None, None
    breiteste = max(koennen, key=lambda b: int(b.split()[0]))
    return breiteste, max(koennen.values())


def sammeln(mesh):
    """Alle verbundenen Geraete mit ihrer Anbindung."""
    punkte = fb.zugangspunkte(mesh)
    schnittstellen = {}
    for knoten in mesh.get("nodes", []):
        for s in knoten.get("node_interfaces", []):
            schnittstellen[s["uid"]] = (knoten, s)

    geraete = []
    for knoten in mesh.get("nodes", []):
        punkt = punkte.get(knoten["uid"])
        if punkt:                      # FRITZ!Box und Repeater selbst ueberspringen
            continue
        name = knoten.get("device_name") or knoten.get("device_friendly_name") or "<ohne Namen>"
        for s in knoten.get("node_interfaces", []):
            for l in (s.get("node_links") or []):
                if l.get("state") != "CONNECTED":
                    continue
                gegen_uid = (l.get("node_interface_1_uid")
                             if l.get("node_interface_2_uid") == s["uid"]
                             else l.get("node_interface_2_uid"))
                gegen = schnittstellen.get(gegen_uid)
                ap_name = ap_modul = None
                if gegen:
                    ap_knoten, ap_s = gegen
                    ap_name = ap_knoten.get("device_name")
                    ap_modul = ap_s.get("name")

                breite, stroeme = _streams(s)
                geraete.append({
                    "name": name,
                    "hersteller": knoten.get("device_manufacturer") or "",
                    "art": s.get("type"),
                    "band": ("2,4 GHz" if ap_modul and ":2G:" in ap_modul
                             else "5 GHz" if ap_modul and ":5G:" in ap_modul else None),
                    "zugangspunkt": ap_name,
                    "modul": ap_modul,
                    "kanal": s.get("current_channel"),
                    "signal": l.get("rx_rcpi") if l.get("rx_rcpi") != 255 else None,
                    "rate_mbit": round((l.get("cur_data_rate_rx") or 0) / 1000) or None,
                    "max_mbit": round((l.get("max_data_rate_rx") or 0) / 1000) or None,
                    "breite": breite,
                    "stroeme": stroeme,
                })
    return geraete


# -- Bewertung ---------------------------------------------------------


def ratschlaege(geraete):
    """Konkrete Vorschlaege, sortiert nach Wirkung."""
    vorschlaege = []

    # 1. Dauerlaeufer, die auch am Kabel haengen koennten
    kabelkandidaten = [g for g in geraete if g["art"] == "WLAN" and _ortsfest(g["name"])]
    if kabelkandidaten:
        vorschlaege.append({
            "titel": "Diese Geraete stehen fest und koennten ans Kabel",
            "geraete": [g["name"] for g in kabelkandidaten],
            "warum": ("Jedes Geraet am Kabel ist eines weniger, das sich Sendezeit "
                      "mit deinem Laptop teilt. Bei Geraeten, die ohnehin nie "
                      "bewegt werden, kostet das nichts ausser einem Kabel."),
        })

    # 2. Langsame Geraete auf 5 GHz - dort bremsen sie am meisten
    langsam_5 = [
        g for g in geraete
        if g["band"] == "5 GHz" and g["rate_mbit"] and g["rate_mbit"] < 150
    ]
    if langsam_5:
        vorschlaege.append({
            "titel": "Langsame Geraete auf dem 5-GHz-Band",
            "geraete": [f"{g['name']} ({g['rate_mbit']} Mbit)" for g in langsam_5],
            "warum": ("Sie belegen den Kanal lange fuer wenig Daten. Auf 2,4 GHz "
                      "stoeren sie niemanden, der Videoanrufe macht."),
        })

    # 3. Geraete, die nur schmale Kanaele koennen
    schmal = [
        g for g in geraete
        if g["band"] == "5 GHz" and g["breite"] in ("20 MHz", "40 MHz")
    ]
    if schmal:
        vorschlaege.append({
            "titel": "Geraete, die 5 GHz gar nicht ausnutzen",
            "geraete": [f"{g['name']} (max {g['breite']}, {g['stroeme']} Strom)"
                        for g in schmal],
            "warum": ("Diese Geraete koennen nur schmale Kanaele. Auf 5 GHz "
                      "gewinnen sie dadurch fast nichts, kosten aber Sendezeit."),
        })

    # 4. Schwach angebundene Geraete
    schwach = [g for g in geraete if g["signal"] is not None and g["signal"] <= -75]
    if schwach:
        vorschlaege.append({
            "titel": "Schwach angebundene Geraete",
            "geraete": [f"{g['name']} ({g['signal']} dBm)" for g in schwach],
            "warum": ("Je schwaecher die Verbindung, desto langsamer die "
                      "Uebertragung und desto mehr Sendezeit geht drauf - auch "
                      "fuer alle anderen am selben Funkmodul."),
        })
    return vorschlaege


# Geraete, die sich bewegen - sie auf dem Grundriss einzuzeichnen ergibt
# keinen Sinn, weil ihr Messwert nichts ueber den Ort aussagt.
BEWEGLICH = ("iphone", "ipad", "watch", "macbook", "airpods", "pixel", "galaxy",
             "handy", "phone", "laptop", "nintendo", "switch", "kindle", "tablet")


def beweglich(name):
    kleines = (name or "").lower()
    return any(wort in kleines for wort in BEWEGLICH)


ORTSFEST = ("sonos", "appletv", "apple-tv", "fernseher", "tv", "drucker",
            "printer", "dishwasher", "spuelmaschine", "waschmaschine",
            "homepod", "nas", "receiver", "konsole", "playstation", "xbox")


def _ortsfest(name):
    kleines = (name or "").lower()
    return any(wort in kleines for wort in ORTSFEST)
