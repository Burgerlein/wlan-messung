"""Kleiner Editor im Browser: Messpunkte verschieben, benennen, ergaenzen.

Startet einen lokalen Webserver, der den Grundriss zeigt. Was dort gespeichert
wird, landet direkt in grundriss/plan.json.
"""

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import heatmap
import stil

WURZEL = Path(__file__).resolve().parent.parent
PLANDATEI = WURZEL / "grundriss" / "plan.json"


def _seite(plan, funkgeraete=()):
    punkte = plan["punkte"]
    b, h = plan["breite"], plan["hoehe"]
    # Nur Huelle und Vorlage kommen fertig vom Server. Raeume, Messpunkte und
    # Geraete zeichnet der Browser, damit sich Aenderungen sofort zeigen.
    nur_rahmen = dict(plan, raeume=[], teilflaechen=[], geraete=[], dosen=[])
    hintergrund = heatmap.svg([], nur_rahmen, kennung="-plan",
                              vorlage=heatmap.vorlage_finden())
    hintergrund = hintergrund.replace("<svg ", '<svg id="plan" class="plan" ', 1)
    raeumeliste = json.dumps(
        [{"name": r["name"], "x1": r["x1"], "y1": r["y1"], "x2": r["x2"],
          "y2": r["y2"], "extern": bool(r.get("extern"))}
         for r in plan.get("raeume", [])],
        ensure_ascii=False,
    )
    hat_vorlage = "true" if heatmap.vorlage_finden() else "false"

    daten = json.dumps(
        [{"raum": p["raum"], "wo": p["wo"], "x": p["x"], "y": p["y"],
          "ebene": p.get("ebene", "")} for p in punkte],
        ensure_ascii=False,
    )
    raeume = json.dumps([r["name"] for r in heatmap.wohnraeume(plan)], ensure_ascii=False)
    stellen = plan.get("geraete_positionen", {})
    # Bereits platzierte Geraete immer mitnehmen, auch wenn die FRITZ!Box sie
    # gerade nicht kennt - sonst verschwinden sie beim naechsten Speichern.
    liste = list(funkgeraete)
    bekannt = {g["name"] for g in liste}
    for name in stellen:
        if name not in bekannt:
            liste.append({"name": name, "beweglich": False, "verbunden": False,
                          "kabel": False})
    geraeteliste = json.dumps(
        [{"name": g["name"], "beweglich": g["beweglich"], "verbunden": g["verbunden"],
          "kabel": g.get("kabel", False),
          "x": stellen.get(g["name"], {}).get("x"),
          "y": stellen.get(g["name"], {}).get("y")}
         for g in liste],
        ensure_ascii=False,
    )
    infraliste = json.dumps(
        [{"name": d["name"], "art": d.get("art", ""), "x": d["x"], "y": d["y"]}
         for d in plan.get("geraete", [])],
        ensure_ascii=False,
    )

    return f"""<!DOCTYPE html>
<html lang="de">
<meta charset="utf-8">
<title>Messpunkte bearbeiten</title>
<style>{stil.CSS}
  .punkt {{ cursor: grab; }}
  .punkt.gewaehlt circle {{ stroke: #2563eb; stroke-width: 4; }}
  .punkt text {{ pointer-events: none; user-select: none; }}
  .geraet {{ cursor: grab; }}
  .geraet.gewaehlt rect {{ stroke: #2563eb; stroke-width: 4; }}
  .raum rect {{ cursor: move; }}
  .raum.gewaehlt > rect:first-child {{ stroke: #2563eb; stroke-width: 8; }}
  .griff {{ cursor: nwse-resize; }}
  svg {{ touch-action: none; }}
</style>
<div class="huelle">
<header>
  <h1>Grundriss bearbeiten</h1>
  <p>
    <strong>Ziehen</strong> verschiebt einen Punkt &middot;
    <strong>Klick</strong> wählt ihn aus &middot;
    <strong>Doppelklick auf freie Fläche</strong> legt einen neuen an &middot;
    <strong>Entf</strong> löscht den gewählten.<br>
    Punkte auf einer zweiten Ebene (Hochbett, Galerie) bekommen mit
    <strong>Obere Ebene</strong> einen gestrichelten Ring. So dürfen zwei Punkte
    an derselben Stelle liegen, einer unten und einer oben.
  </p>
</header>
<div class="leiste karte">
  <div class="reiter">
    <button id="modusRaeume">Räume</button>
    <button id="modusPunkte" class="haupt">Messpunkte</button>
    <button id="modusGeraete">Feste Geräte</button>
  </div>
  <span class="trenner"></span>
  <button id="neu">Punkt hinzufügen</button>
  <button id="extern" disabled>Nicht zur Wohnung</button>
  <button id="umbenennen" disabled>Umbenennen</button>
  <button id="ebene" disabled>Obere Ebene an/aus</button>
  <button id="loeschen" disabled>Löschen</button>
  <span class="trenner"></span>
  <button class="haupt" id="speichern">Speichern</button>
  <button id="zuruecksetzen">Zurücksetzen</button>
  <span id="stand"></span>
</div>
<div class="leiste karte" id="raeumeleiste" hidden>
  <span class="hinweisklein">Auf freier Fläche <strong>aufziehen</strong> legt
    einen Raum an &middot; <strong>ziehen</strong> verschiebt &middot; an der
    <strong>rechten unteren Ecke</strong> ziehen ändert die Größe</span>
  <span id="vorlageregler"></span>
</div>
<div class="leiste karte" id="geraeteleiste" hidden>
  <div style="width:100%">
    <p class="hinweisklein">FRITZ!Box und Repeater lassen sich direkt ziehen.
      Für die übrigen: Gerät anklicken, dann auf den Plan klicken.
      <button id="neuSuchen" style="margin-left:8px">Geräte neu suchen</button></p>
    <div><strong class="hinweisklein">Fest installiert</strong>
      <div id="offeneFest"></div></div>
    <div style="margin-top:8px"><strong class="hinweisklein">Beweglich &mdash;
      meist nicht sinnvoll</strong><div id="offeneMobil"></div></div>
  </div>
</div>
<div class="karte" style="padding:10px">{hintergrund}</div>
</div>
<script>
const RAEUME = {raeume};
let punkte = {daten};
let geraete = {geraeteliste};
let infra = {infraliste};
let raeume = {raeumeliste};
const HAT_VORLAGE = {hat_vorlage};
const anfang = JSON.parse(JSON.stringify(
  {{ punkte: punkte, geraete: geraete, infra: infra, raeume: raeume }}));
let modus = 'punkte', gewaehlt = null, gewaehltArt = 'punkt';
let zieht = null, chipGeraet = null;

const svg = document.getElementById('plan');
const ebene = document.createElementNS('http://www.w3.org/2000/svg', 'g');
svg.appendChild(ebene);
const B = svg.viewBox.baseVal.width, H = svg.viewBox.baseVal.height;
const NS = svg.namespaceURI;

function el(art, eigenschaften) {{
  const k = document.createElementNS(NS, art);
  for (const [name, wert] of Object.entries(eigenschaften)) k.setAttribute(name, wert);
  return k;
}}

function beschriftung(x, y, text, groesse) {{
  const t = el('text', {{ x: x, y: y, 'text-anchor': 'middle', 'font-size': groesse,
    fill: '#3f3f46', stroke: '#fff', 'stroke-width': 4, 'paint-order': 'stroke' }});
  t.textContent = text;
  return t;
}}

function zeichnen() {{
  ebene.innerHTML = '';
  const imRaummodus = modus === 'raeume';

  raeume.forEach((r, i) => {{
    const x = r.x1 * B, y = r.y1 * H;
    const breite = (r.x2 - r.x1) * B, hoehe = (r.y2 - r.y1) * H;
    const g = el('g', {{ class: 'raum' + (imRaummodus && gewaehltArt === 'raum'
                         && i === gewaehlt ? ' gewaehlt' : '') }});
    g.dataset.r = i;
    g.append(el('rect', {{
      x: x, y: y, width: Math.max(0, breite), height: Math.max(0, hoehe),
      fill: r.extern ? '#e4e4e7' : (imRaummodus ? '#eff6ff' : '#fbfbfc'),
      'fill-opacity': HAT_VORLAGE && !imRaummodus ? 0.55 : 1,
      stroke: '#374151', 'stroke-width': 6 }}));
    const schrift = Math.min(21, Math.max(11, breite / (r.name.length * 1.0)));
    const t = el('text', {{ x: x + breite / 2, y: y + schrift + 7,
      'text-anchor': 'middle', 'font-size': schrift, 'font-weight': 600,
      fill: r.extern ? '#a1a1aa' : '#6b7280' }});
    t.textContent = r.name.toUpperCase();
    g.append(t);
    if (imRaummodus) {{
      g.append(el('rect', {{ class: 'griff', x: x + breite - 11, y: y + hoehe - 11,
        width: 22, height: 22, rx: 4, fill: '#2563eb', stroke: '#fff',
        'stroke-width': 2 }}));
    }}
    ebene.appendChild(g);
  }});

  const blass = modus === 'punkte' ? 1 : 0.3;
  punkte.forEach((p, i) => {{
    const obenauf = p.ebene === 'oben';
    const g = el('g', {{ class: 'punkt' + (modus === 'punkte' && gewaehltArt === 'punkt'
                         && i === gewaehlt ? ' gewaehlt' : ''), opacity: blass }});
    g.dataset.i = i;
    g.append(
      el('circle', {{ cx: p.x * B, cy: p.y * H, r: 17,
                     fill: obenauf ? '#eef2ff' : '#fff', stroke: '#111827',
                     'stroke-width': 2.5,
                     'stroke-dasharray': obenauf ? '5 4' : 'none' }}),
      Object.assign(el('text', {{ x: p.x * B, y: p.y * H + 6, 'text-anchor': 'middle',
        'font-size': 18, 'font-weight': 700 }}), {{ textContent: i + 1 }}),
      beschriftung(p.x * B, p.y * H - 23,
                   (obenauf ? '\u2191 ' : '') + (p.wo || p.raum), 15));
    ebene.appendChild(g);
  }});

  infra.forEach((d, i) => {{
    const g = el('g', {{ class: 'geraet' + (modus === 'geraete' && gewaehltArt === 'infra'
                         && i === gewaehlt ? ' gewaehlt' : ''),
                         opacity: modus === 'geraete' ? 1 : 0.4 }});
    g.dataset.infra = i;
    const ton = d.art === 'router' ? '#1d4ed8' : '#7c3aed';
    g.append(
      el('rect', {{ x: d.x * B - 15, y: d.y * H - 15, width: 30, height: 30, rx: 7,
                   fill: ton, stroke: '#fff', 'stroke-width': 3 }}),
      beschriftung(d.x * B, d.y * H + 36, d.name, 15));
    ebene.appendChild(g);
  }});

  geraete.forEach((d, i) => {{
    if (d.x === null || d.x === undefined) return;
    const g = el('g', {{ class: 'geraet' + (modus === 'geraete' && gewaehltArt === 'geraet'
                         && i === gewaehlt ? ' gewaehlt' : ''),
                         opacity: modus === 'geraete' ? 1 : 0.35 }});
    g.dataset.g = i;
    g.append(
      el('rect', {{ x: d.x * B - 13, y: d.y * H - 13, width: 26, height: 26, rx: 6,
                   fill: '#0f766e', stroke: '#fff', 'stroke-width': 3 }}),
      beschriftung(d.x * B, d.y * H + 32, d.name, 14));
    ebene.appendChild(g);
  }});

  const etwasGewaehlt = gewaehlt !== null;
  document.getElementById('umbenennen').disabled =
    !(etwasGewaehlt && (gewaehltArt === 'punkt' || gewaehltArt === 'raum'));
  document.getElementById('ebene').disabled =
    !(etwasGewaehlt && gewaehltArt === 'punkt');
  document.getElementById('extern').disabled =
    !(etwasGewaehlt && gewaehltArt === 'raum');
  document.getElementById('loeschen').disabled =
    !etwasGewaehlt || gewaehltArt === 'infra';
  document.getElementById('neu').disabled = modus !== 'punkte';
  chips();
}}

function chips() {{
  const fest = document.getElementById('offeneFest');
  const mobil = document.getElementById('offeneMobil');
  if (!fest || !mobil) return;
  fest.innerHTML = ''; mobil.innerHTML = '';
  geraete.forEach((d, i) => {{
    if (d.x !== null && d.x !== undefined) return;
    const c = document.createElement('span');
    c.className = 'chip' + (chipGeraet === i ? ' aktiv' : '');
    c.textContent = d.name + (d.kabel ? ' [Kabel]' : '') + (d.verbunden ? '' : ' (aus)');
    c.onclick = () => {{ chipGeraet = (chipGeraet === i ? null : i); chips(); }};
    (d.beweglich ? mobil : fest).appendChild(c);
  }});
  if (!fest.children.length) fest.innerHTML =
    '<span class="hinweisklein">Alle fest installierten Geräte sind platziert.</span>';
  if (!mobil.children.length) mobil.innerHTML =
    '<span class="hinweisklein">keine</span>';
}}

function stelle(e) {{
  const o = Object.assign(svg.createSVGPoint(), {{ x: e.clientX, y: e.clientY }})
    .matrixTransform(svg.getScreenCTM().inverse());
  return {{ x: +Math.min(1, Math.max(0, o.x / B)).toFixed(4),
           y: +Math.min(1, Math.max(0, o.y / H)).toFixed(4) }};
}}

function listeVon(art) {{
  return art === 'punkt' ? punkte : art === 'infra' ? infra : geraete;
}}

let zieheRaum = null;   // {{ art: 'neu'|'verschieben'|'groesse', start, anfang }}

svg.addEventListener('pointerdown', e => {{
  const o = stelle(e);

  if (modus === 'raeume') {{
    const griff = e.target.closest('.griff');
    const raum = e.target.closest('.raum');
    if (griff && raum) {{
      gewaehlt = +raum.dataset.r; gewaehltArt = 'raum';
      zieheRaum = {{ art: 'groesse' }};
    }} else if (raum) {{
      gewaehlt = +raum.dataset.r; gewaehltArt = 'raum';
      const r = raeume[gewaehlt];
      zieheRaum = {{ art: 'verschieben', start: o,
                    anfang: {{ x1: r.x1, y1: r.y1, x2: r.x2, y2: r.y2 }} }};
    }} else {{
      raeume.push({{ name: 'Neuer Raum', x1: o.x, y1: o.y, x2: o.x, y2: o.y,
                    extern: false }});
      gewaehlt = raeume.length - 1; gewaehltArt = 'raum';
      zieheRaum = {{ art: 'neu', start: o }};
    }}
    svg.setPointerCapture(e.pointerId); zeichnen(); melden(''); e.preventDefault();
    return;
  }}

  if (modus === 'geraete' && chipGeraet !== null) {{
    geraete[chipGeraet].x = o.x; geraete[chipGeraet].y = o.y;
    gewaehlt = chipGeraet; gewaehltArt = 'geraet'; chipGeraet = null;
    zeichnen(); melden(''); return;
  }}
  const ziel = e.target.closest(modus === 'punkte' ? '.punkt' : '.geraet');
  if (!ziel) return;
  if (modus === 'punkte') {{
    gewaehltArt = 'punkt'; gewaehlt = +ziel.dataset.i;
  }} else if (ziel.dataset.infra !== undefined) {{
    gewaehltArt = 'infra'; gewaehlt = +ziel.dataset.infra;
  }} else {{
    gewaehltArt = 'geraet'; gewaehlt = +ziel.dataset.g;
  }}
  zieht = gewaehlt;
  svg.setPointerCapture(e.pointerId); zeichnen(); e.preventDefault();
}});

svg.addEventListener('pointermove', e => {{
  const o = stelle(e);
  if (zieheRaum) {{
    const r = raeume[gewaehlt];
    if (zieheRaum.art === 'neu' || zieheRaum.art === 'groesse') {{
      const anker = zieheRaum.art === 'neu'
        ? zieheRaum.start : {{ x: r.x1, y: r.y1 }};
      r.x1 = +Math.min(anker.x, o.x).toFixed(4);
      r.y1 = +Math.min(anker.y, o.y).toFixed(4);
      r.x2 = +Math.max(anker.x, o.x).toFixed(4);
      r.y2 = +Math.max(anker.y, o.y).toFixed(4);
    }} else {{
      const dx = o.x - zieheRaum.start.x, dy = o.y - zieheRaum.start.y;
      const a = zieheRaum.anfang;
      r.x1 = +(a.x1 + dx).toFixed(4); r.x2 = +(a.x2 + dx).toFixed(4);
      r.y1 = +(a.y1 + dy).toFixed(4); r.y2 = +(a.y2 + dy).toFixed(4);
    }}
    zeichnen(); melden(''); return;
  }}
  if (zieht === null) return;
  const liste = listeVon(gewaehltArt);
  liste[zieht].x = o.x; liste[zieht].y = o.y;
  zeichnen(); melden('');
}});

svg.addEventListener('pointerup', e => {{
  if (zieheRaum) {{
    const r = raeume[gewaehlt];
    if (zieheRaum.art === 'neu') {{
      if ((r.x2 - r.x1) < 0.03 || (r.y2 - r.y1) < 0.03) {{
        raeume.pop(); gewaehlt = null;      // zu klein, war wohl ein Fehlklick
      }} else {{
        const name = prompt('Wie heisst der Raum?', 'Neuer Raum');
        if (name) r.name = name; else raeume.pop(), gewaehlt = null;
      }}
    }}
    zieheRaum = null; svg.releasePointerCapture(e.pointerId); zeichnen(); return;
  }}
  if (zieht !== null) {{ zieht = null; svg.releasePointerCapture(e.pointerId); }}
}});

svg.addEventListener('dblclick', e => {{
  if (modus !== 'punkte' || e.target.closest('.punkt')) return;
  punktAnlegen(stelle(e));
}});

function punktAnlegen(o) {{
  const liste = raeume.filter(r => !r.extern).map(r => r.name);
  const raum = prompt('In welchem Raum liegt der Punkt?\\n\\n' + liste.join(', '),
                      liste[0] || '');
  if (!raum) return;
  const wo = prompt('Wie heisst die Stelle? (z.B. "am Herd")', '') || '';
  punkte.push({{ raum: raum, wo: wo, x: o.x, y: o.y }});
  gewaehlt = punkte.length - 1; gewaehltArt = 'punkt'; zeichnen(); melden('');
}}

document.getElementById('neu').onclick = () => punktAnlegen({{ x: 0.5, y: 0.5 }});
document.addEventListener('keydown', e => {{
  if ((e.key === 'Delete' || e.key === 'Backspace') && gewaehlt !== null
      && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) {{
    loeschen(); e.preventDefault();
  }}
}});
function loeschen() {{
  if (gewaehlt === null) return;
  if (gewaehltArt === 'punkt') punkte.splice(gewaehlt, 1);
  else if (gewaehltArt === 'raum') raeume.splice(gewaehlt, 1);
  else if (gewaehltArt === 'geraet') {{
    geraete[gewaehlt].x = null; geraete[gewaehlt].y = null;
  }} else return;        // FRITZ!Box und Repeater gehoeren immer auf den Plan
  gewaehlt = null; zeichnen(); melden('');
}}
document.getElementById('loeschen').onclick = loeschen;
document.getElementById('extern').onclick = () => {{
  const r = raeume[gewaehlt];
  r.extern = !r.extern; zeichnen(); melden('');
}};
document.getElementById('ebene').onclick = () => {{
  const p = punkte[gewaehlt];
  p.ebene = p.ebene === 'oben' ? '' : 'oben';
  zeichnen(); melden('');
}};
document.getElementById('umbenennen').onclick = () => {{
  if (gewaehltArt === 'raum') {{
    const name = prompt('Wie heisst der Raum?', raeume[gewaehlt].name);
    if (name) raeume[gewaehlt].name = name;
  }} else {{
    const p = punkte[gewaehlt];
    const raum = prompt('Raum:', p.raum); if (raum === null) return;
    const wo = prompt('Stelle:', p.wo); if (wo === null) return;
    p.raum = raum; p.wo = wo;
  }}
  zeichnen(); melden('');
}};
document.getElementById('zuruecksetzen').onclick = () => {{
  const k = JSON.parse(JSON.stringify(anfang));
  punkte = k.punkte; geraete = k.geraete; infra = k.infra; raeume = k.raeume;
  gewaehlt = null; chipGeraet = null;
  zeichnen(); melden('Zurückgesetzt - noch nicht gespeichert.');
}};

function modusSetzen(neu) {{
  modus = neu; gewaehlt = null; chipGeraet = null;
  gewaehltArt = neu === 'punkte' ? 'punkt' : neu === 'raeume' ? 'raum' : 'geraet';
  for (const [knopf, name] of [['modusRaeume', 'raeume'],
                               ['modusPunkte', 'punkte'],
                               ['modusGeraete', 'geraete']]) {{
    document.getElementById(knopf).classList.toggle('haupt', neu === name);
  }}
  document.getElementById('raeumeleiste').hidden = neu !== 'raeume';
  document.getElementById('geraeteleiste').hidden = neu !== 'geraete';
  zeichnen();
}}
document.getElementById('modusRaeume').onclick = () => modusSetzen('raeume');
document.getElementById('modusPunkte').onclick = () => modusSetzen('punkte');
document.getElementById('modusGeraete').onclick = () => modusSetzen('geraete');

document.getElementById('neuSuchen').onclick = async () => {{
  melden('Suche ...');
  const antwort = await fetch('/geraete');
  if (!antwort.ok) {{ melden('Suche fehlgeschlagen.'); return; }}
  const frisch = await antwort.json();
  const stellen = {{}};
  geraete.forEach(d => {{ if (d.x !== null && d.x !== undefined) stellen[d.name] = d; }});
  geraete = frisch.map(g => ({{
    name: g.name, beweglich: g.beweglich, verbunden: g.verbunden, kabel: g.kabel,
    x: (stellen[g.name] || {{}}).x ?? null, y: (stellen[g.name] || {{}}).y ?? null
  }}));
  Object.values(stellen).forEach(d => {{
    if (!geraete.some(g => g.name === d.name)) geraete.push(d);
  }});
  gewaehlt = null; chipGeraet = null; zeichnen();
  melden(geraete.length + ' Geräte gefunden.');
}};

function melden(text) {{ document.getElementById('stand').textContent = text; }}

document.getElementById('speichern').onclick = async () => {{
  const stellen = {{}};
  geraete.forEach(d => {{
    if (d.x !== null && d.x !== undefined) stellen[d.name] = {{ x: d.x, y: d.y }};
  }});
  const antwort = await fetch('/speichern', {{
    method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ punkte: punkte, geraete: stellen, infra: infra,
                           raeume: raeume }})
  }});
  melden(antwort.ok
    ? raeume.length + ' Räume, ' + punkte.length + ' Punkte und '
      + Object.keys(stellen).length + ' Geräte gespeichert.'
    : 'Speichern fehlgeschlagen.');
}};

modusSetzen('punkte');
</script>
</html>
"""


def _speichern(nutzlast):
    """Schreibt Punkte und Geraetestellen fest in plan.json."""
    plan = json.loads(PLANDATEI.read_text(encoding="utf-8"))
    plan["punkte"] = [
        {"raum": p["raum"], "wo": p.get("wo", ""),
         "x": round(float(p["x"]), 4), "y": round(float(p["y"]), 4),
         **({"ebene": "oben"} if p.get("ebene") == "oben" else {})}
        for p in nutzlast.get("punkte", [])
    ]
    plan["geraete_positionen"] = {
        name: {"x": round(float(s["x"]), 4), "y": round(float(s["y"]), 4)}
        for name, s in (nutzlast.get("geraete") or {}).items()
    }
    raeume = nutzlast.get("raeume")
    if raeume is not None:
        alt = {r["name"]: r for r in plan.get("raeume", [])}
        neue = []
        for r in raeume:
            x1, x2 = sorted((round(float(r["x1"]), 4), round(float(r["x2"]), 4)))
            y1, y2 = sorted((round(float(r["y1"]), 4), round(float(r["y2"]), 4)))
            eintrag = {"name": r["name"], "x1": x1, "y1": y1, "x2": x2, "y2": y2}
            if r.get("extern"):
                eintrag["extern"] = True
            neue.append(eintrag)
        plan["raeume"] = neue
        # Teilflaechen eines geloeschten Raums mitnehmen
        namen = {r["name"] for r in neue}
        plan["teilflaechen"] = [t for t in plan.get("teilflaechen", [])
                                if t.get("raum") in namen]

    stellen = {d["name"]: d for d in (nutzlast.get("infra") or [])}
    for geraet in plan.get("geraete", []):
        neu = stellen.get(geraet["name"])
        if neu:
            geraet["x"] = round(float(neu["x"]), 4)
            geraet["y"] = round(float(neu["y"]), 4)
    PLANDATEI.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    return (len(plan["punkte"]), len(plan["geraete_positionen"]),
            len(plan.get("raeume", [])))


def geraete_holen():
    """Alle Geraete, die die FRITZ!Box kennt - per Funk wie per Kabel.

    Kabelgeraete lassen sich ebenfalls einzeichnen; sie liefern zwar keinen
    Signalwert fuer die Karte, zeigen aber, was wo steht.
    """
    import fritzbox as fb
    import geraete as geraete_modul

    umgebung = fb.lade_env(WURZEL / ".env")
    try:
        box = fb.Fritzbox(umgebung.get("FRITZBOX_HOST", "fritz.box"),
                          umgebung.get("FRITZBOX_USER"),
                          umgebung.get("FRITZBOX_PASSWORT"))
        mesh = box.mesh_liste()
    except fb.FritzboxFehler:
        return []

    punkte = fb.zugangspunkte(mesh)
    gefunden = {}
    for knoten in mesh.get("nodes", []):
        if knoten["uid"] in punkte:
            continue
        schnittstellen = knoten.get("node_interfaces", [])
        arten = {s.get("type") for s in schnittstellen}
        if not arten & {"WLAN", "LAN"}:
            continue
        name = (knoten.get("device_name") or knoten.get("device_friendly_name")
                or "").strip()
        if not name or name.startswith("<"):
            continue
        verbunden = any(l.get("state") == "CONNECTED"
                        for s in schnittstellen for l in (s.get("node_links") or []))
        eintrag = gefunden.setdefault(
            name, {"name": name, "verbunden": False, "kabel": "WLAN" not in arten})
        eintrag["verbunden"] |= verbunden

    liste = list(gefunden.values())
    for g in liste:
        g["beweglich"] = geraete_modul.beweglich(g["name"]) and not g["kabel"]
    liste.sort(key=lambda g: (g["beweglich"], not g["verbunden"], g["name"].lower()))
    return liste


# Alter Name, damit bestehende Aufrufe weiterlaufen
funkgeraete_holen = geraete_holen


def starten(port=8765, melden=print, browser_oeffnen=True):
    geraete = geraete_holen()

    class Griff(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path.startswith("/geraete"):
                return self.do_GET_geraete()
            # Bei jedem Aufruf frisch bauen, damit ein Neuladen den
            # gespeicherten Stand zeigt und nicht den vom Programmstart.
            seite = _seite(heatmap.plan_laden(), geraete).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(seite)))
            self.end_headers()
            self.wfile.write(seite)

        def do_GET_geraete(self):
            inhalt = json.dumps(geraete_holen(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(inhalt)))
            self.end_headers()
            self.wfile.write(inhalt)

        def do_POST(self):
            laenge = int(self.headers.get("Content-Length", 0))
            try:
                nutzlast = json.loads(self.rfile.read(laenge).decode("utf-8"))
                punkte, stellen, raeume = _speichern(nutzlast)
            except (ValueError, KeyError, TypeError, OSError) as fehler:
                self.send_response(400)
                self.end_headers()
                melden(f"  Speichern fehlgeschlagen: {fehler}")
                return
            self.send_response(200)
            self.end_headers()
            melden(f"  {raeume} Raeume, {punkte} Punkte und "
                   f"{stellen} Geraete gespeichert.")

    class StillerServer(HTTPServer):
        def handle_error(self, anfrage, adresse):
            # Abgebrochene Browser-Anfragen sind normal und kein Grund,
            # dem Benutzer einen Fehlerbericht hinzuwerfen.
            import sys as _sys
            if not isinstance(_sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
                super().handle_error(anfrage, adresse)

    server = StillerServer(("127.0.0.1", port), Griff)
    adresse = f"http://127.0.0.1:{port}/"
    melden(f"  Editor laeuft: {adresse}")
    melden("  Strg-C beendet ihn.\n")
    if browser_oeffnen:
        threading.Timer(0.6, lambda: webbrowser.open(adresse)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        melden("\n  Editor beendet.")
    finally:
        server.server_close()
