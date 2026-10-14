import Foundation
import Network

struct DiscoveredDevice: Identifiable, Equatable {
    var id: String          // device id from the TXT record
    var name: String
    var product: String
    var claimed: Bool
    var endpoint: NWEndpoint
}

/// Finds Pigeon devices advertising `_pigeon._tcp` on the local network.
@MainActor
final class DeviceBrowser: ObservableObject {
    @Published private(set) var devices: [DiscoveredDevice] = []
    @Published private(set) var isBrowsing = false
    private var browser: NWBrowser?

    func start() {
        guard browser == nil else { return }
        let b = NWBrowser(for: .bonjourWithTXTRecord(type: "_pigeon._tcp", domain: nil), using: .tcp)
        b.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in
                guard let self else { return }
                switch state {
                case .ready: self.isBrowsing = true
                case .failed, .cancelled: self.isBrowsing = false; self.browser = nil
                default: break
                }
            }
        }
        b.browseResultsChangedHandler = { [weak self] results, _ in
            let found: [DiscoveredDevice] = results.compactMap { r in
                guard case .bonjour(let txt) = r.metadata else { return nil }
                let d = txt.dictionary
                guard let id = d["id"] else { return nil }
                return DiscoveredDevice(
                    id: id, name: d["name"] ?? "Pigeon", product: d["product"] ?? "clock",
                    claimed: d["claimed"] == "1", endpoint: r.endpoint)
            }
            Task { @MainActor in self?.devices = found.sorted { $0.name < $1.name } }
        }
        b.start(queue: .main)
        browser = b
    }

    func stop() {
        browser?.cancel()
        browser = nil
        isBrowsing = false
    }

    /// Resolve a Bonjour service endpoint to a numeric host and the API port.
    static func resolve(_ endpoint: NWEndpoint) async -> (host: String, port: Int)? {
        await withCheckedContinuation { cont in
            let conn = NWConnection(to: endpoint, using: .tcp)
            let box = ResumeOnce(cont)
            conn.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    if case .hostPort(let host, let port)? = conn.currentPath?.remoteEndpoint {
                        var h = "\(host)"
                        if let pct = h.firstIndex(of: "%") { h = String(h[..<pct]) }
                        box.resume(returning: (h, Int(port.rawValue)))
                    } else { box.resume(returning: nil) }
                    conn.cancel()
                case .failed, .cancelled:
                    box.resume(returning: nil)
                default: break
                }
            }
            conn.start(queue: .global())
            DispatchQueue.global().asyncAfter(deadline: .now() + 5) { box.resume(returning: nil); conn.cancel() }
        }
    }
}

private final class ResumeOnce {
    private var cont: CheckedContinuation<(host: String, port: Int)?, Never>?
    private let lock = NSLock()
    init(_ c: CheckedContinuation<(host: String, port: Int)?, Never>) { cont = c }
    func resume(returning v: (host: String, port: Int)?) {
        lock.lock(); let c = cont; cont = nil; lock.unlock()
        c?.resume(returning: v)
    }
}
