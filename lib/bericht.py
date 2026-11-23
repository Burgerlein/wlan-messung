"""Erzeugt aus den Messdaten einen lesbaren Bericht mit Empfehlungen."""

import json
from datetime import datetime

# Kanaele, die in Europa ohne Radar-Zwangswechsel (DFS) nutzbar sind.
DFS_FREIE_KANAELE_5GHZ = {36, 40, 44, 48}


def _wert(punkt, *pfad, standard=None):
    stelle = punkt
    for schluessel in pfad:
        if not isinstance(stelle, dict):
            return standard
        stelle = stelle.get(schluessel)
    return stelle if stelle is not None else standard


# -- Befunde -----------------------------------------------------------


def befunde(diagnose, punkte, proben=None, verlauf=None):
    """Liste von Befunden, wichtigste zuerst."""
    gefunden = []

    gefunden += _befund_haften(proben or [], verlauf or {})
    gefunden += _befund_dfs(diagnose)
    gefunden += _befund_bandsteering(diagnose)
    gefunden += _befund_repeater_nutzung(punkte)
    gefunden += _befund_schwachstellen(punkte)
    gefunden += _befund_kanal_24(diagnose)

    rang = {"kritisch": 0, "wichtig": 1, "hinweis": 2}
    return sorted(gefunden, key=lambda b: rang.get(b["gewicht"], 9))


def wechsel_finden(proben):
    """Alle Wechsel des Zugangspunkts im Verlauf, mit dem Signal davor."""
    wechsel = []
    vorheriger = None
    for i, p in enumerate(proben):
        jetzt = p.get("zugangspunkt") or f"Kanal {p.get('kanal')}"
        if vorheriger and jetzt != vorheriger:
            davor = [q["rssi"] for q in proben[max(0, i - 6):i]
                     if q.get("rssi") is not None]
            wechsel.append({
                "sekunde": p.get("sekunde"),
                "von": vorheriger,
                "nach": jetzt,
                "signal_davor": min(davor) if davor else None,
                "signal_danach": p.get("rssi"),
            })
        vorheriger = jetzt
    return wechsel


def _befund_haften(proben, verlauf):
    """Haengt das Geraet zu lange am falschen Zugangspunkt?"""
    if not proben:
        return []

    wechsel = wechsel_finden(proben)
    verspaetet = [w for w in wechsel
                  if w["signal_davor"] is not None and w["signal_davor"] <= -75]
    # Strecken, auf denen das Signal unter -72 dBm lag, ohne dass gewechselt wurde
    zaeh = sum(1 for p in proben if (p.get("rssi") or 0) <= -72)
    ausfaelle = verlauf.get("ausfaelle") or []

    if not verspaetet and zaeh < 10:
        return []

    teile = []
    for w in verspaetet:
        teile.append(
            f"bei {w['sekunde']:.0f}s erst bei {w['signal_davor']} dBm von "
            f"{w['von']} auf {w['nach']} gewechselt (danach {w['signal_danach']} dBm)"
        )
    if zaeh:
        teile.append(
            f"insgesamt {zaeh} Sekunden unterhalb von -72 dBm, obwohl ein "
            "besserer Zugangspunkt in Reichweite war"
        )
    if ausfaelle:
        teile.append(
            f"{len(ausfaelle)} Verbindungsabriss(e) von zusammen "
            f"{sum(a['dauer_s'] for a in ausfaelle):.0f} Sekunden"
        )

    return [{
        "gewicht": "kritisch",
        "titel": "Das Geraet haengt zu lange am falschen Zugangspunkt",
        "text": "; ".join(teile) + ".",
        "massnahme": (
            "Bandsteuerung in der FRITZ!Box einschalten. Hilft das nicht genug, "
            "ist der Abstand zwischen den Zugangspunkten zu gross - dann muss der "
            "Repeater naeher an die Luecke ruecken, damit die Uebergabe frueher "
            "faellt."
        ),
    }]


def _befund_dfs(diagnose):
    """Funkmodule auf Radarkanaelen - der Hauptgrund fuer ploetzliche Abrisse."""
    betroffen = diagnose.get("dfs_module") or []
    ereignisse = diagnose.get("wlan_ereignisse") or []
    radar = [e for e in ereignisse
             if "Radar" in (e.get("text") or "") or "bevorrechtigte" in (e.get("text") or "")]
    if not betroffen:
        return []

    namen = ", ".join(
        f"{m['zugangspunkt']} ({m['modul']}) auf Kanal {m['kanal']} mit "
        f"{m['geraete']} Geraet(en)" for m in betroffen
    )
    text = (
        f"Auf radarpflichtigen Kanaelen senden: {namen}. Wird dort ein "
        "Radarsignal erkannt, muss das Funkmodul sofort den Kanal wechseln - "
        "alle daran haengenden Geraete fliegen raus."
    )
    if radar:
        text += f" Im Protokoll stehen {len(radar)} solcher Ereignisse."

    return [{
        "gewicht": "kritisch" if radar else "wichtig",
        "titel": "Funkmodul auf radarpflichtigem Kanal",
        "text": text,
        "massnahme": (
            "Radarfrei sind nur die Kanaele 36, 40, 44 und 48. Bei der FRITZ!Box "
            "laesst sich der Kanal fest einstellen; ein Repeater mit zweitem "
            "5-GHz-Funkmodul hat dort oft keine Wahl - dann hilft nur, dieses "
            "Modul abzuschalten oder die Geraete auf das andere zu lenken."
        ),
    }]


def _befund_bandsteering(diagnose):
    if diagnose.get("steering_aktiv") is not False:
        return []
    return [{
        "gewicht": "wichtig",
        "titel": "Die Steuerung zwischen den Zugangspunkten ist aus",
        "text": (
            "Die FRITZ!Box lenkt Geraete nicht aktiv auf das jeweils bessere "
            "Band oder den naeheren Zugangspunkt."
        ),
        "massnahme": (
            "In der FRITZ!Box unter WLAN > Funkkanal die Option 'WLAN-Geraete "
            "automatisch zwischen den Frequenzbaendern sowie zwischen mehreren "
            "FRITZ!-Produkten im Mesh steuern' einschalten."
        ),
    }]


def _befund_repeater_nutzung(punkte):
    if not punkte:
        return []
    zugangspunkte = [_wert(p, "fritzbox", "zugangspunkt") for p in punkte]
    zugangspunkte = [z for z in zugangspunkte if z]
    if not zugangspunkte:
        return []

    verteilung = {}
    for z in zugangspunkte:
        verteilung[z] = verteilung.get(z, 0) + 1

    repeater = {z: n for z, n in verteilung.items() if z != "fritz.box"}
    schwache_punkte = [
        p for p in punkte
        if (p.get("rssi_mittel") or 0) <= -70
    ]

    befunde_ = []
    if not repeater and schwache_punkte:
        befunde_.append({
            "gewicht": "wichtig",
            "titel": "Der Repeater wird an keinem Messpunkt genutzt",
            "text": (
                "An allen gemessenen Punkten hing der Mac an der FRITZ!Box, obwohl "
                f"{len(schwache_punkte)} Punkt(e) schwach versorgt sind. Der Repeater "
                "steht damit dort, wo er nichts beitraegt."
            ),
            "massnahme": (
                "Den Repeater naeher an die schwachen Raeume ruecken - idealerweise "
                "etwa auf halber Strecke zwischen FRITZ!Box und Problemzone, nicht "
                "in den Problemraum selbst."
            ),
        })
    return befunde_


def _schwachstelle_grund(punkt):
    """Nennt die Kennzahl, die den Punkt herunterzieht."""
    gruende = []
    rssi = punkt.get("rssi_mittel")
    schwaechste = punkt.get("rssi_min")
    if schwaechste is not None and schwaechste <= -75:
        gruende.append(f"faellt auf {schwaechste} dBm ab")
    elif rssi is not None and rssi <= -70:
        gruende.append(f"Signal {rssi} dBm")
    for feld, bezeichnung in (("internet", "Internetstrecke"),
                              ("funkstrecke", "Funkstrecke")):
        messwert = punkt.get(feld) or {}
        if not messwert:
            continue
        if messwert.get("verlust_prozent", 0) > 0.5:
            gruende.append(f"{bezeichnung} verliert {messwert['verlust_prozent']} % der Pakete")
        elif (messwert.get("schwankung_ms") or 0) > 20:
            gruende.append(f"{bezeichnung} schwankt um {messwert['schwankung_ms']} ms")
        elif (messwert.get("laufzeit_ms") or 0) > 100:
            gruende.append(f"{bezeichnung} braucht {messwert['laufzeit_ms']} ms")
    if not gruende and rssi is not None:
        gruende.append(f"Signal {rssi} dBm")
    return ", ".join(gruende)


def _befund_schwachstellen(punkte):
    schwach = [p for p in punkte if p.get("bewertung") in ("kritisch", "brauchbar")]
    if not schwach:
        return []
    namen = ", ".join(
        f"{p['name']}: {_schwachstelle_grund(p)}" for p in schwach
    )
    return [{
        "gewicht": "wichtig" if any(p.get("bewertung") == "kritisch" for p in schwach)
                   else "hinweis",
        "titel": f"{len(schwach)} Messpunkt(e) unterhalb der Teams-Richtwerte",
        "text": namen + ".",
        "massnahme": (
            "Diese Punkte sind die Kandidaten fuer einen besser platzierten oder "
            "zweiten Zugangspunkt."
        ),
    }]


def _befund_kanal_24(diagnose):
    kanal = _wert(diagnose, "baender", "2.4GHz", "kanal")
    nachbarn = diagnose.get("nachbarn_24ghz") or []
    if not kanal:
        return []
    kanal = int(kanal) if str(kanal).isdigit() else None
    stoerer = [n for n in nachbarn if abs((n.get("kanal") or 0) - (kanal or 0)) <= 2]
    if len(stoerer) < 2:
        return []
    return [{
        "gewicht": "hinweis",
        "titel": f"2,4-GHz-Kanal {kanal} ist dicht belegt",
        "text": f"{len(stoerer)} Nachbarnetz(e) funken auf oder direkt neben diesem Kanal.",
        "massnahme": "Kanal 1, 6 oder 11 waehlen - je nachdem, welcher am wenigsten belegt ist.",
    }]


# -- Darstellung -------------------------------------------------------


def markdown(lauf):
    """Baut den Bericht als Markdown."""
    z = []
    zeit = datetime.fromisoformat(lauf["gestartet"]).strftime("%d.%m.%Y %H:%M")
    z.append(f"# WLAN-Messung vom {zeit}")
    z.append("")
    z.append(f"Modus: **{lauf['modus']}**")
    z.append("")

    diagnose = lauf.get("diagnose") or {}
    if diagnose.get("baender"):
        z.append("## Netz zum Zeitpunkt der Messung")
        z.append("")
        z.append("| Band | SSID | Kanal | Standard |")
        z.append("|---|---|---|---|")
        for band, d in diagnose["baender"].items():
            z.append(f"| {band} | {d.get('ssid')} | {d.get('kanal')} | {d.get('standard')} |")
        z.append("")

    punkte = lauf.get("punkte") or []
    if punkte:
        z.append("## Messpunkte")
        z.append("")
        z.append("| Punkt | Signal Mittel | schwaechste Stelle | SNR | Zugangspunkt | Band/Kanal | Laufzeit | Schwankung | Verlust | Urteil |")
        z.append("|---|---|---|---|---|---|---|---|---|---|")
        # Nach der schwaechsten Stelle sortieren - die entscheidet ueber den Raum.
        for p in sorted(punkte, key=lambda x: x.get("rssi_min") or x.get("rssi_mittel") or -99):
            internet = p.get("internet") or {}
            schwaechste = p.get("rssi_min")
            marke = " ⚠" if schwaechste is not None and schwaechste <= -75 else ""
            z.append(
                f"| {p['name']} | {p.get('rssi_mittel')} dBm "
                f"| **{schwaechste} dBm**{marke} "
                f"| {p.get('snr_mittel')} dB "
                f"| {p.get('zugangspunkt') or _wert(p, 'fritzbox', 'zugangspunkt', standard='?')} "
                f"| {p.get('band')} / {p.get('kanal')} "
                f"| {internet.get('laufzeit_ms', '-')} ms "
                f"| {internet.get('schwankung_ms', '-')} ms "
                f"| {internet.get('verlust_prozent', '-')} % "
                f"| **{p.get('bewertung')}** |"
            )
        z.append("")
        z.append("Beim Durchlauf zaehlt die *schwaechste Stelle*: Sie ist der Punkt im "
                 "Raum, an dem ein Anruf zuerst bricht. ⚠ markiert alles ab -75 dBm.")
        z.append("")

    verlauf = lauf.get("verlauf") or {}
    if verlauf.get("ausfaelle"):
        z.append("## Verbindungsabrisse waehrend des Durchlaufs")
        z.append("")
        for a in verlauf["ausfaelle"]:
            marke = a.get("marke") or "unterwegs"
            z.append(f"- nach {a['ab_sekunde']} s, Dauer {a['dauer_s']} s ({marke})")
        z.append("")

    gefunden = lauf.get("befunde") or []
    if gefunden:
        z.append("## Befunde und Massnahmen")
        z.append("")
        for i, b in enumerate(gefunden, 1):
            z.append(f"### {i}. {b['titel']}  _( {b['gewicht']} )_")
            z.append("")
            z.append(b["text"])
            z.append("")
            z.append(f"**Massnahme:** {b['massnahme']}")
            z.append("")

    ereignisse = diagnose.get("wlan_ereignisse") or []
    if ereignisse:
        z.append("## WLAN-Ereignisse der FRITZ!Box")
        z.append("")
        for e in ereignisse[:25]:
            z.append(f"- `{e.get('datum')} {e.get('zeit')}` {e.get('text')}")
        z.append("")

    return "\n".join(z)


def speichern(lauf, ordner):
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "messung.json").write_text(
        json.dumps(lauf, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    pfad = ordner / "bericht.md"
    pfad.write_text(markdown(lauf), encoding="utf-8")
    return pfad
