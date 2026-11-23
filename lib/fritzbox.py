"""Zugriff auf die FRITZ!Box ueber TR-064 (nur Standardbibliothek)."""

import hashlib
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

PORT = 49000
TIMEOUT = 8


class FritzboxFehler(Exception):
    pass


def lade_env(pfad=".env"):
    """Liest eine einfache SCHLUESSEL=WERT-Datei ein."""
    werte = {}
    datei = Path(pfad)
    if not datei.exists():
        return werte
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        schluessel, wert = zeile.split("=", 1)
        werte[schluessel.strip()] = wert.strip().strip('"').strip("'")
    return werte


class Fritzbox:
    def __init__(self, host, benutzer, passwort):
        self.host = host
        self.basis = f"http://{host}:{PORT}"
        # Die FRITZ!Box meldet sich je nach Dienst mit verschiedenen Realms,
        # deshalb ein Passwortspeicher ohne feste Realm-Bindung.
        speicher = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        speicher.add_password(None, self.basis, benutzer, passwort)
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPDigestAuthHandler(speicher),
            urllib.request.HTTPBasicAuthHandler(speicher),
        )

    # -- Grundlagen ----------------------------------------------------

    def _soap(self, control_url, service, aktion, argumente=None):
        argumente = argumente or {}
        inhalt = "".join(f"<{k}>{v}</{k}>" for k, v in argumente.items())
        rumpf = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{aktion} xmlns:u="{service}">{inhalt}</u:{aktion}>'
            "</s:Body></s:Envelope>"
        ).encode("utf-8")

        anfrage = urllib.request.Request(
            f"{self.basis}{control_url}",
            data=rumpf,
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SoapAction": f"{service}#{aktion}",
            },
        )
        try:
            with self.opener.open(anfrage, timeout=TIMEOUT) as antwort:
                roh = antwort.read()
        except urllib.error.HTTPError as fehler:
            if fehler.code == 401:
                raise FritzboxFehler(
                    "Anmeldung abgelehnt - Benutzer oder Passwort in .env pruefen."
                ) from fehler
            raise FritzboxFehler(f"HTTP {fehler.code} bei {aktion}") from fehler
        except (urllib.error.URLError, socket.timeout, TimeoutError) as fehler:
            raise FritzboxFehler(f"{self.host} nicht erreichbar: {fehler}") from fehler

        wurzel = ElementTree.fromstring(roh)
        ergebnis = {}
        for element in wurzel.iter():
            name = element.tag.split("}")[-1]
            if name.startswith("New"):
                ergebnis[name[3:]] = element.text
        return ergebnis

    # -- Abfragen ------------------------------------------------------

    def geraeteinfo(self):
        return self._soap(
            "/upnp/control/deviceinfo", "urn:dslforum-org:service:DeviceInfo:1", "GetInfo"
        )

    def wlan_info(self, index):
        """index 1 = 2,4 GHz, 2 = 5 GHz, 3 = Gastnetz."""
        return self._soap(
            f"/upnp/control/wlanconfig{index}",
            f"urn:dslforum-org:service:WLANConfiguration:{index}",
            "GetInfo",
        )

    def wlan_uebersicht(self):
        baender = {}
        for index, bezeichnung in ((1, "2.4GHz"), (2, "5GHz")):
            try:
                info = self.wlan_info(index)
            except FritzboxFehler:
                continue
            if info.get("Enable") != "1":
                continue
            baender[bezeichnung] = {
                "ssid": info.get("SSID"),
                "kanal": info.get("Channel"),
                "standard": info.get("Standard"),
                "status": info.get("Status"),
            }
        return baender

    def ereignisprotokoll(self):
        """Ereignisse der FRITZ!Box, neueste zuerst."""
        try:
            antwort = self._soap(
                "/upnp/control/deviceinfo",
                "urn:dslforum-org:service:DeviceInfo:1",
                "X_AVM-DE_GetDeviceLogPath",
            )
            pfad = antwort.get("X_AVM-DE_DeviceLogPath")
            if pfad:
                with self.opener.open(f"{self.basis}{pfad}", timeout=TIMEOUT) as a:
                    text = a.read().decode("utf-8", "replace")
                    zeilen = [z for z in text.splitlines() if z.strip()]
                    if zeilen:
                        return zeilen
        except FritzboxFehler:
            pass

        antwort = self._soap(
            "/upnp/control/deviceinfo",
            "urn:dslforum-org:service:DeviceInfo:1",
            "GetDeviceLog",
        )
        text = antwort.get("DeviceLog") or ""
        return [z for z in text.splitlines() if z.strip()]

    def mesh_liste(self):
        antwort = self._soap(
            "/upnp/control/hosts",
            "urn:dslforum-org:service:Hosts:1",
            "X_AVM-DE_GetMeshListPath",
        )
        pfad = antwort.get("X_AVM-DE_MeshListPath")
        if not pfad:
            raise FritzboxFehler("Mesh-Uebersicht nicht verfuegbar.")
        with self.opener.open(f"{self.basis}{pfad}", timeout=TIMEOUT) as antwort:
            return json.loads(antwort.read().decode("utf-8"))


# -- Auswertung der Mesh-Uebersicht ------------------------------------


def zugangspunkte(mesh):
    """Alle Mesh-Knoten, die selbst WLAN aussenden (Fritzbox + Repeater)."""
    punkte = {}
    for knoten in mesh.get("nodes", []):
        if knoten.get("mesh_role") not in ("master", "slave"):
            continue
        punkte[knoten["uid"]] = {
            "name": knoten.get("device_name"),
            "modell": knoten.get("device_model"),
            "rolle": knoten.get("mesh_role"),
        }
    return punkte


def _wlan_interfaces(knoten):
    return [s for s in knoten.get("node_interfaces", []) if s.get("type") == "WLAN"]


def knoten_ips(knoten):
    """IPv4-Adressen eines Mesh-Knotens, ohne Praefixlaenge."""
    adressen = []
    for eintrag in knoten.get("ip_addresses") or []:
        wert = (eintrag.get("value") or "").split("/")[0]
        if eintrag.get("version") == "V4" and wert:
            adressen.append(wert)
    return adressen


def meine_verbindung(mesh, ip):
    """An welchem Zugangspunkt haengt das Geraet mit dieser IP?"""
    punkte = zugangspunkte(mesh)

    mein_knoten = next(
        (k for k in mesh.get("nodes", []) if ip in knoten_ips(k)), None
    )
    if mein_knoten is None:
        return None

    meine_schnittstellen = {s["uid"]: s for s in _wlan_interfaces(mein_knoten)}
    if not meine_schnittstellen:
        return {"zugangspunkt": None, "hinweis": "per Kabel verbunden"}

    for knoten in mesh.get("nodes", []):
        punkt = punkte.get(knoten["uid"])
        if punkt is None:
            continue
        for schnittstelle in _wlan_interfaces(knoten):
            for verbindung in schnittstelle.get("node_links") or []:
                if verbindung.get("state") != "CONNECTED":
                    continue
                beteiligt = {
                    verbindung.get("node_interface_1_uid"),
                    verbindung.get("node_interface_2_uid"),
                }
                eigene = beteiligt & meine_schnittstellen.keys()
                if not eigene:
                    continue
                meine = meine_schnittstellen[eigene.pop()]
                return {
                    "zugangspunkt": punkt["name"],
                    "modell": punkt["modell"],
                    "rolle": punkt["rolle"],
                    "ap_schnittstelle": schnittstelle.get("name"),
                    "ssid": meine.get("ssid"),
                    "kanal": meine.get("current_channel"),
                    "kanalauslastung": meine.get("channel_utilization"),
                    "steering": meine.get("steering_enabled"),
                    "unterstuetzt_11k": meine.get("11k_friendly"),
                    "unterstuetzt_11v": meine.get("11v_friendly"),
                    "rcpi": verbindung.get("rx_rcpi"),
                    "max_rx_mbit": _mbit(verbindung.get("max_data_rate_rx")),
                    "max_tx_mbit": _mbit(verbindung.get("max_data_rate_tx")),
                    "akt_rx_mbit": _mbit(verbindung.get("cur_data_rate_rx")),
                    "akt_tx_mbit": _mbit(verbindung.get("cur_data_rate_tx")),
                    "verfuegbarkeit_rx": verbindung.get("cur_availability_rx"),
                    "verfuegbarkeit_tx": verbindung.get("cur_availability_tx"),
                }
    return None


def _mbit(kbit):
    return round(kbit / 1000) if isinstance(kbit, (int, float)) else None


REPEATER_MUSTER = re.compile(
    r"(repeater|mesh|powerline|WLAN-Ger[aä]t|angemeldet|abgemeldet|neu gestartet|Neustart)",
    re.IGNORECASE,
)


def auffaellige_ereignisse(zeilen, muster=REPEATER_MUSTER):
    return [z for z in zeilen if muster.search(z)]


# -- Weboberflaeche (fuer Daten, die TR-064 nicht herausgibt) -----------


class FritzboxWeb:
    """Anmeldung an der Weboberflaeche, um an Funk- und Protokolldaten zu kommen."""

    def __init__(self, host, benutzer, passwort):
        self.basis = f"http://{host}"
        self.benutzer = benutzer
        self.passwort = passwort
        self.sid = None

    def anmelden(self):
        with urllib.request.urlopen(
            f"{self.basis}/login_sid.lua?version=2", timeout=TIMEOUT
        ) as antwort:
            wurzel = ElementTree.fromstring(antwort.read())
        herausforderung = wurzel.findtext("Challenge") or ""
        sperrzeit = int(wurzel.findtext("BlockTime") or 0)
        if sperrzeit:
            raise FritzboxFehler(
                f"FRITZ!Box sperrt die Anmeldung noch {sperrzeit} Sekunden."
            )

        antwort_wert = self._antwort_bilden(herausforderung)
        daten = urllib.parse.urlencode(
            {"username": self.benutzer, "response": antwort_wert}
        ).encode("ascii")
        with urllib.request.urlopen(
            urllib.request.Request(f"{self.basis}/login_sid.lua?version=2", data=daten),
            timeout=TIMEOUT,
        ) as antwort:
            wurzel = ElementTree.fromstring(antwort.read())
        sid = wurzel.findtext("SID")
        if not sid or sid == "0000000000000000":
            raise FritzboxFehler(
                "Anmeldung an der Weboberflaeche abgelehnt - Zugangsdaten pruefen."
            )
        self.sid = sid
        return sid

    def _antwort_bilden(self, herausforderung):
        if herausforderung.startswith("2$"):
            _, runden1, salz1, runden2, salz2 = herausforderung.split("$")
            stufe1 = hashlib.pbkdf2_hmac(
                "sha256", self.passwort.encode("utf-8"), bytes.fromhex(salz1), int(runden1)
            )
            stufe2 = hashlib.pbkdf2_hmac(
                "sha256", stufe1, bytes.fromhex(salz2), int(runden2)
            )
            return f"{salz2}${stufe2.hex()}"
        roh = f"{herausforderung}-{self.passwort}".encode("utf-16-le")
        return f"{herausforderung}-{hashlib.md5(roh).hexdigest()}"

    def daten(self, seite, **zusatz):
        if not self.sid:
            self.anmelden()
        felder = {"xhr": "1", "sid": self.sid, "lang": "de", "page": seite}
        felder.update({k: str(v) for k, v in zusatz.items()})
        anfrage = urllib.request.Request(
            f"{self.basis}/data.lua",
            data=urllib.parse.urlencode(felder).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT) as antwort:
            roh = antwort.read().decode("utf-8", "replace")
        try:
            return json.loads(roh)
        except json.JSONDecodeError as fehler:
            raise FritzboxFehler(f"Unerwartete Antwort fuer Seite {seite!r}") from fehler

    def wlan_protokoll(self):
        daten = self.daten("log", filter="wlan")
        eintraege = (daten.get("data") or {}).get("log") or []
        ergebnis = []
        for e in eintraege:
            if isinstance(e, dict):
                ergebnis.append(
                    {
                        "datum": e.get("date"),
                        "zeit": e.get("time"),
                        "text": e.get("msg"),
                    }
                )
            elif isinstance(e, list) and len(e) >= 3:
                ergebnis.append({"datum": e[0], "zeit": e[1], "text": e[2]})
        return ergebnis

    def funkkanal(self):
        """Kanalbelegung und Nachbarnetze aus Sicht der FRITZ!Box."""
        return self.daten("chan")


def kanal_karte(mesh):
    """Ordnet jedem Funkkanal den Zugangspunkt zu, der darauf sendet.

    Damit laesst sich auch ohne Ortungsfreigabe erkennen, an welchem Geraet
    der Mac gerade haengt - der Kanal verraet es.
    """
    karte = {}
    punkte = zugangspunkte(mesh)
    for knoten in mesh.get("nodes", []):
        punkt = punkte.get(knoten["uid"])
        if not punkt:
            continue
        for schnittstelle in _wlan_interfaces(knoten):
            name = schnittstelle.get("name") or ""
            if not name.startswith("AP:"):      # Gastnetze ueberspringen
                continue
            kanal = schnittstelle.get("current_channel")
            if not kanal:
                continue
            kanal = int(kanal)
            band = "2,4 GHz" if ":2G:" in name else "5 GHz"
            bezeichnung = f"{punkt['name']} ({band})"
            # Belegt ein Kanal zwei Geraete, ist er nicht mehr eindeutig.
            if kanal in karte and karte[kanal] != bezeichnung:
                karte[kanal] = "mehrdeutig"
            else:
                karte[kanal] = bezeichnung
    return karte


def bssid_karte(mesh):
    """Ordnet jeder Funkkennung (BSSID) den Zugangspunkt zu.

    Zuverlaessiger als die Kanalzuordnung: Die Kennung bleibt gleich, auch
    wenn die FRITZ!Box wegen Radarerkennung den Kanal wechselt.
    """
    karte = {}
    punkte = zugangspunkte(mesh)
    for knoten in mesh.get("nodes", []):
        punkt = punkte.get(knoten["uid"])
        if not punkt:
            continue
        for schnittstelle in _wlan_interfaces(knoten):
            name = schnittstelle.get("name") or ""
            kennung = (schnittstelle.get("mac_address") or "").lower()
            if not name.startswith("AP:") or not kennung:
                continue
            band = "2,4 GHz" if ":2G:" in name else "5 GHz"
            kanal = schnittstelle.get("current_channel")
            zusatz = f", Kanal {kanal}" if kanal else ""
            karte[kennung] = f"{punkt['name']} ({band}{zusatz})"
    return karte


# In Europa radarpflichtig (DFS): 52-64 und 100-144. Frei: 36-48.
DFS_BEREICH = range(52, 145)


def steering_aktiv(mesh):
    """Lenkt die FRITZ!Box Geraete aktiv zwischen Baendern und Zugangspunkten?

    Steht in den Mesh-Daten an den Zugangspunkt-Schnittstellen. Das Feld auf
    der Funkkanal-Seite gibt etwas anderes an und taugt dafuer nicht.
    """
    werte = []
    punkte = zugangspunkte(mesh)
    for knoten in mesh.get("nodes", []):
        if knoten["uid"] not in punkte:
            continue
        for s in _wlan_interfaces(knoten):
            if (s.get("name") or "").startswith("AP:") and "steering_enabled" in s:
                werte.append(bool(s["steering_enabled"]))
    if not werte:
        return None
    return all(werte)


def dfs_funkmodule(mesh):
    """Funkmodule, die auf einem radarpflichtigen Kanal senden."""
    betroffen = []
    punkte = zugangspunkte(mesh)
    for knoten in mesh.get("nodes", []):
        punkt = punkte.get(knoten["uid"])
        if not punkt:
            continue
        for s in _wlan_interfaces(knoten):
            if not (s.get("name") or "").startswith("AP:"):
                continue
            kanal = s.get("current_channel")
            if kanal and int(kanal) in DFS_BEREICH:
                betroffen.append({
                    "zugangspunkt": punkt["name"],
                    "modul": s["name"],
                    "kanal": int(kanal),
                    "geraete": sum(1 for l in (s.get("node_links") or [])
                                   if l.get("state") == "CONNECTED"),
                })
    return betroffen
