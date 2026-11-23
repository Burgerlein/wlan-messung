# Bildmaterial

Alles hier ist **veröffentlichungsfertig**: Der Grundriss ist die
Beispielwohnung, Gerätenamen und Netzwerkname sind ersetzt. Die Messwerte
selbst sind echt.

## Karten

| Datei | Inhalt |
|---|---|
| `heatmap.png` | Heatmap auf dem Grundriss, 40 Messpunkte |
| `messpunkte.png` | derselbe Grundriss ohne Werte, nur die Punkte |
| `editor.png` | der Editor im Browser |

## Konsole

| Datei | Inhalt |
|---|---|
| `konsole/punktmessung.png` | kompletter Ablauf: Start, Diagnose, Menü, Messung mit Urteil |
| `konsole/befunde.png` | die Befunde eines Laufs, nach Gewicht eingefärbt |
| `konsole/wache.png` | **der dramatische Moment** — Kanalwechsel und zwei Kabelabrisse |
| `konsole/vergleich.png` | zwei Messungen gegenübergestellt, Delta je Punkt |
| `konsole/geraete.png` | alle Geräte im Netz, nach Zugangspunkt gruppiert |

## Neu erzeugen

```bash
FORCE_COLOR=1 python3 wlanmess.py --geraete \
  | python3 veroeffentlichung/anonymisieren.py \
  | python3 veroeffentlichung/konsolenbild.py "wlanmess.py --geraete" > /tmp/bild.html

"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
  --screenshot=bild.png --window-size=1000,840 --hide-scrollbars file:///tmp/bild.html
```

`anonymisieren.py` ersetzt Netzwerkname, Gerätenamen und Pfade.
**Prüf das Ergebnis trotzdem von Hand** — es kennt nur die Namen, die es kennt.
