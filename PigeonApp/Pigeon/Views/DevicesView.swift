import SwiftUI

struct DevicesView: View {
    @EnvironmentObject private var store: DeviceStore
    @EnvironmentObject private var browser: DeviceBrowser
    @State private var showAdd = false

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.canvas.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 12) {
                        if store.devices.isEmpty {
                            Text("No devices yet.").font(Theme.ui(16)).foregroundStyle(Theme.secondaryText)
                                .padding(.top, 40)
                        }
                        ForEach(store.devices) { d in
                            NavigationLink(value: d) { DeviceRow(device: d, selected: d.id == store.selectedID) }
                                .buttonStyle(.plain)
                        }
                    }
                    .padding(Theme.gutter)
                }
            }
            .navigationTitle("Devices")
            .navigationDestination(for: KnownDevice.self) { DeviceDetailView(device: $0) }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showAdd = true } label: { Image(systemName: "plus") }
                }
            }
            .sheet(isPresented: $showAdd) { AddDeviceView() }
        }
    }
}


struct DeviceRow: View {
    let device: KnownDevice
    let selected: Bool
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                LCDLabel(text: device.name, size: 26)
                Text(device.product == "marquee" ? "Pigeon Marquee" : "Pigeon Clock")
                    .font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
            }
            Spacer()
            Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
        }
        .tile(selected: selected)
    }
}

struct DeviceDetailView: View {
    @EnvironmentObject private var store: DeviceStore
    @Environment(\.dismiss) private var dismiss
    let device: KnownDevice

    @State private var info: DeviceInfo?
    @State private var caps: Capabilities?
    @State private var status: DeviceStatus?
    @State private var name = ""
    @State private var errorText: String?
    @State private var confirmRemove = false

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 8) {
                        LCDLabel(text: "Name", size: 18, color: Theme.accent)
                        TextField("Name", text: $name)
                            .font(Theme.uiBold(20))
                            .submitLabel(.done)
                            .onSubmit { Task { await rename() } }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading).tile()

                    if caps?.capabilities.contains("rooms") == true {
                        RoomsCard(client: store.client(for: device))
                    }
                    if caps?.capabilities.contains("pigeon_settings") == true {
                        PigeonSettingsCard(client: store.client(for: device))
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        LCDLabel(text: "Status", size: 18, color: Theme.accent)
                        row("State", status?.state.capitalized ?? "—")
                        row("Now playing", status?.nowPlaying?.title ?? "Nothing")
                        row("Version", info?.version ?? "—")
                        row("Address", "\(device.host):\(device.port)")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading).tile()

                    if let caps {
                        VStack(alignment: .leading, spacing: 8) {
                            LCDLabel(text: "Can do", size: 18, color: Theme.accent)
                            Text(caps.capabilities.map { $0.replacingOccurrences(of: "_", with: " ") }.joined(separator: " · "))
                                .font(Theme.ui(15)).foregroundStyle(Theme.secondaryText)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading).tile()
                    }

                    if status?.nowPlaying != nil {
                        NavigationLink {
                            NowPlayingFixView(client: store.client(for: device), deviceName: device.name)
                        } label: {
                            HStack {
                                Text("Fix what's showing").font(Theme.uiBold(16)).foregroundStyle(.white)
                                Spacer()
                                Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
                            }.tile()
                        }.buttonStyle(.plain)
                    }

                    if let errorText { Text(errorText).font(Theme.ui(14)).foregroundStyle(Theme.bad) }

                    Button(role: .destructive) { confirmRemove = true } label: {
                        Text("Remove from this phone").font(Theme.uiBold(16))
                            .frame(maxWidth: .infinity).padding(.vertical, 14)
                            .background(Theme.tile, in: RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
                    }
                }
                .padding(Theme.gutter)
            }
        }
        .navigationTitle(device.name)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .confirmationDialog("Remove \(device.name)?", isPresented: $confirmRemove, titleVisibility: .visible) {
            Button("Remove", role: .destructive) { store.remove(id: device.id); dismiss() }
        } message: { Text("The device keeps working. Add it again with its on-screen code.") }
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack {
            Text(k).font(Theme.ui(15)).foregroundStyle(Theme.secondaryText)
            Spacer()
            Text(v).font(Theme.uiBold(15)).foregroundStyle(.white).multilineTextAlignment(.trailing)
        }
    }

    private func load() async {
        let c = store.client(for: device)
        do {
            async let i = c.device()
            async let k = c.capabilities()
            async let s = c.status()
            (info, caps, status) = try await (i, k, s)
            name = info?.name ?? device.name
            errorText = nil
        } catch { errorText = error.localizedDescription }
    }

    private func rename() async {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed != device.name else { return }
        do {
            let updated: DeviceInfo = try await store.client(for: device)
                .send("PATCH", "/device", body: ["name": trimmed])
            store.rename(id: device.id, to: updated.name)
            errorText = nil
        } catch { errorText = error.localizedDescription }
    }
}

// MARK: Room

@MainActor
final class RoomsModel: ObservableObject {
    @Published private(set) var data: RoomsResponse?
    @Published private(set) var busy = false
    @Published var errorText: String?
    private let client: PigeonClient
    init(client: PigeonClient) { self.client = client }

    func load() async {
        do { data = try await client.rooms(); errorText = nil } catch { errorText = error.localizedDescription }
    }

    func choose(_ room: Room) async {
        guard !room.current else { return }
        await run { self.data = try await self.client.switchRoom(room.id) }
    }

    func rename(_ room: Room, to name: String) async {
        let n = name.trimmingCharacters(in: .whitespaces)
        guard !n.isEmpty, n != room.name else { return }
        await run { self.data = try await self.client.renameRoom(room.id, to: n) }
    }

    private func run(_ work: @escaping () async throws -> Void) async {
        busy = true
        defer { busy = false }
        do { try await work(); errorText = nil } catch { errorText = error.localizedDescription }
    }
}

struct RoomsCard: View {
    @StateObject private var model: RoomsModel
    @State private var renaming: Room?
    @State private var newName = ""

    init(client: PigeonClient) { _model = StateObject(wrappedValue: RoomsModel(client: client)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                LCDLabel(text: "Room", size: 18, color: Theme.accent)
                Spacer()
                if model.busy { ProgressView() }
            }
            Text("Players and receivers belong to a room. Switching rooms changes which ones this Pigeon uses.")
                .font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
            ForEach(model.data?.rooms ?? []) { r in
                HStack {
                    Button { Task { await model.choose(r) } } label: {
                        HStack(spacing: 10) {
                            Image(systemName: r.current ? "largecircle.fill.circle" : "circle")
                                .foregroundStyle(r.current ? Theme.accent : Theme.inactive)
                            Text(r.name).font(Theme.uiBold(17)).foregroundStyle(.white)
                            Spacer()
                        }
                    }
                    .buttonStyle(.plain)
                    Button { newName = r.name; renaming = r } label: {
                        Image(systemName: "pencil").foregroundStyle(Theme.secondaryText)
                    }
                    .buttonStyle(.plain)
                }
                .padding(.vertical, 6)
            }
            if let e = model.errorText { Text(e).font(Theme.ui(13)).foregroundStyle(Theme.bad) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
        .task { await model.load() }
        .alert("Rename room", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Room name", text: $newName)
            Button("Save") { if let r = renaming { Task { await model.rename(r, to: newName) } } }
            Button("Cancel", role: .cancel) {}
        } message: {
            if let p = model.data?.presets, !p.isEmpty { Text("e.g. " + p.prefix(4).joined(separator: ", ")) }
        }
    }
}

// MARK: Pigeon-page settings

@MainActor
final class PigeonSettingsModel: ObservableObject {
    @Published private(set) var data: PigeonSettings?
    @Published var zipText = ""
    @Published private(set) var busy = false
    @Published var errorText: String?
    private let client: PigeonClient
    init(client: PigeonClient) { self.client = client }

    func load() async {
        do {
            let d = try await client.pigeonSettings()
            data = d
            zipText = d.zip ?? ""
            errorText = nil
        } catch { errorText = error.localizedDescription }
    }

    func setOption(_ key: String, _ value: String) async {
        await send(.init(zip: nil, timezone: nil, options: [key: value], uiColor: nil))
    }

    func setColor(_ key: String) async {
        await send(.init(zip: nil, timezone: nil, options: nil, uiColor: key))
    }

    func setTimezone(_ name: String) async {
        await send(.init(zip: nil, timezone: name, options: nil, uiColor: nil))
    }

    func saveZip() async {
        await send(.init(zip: zipText.trimmingCharacters(in: .whitespaces), timezone: nil, options: nil, uiColor: nil))
        // The device looks the timezone up in the background; refresh once it's had a moment.
        try? await Task.sleep(for: .seconds(3))
        await load()
    }

    private func send(_ patch: PigeonSettingsPatch) async {
        busy = true
        defer { busy = false }
        do { data = try await client.patchPigeonSettings(patch); errorText = nil }
        catch { errorText = error.localizedDescription }
    }
}

struct PigeonSettingsCard: View {
    @StateObject private var model: PigeonSettingsModel
    init(client: PigeonClient) { _model = StateObject(wrappedValue: PigeonSettingsModel(client: client)) }

    private static let rows: [(key: String, title: String, labels: [String: String])] = [
        ("time_format", "Clock", ["12": "12 hr", "24": "24 hr"]),
        ("temp_format", "Temperature", ["f": "°F", "c": "°C"]),
        ("color_format", "Look", ["color": "Theme", "dark": "Dark"]),
        ("zone4_mode", "Playback bar", ["info": "Info", "visualizer": "Visualizer"]),
        ("zone6_mode", "Now playing layout", ["now_playing": "Zone 6", "zone11": "Zone 11"]),
    ]

    private static let swatches: [String: Color] = [
        "blue": Color(hex: 0x4EA6F7), "green": Color(hex: 0x00A32E), "yellow": Color(hex: 0xE6FF0A),
        "orange": Color(hex: 0xE39F00), "red": Color(hex: 0xFF0000), "grey": Color(hex: 0x777777),
        "white": .white,
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                LCDLabel(text: "Pigeon settings", size: 18, color: Theme.accent)
                Spacer()
                if model.busy { ProgressView() }
            }
            if let d = model.data {
                // Location
                VStack(alignment: .leading, spacing: 8) {
                    Text("Zip code").font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
                    HStack {
                        TextField("5 digits", text: $model.zipText)
                            .keyboardType(.numberPad).font(Theme.uiBold(17))
                            .padding(10)
                            .background(Theme.tileRaised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                        Button("Save") { Task { await model.saveZip() } }
                            .font(Theme.uiBold(16))
                            .disabled(model.zipText.count != 5 || model.zipText == (d.zip ?? ""))
                    }
                    Text("Timezone").font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
                    Menu {
                        ForEach(d.timezoneChoices, id: \.self) { tz in
                            Button(tz) { Task { await model.setTimezone(tz) } }
                        }
                    } label: {
                        HStack {
                            Text(d.timezone ?? "System default").font(Theme.uiBold(16)).foregroundStyle(.white)
                            Spacer()
                            Image(systemName: "chevron.up.chevron.down").foregroundStyle(Theme.secondaryText)
                        }
                        .padding(10)
                        .background(Theme.tileRaised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                }

                // The five switches
                ForEach(Self.rows, id: \.key) { row in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(row.title).font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
                        Picker(row.title, selection: Binding(
                            get: { d.options[row.key] ?? "" },
                            set: { v in Task { await model.setOption(row.key, v) } })) {
                            ForEach(d.optionValues[row.key] ?? [], id: \.self) { v in
                                Text(row.labels[v] ?? v).tag(v)
                            }
                        }
                        .pickerStyle(.segmented)
                    }
                }

                // UI color
                VStack(alignment: .leading, spacing: 8) {
                    Text("Interface color").font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
                    HStack(spacing: 12) {
                        ForEach(d.uiColorChoices, id: \.self) { key in
                            Button { Task { await model.setColor(key) } } label: {
                                Circle().fill(Self.swatches[key] ?? .gray)
                                    .frame(width: 34, height: 34)
                                    .overlay(Circle().stroke(Color.white, lineWidth: d.uiColor == key ? 3 : 0).padding(-4))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                Text("Pigeon \(d.version)").font(Theme.ui(12)).foregroundStyle(Theme.secondaryText)
            } else if model.errorText == nil {
                ProgressView()
            }
            if let e = model.errorText { Text(e).font(Theme.ui(13)).foregroundStyle(Theme.bad) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
        .task { await model.load() }
    }
}
