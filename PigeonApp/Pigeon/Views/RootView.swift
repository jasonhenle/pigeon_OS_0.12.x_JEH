import SwiftUI

struct RootView: View {
    @EnvironmentObject private var store: DeviceStore
    @EnvironmentObject private var browser: DeviceBrowser

    var body: some View {
        DevicesView()
            .background(Theme.canvas)
            .onChange(of: browser.devices) { _, found in
                // Keep known devices reachable when their IP changes.
                for d in found where store.devices.contains(where: { $0.id == d.id }) {
                    Task {
                        if let r = await DeviceBrowser.resolve(d.endpoint) {
                            store.updateAddress(id: d.id, host: r.host, port: r.port)
                            if let known = store.devices.first(where: { $0.id == d.id }), known.pin == nil,
                               let hello = try? await PigeonClient(host: r.host, port: r.port).hello(),
                               hello.id == d.id, let tls = hello.tls {
                                store.adoptPin(id: d.id, tls.pin)
                            }
                        }
                    }
                }
            }
    }
}
