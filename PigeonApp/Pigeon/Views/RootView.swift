import SwiftUI

struct RootView: View {
    @EnvironmentObject private var store: DeviceStore
    @EnvironmentObject private var browser: DeviceBrowser
    @State private var tab: Tab = .search

    enum Tab { case search, devices }

    var body: some View {
        TabView(selection: $tab) {
            SearchView(goToDevices: { tab = .devices })
                .tabItem { Label("Search", systemImage: "magnifyingglass") }
                .tag(Tab.search)
            DevicesView()
                .tabItem { Label("Devices", systemImage: "rectangle.on.rectangle") }
                .tag(Tab.devices)
        }
        .background(Theme.canvas)
        .onChange(of: browser.devices) { _, found in
            // Keep known devices reachable when their IP changes.
            for d in found where store.devices.contains(where: { $0.id == d.id }) {
                Task {
                    if let r = await DeviceBrowser.resolve(d.endpoint) {
                        store.updateAddress(id: d.id, host: r.host, port: r.port)
                    }
                }
            }
        }
    }
}
