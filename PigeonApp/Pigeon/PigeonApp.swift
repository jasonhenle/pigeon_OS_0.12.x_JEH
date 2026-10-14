import SwiftUI

@main
struct PigeonApp: App {
    @StateObject private var store = DeviceStore()
    @StateObject private var browser = DeviceBrowser()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(store)
                .environmentObject(browser)
                .preferredColorScheme(.dark)
                .tint(Theme.accent)
                .onAppear { browser.start() }
        }
    }
}
