"""Zeichnet den Grundriss als Vektor-SVG und faerbt die Messwerte darueber.

Bewusst ohne Bildbibliothek: Der Grundriss ist als Rechtecke beschrieben
(grundriss/plan.json), die Heatmap entsteht durch Interpolation zwischen den
Messpunkten. Ergebnis sind eine .svg und eine .html zum Anschauen.
"""

import json
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
GRUNDRISS = WURZEL / "grundriss"

BREITE = 1000          # Zeichenbreite; die Hoehe folgt dem Seitenverhaeltnis

# Signalstaerken und ihre Farben. Dazwischen wird gemischt.
SKALA = [
    (-45, (26, 140, 80)),    # sattes Gruen - exzellent
    (-55, (130, 185, 55)),   # hellgruen
    (-62, (238, 200, 48)),   # gelb
    (-70, (240, 140, 45)),   # orange
    (-78, (214, 58, 44)),    # rot
    (-88, (118, 24, 58)),    # dunkelrot
]

RASTER = 54            # Aufloesung der Interpolation in der Breite
POTENZ = 2.4           # hoeher = lokaler, niedriger = weicher
REICHWEITE = 0.17      # nur in diesem Umkreis um Messpunkte einfaerben


def wohnraeume(plan):
    return [r for r in plan.get("raeume", []) if not r.get("extern")]


def _raster(raum, abstand):
    """Verteilt Messpunkte gleichmaessig ueber einen Raum."""
    breite = raum["x2"] - raum["x1"]
    hoehe = raum["y2"] - raum["y1"]
    spalten = max(1, round(breite / abstand))
    zeilen = max(1, round(hoehe / abstand))
    while spalten * zeilen < 3:            # jeder Raum mindestens dreimal
        if hoehe >= breite:
            zeilen += 1
        else:
            spalten += 1

    # Oben etwas Platz lassen, dort steht der Raumname.
    kopfzeile = min(0.022, hoehe * 0.18)
    nutzhoehe = hoehe - kopfzeile

    punkte = []
    for z in range(zeilen):
        spaltenfolge = range(spalten) if z % 2 == 0 else reversed(range(spalten))
        for sp in spaltenfolge:
            punkte.append({
                "raum": raum["name"],
                "wo": "",
                "x": round(raum["x1"] + breite * (sp + 0.5) / spalten, 4),
                "y": round(raum["y1"] + kopfzeile + nutzhoehe * (z + 0.5) / zeilen, 4),
            })
    return punkte


def punkte_erzeugen(plan):
    """Baut die Messpunktliste.

    Stehen in plan.json feste Punkte (vom Editor gespeichert), gelten die.
    Sonst entsteht ein Raster je Raum plus die benannten Sonderpunkte.
    """
    fest = plan.get("punkte")
    if fest:
        return _durchnummerieren([dict(p) for p in fest])

    abstand = plan.get("rasterabstand", 0.115)
    sonder = plan.get("sonderpunkte", [])
    alle = []
    mindestabstand = abstand * 0.48
    for raum in wohnraeume(plan):
        besondere = [dict(s) for s in sonder if s["raum"] == raum["name"]]
        eigene = [
            p for p in _raster(raum, abstand)
            if all(((p["x"] - b["x"]) ** 2 + (p["y"] - b["y"]) ** 2) ** 0.5
                   > mindestabstand for b in besondere)
        ]
        eigene += besondere
        # Von oben nach unten durchnummerieren, damit der Weg Sinn ergibt
        eigene.sort(key=lambda p: (p["y"], p["x"]))
        alle.extend(eigene)

    return _durchnummerieren(alle)


def _durchnummerieren(punkte):
    """Vergibt Nummern und benennt unbenannte Stellen eindeutig."""
    for nummer, punkt in enumerate(punkte, 1):
        punkt["nr"] = nummer
        punkt.setdefault("wo", "")
        if not punkt["wo"]:
            gleiche = [p for p in punkte if p["raum"] == punkt["raum"]]
            punkt["wo"] = f"Stelle {gleiche.index(punkt) + 1} von {len(gleiche)}"
    return punkte


def plan_laden(pfad=None):
    pfad = Path(pfad) if pfad else GRUNDRISS / "plan.json"
    plan = json.loads(pfad.read_text(encoding="utf-8"))
    plan["breite"] = BREITE
    plan["hoehe"] = round(BREITE / plan.get("seitenverhaeltnis", 0.562))
    plan["punkte"] = punkte_erzeugen(plan)
    return plan


# -- Farben ------------------------------------------------------------


def farbe(rssi):
    """Signalstaerke in eine Farbe uebersetzen, mit weichem Uebergang."""
    if rssi >= SKALA[0][0]:
        return SKALA[0][1]
    if rssi <= SKALA[-1][0]:
        return SKALA[-1][1]
    for (oben, farbe_oben), (unten, farbe_unten) in zip(SKALA, SKALA[1:]):
        if unten <= rssi <= oben:
            anteil = (oben - rssi) / (oben - unten)
            return tuple(
                round(a + (b - a) * anteil) for a, b in zip(farbe_oben, farbe_unten)
            )
    return SKALA[-1][1]


def hex_farbe(rssi):
    return "#%02x%02x%02x" % farbe(rssi)


# -- Interpolation -----------------------------------------------------


def _interpolieren(messwerte, x, y):
    """Inverse Distanzgewichtung: naeher gelegene Messpunkte zaehlen mehr."""
    zaehler = nenner = 0.0
    for m in messwerte:
        abstand = ((m["x"] - x) ** 2 + (m["y"] - y) ** 2) ** 0.5
        if abstand < 1e-6:
            return m["rssi"]
        gewicht = 1.0 / (abstand ** POTENZ)
        zaehler += gewicht * m["rssi"]
        nenner += gewicht
    return zaehler / nenner if nenner else None


def _in_reichweite(messwerte, x, y):
    return min(
        ((m["x"] - x) ** 2 + (m["y"] - y) ** 2) ** 0.5 for m in messwerte
    ) <= REICHWEITE


# -- Grundriss ---------------------------------------------------------


def _huelle(plan, b, h):
    ecken = plan.get("huelle") or []
    if not ecken:
        return ""
    punkte = " ".join(f"{x * b:.0f},{y * h:.0f}" for x, y in ecken)
    return (f'<polygon points="{punkte}" fill="#ffffff" stroke="#1f2937" '
            f'stroke-width="9" stroke-linejoin="round"/>')


def _raeume(plan, b, h, mit_namen=True, nur_umriss=False):
    teile = []
    for raum in plan.get("raeume", []):
        x, y = raum["x1"] * b, raum["y1"] * h
        breite = (raum["x2"] - raum["x1"]) * b
        hoehe = (raum["y2"] - raum["y1"]) * h
        if nur_umriss:
            fuellung = "none"
        else:
            fuellung = "#e4e4e7" if raum.get("extern") else "#fbfbfc"
        teile.append(
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{breite:.0f}" '
            f'height="{hoehe:.0f}" fill="{fuellung}" stroke="#374151" '
            f'stroke-width="6"/>'
        )
        if mit_namen:
            # Schmale Raeume bekommen kleinere Schrift, damit nichts herauslaeuft.
            schrift = min(21, max(12, breite / (len(raum["name"]) * 1.0)))
            ton = "#a1a1aa" if raum.get("extern") else "#6b7280"
            teile.append(
                f'<text x="{x + breite / 2:.0f}" y="{y + schrift + 7:.0f}" '
                f'text-anchor="middle" font-size="{schrift:.0f}" font-weight="600" '
                f'fill="{ton}" letter-spacing="0.4">{raum["name"].upper()}</text>'
            )
            if raum.get("extern"):
                teile.append(
                    f'<text x="{x + breite / 2:.0f}" y="{y + schrift + 28:.0f}" '
                    f'text-anchor="middle" font-size="13" fill="#a1a1aa">'
                    f'nicht zur Wohnung</text>'
                )
    return "\n".join(teile)


def _teilflaechen(plan, b, h):
    """Bereiche innerhalb eines Raums, etwa eine zweite Ebene."""
    teile = []
    for flaeche in plan.get("teilflaechen", []):
        x, y = flaeche["x1"] * b, flaeche["y1"] * h
        breite = (flaeche["x2"] - flaeche["x1"]) * b
        hoehe = (flaeche["y2"] - flaeche["y1"]) * h
        teile.append(
            f'<rect x="{x + 5:.0f}" y="{y + 5:.0f}" width="{breite - 10:.0f}" '
            f'height="{hoehe - 10:.0f}" fill="none" stroke="#9ca3af" '
            f'stroke-width="3" stroke-dasharray="11 8" rx="6"/>'
            f'<text x="{x + breite / 2:.0f}" y="{y + hoehe - 14:.0f}" '
            f'text-anchor="middle" font-size="14" fill="#9ca3af" '
            f'font-style="italic">{flaeche["name"]}</text>'
        )
    return "\n".join(teile)


def _geraete(plan, b, h):
    teile = []
    for g in plan.get("geraete", []):
        x, y = g["x"] * b, g["y"] * h
        ton = "#1d4ed8" if g.get("art") == "router" else "#7c3aed"
        teile.append(
            f'<g><rect x="{x - 15:.0f}" y="{y - 15:.0f}" width="30" height="30" '
            f'rx="7" fill="{ton}" stroke="#fff" stroke-width="3"/>'
            f'<text x="{x:.0f}" y="{y + 38:.0f}" text-anchor="middle" font-size="20" '
            f'font-weight="700" fill="{ton}" stroke="#fff" stroke-width="4" '
            f'paint-order="stroke">{g["name"]}</text></g>'
        )
    return "\n".join(teile)


def _dosen(plan, b, h):
    teile = []
    for dose in plan.get("dosen", []):
        x, y = dose["x"] * b, dose["y"] * h
        teile.append(
            f'<g><rect x="{x - 9:.0f}" y="{y - 9:.0f}" width="18" height="18" '
            f'rx="3" fill="#ffffff" stroke="#0f766e" stroke-width="3.5"/>'
            f'<title>Netzwerkdose: {dose["wo"]}</title></g>'
        )
    return "\n".join(teile)


def _punkte(messwerte, b, h):
    teile = []
    for m in messwerte:
        x, y = m["x"] * b, m["y"] * h
        rssi = m.get("rssi")
        fuellung = hex_farbe(rssi) if rssi is not None else "#ffffff"
        schrift = "#ffffff" if rssi is not None and rssi <= -62 else "#111827"
        obenauf = m.get("ebene") == "oben"
        strich = ' stroke-dasharray="5 4"' if obenauf else ""
        # Feste Geraete bekommen ein Quadrat, damit man sie von den
        # selbst gemessenen Punkten unterscheiden kann.
        if m.get("art") == "geraet":
            marke = (f'<rect x="{x - 15:.0f}" y="{y - 15:.0f}" width="30" '
                     f'height="30" rx="6" fill="{fuellung}" stroke="#111827" '
                     f'stroke-width="2.5"/>')
        else:
            marke = (f'<circle cx="{x:.0f}" cy="{y:.0f}" r="16" fill="{fuellung}" '
                     f'stroke="#111827" stroke-width="2.5"{strich}/>')
        teile.append(
            f'<g>{marke}'
            f'<text x="{x:.0f}" y="{y + 6:.0f}" text-anchor="middle" font-size="18" '
            f'font-weight="700" fill="{schrift}">{m["nr"]}</text>'
        )
        if rssi is not None:
            teile.append(
                f'<text x="{x:.0f}" y="{y - 21:.0f}" text-anchor="middle" '
                f'font-size="17" font-weight="700" fill="#111827" stroke="#fff" '
                f'stroke-width="4" paint-order="stroke">{rssi}</text>'
            )
        teile.append("</g>")
    return "\n".join(teile)


def _flaeche(messwerte, b, h):
    """Die eingefaerbte Flaeche als viele kleine Rechtecke."""
    if not messwerte:
        return ""
    schritt_x = 1.0 / RASTER
    zeilen = max(10, round(RASTER * h / b))
    schritt_y = 1.0 / zeilen
    teile = []
    for i in range(RASTER):
        for j in range(zeilen):
            x = (i + 0.5) * schritt_x
            y = (j + 0.5) * schritt_y
            if not _in_reichweite(messwerte, x, y):
                continue
            wert = _interpolieren(messwerte, x, y)
            if wert is None:
                continue
            teile.append(
                f'<rect x="{i * schritt_x * b:.1f}" y="{j * schritt_y * h:.1f}" '
                f'width="{schritt_x * b + 1.2:.1f}" height="{schritt_y * h + 1.2:.1f}" '
                f'fill="{hex_farbe(wert)}"/>'
            )
    return "\n".join(teile)


# -- Ausgabe -----------------------------------------------------------


def svg(messwerte, plan, deckkraft=0.58, kennung=""):
    """kennung macht die internen Bezeichner eindeutig, wenn mehrere
    Grafiken in derselben HTML-Seite liegen."""
    b, h = plan["breite"], plan["hoehe"]
    weich, innen = f"weich{kennung}", f"innen{kennung}"
    gemessen = [m for m in messwerte if m.get("rssi") is not None]
    flaeche = (
        f'<g filter="url(#{weich})" opacity="{deckkraft}" '
        f'clip-path="url(#{innen})">\n{_flaeche(gemessen, b, h)}\n</g>'
        if gemessen else ""
    )
    # Die Farbe gehoert in die Raeume, nicht in Waende oder nach draussen.
    kacheln = "".join(
        f'<rect x="{r["x1"] * b:.0f}" y="{r["y1"] * h:.0f}" '
        f'width="{(r["x2"] - r["x1"]) * b:.0f}" '
        f'height="{(r["y2"] - r["y1"]) * h:.0f}"/>'
        for r in wohnraeume(plan)
    )
    maske = f'<clipPath id="{innen}">{kacheln}</clipPath>' 

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {b} {h}" \
font-family="-apple-system, system-ui, sans-serif">
  <defs>
    <filter id="{weich}" x="-15%" y="-15%" width="130%" height="130%">
      <feGaussianBlur stdDeviation="{b / 42:.0f}"/>
    </filter>
    {maske}
  </defs>
  <rect width="{b}" height="{h}" fill="#f8fafc"/>
  {_huelle(plan, b, h)}
  {_raeume(plan, b, h)}
  {flaeche}
  {_raeume(plan, b, h, mit_namen=False, nur_umriss=True) if gemessen else ""}
  {_teilflaechen(plan, b, h)}
  {_dosen(plan, b, h)}
  {_geraete(plan, b, h)}
  {_punkte(messwerte, b, h)}
</svg>"""


def _legende():
    return "".join(
        f'<span class="feld"><i style="background:{hex_farbe(g)}"></i>{g} dBm</span>'
        for g, _ in SKALA
    )


def zeichnen(messwerte, plan, titel, ziel, aktualisieren=0):
    """Schreibt <ziel>.svg und <ziel>.html und gibt die HTML-Datei zurueck.

    aktualisieren: Sekunden, nach denen sich die Seite selbst neu laedt.
    Waehrend eines laufenden Rundgangs nuetzlich, sonst stoerend.
    """
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    inhalt = svg(messwerte, plan)

    svg_pfad = ziel.with_suffix(".svg")
    svg_pfad.write_text(inhalt, encoding="utf-8")

    gemessen = sum(1 for m in messwerte if m.get("rssi") is not None)
    neuladen = (f'<meta http-equiv="refresh" content="{aktualisieren}">'
                if aktualisieren else "")
    html = f"""<!DOCTYPE html>
<html lang="de">
<meta charset="utf-8">
{neuladen}
<title>{titel}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 0;
          background: #f4f4f5; color: #18181b; }}
  header {{ padding: 20px 24px 10px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  p {{ margin: 0; color: #52525b; font-size: 14px; }}
  .legende {{ display: flex; flex-wrap: wrap; gap: 14px; padding: 12px 24px; }}
  .feld {{ display: flex; align-items: center; gap: 6px; font-size: 13px; }}
  .feld i {{ width: 22px; height: 14px; border-radius: 3px; display: block; }}
  .bild {{ padding: 0 24px 32px; }}
  svg {{ width: 100%; height: auto; max-width: 760px; display: block;
         border-radius: 10px; box-shadow: 0 2px 14px rgba(0,0,0,.13);
         background: #fff; }}
</style>
<header>
  <h1>{titel}</h1>
  <p>{gemessen} von {len(messwerte)} Punkten gemessen &middot; Grundriss schematisch nachgezeichnet</p>
</header>
<div class="legende">{_legende()}</div>
<div class="bild">{inhalt}</div>
</html>
"""
    ziel = ziel.with_suffix(".html")
    ziel.write_text(html, encoding="utf-8")
    return ziel
