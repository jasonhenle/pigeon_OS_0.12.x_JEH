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
    /// The device's clock settings (hours, time zone) for the live clock on the settings button.
    @State private var clockSettings: PigeonSettings?
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

                    NavigationLink {
                        PigeonClockSettingsView(device: device, caps: caps, info: info, status: status)
                    } label: {
                        PigeonClockSettingsButton(settings: clockSettings)
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
        if caps?.capabilities.contains("pigeon_settings") == true {
            clockSettings = try? await c.pigeonSettings()
        }
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

/// The device's Settings > Pigeon page on one screen: rooms and sports up top, then
/// Display, Theme, Clock and System as collapsible sections.
struct PigeonClockSettingsView: View {
    @EnvironmentObject private var store: DeviceStore
    let device: KnownDevice
    let caps: Capabilities?
    let info: DeviceInfo?
    let status: DeviceStatus?

    var body: some View {
        PigeonClockSettingsPage(client: store.client(for: device), device: device,
                                caps: caps?.capabilities ?? [], info: info, status: status)
            .navigationTitle("Pigeon Clock Settings")
            .navigationBarTitleDisplayMode(.inline)
    }
}

private struct PigeonClockSettingsPage: View {
    @StateObject private var settings: PigeonSettingsModel
    /// Bumped after a reset so everything re-reads the device.
    @State private var reload = 0
    let client: PigeonClient
    let device: KnownDevice
    let caps: [String]
    let info: DeviceInfo?
    let status: DeviceStatus?

    init(client: PigeonClient, device: KnownDevice, caps: [String], info: DeviceInfo?, status: DeviceStatus?) {
        _settings = StateObject(wrappedValue: PigeonSettingsModel(client: client))
        self.client = client
        self.device = device
        self.caps = caps
        self.info = info
        self.status = status
    }

    private var hasSettings: Bool { caps.contains("pigeon_settings") }

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if caps.contains("rooms") {
                        RoomsCard(client: client, canReset: caps.contains("room_reset")).id(reload)
                    }
                    if caps.contains("sports") { sports }
                    if hasSettings || caps.contains("display_brightness") {
                        CollapsibleTile(title: "Display") { display }
                    }
                    if hasSettings {
                        CollapsibleTile(title: "Theme") { theme }
                        CollapsibleTile(title: "Clock") { clock }
                    }
                    CollapsibleTile(title: "System") { system }
                    if let e = settings.errorText { Text(e).font(Theme.ui(13)).foregroundStyle(Theme.bad) }
                }
                .padding(Theme.gutter)
            }
        }
        .toolbar { if settings.busy { ToolbarItem(placement: .topBarTrailing) { ProgressView() } } }
        .task(id: reload) { if hasSettings { await settings.load() } }
    }

    private var sports: some View {
        NavigationLink { SportsView(client: client) } label: {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    LCDLabel(text: "Sports", size: 18, color: Theme.accent)
                    Text("Scores, followed teams and today's games")
                        .font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
                }
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
            }
            .frame(maxWidth: .infinity, alignment: .leading).tile()
        }
        .buttonStyle(.plain)
    }

    // MARK: Display: brightness, now playing layout, playback bar

    @ViewBuilder private var display: some View {
        if caps.contains("display_brightness") {
            BrightnessControl(client: client).id(reload)
        }
        if hasSettings {
            if let d = settings.data {
                OptionRow(model: settings, data: d, key: "np_layout", title: "Now playing layout",
                          labels: ["zone11": "Zone 11", "zone63": "Zone 6,3"],
                          note: d.options["np_layout"] == "zone63"
                              ? "Wide title, with the volume beside it."
                              : "Title across the top, with input, volume and running time below it.")
                // Zone 11's own look; Pigeon only offers it while the layout is Zone 11.
                if d.options["np_layout"] != "zone63" {
                    OptionRow(model: settings, data: d, key: "zone11_style", title: "Zone 11 style",
                              labels: ["standard": "Zone 11", "alt": "11 Alt"],
                              note: d.options["zone11_style"] == "alt"
                                  ? "No input, clock or volume; the title grows to fill the top."
                                  : "Input, clock and volume along the top.")
                }
                OptionRow(model: settings, data: d, key: "zone4_mode", title: "Playback bar",
                          labels: ["info": "Info", "visualizer": "Visualizer"])
            } else {
                placeholder
            }
        }
    }

    // MARK: Theme: interface color and standard / simple

    @ViewBuilder private var theme: some View {
        if let d = settings.data {
            VStack(alignment: .leading, spacing: 6) {
                Text("Color").font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
                ColorSwatches(model: settings, data: d)
            }
            OptionRow(model: settings, data: d, key: "ui_style", title: "Settings look",
                      labels: ["standard": "Standard", "simple": "Simple"],
                      note: d.options["ui_style"] == "simple"
                          ? "Settings are drawn in just the theme color and black."
                          : "Settings are drawn over the full themed background.")
        } else {
            placeholder
        }
    }

    // MARK: Clock: 12 / 24 hour, face, °F / °C, zip and timezone

    @ViewBuilder private var clock: some View {
        if let d = settings.data {
            OptionRow(model: settings, data: d, key: "time_format", title: "Hours",
                      labels: ["12": "12 hr", "24": "24 hr"])
            OptionRow(model: settings, data: d, key: "clock_format", title: "Clock face",
                      labels: ["digital": "Digital", "analog": "Analog"])
            OptionRow(model: settings, data: d, key: "temp_format", title: "Temperature",
                      labels: ["f": "°F", "c": "°C"])
            LocationFields(model: settings, data: d)
        } else {
            placeholder
        }
    }

    // MARK: System: status, update / factory reset / restart

    @ViewBuilder private var system: some View {
        VStack(alignment: .leading, spacing: 8) {
            row("State", status?.state.capitalized ?? "—")
            row("Now playing", status?.nowPlaying?.title ?? "Nothing")
            row("Version", settings.data?.version ?? info?.version ?? "—")
            row("Address", "\(device.host):\(device.port)")
        }
        if caps.contains("restart") || caps.contains("update") || caps.contains("factory_reset") {
            MaintenanceControls(client: client, caps: caps) { reload += 1 }
        }
    }

    @ViewBuilder private var placeholder: some View {
        if settings.errorText == nil {
            ProgressView().frame(maxWidth: .infinity)
        }
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack {
            Text(k).font(Theme.ui(15)).foregroundStyle(Theme.secondaryText)
            Spacer()
            Text(v).font(Theme.uiBold(15)).foregroundStyle(.white).multilineTextAlignment(.trailing)
        }
    }
}

/// A settings tile that folds down to its title; starts collapsed.
private struct CollapsibleTile<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button { withAnimation(.easeInOut(duration: 0.2)) { expanded.toggle() } } label: {
                HStack {
                    LCDLabel(text: title, size: 18, color: Theme.accent)
                    Spacer()
                    Image(systemName: "chevron.down")
                        .rotationEffect(.degrees(expanded ? 180 : 0))
                        .foregroundStyle(Theme.inactive)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityValue(expanded ? "Expanded" : "Collapsed")
            if expanded { content }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
        // Keeps the contents inside the tile while it grows or shrinks.
        .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
    }
}

/// The device page's way into its settings, drawn as Pigeon's digital clock:
/// date, HH:MM:SS and the 60 second boxes that fill as the minute goes by.
struct PigeonClockSettingsButton: View {
    /// Supplies the device's 12 / 24 hour choice and time zone; the phone's are used until it loads.
    let settings: PigeonSettings?

    private var timeZone: TimeZone {
        settings?.timezone.flatMap(TimeZone.init(identifier:)) ?? .current
    }

    private var uses24h: Bool { settings?.options["time_format"] == "24" }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                LCDLabel(text: "Pigeon Clock Settings", size: 18, color: Theme.accent)
                Spacer()
                Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
            }
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                VStack(spacing: 8) {
                    Text(Self.format(ctx.date, "EEEE, MMMM d", timeZone))
                        .font(Theme.uiBold(15)).foregroundStyle(Theme.secondaryText)
                    LCDLabel(text: Self.format(ctx.date, uses24h ? "HH:mm:ss" : "h:mm:ss", timeZone),
                             size: 72, color: Theme.accent)
                        .lineLimit(1).minimumScaleFactor(0.5)
                    SecondsBoxes(filled: Self.second(ctx.date, timeZone) + 1)
                }
                .frame(maxWidth: .infinity)
            }
            .accessibilityHidden(true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Pigeon Clock Settings")
    }

    private static func format(_ date: Date, _ pattern: String, _ tz: TimeZone) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = tz
        f.dateFormat = pattern
        return f.string(from: date)
    }

    private static func second(_ date: Date, _ tz: TimeZone) -> Int {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = tz
        return cal.component(.second, from: date)
    }
}

/// Pigeon's seconds track: 60 boxes, the elapsed ones lit (":00" lights one, ":59" all 60).
private struct SecondsBoxes: View {
    let filled: Int

    var body: some View {
        HStack(spacing: 1.5) {
            ForEach(0..<60, id: \.self) { i in
                RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                    .fill(i < filled ? Theme.accent : Theme.inactive.opacity(0.6))
            }
        }
        .frame(height: 16)
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
    func reset(_ room: Room) async {
        await run { self.data = try await self.client.resetRoom(room.id) }
    }

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
    @State private var resetting: Room?
    @State private var switching: Room?
    @State private var newName = ""
    /// The device can empty a single room (trash icon).
    let canReset: Bool

    init(client: PigeonClient, canReset: Bool = false) {
        _model = StateObject(wrappedValue: RoomsModel(client: client))
        self.canReset = canReset
    }

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
                    // Ask first: a stray tap while scrolling would switch players.
                    Button { if !r.current { switching = r } } label: {
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
                    if canReset {
                        Button { resetting = r } label: {
                            Image(systemName: "trash").foregroundStyle(Theme.secondaryText)
                                .frame(width: 36, height: 36).contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Reset \(r.name)")
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
        .alert("Switch to \(switching?.name.uppercased() ?? "room")?",
               isPresented: Binding(get: { switching != nil }, set: { if !$0 { switching = nil } })) {
            Button("Switch") { if let r = switching { Task { await model.choose(r) } } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Pigeon will use this room's player and audio receiver instead.")
        }
        .alert("Reset \(resetting?.name.uppercased() ?? "room")?",
               isPresented: Binding(get: { resetting != nil }, set: { if !$0 { resetting = nil } })) {
            Button("Reset", role: .destructive) { if let r = resetting { Task { await model.reset(r) } } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Unpairs this room's player and audio receiver and puts its name back to ROOM \(resetting?.slot ?? 1). Other rooms aren't changed.")
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

    func reset() async -> Bool {
        phase = .working("Resetting…")
        do {
            try await client.factoryReset()
            errorText = nil
            phase = .done("Pigeon is back to its default settings.")
            return true
        } catch { errorText = error.localizedDescription; phase = .idle; return false }
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

/// Check for updates, Factory Reset Pigeon and Restart Pigeon, for the System section.
struct MaintenanceControls: View {
    @StateObject private var model: MaintenanceModel
    let caps: [String]
    /// Called once a reset has gone through, so the other cards can re-read the device.
    let onReset: () -> Void
    @State private var confirmRestart = false
    @State private var confirmInstall = false
    @State private var confirmReset = false

    init(client: PigeonClient, caps: [String], onReset: @escaping () -> Void = {}) {
        _model = StateObject(wrappedValue: MaintenanceModel(client: client))
        self.caps = caps
        self.onReset = onReset
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            switch model.phase {
            case .working(let t):
                HStack(spacing: 8) {
                    ProgressView()
                    Text(t).font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
                }
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
            if caps.contains("factory_reset") {
                button("Factory Reset Pigeon", filled: false) { confirmReset = true }
            }
            if caps.contains("restart") {
                button("Restart Pigeon", filled: false) { confirmRestart = true }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .disabled(model.busy)
        .alert("Restart Pigeon?", isPresented: $confirmRestart) {
            Button("Restart", role: .destructive) { Task { await model.restart() } }
            Button("Cancel", role: .cancel) {}
        } message: { Text("The screen goes dark for about a minute while it starts back up.") }
        .alert("Install the update?", isPresented: $confirmInstall) {
            Button("Update") { Task { await model.install() } }
            Button("Cancel", role: .cancel) {}
        } message: { Text("Pigeon downloads the update, installs it and restarts. Your settings are kept.") }
        .alert("Factory Reset Pigeon?", isPresented: $confirmReset) {
            Button("Factory Reset", role: .destructive) {
                Task {
                    guard await model.reset() else { return }
                    try? await Task.sleep(for: .seconds(1.5))  // the device resets just after it replies
                    onReset()
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Theme, clock, location, rooms and paired players and receivers go back to their defaults. This can't be undone. This phone stays connected.")
        }
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

    /// Picking a color also leaves the old dark mode, like the device's theme menu.
    func setColor(_ key: String) async {
        await send(.init(zip: nil, timezone: nil, options: ["color_format": "color"], uiColor: key))
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

/// One of the device's two-way switches. Hidden when the device doesn't offer the option.
private struct OptionRow: View {
    @ObservedObject var model: PigeonSettingsModel
    let data: PigeonSettings
    let key: String
    let title: String
    let labels: [String: String]
    var note: String? = nil

    var body: some View {
        if let values = data.optionValues[key] {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
                Picker(title, selection: Binding(
                    get: { data.options[key] ?? values.first ?? "" },
                    set: { v in Task { await model.setOption(key, v) } })) {
                    ForEach(values, id: \.self) { v in Text(labels[v] ?? v).tag(v) }
                }
                .pickerStyle(.segmented)
                if let note { Text(note).font(Theme.ui(12)).foregroundStyle(Theme.secondaryText) }
            }
        }
    }
}

private struct ColorSwatches: View {
    @ObservedObject var model: PigeonSettingsModel
    let data: PigeonSettings

    static let swatches: [String: Color] = [
        "blue": Color(hex: 0x4EA6F7), "green": Color(hex: 0x00A32E), "yellow": Color(hex: 0xE6FF0A),
        "pink": Color(hex: 0xFF5CA8), "red": Color(hex: 0xFF0000),
        "orange": Color(hex: 0xE39F00), "grey": Color(hex: 0x777777), "white": .white,
    ]

    var body: some View {
        HStack(spacing: 14) {
            ForEach(data.uiColorChoices, id: \.self) { key in
                let selected = data.uiColor == key && data.options["color_format"] != "dark"
                Button { Task { await model.setColor(key) } } label: {
                    Circle().fill(Self.swatches[key] ?? .gray)
                        .frame(width: 38, height: 38)
                        .overlay(Circle().stroke(Color.white, lineWidth: selected ? 3 : 0).padding(-4))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(key.capitalized)
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
        .padding(.vertical, 4)
    }
}

private struct LocationFields: View {
    @ObservedObject var model: PigeonSettingsModel
    let data: PigeonSettings

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Zip code").font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
            HStack {
                TextField("5 digits", text: $model.zipText)
                    .keyboardType(.numberPad).font(Theme.uiBold(17))
                    .padding(10)
                    .background(Theme.tileRaised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                Button("Save") { Task { await model.saveZip() } }
                    .font(Theme.uiBold(16))
                    .disabled(model.zipText.count != 5 || model.zipText == (data.zip ?? ""))
            }
            Text("Time zone").font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
            Menu {
                ForEach(data.timezoneChoices, id: \.self) { tz in
                    Button(tz) { Task { await model.setTimezone(tz) } }
                }
            } label: {
                HStack {
                    Text(data.timezone ?? "System default").font(Theme.uiBold(16)).foregroundStyle(.white)
                    Spacer()
                    Image(systemName: "chevron.up.chevron.down").foregroundStyle(Theme.secondaryText)
                }
                .padding(10)
                .background(Theme.tileRaised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            Text("Setting a zip code also sets the time zone.").font(Theme.ui(12)).foregroundStyle(Theme.secondaryText)
        }
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

struct BrightnessControl: View {
    @StateObject private var model: BrightnessModel
    init(client: PigeonClient) { _model = StateObject(wrappedValue: BrightnessModel(client: client)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Brightness").font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
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
        .task { await model.load() }
    }
}
