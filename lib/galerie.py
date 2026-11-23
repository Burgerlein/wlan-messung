"""Eine Seite mit allen Messungen zum Umschalten und Vergleichen.

Zwei Auswahlfelder, zwei Heatmaps nebeneinander, darunter die Veraenderung
Punkt fuer Punkt. So sieht man unmittelbar, was eine Massnahme gebracht hat.
"""

import json
from datetime import datetime
from pathlib import Path

import heatmap
import stil

WURZEL = Path(__file__).resolve().parent.parent
ERGEBNISSE = WURZEL / "messungen"


def laeufe_sammeln(ordner=None):
    """Alle Messungen, die sich auf dem Grundriss darstellen lassen."""
    ordner = Path(ordner) if ordner else ERGEBNISSE
    laeufe, uebersprungen = [], []
    for pfad in sorted(ordner.glob("*/messung.json")):
        try:
            lauf = json.loads(pfad.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        messwerte = [m for m in (lauf.get("messwerte") or []) if m.get("rssi") is not None]
        if not messwerte:
            continue
        plan = lauf.get("plan")
        if plan is None:
            # Aeltere Messung ohne mitgespeicherten Grundriss: Sie laesst sich
            # trotzdem darstellen, wenn ihre Punkte zum heutigen Plan passen.
            plan = heatmap.plan_laden()
            if not _punkte_passen(messwerte, plan):
                uebersprungen.append((pfad.parent.name, lauf.get("gestartet")))
                continue
        laeufe.append({
            "ordner": pfad.parent.name,
            "gestartet": lauf.get("gestartet"),
            "titel": _titel(lauf, pfad.parent.name),
            "messwerte": messwerte,
            "plan": plan,
            "notiz": lauf.get("notiz", ""),
        })
    laeufe.sort(key=lambda l: l["gestartet"] or "")
    return laeufe, uebersprungen


def _punkte_passen(messwerte, plan, abweichung=0.01):
    """Sitzen die Messpunkte dort, wo der heutige Plan sie vorsieht?"""
    heute = {f"{p['raum']} {p['wo']}".strip(): (p["x"], p["y"]) for p in plan["punkte"]}
    geprueft = 0
    for m in messwerte:
        if m.get("x") is None or m.get("y") is None:
            return False
        stelle = heute.get(f"{m['raum']} {m.get('wo', '')}".strip())
        if stelle is None:
            return False
        if (abs(stelle[0] - m["x"]) > abweichung
                or abs(stelle[1] - m["y"]) > abweichung):
            return False
        geprueft += 1
    return geprueft > 0


def _titel(lauf, ordner):
    try:
        zeit = datetime.fromisoformat(lauf["gestartet"]).strftime("%d.%m. %H:%M")
    except (KeyError, TypeError, ValueError):
        zeit = ordner
    notiz = lauf.get("notiz")
    return f"{zeit} - {notiz}" if notiz else zeit


def _werte(lauf):
    """Messwerte als {Punktname: dBm} fuer den Vergleich im Browser."""
    return {
        f"{m['raum']} {m.get('wo', '')}".strip(): m["rssi"]
        for m in lauf["messwerte"]
    }


def bauen(laeufe, ziel, uebersprungen=()):
    if not laeufe:
        inhalt = ("<p class='leer'>Noch keine darstellbare Messung. "
                  "Lauf einmal Modus 4 (Heatmap).</p>")
        karten = daten = "{}"
    else:
        karten = {l["ordner"]: heatmap.svg(l["messwerte"], l["plan"],
                                           kennung=f"-{i}")
                  for i, l in enumerate(laeufe)}
        daten = json.dumps(
            {l["ordner"]: {"titel": l["titel"], "werte": _werte(l)} for l in laeufe},
            ensure_ascii=False,
        )
        inhalt = "".join(
            f'<div class="karte" data-lauf="{l["ordner"]}">{karten[l["ordner"]]}</div>'
            for l in laeufe
        )
        karten = "ok"

    optionen = "".join(
        f'<option value="{l["ordner"]}">{l["titel"]}</option>' for l in laeufe
    )
    hinweis = ""
    if uebersprungen:
        namen = ", ".join(o for o, _ in uebersprungen)
        hinweis = (f'<p class="hinweis">Nicht darstellbar, weil mit einem anderen '
                   f'Grundriss gemessen: {namen}</p>')

    legende = "".join(
        f'<span class="feld"><i style="background:{heatmap.hex_farbe(g)}"></i>{g}</span>'
        for g, _ in heatmap.SKALA
    )

    html = f"""<!DOCTYPE html>
<html lang="de">
<meta charset="utf-8">
<title>WLAN-Messungen im Vergleich</title>
<style>{stil.CSS}
  .buehne {{ display: grid; gap: 18px; grid-template-columns: 1fr 1fr; }}
  @media (max-width: 880px) {{ .buehne {{ grid-template-columns: 1fr; }} }}
  .spalte h2 {{ font-size: 13px; margin: 0 0 9px; color: var(--leise);
                font-weight: 600; text-transform: uppercase;
                letter-spacing: .5px; }}
  .karte.bild {{ padding: 10px; }}
  .pane .karte {{ display: none; border: none; box-shadow: none;
                  background: none; padding: 0; }}
  .pane .karte.sichtbar {{ display: block; }}
  .pane svg {{ width: 100%; height: auto; display: block;
               border-radius: 11px; background: #fff; }}
  .bilanz {{ padding: 14px 16px; margin: 18px 0 14px; font-size: 14.5px; }}
  .leer {{ color: var(--leise); padding: 20px 0; }}
</style>
<div class="huelle">
<header>
  <h1>WLAN-Messungen im Vergleich</h1>
  <p>Links der frühere Stand, rechts der spätere. Darunter steht, was sich an
     jedem Messpunkt geändert hat — <strong>positiv heißt besser geworden</strong>,
     also stärkeres Signal.</p>
  {hinweis}
</header>
<div class="leiste karte">
  <div class="wahl"><label class="hinweisklein">Vorher</label><br>
    <select id="links">{optionen}</select></div>
  <div class="wahl"><label class="hinweisklein">Nachher</label><br>
    <select id="rechts">{optionen}</select></div>
</div>
<div class="legende karte">{legende}<span class="feld">dBm</span></div>
<div class="buehne">
  <div class="spalte"><h2 id="titelLinks"></h2>
    <div class="karte bild pane" id="paneLinks">{inhalt}</div></div>
  <div class="spalte"><h2 id="titelRechts"></h2>
    <div class="karte bild pane" id="paneRechts">{inhalt}</div></div>
</div>
<div class="bilanz karte" id="bilanz"></div>
<div class="karte" id="tabelle"></div>
</div>
<script>
const DATEN = {daten};

function zeigen(paneId, titelId, lauf) {{
  const pane = document.getElementById(paneId);
  pane.querySelectorAll('.karte').forEach(k => {{
    k.classList.toggle('sichtbar', k.dataset.lauf === lauf);
  }});
  document.getElementById(titelId).textContent = (DATEN[lauf] || {{}}).titel || '';
}}

function vergleichen() {{
  const a = document.getElementById('links').value;
  const b = document.getElementById('rechts').value;
  zeigen('paneLinks', 'titelLinks', a);
  zeigen('paneRechts', 'titelRechts', b);

  const bilanz = document.getElementById('bilanz');
  const tabelle = document.getElementById('tabelle');
  if (!DATEN[a] || !DATEN[b] || a === b) {{
    bilanz.textContent = a === b ? 'Beide Seiten zeigen dieselbe Messung.' : '';
    tabelle.innerHTML = '';
    return;
  }}

  const links = DATEN[a].werte, rechts = DATEN[b].werte;
  const zeilen = Object.keys(rechts)
    .filter(k => k in links)
    .map(k => ({{ punkt: k, vorher: links[k], nachher: rechts[k],
                 delta: rechts[k] - links[k] }}))
    .sort((x, y) => x.delta - y.delta);

  if (!zeilen.length) {{
    bilanz.textContent = 'Keine gemeinsamen Messpunkte - die beiden Laeufe sind nicht vergleichbar.';
    tabelle.innerHTML = '';
    return;
  }}

  const mittel = zeilen.reduce((s, z) => s + z.delta, 0) / zeilen.length;
  const besser = zeilen.filter(z => z.delta >= 3).length;
  const schlechter = zeilen.filter(z => z.delta <= -3).length;
  bilanz.innerHTML = `<strong>${{mittel >= 0 ? '+' : ''}}${{mittel.toFixed(1)}} dB im Mittel</strong>
    ueber ${{zeilen.length}} Punkte &middot; besser an ${{besser}}, schlechter an ${{schlechter}}
    (ab 3 dB gezaehlt)`;

  const klasse = d => d >= 3 ? 'besser' : d <= -3 ? 'schlechter' : 'gleich';
  tabelle.innerHTML = `<table><tr><th>Punkt</th><th>Vorher</th><th>Nachher</th>
    <th>Veraenderung</th></tr>` + zeilen.map(z =>
      `<tr><td>${{z.punkt}}</td><td class="zahl">${{z.vorher}} dBm</td>
       <td class="zahl">${{z.nachher}} dBm</td>
       <td class="zahl ${{klasse(z.delta)}}">${{z.delta >= 0 ? '+' : ''}}${{z.delta}} dB</td></tr>`
    ).join('') + '</table>';
}}

document.getElementById('links').addEventListener('change', vergleichen);
document.getElementById('rechts').addEventListener('change', vergleichen);
const auswahl = document.getElementById('links');
if (auswahl.options.length) {{
  auswahl.selectedIndex = 0;
  const r = document.getElementById('rechts');
  r.selectedIndex = r.options.length - 1;
  vergleichen();
}}
</script>
</html>
"""
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(html, encoding="utf-8")
    return ziel
