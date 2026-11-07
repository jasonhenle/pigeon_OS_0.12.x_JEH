import Foundation

/// What the Welcome screen's QR code carries:
/// `pigeon://setup#v=1&id=pgn-7f3a91&name=Pigeon+Clock&code=482913&fp=<64 hex>` (form-encoded fragment).
/// `code` is there only while the device accepts a claim, `fp` only when it serves HTTPS, and
/// `host`/`port` (its LAN address) when it knows them.
struct SetupLink: Equatable {
    var deviceID: String
    var name: String
    var code: String?
    /// SHA-256 of the device certificate, read off its screen, so it needs no further confirmation.
    var fingerprint: String?
    /// Direct address to try before mDNS, which can be slow to resolve a device that just booted.
    var host: String?
    var port: Int?

    init(deviceID: String, name: String, code: String? = nil, fingerprint: String? = nil,
         host: String? = nil, port: Int? = nil) {
        self.deviceID = deviceID
        self.name = name
        self.code = code
        self.fingerprint = fingerprint
        self.host = host
        self.port = port
    }

    /// `nil` for anything that isn't a Pigeon setup link.
    init?(url: URL) {
        let scheme = url.scheme?.lowercased()
        // pigeon://setup#…, or a future https://…/setup#… universal link.
        let isSetup = (scheme == "pigeon" && url.host?.lowercased() == "setup")
            || (scheme == "https" && url.path.hasSuffix("/setup"))
        guard isSetup,
              let fragment = URLComponents(url: url, resolvingAgainstBaseURL: false)?.percentEncodedFragment
        else { return nil }
        var fields: [String: String] = [:]
        for pair in fragment.split(separator: "&") {
            let kv = pair.split(separator: "=", maxSplits: 1).map(String.init)
            guard kv.count == 2 else { continue }
            let decode = { (s: String) in s.replacingOccurrences(of: "+", with: " ").removingPercentEncoding ?? s }
            fields[decode(kv[0])] = decode(kv[1])
        }
        guard let id = fields["id"], !id.isEmpty else { return nil }
        deviceID = id
        name = fields["name"].flatMap { $0.isEmpty ? nil : $0 } ?? "Pigeon"
        code = fields["code"].flatMap { $0.count == 6 && $0.allSatisfy(\.isNumber) ? $0 : nil }
        fingerprint = fields["fp"].flatMap { s in
            let f = s.lowercased()
            return f.count == 64 && f.allSatisfy(\.isHexDigit) ? f : nil
        }
        host = fields["host"].flatMap { h in
            !h.isEmpty && h.count <= 253 && h.allSatisfy({ $0.isLetter || $0.isNumber || ".:-".contains($0) }) ? h : nil
        }
        port = fields["port"].flatMap(Int.init).flatMap { (1...65535).contains($0) ? $0 : nil }
    }
}

/// Starts the setup flow: from a scanned QR code, or after pairing a device that still needs setup.
@MainActor
final class SetupCoordinator: ObservableObject {
    enum Request: Identifiable, Equatable {
        case link(SetupLink)
        case device(id: String)

        var id: String {
            switch self {
            case .link(let l): return "link:" + l.deviceID
            case .device(let id): return "device:" + id
            }
        }
    }

    @Published var request: Request?

    /// True when the app should handle the URL (it is a setup link).
    @discardableResult
    func open(_ url: URL) -> Bool {
        guard let link = SetupLink(url: url) else { return false }
        request = .link(link)
        return true
    }
}
