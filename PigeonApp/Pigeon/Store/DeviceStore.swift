import Foundation
import SwiftUI

struct KnownDevice: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var product: String
    var host: String
    var port: Int
}

/// The app's registry of claimed devices. Tokens live in the Keychain, the rest in UserDefaults.
@MainActor
final class DeviceStore: ObservableObject {
    @Published private(set) var devices: [KnownDevice] = []
    @Published var selectedID: String? { didSet { defaults.set(selectedID, forKey: Keys.selected) } }

    private let defaults: UserDefaults
    private enum Keys {
        static let devices = "known_devices"
        static let selected = "selected_device"
        static let controller = "controller_id"
    }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey: Keys.devices),
           let list = try? JSONDecoder().decode([KnownDevice].self, from: data) {
            devices = list
        }
        selectedID = defaults.string(forKey: Keys.selected)
        if selectedID == nil || !devices.contains(where: { $0.id == selectedID }) {
            selectedID = devices.first?.id
        }
    }

    /// Stable id this phone sends when claiming, so re-claiming replaces rather than duplicates.
    var controllerID: String {
        if let id = defaults.string(forKey: Keys.controller) { return id }
        let id = UUID().uuidString
        defaults.set(id, forKey: Keys.controller)
        return id
    }

    var selected: KnownDevice? { devices.first { $0.id == selectedID } }

    func token(for id: String) -> String? { Keychain.get(id) }

    func client(for device: KnownDevice) -> PigeonClient {
        PigeonClient(host: device.host, port: device.port, token: Keychain.get(device.id))
    }

    func add(_ device: KnownDevice, token: String) {
        Keychain.set(token, for: device.id)
        if let i = devices.firstIndex(where: { $0.id == device.id }) { devices[i] = device }
        else { devices.append(device) }
        selectedID = device.id
        persist()
    }

    func updateAddress(id: String, host: String, port: Int) {
        guard let i = devices.firstIndex(where: { $0.id == id }),
              devices[i].host != host || devices[i].port != port else { return }
        devices[i].host = host
        devices[i].port = port
        persist()
    }

    func rename(id: String, to name: String) {
        guard let i = devices.firstIndex(where: { $0.id == id }) else { return }
        devices[i].name = name
        persist()
    }

    func remove(id: String) {
        Keychain.delete(id)
        devices.removeAll { $0.id == id }
        if selectedID == id { selectedID = devices.first?.id }
        persist()
    }

    private func persist() {
        if let data = try? JSONEncoder().encode(devices) { defaults.set(data, forKey: Keys.devices) }
    }
}
