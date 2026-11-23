import Foundation
import CoreWLAN
import CoreLocation

/// Requests Location Services authorization once, so macOS stops redacting SSID/BSSID.
final class LocationGate: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var done = false

    func request(timeout: TimeInterval = 45) {
        manager.delegate = self
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
        let deadline = Date().addingTimeInterval(timeout)
        while !done && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.2))
            if manager.authorizationStatus != .notDetermined { done = true }
        }
        manager.stopUpdatingLocation()
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) { done = true }
}

func bandName(_ band: CWChannelBand) -> String {
    switch band {
    case .band2GHz: return "2.4GHz"
    case .band5GHz: return "5GHz"
    case .band6GHz: return "6GHz"
    default: return "unbekannt"
    }
}

func widthName(_ width: CWChannelWidth) -> String {
    switch width {
    case .width20MHz: return "20MHz"
    case .width40MHz: return "40MHz"
    case .width80MHz: return "80MHz"
    case .width160MHz: return "160MHz"
    default: return "unbekannt"
    }
}

func phyName(_ mode: CWPHYMode) -> String {
    switch mode {
    case .mode11a: return "a"
    case .mode11b: return "b"
    case .mode11g: return "g"
    case .mode11n: return "n"
    case .mode11ac: return "ac"
    case .mode11ax: return "ax"
    default: return "unbekannt"
    }
}

let args = CommandLine.arguments

/// Beim Start ueber LaunchServices gibt es keine Standardausgabe,
/// deshalb kann das Ergebnis in eine Datei geschrieben werden.
var ausgabedatei: String? = nil
if let stelle = args.firstIndex(of: "--out"), stelle + 1 < args.count {
    ausgabedatei = args[stelle + 1]
}

if args.contains("--authorize") {
    let gate = LocationGate()
    gate.request()
}

guard let iface = CWWiFiClient.shared().interface() else {
    print(#"{"error":"kein WLAN-Interface gefunden"}"#)
    exit(1)
}

var sample: [String: Any] = [
    "zeit": ISO8601DateFormatter().string(from: Date()),
    "interface": iface.interfaceName ?? "",
    "rssi": iface.rssiValue(),
    "noise": iface.noiseMeasurement(),
    "tx_rate_mbit": iface.transmitRate(),
    "aktiv": iface.powerOn(),
    "standort_freigabe": CLLocationManager().authorizationStatus == .authorizedAlways
        || CLLocationManager().authorizationStatus == .authorized,
]
sample["freigabe_code"] = CLLocationManager().authorizationStatus.rawValue
sample["ist_app"] = Bundle.main.bundleIdentifier ?? "<keine Bundle-Kennung>"
sample["snr"] = iface.rssiValue() - iface.noiseMeasurement()
sample["ssid"] = iface.ssid() ?? NSNull()
sample["bssid"] = iface.bssid() ?? NSNull()
sample["phy"] = phyName(iface.activePHYMode())

if let ch = iface.wlanChannel() {
    sample["kanal"] = ch.channelNumber
    sample["band"] = bandName(ch.channelBand)
    sample["breite"] = widthName(ch.channelWidth)
}

let data = try JSONSerialization.data(withJSONObject: sample, options: [.sortedKeys])
let text = String(data: data, encoding: .utf8)!
if let pfad = ausgabedatei {
    try? text.write(toFile: pfad, atomically: true, encoding: .utf8)
} else {
    print(text)
}
