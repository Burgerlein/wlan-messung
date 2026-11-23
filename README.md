# WifiOptimizer

Findet heraus, warum Videoanrufe zu Hause abreißen — und belegt es mit Zahlen
statt mit Vermutungen.

Das Werkzeug misst die WLAN-Versorgung einer Wohnung, liest parallel die
FRITZ!Box aus und bringt beides zusammen: Was empfängt mein Rechner gerade, an
welchem Zugangspunkt hängt er, und hält die Verbindung überhaupt durch? Das
Ergebnis ist eine Heatmap auf dem Grundriss und ein Bericht mit konkreten
Maßnahmen.

Entstanden ist es aus einem echten Fall: wiederkehrende Aussetzer in
Teams-Anrufen, bei denen Speedtest und Signalstärke unauffällig aussahen. Die
Ursache war am Ende ein Repeater, dessen Netzwerkbuchse alle 40 Sekunden für
vier Sekunden ausfiel — sichtbar nur, weil durchgehend mitgemessen wurde.

## Was es misst

**Vom Mac**, im Sekundentakt: Signalstärke, Rauschen, Störabstand, Band, Kanal,
Kanalbreite, WLAN-Standard, Übertragungsrate und die Kennung des verbundenen
Zugangspunkts.

**Von der FRITZ!Box**: Mesh-Aufbau, Kanalbelegung aller Funkmodule, das
WLAN-Ereignisprotokoll (inklusive Zwangskanalwechseln durch Radarerkennung),
die Anbindung jedes einzelnen Geräts und der Zustand der Kabelstrecken.

**Für die Anrufqualität**: Laufzeit, Schwankung und Paketverlust, gemessen
getrennt bis zur FRITZ!Box und bis ins Internet. Erst diese Trennung zeigt, ob
ein Problem im Funk liegt oder dahinter.

## Messmodi

| Modus | Wofür |
|---|---|
| **Punktmessung** | An einem Ort stehen bleiben, 15 Sekunden, belastbare Werte |
| **Durchlauf** | Durch die Wohnung laufen, Dauerping findet Abrisse sekundengenau |
| **Diagnose** | Nur die FRITZ!Box auslesen |
| **Heatmap** | Geführt Punkt für Punkt, ergibt die Karte |
| **Schnellblick** | Grobe Karte aus fest installierten Geräten, ohne zu laufen |

Dazu eine **Wache**, die Ausfälle protokolliert, die die FRITZ!Box selbst nicht
meldet, und ein **Kabeltest** für Netzwerkdosen — mit Kontrollmessung, damit
sich ein Kabelfehler von einer Funkstörung unterscheiden lässt.

## Voraussetzungen

- **macOS** mit Xcode-Befehlszeilenwerkzeugen. Ein kleiner Swift-Helfer wird
  beim ersten Start automatisch übersetzt; er liest die WLAN-Werte in 50
  Millisekunden statt der sechs Sekunden, die `system_profiler` braucht.
- **Eine FRITZ!Box**, erreichbar im Netz, mit aktivierter Anwendungs­schnittstelle
  (*Heimnetz → Netzwerk → Netzwerkeinstellungen → Zugriff für Anwendungen
  zulassen*).
- Sonst nichts. Kein `pip install`, keine Fremdbibliotheken — ausschließlich
  Python-Standardbibliothek.

## Einrichtung

```bash
cp .env.example .env     # und Zugangsdaten eintragen
python3 wlanmess.py
```

Die `.env`:

```
FRITZBOX_HOST=fritz.box
FRITZBOX_USER=<Benutzername>
FRITZBOX_PASSWORT=<Passwort>
```

Den Grundriss beschreibt `grundriss/plan.json` als Rechtecke — die
mitgelieferte Datei ist ein Beispiel, das du durch deine eigene Wohnung
ersetzt. Dafür gibt es einen Editor im Browser:

```bash
python3 wlanmess.py --bearbeiten
```

Ziehen verschiebt Messpunkte, Doppelklick legt neue an, Geräte und Repeater
lassen sich platzieren. Gespeichert wird direkt in `plan.json`.

## Alle Aufrufe

```bash
python3 wlanmess.py                      # Messmodi zur Auswahl
python3 wlanmess.py --bearbeiten         # Messpunkte und Geräte im Browser
python3 wlanmess.py --karte              # Messpunktkarte erzeugen
python3 wlanmess.py --geraete            # wer hängt wo im Netz
python3 wlanmess.py --funkkarte          # Karte aus festen Geräten
python3 wlanmess.py --wache [min] [s]    # Netz beobachten, Ausfälle festhalten
python3 wlanmess.py --kabeltest [gerät]  # Netzwerkdose prüfen
python3 wlanmess.py --leitung [min]      # eigene Leitung zur FRITZ!Box messen
python3 wlanmess.py --vergleich <a> <b>  # zwei Messungen gegenüberstellen
python3 wlanmess.py --uebersicht         # Vergleichsseite für alle Rundgänge
python3 wlanmess.py --umhaengen <ordner> # Messung auf geänderte Punkte legen
python3 wlanmess.py --neu <ordner>       # Messung neu auswerten
python3 wlanmess.py --standort           # Ortungsfreigabe anfordern
```

## Was es nicht kann

- **Nur macOS.** Der Helfer nutzt CoreWLAN.
- **Nur FRITZ!Box.** Die halbe Aussagekraft kommt aus deren Mesh-Daten.
- **Keine Höhenmessung.** Eine zweite Ebene (Hochbett, Galerie) lässt sich
  markieren, aber der Grundriss bleibt zweidimensional.
- **Die Werte fester Geräte sind untereinander nicht vergleichbar.** Ein
  Lautsprecher sendet schwächer als ein Laptop. Für denselben Ort über die Zeit
  taugen sie, für den Vergleich zweier Orte nicht.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
