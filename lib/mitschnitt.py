"""Dauerhafter Ping im Hintergrund, um Verbindungsabrisse zeitgenau zu finden."""

import re
import subprocess
import threading
import time

SEQ_MUSTER = re.compile(r"icmp_seq=(\d+).*?time=([\d.]+)\s*ms")


class Dauerping:
    """Pingt durchgehend und merkt sich, welche Pakete verloren gingen."""

    def __init__(self, ziel="fritz.box", abstand_s=0.5):
        self.ziel = ziel
        self.abstand_s = abstand_s
        self.start_zeit = None
        self.antworten = {}       # seq -> (zeitpunkt, laufzeit_ms)
        self._prozess = None
        self._faden = None
        self._laeuft = False

    def starten(self):
        self.start_zeit = time.time()
        self._prozess = subprocess.Popen(
            ["ping", "-i", str(self.abstand_s), "-W", "1000", self.ziel],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._laeuft = True
        self._faden = threading.Thread(target=self._lesen, daemon=True)
        self._faden.start()

    def _lesen(self):
        for zeile in self._prozess.stdout:
            if not self._laeuft:
                break
            treffer = SEQ_MUSTER.search(zeile)
            if treffer:
                self.antworten[int(treffer.group(1))] = (
                    time.time(),
                    float(treffer.group(2)),
                )

    def stoppen(self):
        self._laeuft = False
        if self._prozess and self._prozess.poll() is None:
            self._prozess.terminate()
            try:
                self._prozess.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._prozess.kill()

    # -- Auswertung ----------------------------------------------------

    def ausfaelle(self, mindestluecke=2):
        """Zusammenhaengende Luecken, umgerechnet in Sekunden."""
        if not self.antworten:
            return []
        hoechste = max(self.antworten)
        fehlend = sorted(set(range(hoechste + 1)) - set(self.antworten))
        if not fehlend:
            return []

        gruppen, aktuell = [], [fehlend[0]]
        for seq in fehlend[1:]:
            if seq == aktuell[-1] + 1:
                aktuell.append(seq)
            else:
                gruppen.append(aktuell)
                aktuell = [seq]
        gruppen.append(aktuell)

        return [
            {
                "ab_sekunde": round(g[0] * self.abstand_s, 1),
                "dauer_s": round(len(g) * self.abstand_s, 1),
                "pakete": len(g),
            }
            for g in gruppen
            if len(g) >= mindestluecke
        ]

    def zusammenfassung(self):
        if not self.antworten:
            return {"pakete": 0, "verlust_prozent": 100.0, "ausfaelle": []}
        hoechste = max(self.antworten) + 1
        verloren = hoechste - len(self.antworten)
        laufzeiten = [t for _, t in self.antworten.values()]
        return {
            "pakete": hoechste,
            "empfangen": len(self.antworten),
            "verlust_prozent": round(100 * verloren / hoechste, 2),
            "laufzeit_mittel_ms": round(sum(laufzeiten) / len(laufzeiten), 1),
            "laufzeit_max_ms": round(max(laufzeiten), 1),
            "ausfaelle": self.ausfaelle(),
        }
