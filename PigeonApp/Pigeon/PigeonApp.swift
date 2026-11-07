import SwiftUI

@main
struct PigeonApp: App {
    @StateObject private var store = DeviceStore()
    @StateObject private var browser = DeviceBrowser()
    @StateObject private var setup = SetupCoordinator()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(store)
                .environmentObject(browser)
                .environmentObject(setup)
                .onOpenURL { setup.open($0) }  // pigeon://setup#… from a Pigeon's Welcome screen
                .preferredColorScheme(.dark)
                .tint(Theme.accent)
                .onAppear { browser.start() }
        }
    }
}
