"""Prueft eine Netzwerkdose: Reisst die Verbindung ab? Wie schnell handelt sie aus?

Das Tueckische an einer schlechten Hausverkabelung ist, dass sie meistens
funktioniert. Deshalb wird hier dauerhaft gemessen - und zur Kontrolle immer
auch die FRITZ!Box selbst. Bricht nur das Ziel weg, liegt es am Kabel. Brechen
beide weg, lag es am WLAN des messenden Rechners.
"""

import subprocess
import time

import fritzbox as fb
import mitschnitt


def kabelgeraete(mesh):
    """Alle Geraete, die per Kabel an der FRITZ!Box haengen."""
    punkte = fb.zugangspunkte(mesh)
    schnittstellen = {}
    for knoten in mesh.get("nodes", []):
        for s in knoten.get("node_interfaces", []):
            schnittstellen[s["uid"]] = (knoten, s)

    gefunden = []
    for knoten in mesh.get("nodes", []):
        if knoten["uid"] not in punkte:
            continue
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
                adressen = fb.knoten_ips(gegen_knoten)
                gefunden.append({
                    "name": gegen_knoten.get("device_name") or "<ohne Namen>",
                    "ip": adressen[0] if adressen else None,
                    "buchse": s.get("name"),
                    "mbit": round((l.get("cur_data_rate_rx") or 0) / 1000),
                })
    return gefunden


def antwortet(ip, versuche=4):
    """Antwortet das Geraet ueberhaupt auf Ping?

    Windows blockt ICMP standardmaessig. Ohne diese Pruefung wuerde der Test
    eine kerngesunde Strecke als tot melden.
    """
    ergebnis = subprocess.run(
        ["ping", "-c", str(versuche), "-W", "1500", ip],
        capture_output=True, text=True,
    )
    return ergebnis.returncode == 0


def link_zustand(box, name):
    """Geschwindigkeit der Kabelstrecke zu einem Geraet, None wenn weg."""
    for geraet in kabelgeraete(box.mesh_liste()):
        if geraet["name"] == name:
            return geraet["mbit"]
    return None


def messen(box, ziel, router_host, dauer_s, abstand_s=3, melden=print,
           mit_ping=True):
    """Misst Ziel und FRITZ!Box gleichzeitig und beobachtet die Aushandlung."""
    ziel_ping = mitschnitt.Dauerping(ziel["ip"], abstand_s=0.5) if mit_ping else None
    kontrolle = mitschnitt.Dauerping(router_host, abstand_s=0.5)
    if ziel_ping:
        ziel_ping.starten()
    kontrolle.starten()

    verlauf = []
    letzte = ziel["mbit"]
    ende = time.time() + dauer_s
    try:
        while time.time() < ende:
            time.sleep(abstand_s)
            try:
                jetzt = link_zustand(box, ziel["name"])
            except fb.FritzboxFehler:
                continue
            if jetzt != letzte:
                zeitpunkt = time.strftime("%H:%M:%S")
                text = (f"Verbindung WEG" if jetzt is None
                        else f"wieder da mit {jetzt} Mbit" if letzte is None
                        else f"{letzte} -> {jetzt} Mbit")
                verlauf.append((zeitpunkt, text))
                melden(f"  {zeitpunkt}  {text}")
                letzte = jetzt
    except KeyboardInterrupt:
        melden("\n  Abgebrochen.")
    finally:
        if ziel_ping:
            ziel_ping.stoppen()
        kontrolle.stoppen()

    return {
        "ziel": ziel_ping.zusammenfassung() if ziel_ping else None,
        "kontrolle": kontrolle.zusammenfassung(),
        "verlauf": verlauf,
    }


def urteil(ergebnis, ausgehandelt):
    """Was sagen die Zahlen?"""
    z, k = ergebnis["ziel"], ergebnis["kontrolle"]
    saetze = []

    if z is None:
        saetze.append(
            "Das Geraet antwortet nicht auf Ping - vermutlich die Windows-Firewall. "
            "Gemessen wurde deshalb nur, was die FRITZ!Box ueber die Leitung sieht: "
            "Abrisse werden erkannt, aber erst nach einigen Sekunden."
        )

    if ausgehandelt and ausgehandelt < 1000:
        saetze.append(
            f"Die Strecke handelt nur {ausgehandelt} Mbit aus statt 1000. Das deutet "
            "auf beschaedigte Adern im Kabel oder eine schlecht aufgelegte Dose hin - "
            "es sei denn, das Geraet selbst kann nicht mehr."
        )

    if ergebnis["verlauf"]:
        saetze.append(
            f"Die Verbindung hat sich waehrend des Tests {len(ergebnis['verlauf'])} Mal "
            "veraendert oder war weg. Eine gesunde Strecke tut das nie."
        )

    ziel_aus = (z.get("ausfaelle") or []) if z else []
    kontroll_aus = k.get("ausfaelle") or []
    if ziel_aus and not kontroll_aus:
        saetze.append(
            f"{len(ziel_aus)} Ausfall/Ausfaelle am Ziel, aber keiner zur FRITZ!Box. "
            "Das spricht eindeutig fuer die Kabelstrecke."
        )
    elif ziel_aus and kontroll_aus:
        saetze.append(
            f"{len(ziel_aus)} Ausfall/Ausfaelle am Ziel, aber auch {len(kontroll_aus)} "
            "zur FRITZ!Box. Die Aussetzer kommen also vom WLAN dieses Rechners, "
            "nicht vom Kabel."
        )

    if not saetze:
        saetze.append("Keine Auffaelligkeit. Die Strecke war durchgehend stabil.")
    elif not ziel_aus and not ergebnis["verlauf"]:
        saetze.append("Abrisse gab es waehrend des Tests keine - die Strecke war "
                      "durchgehend verbunden.")
    return saetze
