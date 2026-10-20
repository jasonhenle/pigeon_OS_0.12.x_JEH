import SwiftUI

struct DevicesView: View {
    @EnvironmentObject private var store: DeviceStore
    @EnvironmentObject private var browser: DeviceBrowser
    @State private var showAdd = false

    private static var appVersion: String {
        let info = Bundle.main.infoDictionary
        let v = info?["CFBundleShortVersionString"] as? String ?? "?"
        let b = info?["CFBundleVersion"] as? String ?? "?"
        return "\(v) (build \(b))"
    }

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.canvas.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 12) {
                        if store.devices.isEmpty {
                            VStack(spacing: 10) {
                                LCDLabel(text: "Pigeon Remote", size: 34)
                                Text("Tap + to add a Pigeon and start searching.")
                                    .font(Theme.ui(16)).foregroundStyle(Theme.secondaryText)
                            }.padding(.top, 40)
                        }
                        ForEach(store.devices) { d in
                            NavigationLink(value: d) { DeviceRow(device: d, selected: d.id == store.selectedID) }
                                .buttonStyle(.plain)
                                .simultaneousGesture(TapGesture().onEnded { store.selectedID = d.id })
                        }
                        Text("App version \(Self.appVersion)")
                            .font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
                            .frame(maxWidth: .infinity).padding(.top, 8)
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

                    PlayingNowSection(device: device)

                    if caps?.capabilities.contains("display_brightness") == true {
                        BrightnessCard(client: store.client(for: device))
                    }

                    NavigationLink {
                        PigeonClockSettingsView(device: device, caps: caps, info: info, status: status)
                    } label: {
                        HStack {
                            LCDLabel(text: "Pigeon Clock Settings", size: 18, color: Theme.accent)
                            Spacer()
                            Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading).tile()
                    }
                    .buttonStyle(.plain)

                    if let errorText { Text(errorText).font(Theme.ui(14)).foregroundStyle(Theme.bad) }

                    Button(role: .destructive) { confirmRemove = true } label: {
                        Text("Remove from this device").font(Theme.uiBold(16))
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
        .alert("Remove \(device.name)?", isPresented: $confirmRemove) {
            Button("Remove", role: .destructive) {
                Task { await store.unpair(device); dismiss() }
            }
            Button("Cancel", role: .cancel) {}
        } message: { Text("The Pigeon keeps working. Add it again with its on-screen code.") }
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

/// Everything about the device itself: room, its settings, status and software.
struct PigeonClockSettingsView: View {
    @EnvironmentObject private var store: DeviceStore
    let device: KnownDevice
    let caps: Capabilities?
    let info: DeviceInfo?
    let status: DeviceStatus?

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
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

                    if caps?.capabilities.contains("restart") == true || caps?.capabilities.contains("update") == true {
                        MaintenanceCard(client: store.client(for: device), caps: caps?.capabilities ?? [],
                                        version: info?.version)
                    }
                }
                .padding(Theme.gutter)
            }
        }
        .navigationTitle("Pigeon Clock Settings")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack {
            Text(k).font(Theme.ui(15)).foregroundStyle(Theme.secondaryText)
            Spacer()
            Text(v).font(Theme.uiBold(15)).foregroundStyle(.white).multilineTextAlignment(.trailing)
        }
    }
}

// MARK: Room

@MainActor
final class RoomsModel: ObservableObject {
    @Published private(set) var data: RoomsResponse?
    @Published private(set) var busy = false
    @Published var errorText: String?
    @Published private(set) var notice: String?
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
        let n = name.trimmingCharacters(in: .whitespaces).uppercased()  // Pigeon only shows capitals
        guard !n.isEmpty, n != room.name else { return }
        await run { self.data = try await self.client.renameRoom(room.id, to: n) }
    }

    /// Starts the device-side search for a player (`player`) or audio receiver (`audio`) in this room.
    func startPairing(_ room: Room, kind: String) async {
        await run {
            try await self.client.startPairing(room: room.id, kind: kind)
            self.data = try await self.client.rooms()
            self.notice = "Pigeon is searching for \(kind == "player" ? "players" : "audio devices"). Pick one on its screen."
        }
    }

    private func run(_ work: @escaping () async throws -> Void) async {
        busy = true
        notice = nil
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
                            Text(r.name.uppercased()).font(Theme.uiBold(17)).foregroundStyle(.white)
                            Spacer()
                        }
                    }
                    .buttonStyle(.plain)
                    Menu {
                        Button { newName = r.name.uppercased(); renaming = r } label: {
                            Label("Rename", systemImage: "pencil")
                        }
                        Button { Task { await model.startPairing(r, kind: "player") } } label: {
                            Label("Add player", systemImage: "appletv")
                        }
                        Button { Task { await model.startPairing(r, kind: "audio") } } label: {
                            Label("Add audio", systemImage: "hifispeaker")
                        }
                    } label: {
                        Image(systemName: "pencil").foregroundStyle(Theme.secondaryText)
                            .frame(width: 36, height: 36).contentShape(Rectangle())
                    }
                }
                .padding(.vertical, 6)
            }
            if let n = model.notice { Text(n).font(Theme.ui(13)).foregroundStyle(Theme.ok) }
            if let e = model.errorText { Text(e).font(Theme.ui(13)).foregroundStyle(Theme.bad) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
        .task { await model.load() }
        .alert("Rename room", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("ROOM NAME", text: $newName)
                .textInputAutocapitalization(.characters)
                .onChange(of: newName) { _, v in if v != v.uppercased() { newName = v.uppercased() } }
            Button("Save") { if let r = renaming { Task { await model.rename(r, to: newName) } } }
            Button("Cancel", role: .cancel) {}
        } message: {
            if let p = model.data?.presets, !p.isEmpty { Text("e.g. " + p.prefix(4).joined(separator: ", ")) }
        }
    }
}

// MARK: Restart and update

@MainActor
final class MaintenanceModel: ObservableObject {
    enum Phase: Equatable { case idle, working(String), upToDate, available(String), done(String) }
    @Published private(set) var phase: Phase = .idle
    @Published var errorText: String?
    private let client: PigeonClient
    init(client: PigeonClient) { self.client = client }

    var busy: Bool { if case .working = phase { return true }; return false }

    func restart() async {
        phase = .working("Restarting…")
        do {
            try await client.restart()
            errorText = nil
            phase = .done("Restarting. It'll be back in about a minute.")
        } catch { errorText = error.localizedDescription; phase = .idle }
    }

    func check() async {
        phase = .working("Checking for updates…")
        do {
            let u = try await client.checkUpdate()
            if let e = u.error { errorText = "Couldn't check: \(e)"; phase = .idle; return }
            errorText = nil
            if u.applying { phase = .done("An update is already installing."); return }
            phase = u.updateAvailable ? .available(u.remoteVersion ?? "") : .upToDate
        } catch { errorText = error.localizedDescription; phase = .idle }
    }

    func install() async {
        phase = .working("Starting update…")
        do {
            try await client.applyUpdate()
            errorText = nil
            phase = .done("Installing. Pigeon restarts itself when it's finished.")
        } catch { errorText = error.localizedDescription; phase = .idle }
    }
}

struct MaintenanceCard: View {
    @StateObject private var model: MaintenanceModel
    let caps: [String]
    let version: String?
    @State private var confirmRestart = false
    @State private var confirmInstall = false

    init(client: PigeonClient, caps: [String], version: String?) {
        _model = StateObject(wrappedValue: MaintenanceModel(client: client))
        self.caps = caps
        self.version = version
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                LCDLabel(text: "Pigeon Clock Software", size: 18, color: Theme.accent)
                Spacer()
                if model.busy { ProgressView() }
            }
            if let version { Text("Version \(version)").font(Theme.ui(14)).foregroundStyle(Theme.secondaryText) }

            switch model.phase {
            case .working(let t): Text(t).font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
            case .upToDate: Text("Pigeon is up to date.").font(Theme.ui(14)).foregroundStyle(Theme.ok)
            case .available(let v): Text("Version \(v) is available.").font(Theme.uiBold(14)).foregroundStyle(Theme.ok)
            case .done(let t): Text(t).font(Theme.ui(14)).foregroundStyle(Theme.ok)
            case .idle: EmptyView()
            }
            if let e = model.errorText { Text(e).font(Theme.ui(13)).foregroundStyle(Theme.bad) }

            if caps.contains("update") {
                if case .available(let v) = model.phase {
                    button("Update to \(v)", filled: true) { confirmInstall = true }
                } else {
                    button("Check for updates", filled: false) { Task { await model.check() } }
                }
            }
            if caps.contains("restart") {
                button("Restart Pigeon", filled: false) { confirmRestart = true }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
        .disabled(model.busy)
        .alert("Restart Pigeon?", isPresented: $confirmRestart) {
            Button("Restart", role: .destructive) { Task { await model.restart() } }
            Button("Cancel", role: .cancel) {}
        } message: { Text("The screen goes dark for about a minute while it starts back up.") }
        .alert("Install the update?", isPresented: $confirmInstall) {
            Button("Update") { Task { await model.install() } }
            Button("Cancel", role: .cancel) {}
        } message: { Text("Pigeon downloads the update, installs it and restarts. Your settings are kept.") }
    }

    private func button(_ title: String, filled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(Theme.uiBold(16)).frame(maxWidth: .infinity).padding(.vertical, 12)
                .foregroundStyle(filled ? Color.black : Color.white)
                .background(filled ? Theme.accent : Theme.tileRaised, in: Capsule())
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

    /// Picking a color also leaves dark mode, like the device's theme menu.
    func setColor(_ key: String) async {
        await send(.init(zip: nil, timezone: nil, options: ["color_format": "color"], uiColor: key))
    }

    func setDark() async {
        await send(.init(zip: nil, timezone: nil, options: ["color_format": "dark"], uiColor: nil))
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
        ("clock_format", "Clock face", ["digital": "Digital", "analog": "Analog"]),
        ("zone4_mode", "Playback bar", ["info": "Info", "visualizer": "Visualizer"]),
    ]

    private func isDark(_ d: PigeonSettings) -> Bool { d.options["color_format"] == "dark" }

    private static let swatches: [String: Color] = [
        "blue": Color(hex: 0x4EA6F7), "green": Color(hex: 0x00A32E), "yellow": Color(hex: 0xE6FF0A),
        "pink": Color(hex: 0xFF5CA8),
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

                // The switches (clock, temperature, clock face, playback bar)
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
                                    .overlay(Circle().stroke(Color.white, lineWidth: d.uiColor == key && !isDark(d) ? 3 : 0).padding(-4))
                            }
                            .buttonStyle(.plain)
                        }
                        // Dark: monochrome red on black.
                        Button { Task { await model.setDark() } } label: {
                            Circle().fill(.black)
                                .overlay(Circle().stroke(Color(hex: 0xD60000), lineWidth: 5))
                                .frame(width: 34, height: 34)
                                .overlay(Circle().stroke(Color.white, lineWidth: isDark(d) ? 3 : 0).padding(-4))
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Dark")
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

// MARK: Brightness

@MainActor
final class BrightnessModel: ObservableObject {
    @Published var level: Double = 100
    @Published private(set) var info: DisplayInfo?
    @Published var errorText: String?
    private let client: PigeonClient
    private var pending: Task<Void, Never>?
    init(client: PigeonClient) { self.client = client }

    func load() async {
        do {
            let d = try await client.display()
            info = d
            level = Double(d.brightness)
            errorText = nil
        } catch { errorText = error.localizedDescription }
    }

    /// Called while dragging: send at most one request every 150 ms so the screen follows live.
    func levelChanged() {
        pending?.cancel()
        let target = Int(level.rounded())
        pending = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled, let self else { return }
            do { self.info = try await self.client.setBrightness(target); self.errorText = nil }
            catch { self.errorText = error.localizedDescription }
        }
    }
}

struct BrightnessCard: View {
    @StateObject private var model: BrightnessModel
    init(client: PigeonClient) { _model = StateObject(wrappedValue: BrightnessModel(client: client)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                LCDLabel(text: "Brightness", size: 18, color: Theme.accent)
                Spacer()
                LCDLabel(text: "\(Int(model.level.rounded()))%", size: 22)
            }
            HStack(spacing: 12) {
                Image(systemName: "sun.min").foregroundStyle(Theme.secondaryText)
                Slider(value: $model.level,
                       in: Double(model.info?.min ?? 10)...Double(model.info?.max ?? 100), step: 1)
                    .onChange(of: model.level) { _, _ in model.levelChanged() }
                Image(systemName: "sun.max.fill").foregroundStyle(.white)
            }
            if let info = model.info {
                Text(info.mode == "backlight" ? "Dims the panel's backlight." : "Dims the picture on this display.")
                    .font(Theme.ui(12)).foregroundStyle(Theme.secondaryText)
            }
            if let e = model.errorText { Text(e).font(Theme.ui(13)).foregroundStyle(Theme.bad) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
        .task { await model.load() }
    }
}
