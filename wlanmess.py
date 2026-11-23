#!/usr/bin/env python3
"""WLAN-Messung fuer die Wohnung: Funkloecher finden, Repeater richtig stellen.

Aufruf:  python3 wlanmess.py
"""

import socket
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import bericht
import fritzbox as fb
import editor
import farbe
import galerie
import geraete as geraete_modul
import heatmap
import kabeltest as kabeltest_modul
import mitschnitt
import qualitaet
import tasten
import umhaengen as umhaengen_modul
import vergleich
import wache
import wlan

WURZEL = Path(__file__).resolve().parent
ERGEBNISSE = WURZEL / "messungen"

TRENNER = "─" * 72


# -- Darstellung -------------------------------------------------------


def kopf(text):
    print(f"\n{TRENNER}\n  {text}\n{TRENNER}")


def zeile(beschriftung, wert, breite=24):
    print(f"  {beschriftung:<{breite}} {wert}")


def eigene_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.168.178.1", 80))
        return s.getsockname()[0]


# -- Fritzbox-Diagnose -------------------------------------------------


def diagnose_erheben(stumm=False):
    """Alles, was die FRITZ!Box ueber sich und das Funknetz verraet."""
    umgebung = fb.lade_env(WURZEL / ".env")
    host = umgebung.get("FRITZBOX_HOST", "fritz.box")
    benutzer = umgebung.get("FRITZBOX_USER")
    passwort = umgebung.get("FRITZBOX_PASSWORT")

    ergebnis = {"host": host, "erreichbar": False}
    if not (benutzer and passwort):
        ergebnis["fehler"] = "In .env fehlen FRITZBOX_USER oder FRITZBOX_PASSWORT."
        return ergebnis

    try:
        box = fb.Fritzbox(host, benutzer, passwort)
        info = box.geraeteinfo()
        ergebnis.update(
            erreichbar=True,
            modell=info.get("ModelName"),
            firmware=info.get("SoftwareVersion"),
            laufzeit_tage=round(int(info.get("UpTime") or 0) / 86400, 1),
            baender=box.wlan_uebersicht(),
        )
        mesh = box.mesh_liste()
        ergebnis["zugangspunkte"] = list(fb.zugangspunkte(mesh).values())
        ergebnis["kanal_karte"] = fb.kanal_karte(mesh)
        ergebnis["bssid_karte"] = fb.bssid_karte(mesh)
        ergebnis["steering_aktiv"] = fb.steering_aktiv(mesh)
        ergebnis["dfs_module"] = fb.dfs_funkmodule(mesh)
        ergebnis["_box"] = box
    except fb.FritzboxFehler as fehler:
        ergebnis["fehler"] = str(fehler)
        return ergebnis

    try:
        web = fb.FritzboxWeb(host, benutzer, passwort)
        ergebnis["wlan_ereignisse"] = web.wlan_protokoll()
        kanal = web.funkkanal().get("data", {})
        ergebnis["kanaleinstellung"] = {
            "modus": kanal.get("channelSelectMode"),
            "ht160_moeglich": bool((kanal.get("ht160") or {}).get("support")),
        }
        ergebnis["_web"] = web
    except fb.FritzboxFehler as fehler:
        if not stumm:
            print(f"  Hinweis: Weboberflaeche nicht lesbar ({fehler})")
    return ergebnis


def diagnose_zeigen(d):
    kopf("FRITZ!Box")
    if not d.get("erreichbar"):
        print(f"  Nicht erreichbar: {d.get('fehler')}")
        return
    zeile("Modell", f"{d['modell']} (FRITZ!OS {d['firmware']})")
    zeile("Laufzeit", f"{d['laufzeit_tage']} Tage")
    for band, werte in (d.get("baender") or {}).items():
        zeile(f"WLAN {band}", f"Kanal {werte['kanal']}, {werte['standard']}, SSID {werte['ssid']!r}")
    for punkt in d.get("zugangspunkte") or []:
        rolle = "Basis" if punkt["rolle"] == "master" else "Repeater"
        zeile(rolle, f"{punkt['name']} ({punkt['modell']})")
    einst = d.get("kanaleinstellung") or {}
    if einst:
        zeile("Kanalwahl", einst.get("modus"))
    if d.get("steering_aktiv") is not None:
        zeile("Steuerung", "an" if d["steering_aktiv"] else "aus")
    for modul in d.get("dfs_module") or []:
        zeile(farbe.schlecht("Radarkanal!"),
              f"{modul['zugangspunkt']} {modul['modul']} auf Kanal "
              f"{farbe.schlecht(modul['kanal'])}, {modul['geraete']} Geraete")


def zugangspunkt_bestimmen(diagnose, probe):
    """Welcher Zugangspunkt? Erst ueber die Funkkennung, sonst ueber den Kanal.

    Die Kennung ist zuverlaessiger - sie bleibt gleich, auch wenn wegen
    Radarerkennung der Kanal gewechselt wird.
    """
    kennung = (probe.get("bssid") or "").lower()
    ueber_bssid = (diagnose.get("bssid_karte") or {}).get(kennung)
    if ueber_bssid:
        return ueber_bssid
    return (diagnose.get("kanal_karte") or {}).get(probe.get("kanal"))


def mesh_verbindung(diagnose, ip):
    box = diagnose.get("_box")
    if not box:
        return None
    try:
        return fb.meine_verbindung(box.mesh_liste(), ip)
    except fb.FritzboxFehler:
        return None


# -- Modus 1: Punktmessung ---------------------------------------------


def punkt_messen(name, diagnose, ip, dauer_s=15):
    """Misst an einem Ort: Funkwerte im Mittel plus Verbindungsqualitaet."""
    proben = []
    stoppen = threading.Event()

    def sammeln():
        while not stoppen.is_set():
            try:
                proben.append(wlan.probe())
            except wlan.WlanFehler:
                pass
            stoppen.wait(1.0)

    faden = threading.Thread(target=sammeln, daemon=True)
    faden.start()
    print(f"  Messe {dauer_s} Sekunden - bitte stehen bleiben ...", end="", flush=True)
    ergebnis = qualitaet.messen(dauer_s=dauer_s)
    stoppen.set()
    faden.join(timeout=3)
    print(" fertig.")

    gueltig = [p for p in proben if p.get("rssi") is not None]
    rssi = [p["rssi"] for p in gueltig]
    snr = [p["snr"] for p in gueltig]
    letzte = gueltig[-1] if gueltig else {}

    punkt = {
        "name": name,
        "zeit": datetime.now().isoformat(timespec="seconds"),
        "proben": len(gueltig),
        "rssi_mittel": round(statistics.mean(rssi)) if rssi else None,
        "rssi_min": min(rssi) if rssi else None,
        "rssi_max": max(rssi) if rssi else None,
        "snr_mittel": round(statistics.mean(snr)) if snr else None,
        "band": letzte.get("band"),
        "kanal": letzte.get("kanal"),
        "breite": letzte.get("breite"),
        "phy": letzte.get("phy"),
        "tx_rate_mbit": letzte.get("tx_rate_mbit"),
        "bssid": letzte.get("bssid"),
        "zugangspunkt": zugangspunkt_bestimmen(diagnose, letzte) if letzte else None,
        "funkstrecke": ergebnis["funkstrecke"],
        "internet": ergebnis["internet"],
        "fritzbox": mesh_verbindung(diagnose, ip),
    }

    urteile = [qualitaet.bewerten(ergebnis["funkstrecke"]),
               qualitaet.bewerten(ergebnis["internet"])]
    if "kritisch" in urteile:
        punkt["bewertung"] = "kritisch"
    elif "brauchbar" in urteile:
        punkt["bewertung"] = "brauchbar"
    else:
        punkt["bewertung"] = "gut"
    if (punkt["rssi_mittel"] or 0) <= -75 and punkt["bewertung"] == "gut":
        punkt["bewertung"] = "brauchbar"
    return punkt


def punkt_zeigen(p):
    print()
    bewertung = wlan.rssi_bewertung(p["rssi_mittel"])
    zeile("Signal", f"{farbe.balken(p['rssi_mittel'])}  "
                    f"{farbe.nach_signal(str(p['rssi_mittel']) + ' dBm', p['rssi_mittel'])}"
                    f"  ({farbe.nach_bewertung(bewertung, bewertung)}, "
                    f"Schwankung {p['rssi_min']} bis {p['rssi_max']})")
    snr_wert = wlan.snr_bewertung(p["snr_mittel"])
    zeile("Stoerabstand", f"{p['snr_mittel']} dB  "
                          f"({farbe.nach_bewertung(snr_wert, snr_wert)})")
    zeile("Verbindung", f"{p['band']}, Kanal {p['kanal']}, {p['breite']}, "
                        f"{p['tx_rate_mbit']} Mbit/s")
    ap = p.get("zugangspunkt") or (p.get("fritzbox") or {}).get("zugangspunkt")
    if ap:
        zeile("Haengt an", ap)
    for feld, bezeichnung in (("funkstrecke", "Bis zur FRITZ!Box"), ("internet", "Bis ins Internet")):
        m = p[feld]
        urteil = qualitaet.bewerten(m)
        zeile(bezeichnung, f"{farbe.nach_bewertung(f'{urteil:<10s}', urteil)} "
                           f"{qualitaet.begruendung(m)}")
    print(f"\n  >>> Urteil fuer Videoanrufe: "
          f"{farbe.nach_bewertung(p['bewertung'].upper(), p['bewertung'])}")


def modus_punktmessung(diagnose, ip):
    kopf("Punktmessung")
    print("  Geh zu einem Ort, bleib stehen, gib den Namen ein.")
    print("  Leere Eingabe beendet die Messung.\n")
    punkte = []
    while True:
        try:
            name = input("  Ort (leer = fertig): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not name:
            break
        punkt = punkt_messen(name, diagnose, ip)
        punkte.append(punkt)
        punkt_zeigen(punkt)
        print()
    return punkte


# -- Modus 2: Durchlauf ------------------------------------------------


def orte_erfragen():
    """Die Orte, die unterwegs per Zifferntaste markiert werden."""
    print("  Welche Orte willst du unterwegs markieren?")
    print("  Namen mit Komma trennen, z.B.: Kueche, Arbeitszimmer, Mein Zimmer, Flur")
    eingabe = input("  Orte: ").strip()
    orte = [o.strip() for o in eingabe.split(",") if o.strip()]
    return orte[:9]


def modus_durchlauf(diagnose, ip):
    kopf("Durchlauf")
    orte = orte_erfragen()
    if not orte:
        print("  Keine Orte angegeben - der Durchlauf wird ohne Marken aufgezeichnet.")

    hoechstdauer = None
    if tasten.interaktiv():
        eingabe = input("  Hoechstdauer in Minuten (Enter = ohne Begrenzung): ").strip()
        if eingabe.replace(".", "", 1).isdigit():
            hoechstdauer = float(eingabe) * 60
    else:
        hoechstdauer = 30  # ohne Tastatur gibt es keinen Abbruch per Taste

    print()
    for nummer, ort in enumerate(orte, 1):
        print(f"    [{nummer}]  {ort}")
    print("    [q]  beenden\n")
    print("  Lauf los. Beim Betreten eines Raums die passende Ziffer druecken -")
    print("  keine Eingabetaste noetig. Die Anzeige laeuft derweil weiter.\n")
    if not tasten.interaktiv():
        print(f"  (Keine Tastatur erkannt - laeuft {hoechstdauer:.0f} s ohne Marken.)\n")

    proben = []
    marken = []
    start = time.time()

    ping = mitschnitt.Dauerping(diagnose.get("host", "fritz.box"))
    ping.starten()

    letzte_kennung = None
    letzte_probe = 0.0
    beendet = False
    tiefstwert = None   # schlechtestes Signal im aktuellen Raum

    try:
        with tasten.sofortmodus():
            while not beendet:
                if hoechstdauer and time.time() - start >= hoechstdauer:
                    print("\r\033[K  Hoechstdauer erreicht.")
                    break
                zeichen = tasten.taste(wartezeit_s=0.1)
                if zeichen:
                    if zeichen in ("q", "Q", "\x03"):
                        beendet = True
                    elif zeichen.isdigit() and 1 <= int(zeichen) <= len(orte):
                        ort = orte[int(zeichen) - 1]
                        sekunde = round(time.time() - start, 1)
                        marken.append({"sekunde": sekunde, "name": ort})
                        tiefstwert = None
                        print(f"\r\033[K  >> {sekunde:.0f}s  Marke: {ort}")

                if time.time() - letzte_probe < 1.0:
                    continue
                letzte_probe = time.time()

                try:
                    p = wlan.probe()
                except wlan.WlanFehler:
                    continue
                p["sekunde"] = round(time.time() - start, 1)
                proben.append(p)

                p["zugangspunkt"] = zugangspunkt_bestimmen(diagnose, p)
                kennung = p.get("bssid") or f"{p.get('band')}/{p.get('kanal')}"
                if letzte_kennung and kennung != letzte_kennung:
                    wohin = p["zugangspunkt"] or f"Kanal {p.get('kanal')}"
                    print(f"\r\033[K  >> {p['sekunde']:.0f}s  gewechselt zu {wohin} "
                          f"bei {p['rssi']} dBm")
                letzte_kennung = kennung

                aktueller_ort = marken[-1]["name"] if marken else "unterwegs"
                tiefstwert = p["rssi"] if tiefstwert is None else min(tiefstwert, p["rssi"])
                signal_text = f"{p['rssi']:4d} dBm SNR {p['snr']:3d}"
                print(
                    f"\r\033[K  {p['sekunde']:5.0f}s  "
                    f"{farbe.balken(p['rssi'], 10)} "
                    f"{farbe.nach_signal(signal_text, p['rssi'])}  "
                    f"{p['band']:>6s} K{p['kanal']:<4d} {p['tx_rate_mbit']:5d} Mbit  "
                    f"{farbe.leise('tiefster hier:')} "
                    f"{farbe.nach_signal(f'{tiefstwert} dBm', tiefstwert)}  "
                    f"{farbe.leise('|')} {aktueller_ort}",
                    end="", flush=True,
                )
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        ping.stoppen()

    print("\n")
    return proben, marken, ping.zusammenfassung()


def _haeufigster_ap(proben):
    """Der Zugangspunkt, an dem das Geraet im Abschnitt am laengsten hing."""
    zaehler = {}
    for p in proben:
        name = p.get("zugangspunkt")
        if name:
            zaehler[name] = zaehler.get(name, 0) + 1
    return max(zaehler, key=zaehler.get) if zaehler else None


def durchlauf_auswerten(proben, marken, ping_ergebnis):
    """Macht aus dem Verlauf Messpunkte je Marke plus die Abrisse.

    Eine Marke wird beim *Betreten* eines Raums gesetzt, der Abschnitt reicht
    also von dieser Marke bis zur naechsten.
    """
    if not proben:
        return [], {}

    abschnitte = []
    for i, marke in enumerate(marken):
        bis = marken[i + 1]["sekunde"] if i + 1 < len(marken) else float("inf")
        abschnitte.append((marke["name"], marke["sekunde"], bis))

    punkte = []
    for name, von, bis in abschnitte:
        teil = [p for p in proben if von <= p["sekunde"] < bis]
        if not teil:
            continue
        rssi = [p["rssi"] for p in teil]
        snr = [p["snr"] for p in teil]
        mittel = statistics.mean(rssi)
        punkte.append({
            "name": name,
            "proben": len(teil),
            "von_sekunde": von,
            "rssi_mittel": round(mittel),
            "rssi_min": min(rssi),
            "rssi_max": max(rssi),
            "snr_mittel": round(statistics.mean(snr)),
            "band": teil[-1].get("band"),
            "kanal": teil[-1].get("kanal"),
            "zugangspunkt": _haeufigster_ap(teil),
            "bewertung": ("kritisch" if min(rssi) <= -78
                          else "brauchbar" if mittel <= -70
                          else "gut"),
        })

    for ausfall in ping_ergebnis.get("ausfaelle", []):
        zeitpunkt = ausfall["ab_sekunde"]
        passend = [a for a in abschnitte if a[1] <= zeitpunkt < a[2]]
        ausfall["marke"] = passend[0][0] if passend else "unterwegs"

    schwaechste = min(proben, key=lambda p: p["rssi"])
    verlauf = dict(ping_ergebnis)
    verlauf["schwaechste_stelle"] = {
        "sekunde": schwaechste["sekunde"],
        "rssi": schwaechste["rssi"],
        "band": schwaechste.get("band"),
        "kanal": schwaechste.get("kanal"),
    }
    return punkte, verlauf


# -- Modus 4: Gefuehrter Rundgang fuer die Heatmap ---------------------


def karte_schreiben(messwerte, plan, titel, ziel, aktualisieren=0):
    return heatmap.zeichnen(messwerte, plan, titel, ziel, aktualisieren)


def modus_heatmap(diagnose, ip, dauer_s=10):
    kopf("Gefuehrter Rundgang")
    try:
        notiz = input("  Kurze Notiz zu diesem Lauf (z.B. 'ohne Repeater'): ").strip()
    except (EOFError, KeyboardInterrupt):
        notiz = ""
    plan = heatmap.plan_laden()
    punkte = plan["punkte"]

    vorschau = WURZEL / "grundriss" / "messpunkte.html"
    karte_schreiben(punkte, plan, "Messpunkte", vorschau, aktualisieren=5)
    print(f"  Die Karte laeuft mit und laedt sich alle 5 Sekunden selbst neu:")
    print(f"    {vorschau}\n")
    print(f"  {len(punkte)} Punkte, je {dauer_s} Sekunden. Ich sage dir, wohin.")
    print("  Eingabetaste = messen,  s = ueberspringen,  q = abbrechen\n")

    messwerte = []
    for i, punkt in enumerate(punkte, 1):
        ort = f"{punkt['raum']}" + (f", {punkt['wo']}" if punkt["wo"] else "")
        print(f"{TRENNER}")
        print(f"  Punkt {i} von {len(punkte)}:  {ort}")
        try:
            eingabe = input("  Dort angekommen? [Enter/s/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if eingabe == "q":
            break
        if eingabe == "s":
            print("  uebersprungen.\n")
            continue

        ergebnis = punkt_messen(ort, diagnose, ip, dauer_s=dauer_s)
        eintrag = dict(punkt)
        eintrag.update({
            "rssi": ergebnis["rssi_mittel"],
            "rssi_min": ergebnis["rssi_min"],
            "snr": ergebnis["snr_mittel"],
            "band": ergebnis["band"],
            "kanal": ergebnis["kanal"],
            "zugangspunkt": ergebnis.get("zugangspunkt"),
            "bewertung": ergebnis["bewertung"],
            "messung": ergebnis,
        })
        messwerte.append(eintrag)

        zeile("Signal", f"{eintrag['rssi']} dBm ({wlan.rssi_bewertung(eintrag['rssi'])}), "
                        f"schwaechster Wert {eintrag['rssi_min']} dBm")
        zeile("Haengt an", eintrag["zugangspunkt"] or f"Kanal {eintrag['kanal']}")
        zeile("Urteil", eintrag["bewertung"].upper())
        print()

        # Zwischenstand sofort sichtbar machen: Gemessenes plus noch Offenes
        erledigt = {m["nr"] for m in messwerte}
        offen = [q for q in punkte if q["nr"] not in erledigt]
        karte_schreiben(messwerte + offen, plan, "WLAN-Heatmap (laeuft)",
                        vorschau, aktualisieren=5)

    # Die fest eingezeichneten Geraete liefern gratis weitere Stuetzpunkte.
    if plan.get("geraete_positionen") and messwerte:
        print(f"{TRENNER}")
        try:
            antwort = input("  Feste Geraete mitrechnen? [J/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            antwort = ""
        if not antwort.startswith("n"):
            zusatz, fehlend = geraete_messwerte(plan, start_nr=len(messwerte) + 1)
            messwerte.extend(zusatz)
            zeile("Dazugenommen", f"{len(zusatz)} feste Geraete", breite=20)
            if fehlend:
                zeile("Nicht verbunden", ", ".join(fehlend)[:70], breite=20)
            print("\n  Sie erscheinen als Quadrat statt Kreis. Ihre Werte sind mit")
            print("  deinen Messpunkten nur grob vergleichbar - andere Antennen,")
            print("  andere Sendeleistung.")

    return messwerte, plan, notiz


# -- Ablauf ------------------------------------------------------------


def wlan_pruefen():
    """Liest den aktuellen WLAN-Zustand. Ohne Rueckfragen."""
    try:
        return wlan.probe()
    except wlan.WlanFehler as fehler:
        print(f"  WLAN nicht lesbar: {fehler}")
        return None


def zuordnung_pruefen(diagnose, probe):
    """Warnt nur, wenn der Zugangspunkt sich nicht ueber den Kanal bestimmen laesst."""
    karte = diagnose.get("kanal_karte") or {}
    if not karte:
        print("\n  Hinweis: Ohne FRITZ!Box-Zugang laesst sich nicht erkennen, an")
        print("  welchem Zugangspunkt du haengst - nur Signalstaerke und Kanal.")
        return
    # Ueber die Funkkennung ist die Zuordnung eindeutig - dann ist alles gut.
    if probe and zugangspunkt_bestimmen(diagnose, probe):
        return
    kanal = probe.get("kanal") if probe else None
    if kanal:
        print(f"\n  Hinweis: Kanal {kanal} laesst sich keinem Geraet eindeutig")
        print("  zuordnen. Die Spalte 'Zugangspunkt' bleibt dort leer.")


def hauptmenue():
    kopf("Was soll gemessen werden?")
    print("  1  Punktmessung  - an festen Orten stehen bleiben (genau)")
    print("  2  Durchlauf     - durch die Wohnung laufen (findet Abrisse)")
    print("  3  Nur Diagnose  - FRITZ!Box auslesen, nicht messen")
    print("  4  Heatmap       - gefuehrt Punkt fuer Punkt, ergibt eine Karte")
    print("  5  Schnellblick  - grobe Karte aus den festen Geraeten, ohne Laufen")
    print()
    while True:
        wahl = input("  Auswahl [1/2/3/4/5]: ").strip()
        if wahl in ("1", "2", "3", "4", "5"):
            return wahl


def leitung_zeigen(minuten=10.0):
    """Misst die eigene Leitung zur FRITZ!Box - egal ob per Kabel oder Funk.

    Gedacht fuer den Fall, dass dieser Rechner selbst an der fraglichen Dose
    haengt. Dann ist der Weg kurz und jeder Ausfall gehoert der Strecke.
    """
    umgebung = fb.lade_env(WURZEL / ".env")
    host = umgebung.get("FRITZBOX_HOST", "fritz.box")

    anbindung = "Kabel" if _per_kabel() else "WLAN"
    kopf(f"Leitungstest ueber {anbindung}")
    zeile("Ziel", host)
    zeile("Dauer", f"{minuten:.0f} Minuten")
    print("\n  Laeuft. Strg-C beendet frueher.\n")

    ping = mitschnitt.Dauerping(host, abstand_s=0.5)
    ping.starten()
    try:
        ende = time.time() + minuten * 60
        while time.time() < ende:
            time.sleep(2)
            stand = ping.zusammenfassung()
            print(f"\r\033[K  {stand.get('empfangen', 0):5d} Pakete, "
                  f"{stand.get('verlust_prozent', 0)} % Verlust, "
                  f"{len(stand.get('ausfaelle') or [])} Ausfaelle", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        ping.stoppen()

    stand = ping.zusammenfassung()
    print("\n")
    kopf("Ergebnis")
    zeile("Anbindung", anbindung)
    zeile("Pakete", f"{stand.get('empfangen')} von {stand.get('pakete')}")
    zeile("Verlust", f"{stand.get('verlust_prozent')} %")
    zeile("Laufzeit", f"Mittel {stand.get('laufzeit_mittel_ms')} ms, "
                      f"max {stand.get('laufzeit_max_ms')} ms")
    ausfaelle = stand.get("ausfaelle") or []
    zeile("Ausfaelle", len(ausfaelle) or "keine")
    for a in ausfaelle:
        print(f"      nach {a['ab_sekunde']:.0f} s fuer {a['dauer_s']} s")
    if ausfaelle and anbindung == "Kabel":
        print("\n  Ausfaelle ueber Kabel sind immer ein Befund - da gibt es keine")
        print("  Funkstoerung, auf die man sie schieben koennte.")
    return 0


def _per_kabel():
    """Haengt dieser Rechner gerade am Kabel?"""
    ergebnis = subprocess.run(["route", "-n", "get", "default"],
                              capture_output=True, text=True)
    for zeile_ in ergebnis.stdout.splitlines():
        if "interface:" in zeile_:
            return not zeile_.split(":")[1].strip().startswith("en0")
    return False


def kabeltest_zeigen(name=None, minuten=10.0):
    """Prueft eine Kabelstrecke auf Abrisse und zu langsame Aushandlung."""
    umgebung = fb.lade_env(WURZEL / ".env")
    host = umgebung.get("FRITZBOX_HOST", "fritz.box")
    try:
        box = fb.Fritzbox(host, umgebung.get("FRITZBOX_USER"),
                          umgebung.get("FRITZBOX_PASSWORT"))
        geraete = kabeltest_modul.kabelgeraete(box.mesh_liste())
    except fb.FritzboxFehler as fehler:
        print(f"  FRITZ!Box nicht erreichbar: {fehler}")
        return 1

    mit_ip = [g for g in geraete if g["ip"]]
    if not mit_ip:
        kopf("Kein Kabelgeraet gefunden")
        print("  Steck ein Geraet in die Dose, die du pruefen willst.")
        return 1

    if name:
        ziel = next((g for g in mit_ip if name.lower() in g["name"].lower()), None)
        if ziel is None:
            print(f"  Kein Kabelgeraet gefunden, das zu {name!r} passt.")
            name = None
    if not name:
        kopf("Welche Kabelstrecke soll geprueft werden?")
        for nummer, g in enumerate(mit_ip, 1):
            print(f"  {nummer}  {g['name'][:34]:<34s} {g['mbit']:>5d} Mbit  "
                  f"an {g['buchse']}  ({g['ip']})")
        print()
        while True:
            wahl = input(f"  Auswahl [1-{len(mit_ip)}]: ").strip()
            if wahl.isdigit() and 1 <= int(wahl) <= len(mit_ip):
                ziel = mit_ip[int(wahl) - 1]
                break

    kopf(f"Kabeltest: {ziel['name']}")
    zeile("Buchse", ziel["buchse"])
    zeile("Adresse", ziel["ip"])
    zeile("Ausgehandelt", f"{ziel['mbit']} Mbit"
                          + ("" if ziel["mbit"] >= 1000 else "   <-- nicht volle Gigabit"))
    mit_ping = kabeltest_modul.antwortet(ziel["ip"])
    if not mit_ping:
        zeile("Ping", "keine Antwort - vermutlich Firewall, messe nur die Leitung")

    print(f"\n  Messe {minuten:.0f} Minuten. Zur Kontrolle laeuft parallel ein Ping")
    print("  auf die FRITZ!Box - so laesst sich das Kabel vom WLAN trennen.")
    print("  Strg-C beendet frueher.\n")

    ergebnis = kabeltest_modul.messen(box, ziel, host, minuten * 60,
                                      mit_ping=mit_ping)

    kopf("Ergebnis")
    messungen_ = [("FRITZ!Box (Kontrolle)", ergebnis["kontrolle"])]
    if ergebnis["ziel"]:
        messungen_.insert(0, ("Ziel ueber Kabel", ergebnis["ziel"]))
    for titel, werte in messungen_:
        aus = werte.get("ausfaelle") or []
        zeile(titel, f"{werte.get('verlust_prozent')} % Verlust, "
                     f"{len(aus)} Ausfall/Ausfaelle, "
                     f"Laufzeit {werte.get('laufzeit_mittel_ms')} ms", breite=24)
        for a in aus:
            print(f"      nach {a['ab_sekunde']:.0f} s fuer {a['dauer_s']} s")

    kopf("Urteil")
    for satz in kabeltest_modul.urteil(ergebnis, ziel["mbit"]):
        print(f"  {satz}")
    return 0


def geraete_messwerte(plan, start_nr=1):
    """Signalwerte der eingezeichneten festen Geraete, als Messpunkte."""
    stellen = plan.get("geraete_positionen") or {}
    if not stellen:
        return [], []

    umgebung = fb.lade_env(WURZEL / ".env")
    try:
        box = fb.Fritzbox(umgebung.get("FRITZBOX_HOST", "fritz.box"),
                          umgebung.get("FRITZBOX_USER"),
                          umgebung.get("FRITZBOX_PASSWORT"))
        liste = geraete_modul.sammeln(box.mesh_liste())
    except fb.FritzboxFehler:
        return [], list(stellen)

    beste = {}
    for g in liste:
        if g["art"] != "WLAN" or g["signal"] is None:
            continue
        if g["name"] not in beste or g["signal"] > beste[g["name"]]["signal"]:
            beste[g["name"]] = g

    messwerte, fehlend = [], []
    for name, stelle in sorted(stellen.items()):
        g = beste.get(name)
        if g is None:
            fehlend.append(name)
            continue
        messwerte.append({
            "nr": start_nr + len(messwerte), "raum": name, "wo": "", "art": "geraet",
            "x": stelle["x"], "y": stelle["y"], "rssi": g["signal"],
            "zugangspunkt": g["zugangspunkt"], "band": g["band"],
            "kanal": g["kanal"], "rate_mbit": g["rate_mbit"],
        })
    return messwerte, fehlend


def funkkarte_zeigen(stumm=False):
    """Grober Ueberblick aus den eingezeichneten Geraeten - ohne herumzulaufen."""
    plan = heatmap.plan_laden()
    if not (plan.get("geraete_positionen") or {}):
        kopf("Keine Geraete eingezeichnet")
        print("  Zeichne sie zuerst ein:  python3 wlanmess.py --bearbeiten")
        print("  Dort auf 'Feste Geraete' umschalten.")
        return 1

    messwerte, fehlend = geraete_messwerte(plan)
    if not messwerte:
        print("  Keines der eingezeichneten Geraete ist gerade verbunden.")
        return 1

    kopf(f"Schnelluebersicht aus {len(messwerte)} festen Geraeten")
    for m in sorted(messwerte, key=lambda m: m["rssi"]):
        wert = farbe.nach_signal(f"{m['rssi']:>4d} dBm", m["rssi"])
        zeile(m["raum"][:28],
              f"{farbe.balken(m['rssi'], 10)} {wert}   "
              f"{m['band']}, {m['rate_mbit']} Mbit   {m['zugangspunkt']}", breite=30)
    if fehlend:
        print("\n  Eingezeichnet, aber gerade nicht verbunden:")
        for name in fehlend:
            print(f"    {name}")
    print("\n  Achtung: Die Werte sind untereinander nicht vergleichbar - ein")
    print("  Lautsprecher sendet schwaecher als ein Laptop. Fuer den Vergleich")
    print("  derselben Stelle ueber die Zeit sind sie dagegen genau richtig.")

    ziel = heatmap.zeichnen(messwerte, plan, "Schnelluebersicht der festen Geraete",
                            WURZEL / "grundriss" / "funkkarte")
    kopf("Gespeichert")
    zeile("Karte", ziel)
    return 0


def umhaengen_zeigen(ordner):
    """Haengt eine Messung auf die aktuelle Punktanordnung um."""
    plan = heatmap.plan_laden()
    ergebnis = umhaengen_modul.anwenden(ordner, plan)
    if ergebnis is None:
        return 1
    treffer, verwaist, ohne, sicherung = ergebnis

    kopf("Umgehaengt")
    zeile("Zugeordnet", f"{len(treffer)} von {len(treffer) + len(verwaist)} Messwerten")
    zeile("Original gesichert", sicherung)

    gewandert = [t for t in treffer if t["abstand"] > 0.005]
    if gewandert:
        print("\n  Diese Punkte liegen jetzt woanders:")
        for t in sorted(gewandert, key=lambda t: -t["abstand"]):
            print(f"    {t['frueher']:<34s} -> {t['raum']} {t['wo']}"
                  f"   ({t['abstand']:.3f} verschoben)")
    if verwaist:
        print("\n  Ohne Gegenstueck im neuen Plan (Messwert entfaellt):")
        for m in verwaist:
            print(f"    {m['raum']} {m.get('wo', '')}".rstrip())
    if ohne:
        print("\n  Neue Punkte, fuer die es keinen alten Messwert gibt:")
        for punkt in ohne:
            hoehe = "  (obere Ebene)" if punkt.get("ebene") == "oben" else ""
            print(f"    {punkt['raum']} {punkt['wo']}".rstrip() + hoehe)

    laeufe, uebersprungen = galerie.laeufe_sammeln()
    zeile("Vergleichsseite", galerie.bauen(laeufe, ERGEBNISSE / "uebersicht.html",
                                           uebersprungen), breite=20)
    return 0


def geraete_zeigen():
    """Wer haengt wo im Netz, und was liesse sich besser aufteilen?"""
    umgebung = fb.lade_env(WURZEL / ".env")
    try:
        box = fb.Fritzbox(
            umgebung.get("FRITZBOX_HOST", "fritz.box"),
            umgebung.get("FRITZBOX_USER"),
            umgebung.get("FRITZBOX_PASSWORT"),
        )
        liste = geraete_modul.sammeln(box.mesh_liste())
    except fb.FritzboxFehler as fehler:
        print(f"  FRITZ!Box nicht erreichbar: {fehler}")
        return 1

    gruppen = {}
    for g in liste:
        if g["art"] == "LAN":
            schluessel = "Am Kabel"
        else:
            schluessel = f"{g['zugangspunkt']} - {g['band']}, Kanal {g['kanal']}"
        gruppen.setdefault(schluessel, []).append(g)

    kopf(f"Geraete im Netz ({len(liste)})")
    for schluessel in sorted(gruppen, key=lambda s: (s != "Am Kabel", s)):
        eintraege = sorted(gruppen[schluessel],
                           key=lambda g: g["rate_mbit"] or 0, reverse=True)
        print(f"\n  {schluessel}  ({len(eintraege)})")
        for g in eintraege:
            signal = f"{g['signal']:>4d} dBm" if g["signal"] is not None else "        "
            rate = f"{g['rate_mbit']:>5d} Mbit" if g["rate_mbit"] else "          "
            koennen = f"{g['breite']}, {g['stroeme']}x" if g["breite"] else ""
            print(f"    {g['name'][:30]:<30s} {signal}  {rate}   {koennen}")

    for rat in geraete_modul.ratschlaege(liste):
        kopf(rat["titel"])
        for name in rat["geraete"]:
            print(f"    - {name}")
        print(f"\n  {rat['warum']}")
    return 0


def wache_laufen(minuten, abstand_s=2.0):
    """Beobachtet Repeater und FRITZ!Box und meldet jede Aenderung sofort."""
    umgebung = fb.lade_env(WURZEL / ".env")
    try:
        box = fb.Fritzbox(
            umgebung.get("FRITZBOX_HOST", "fritz.box"),
            umgebung.get("FRITZBOX_USER"),
            umgebung.get("FRITZBOX_PASSWORT"),
        )
        zustand = wache.zustand_erheben(box)
    except fb.FritzboxFehler as fehler:
        print(f"  FRITZ!Box nicht erreichbar: {fehler}")
        return 1

    kopf("Netz-Wache")
    for name, werte in zustand["zugangspunkte"].items():
        funk = ", ".join(f"{m.split(':', 1)[1]} auf {w['kanal']} ({w['geraete']})"
                         for m, w in werte["funk"].items())
        zeile(name, funk, breite=30)
    for name, werte in zustand["kabel"].items():
        zeile(f"Kabel: {name}"[:29], f"{werte['mbit']} Mbit an {werte['buchse']}", breite=30)
    spanne = (f"{minuten:.0f} Minuten" if minuten >= 1
              else f"{minuten * 60:.0f} Sekunden")
    print(f"\n  Beobachte {spanne}, Abfrage alle {abstand_s} Sekunden.")
    print("  Gemeldet wird nur, was sich aendert. Strg-C beendet.\n")

    ordner = ERGEBNISSE / datetime.now().strftime("%Y-%m-%d_%H-%M")
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / "wache.md"
    ziel.write_text(
        f"# Repeater-Wache\n\nBegonnen {datetime.now():%d.%m.%Y %H:%M}, "
        f"Abfrage alle {abstand_s:.0f} Sekunden.\n\n",
        encoding="utf-8",
    )
    print(f"  Mitschrift: {ziel}\n")

    try:
        protokoll = wache.bewachen(box, minuten * 60, abstand_s, mitschrift=ziel)
    except KeyboardInterrupt:
        print("\n  Abgebrochen - das Protokoll ist vollstaendig.")
        protokoll = []
    kopf("Ergebnis")
    if protokoll:
        zeile("Ereignisse", len(protokoll))
    else:
        print("  Keine Auffaelligkeit - weder Ausfall noch Kanalwechsel.")
    zeile("Protokoll", ziel)
    return 0


def vergleich_zeigen(alt, neu):
    """Stellt zwei Messungen gegenueber und schreibt das Ergebnis dazu."""
    try:
        vorher = vergleich.laden(alt)
        nachher = vergleich.laden(neu)
    except FileNotFoundError as fehler:
        print(f"  Datei nicht gefunden: {fehler.filename}")
        return 1

    paare = vergleich.vergleichen(vorher, nachher)
    zus = vergleich.zusammenfassung(paare)
    vz, nz = vergleich.zeit(vorher), vergleich.zeit(nachher)

    kopf("Vergleich")
    print(vergleich.text(paare, zus, vz, nz))

    if paare:
        ziel = Path(neu) / "vergleich.md"
        ziel.write_text(vergleich.markdown(paare, zus, vz, nz), encoding="utf-8")
        kopf("Gespeichert")
        zeile("Vergleich", ziel)
    return 0


def neu_auswerten(ordner):
    """Wertet eine gespeicherte Messung mit der aktuellen Logik neu aus."""
    import json

    ordner = Path(ordner)
    lauf = json.loads((ordner / "messung.json").read_text(encoding="utf-8"))
    proben = lauf.get("proben") or []
    if not proben:
        print("  Diese Messung enthaelt keine Rohdaten zum Neuauswerten.")
        return 1

    print("  Hole die aktuelle Kanalbelegung von der FRITZ!Box ...")
    diagnose = diagnose_erheben(stumm=True)
    for probe in proben:
        probe["zugangspunkt"] = zugangspunkt_bestimmen(diagnose, probe)

    marken = lauf.get("marken") or _marken_aus_punkten(lauf)
    ping_ergebnis = dict(lauf.get("verlauf") or {})
    lauf["punkte"], lauf["verlauf"] = durchlauf_auswerten(proben, marken, ping_ergebnis)
    diagnose.pop("_box", None)
    diagnose.pop("_web", None)
    lauf["diagnose"] = diagnose
    lauf["befunde"] = bericht.befunde(diagnose, lauf["punkte"], proben, lauf["verlauf"])

    pfad = bericht.speichern(lauf, ordner)
    kopf("Neu ausgewertet")
    zeile("Bericht", pfad)
    return 0


def _marken_aus_punkten(lauf):
    """Rekonstruiert die Marken aus einer frueher gespeicherten Auswertung."""
    marken = []
    for punkt in lauf.get("punkte") or []:
        if punkt.get("von_sekunde") is not None:
            marken.append({"sekunde": punkt["von_sekunde"], "name": punkt["name"]})
    return sorted(marken, key=lambda m: m["sekunde"])


def main():
    if "--neu" in sys.argv:
        return neu_auswerten(sys.argv[sys.argv.index("--neu") + 1])
    if "--standort" in sys.argv:
        kopf("Ortungsfreigabe anfordern")
        print("  macOS zeigt den Dialog nur fuer signierte Programme zuverlaessig.")
        print("  Bleibt er aus, aendert das nichts an der Messung.\n")
        try:
            ergebnis = wlan.standortfreigabe_anfordern()
            zeile("Erteilt", "ja" if ergebnis.get("bssid") else "nein")
        except wlan.WlanFehler as fehler:
            zeile("Fehlgeschlagen", fehler)
        return 0
    if "--umhaengen" in sys.argv:
        stelle = sys.argv.index("--umhaengen")
        if len(sys.argv) <= stelle + 1:
            print("  Aufruf: wlanmess.py --umhaengen <Messordner>")
            return 1
        return umhaengen_zeigen(sys.argv[stelle + 1])
    if "--leitung" in sys.argv:
        stelle = sys.argv.index("--leitung")
        rest = sys.argv[stelle + 1:stelle + 2]
        return leitung_zeigen(float(rest[0]) if rest and
                              rest[0].replace(".", "").isdigit() else 10.0)
    if "--kabeltest" in sys.argv:
        stelle = sys.argv.index("--kabeltest")
        rest = sys.argv[stelle + 1:stelle + 3]
        name = rest[0] if rest and not rest[0].replace(".", "").isdigit() else None
        zahlen = [r for r in rest if r.replace(".", "").isdigit()]
        return kabeltest_zeigen(name, float(zahlen[0]) if zahlen else 10.0)
    if "--funkkarte" in sys.argv:
        return funkkarte_zeigen()
    if "--bearbeiten" in sys.argv:
        kopf("Messpunkte bearbeiten")
        print("  Ziehen verschiebt, Doppelklick legt neu an, Entf loescht.")
        print("  Gespeichert wird direkt in grundriss/plan.json.\n")
        editor.starten()
        return 0
    if "--uebersicht" in sys.argv:
        laeufe, uebersprungen = galerie.laeufe_sammeln()
        ziel = galerie.bauen(laeufe, ERGEBNISSE / "uebersicht.html", uebersprungen)
        kopf("Vergleichsseite")
        for lauf in laeufe:
            zeile(lauf["titel"], f"{len(lauf['messwerte'])} Punkte", breite=34)
        for ordner, _ in uebersprungen:
            zeile(ordner, "uebersprungen (anderer Grundriss)", breite=34)
        zeile("Datei", ziel, breite=34)
        return 0
    if "--geraete" in sys.argv:
        return geraete_zeigen()
    if "--wache" in sys.argv:
        stelle = sys.argv.index("--wache")
        zahlen = []
        for wert in sys.argv[stelle + 1:stelle + 3]:
            try:
                zahlen.append(float(wert))
            except ValueError:
                break
        minuten = zahlen[0] if zahlen else 30.0
        abstand = zahlen[1] if len(zahlen) > 1 else 2.0
        return wache_laufen(minuten, abstand)
    if "--vergleich" in sys.argv:
        stelle = sys.argv.index("--vergleich")
        if len(sys.argv) < stelle + 3:
            print("  Aufruf: wlanmess.py --vergleich <alter Ordner> <neuer Ordner>")
            return 1
        return vergleich_zeigen(sys.argv[stelle + 1], sys.argv[stelle + 2])
    if "--karte" in sys.argv:
        plan = heatmap.plan_laden()
        raster = "--raster" in sys.argv
        ziel = heatmap.zeichnen(
            plan["punkte"], plan,
            "Grundriss mit Gitternetz" if raster else "Messpunkte",
            WURZEL / "grundriss" / "messpunkte.html", mit_raster=raster,
        )
        kopf("Karte erzeugt")
        zeile("Datei", ziel)
        return 0

    kopf("WLAN-Messung")
    probe = wlan_pruefen()
    if probe is None:
        return 1
    zeile("WLAN", f"{probe['band']}, Kanal {probe['kanal']}, {probe['rssi']} dBm")

    print("\n  Frage die FRITZ!Box ab ...")
    diagnose = diagnose_erheben()
    diagnose_zeigen(diagnose)
    zuordnung_pruefen(diagnose, probe)

    try:
        ip = eigene_ip()
    except OSError:
        ip = None

    wahl = hauptmenue()
    if wahl == "5":
        return funkkarte_zeigen()
    lauf = {
        "gestartet": datetime.now().isoformat(timespec="seconds"),
        "modus": {"1": "Punktmessung", "2": "Durchlauf", "3": "Diagnose",
                  "4": "Heatmap", "5": "Schnellblick"}[wahl],
        "punkte": [],
        "verlauf": {},
    }

    if wahl == "1":
        lauf["punkte"] = modus_punktmessung(diagnose, ip)
    elif wahl == "2":
        proben, marken, ping_ergebnis = modus_durchlauf(diagnose, ip)
        lauf["punkte"], lauf["verlauf"] = durchlauf_auswerten(proben, marken, ping_ergebnis)
        lauf["proben"] = proben
        lauf["marken"] = marken
    elif wahl == "4":
        messwerte, plan, notiz = modus_heatmap(diagnose, ip)
        lauf["messwerte"] = messwerte
        lauf["notiz"] = notiz
        lauf["plan"] = plan
        lauf["punkte"] = [
            {**m["messung"], "name": f"{m['raum']} {m['wo']}".strip(),
             "zugangspunkt": m.get("zugangspunkt")}
            for m in messwerte
        ]
        lauf["_plan"] = plan

    diagnose.pop("_box", None)
    diagnose.pop("_web", None)
    lauf["diagnose"] = diagnose
    lauf["befunde"] = bericht.befunde(
        diagnose, lauf["punkte"], lauf.get("proben"), lauf.get("verlauf")
    )

    kopf("Befunde")
    if not lauf["befunde"]:
        print("  Keine Auffaelligkeiten gefunden.")
    for i, b in enumerate(lauf["befunde"], 1):
        marke = farbe.nach_gewicht(f"[{b['gewicht']}]", b["gewicht"])
        print(f"\n  {i}. {marke} {farbe.betont(b['titel'])}")
        print(f"     {b['text']}")
        print(f"     {farbe.leise('Massnahme:')} {b['massnahme']}")

    ordner = ERGEBNISSE / datetime.now().strftime("%Y-%m-%d_%H-%M")
    plan = lauf.pop("_plan", None)
    pfad = bericht.speichern(lauf, ordner)
    karte_pfad = None
    if plan and lauf.get("messwerte"):
        karte_pfad = karte_schreiben(
            lauf["messwerte"], plan, "WLAN-Heatmap", ordner / "heatmap.html"
        )
    kopf("Gespeichert")
    zeile("Bericht", pfad)
    if karte_pfad:
        zeile("Heatmap", karte_pfad)
        laeufe, uebersprungen = galerie.laeufe_sammeln()
        zeile("Vergleichsseite", galerie.bauen(laeufe, ERGEBNISSE / "uebersicht.html",
                                               uebersprungen))
    zeile("Rohdaten", ordner / "messung.json")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        sys.exit(130)
