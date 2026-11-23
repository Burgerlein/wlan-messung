"""Haengt eine alte Messung an eine neue Messpunkt-Anordnung.

Wer die Punkte im Editor verschiebt oder umbenennt, verliert sonst die
Vergleichbarkeit mit frueheren Messungen. Hier wird jeder alte Messwert dem
raeumlich naechstgelegenen neuen Punkt zugeordnet - aber nur, wenn der nah
genug liegt. Alles andere bleibt unzugeordnet und wird benannt.
"""

import json
from pathlib import Path

# Hoechstabstand als Anteil der Plandiagonale. 0.05 entspricht in einer
# Wohnung dieser Groesse rund einem Meter.
HOECHSTABSTAND = 0.05


def _abstand(a, b):
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5


def _name(eintrag):
    return f"{eintrag['raum']} {eintrag.get('wo', '')}".strip()


def zuordnen(messwerte, plan, hoechstabstand=HOECHSTABSTAND):
    """Ordnet Messwerte den Punkten des neuen Plans zu.

    Zuerst ueber den Namen: Wer einen Punkt im Editor nur verschiebt, behaelt
    seine Bezeichnung - dann ist die Zuordnung eindeutig, egal wie weit er
    gewandert ist. Erst fuer den Rest entscheidet die Entfernung.
    """
    treffer = []
    offen_m = set(range(len(messwerte)))
    offen_p = set(range(len(plan["punkte"])))

    nach_name = {}
    for j, punkt in enumerate(plan["punkte"]):
        nach_name.setdefault(_name(punkt), j)

    def uebernehmen(i, j):
        alt, neu_punkt = messwerte[i], plan["punkte"][j]
        treffer.append({
            **alt,
            "nr": neu_punkt["nr"],
            "raum": neu_punkt["raum"],
            "wo": neu_punkt["wo"],
            "x": neu_punkt["x"],
            "y": neu_punkt["y"],
            "ebene": neu_punkt.get("ebene", ""),
            "abstand": round(_abstand(alt, neu_punkt), 4),
            "frueher": _name(alt),
        })
        offen_m.discard(i)
        offen_p.discard(j)

    for i, messwert in enumerate(messwerte):
        j = nach_name.get(_name(messwert))
        if j is not None and j in offen_p:
            uebernehmen(i, j)

    # Was uebrig bleibt, ueber die Entfernung - die naechsten Paare zuerst
    kandidaten = sorted(
        ((_abstand(messwerte[i], plan["punkte"][j]), i, j)
         for i in offen_m for j in offen_p),
        key=lambda k: k[0],
    )
    for abstand, i, j in kandidaten:
        if abstand > hoechstabstand or i not in offen_m or j not in offen_p:
            continue
        uebernehmen(i, j)

    treffer.sort(key=lambda m: m["nr"])
    verwaist = [messwerte[i] for i in sorted(offen_m)]
    ohne_messwert = [plan["punkte"][j] for j in sorted(offen_p)]
    return treffer, verwaist, ohne_messwert


def anwenden(ordner, plan, hoechstabstand=HOECHSTABSTAND, melden=print):
    """Schreibt die Zuordnung in die Messung - mit Sicherung des Originals."""
    ordner = Path(ordner)
    datei = ordner / "messung.json"
    lauf = json.loads(datei.read_text(encoding="utf-8"))
    messwerte = [m for m in (lauf.get("messwerte") or []) if m.get("x") is not None]
    if not messwerte:
        melden("  Diese Messung hat keine Punkte mit Position - nichts umzuhaengen.")
        return None

    treffer, verwaist, ohne = zuordnen(messwerte, plan, hoechstabstand)

    sicherung = ordner / "messung-original.json"
    if not sicherung.exists():
        sicherung.write_text(datei.read_text(encoding="utf-8"), encoding="utf-8")

    lauf["messwerte"] = treffer
    lauf["plan"] = plan
    lauf["umgehaengt"] = {
        "zugeordnet": len(treffer),
        "verwaist": [f"{m['raum']} {m.get('wo', '')}".strip() for m in verwaist],
        "ohne_messwert": [f"{p['raum']} {p['wo']}".strip() for p in ohne],
        "hoechstabstand": hoechstabstand,
    }
    datei.write_text(json.dumps(lauf, indent=2, ensure_ascii=False), encoding="utf-8")
    return treffer, verwaist, ohne, sicherung
