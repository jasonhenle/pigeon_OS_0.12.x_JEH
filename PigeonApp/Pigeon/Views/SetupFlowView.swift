import SwiftUI
import UIKit

/// First-run setup, started by scanning a Pigeon's Welcome screen (or after pairing one that still
/// needs setup): find it on the network, pair, then location, player, audio, done.
@MainActor
final class SetupFlowModel: ObservableObject {
    enum Phase: Equatable {
        case connecting(String)
        case failed(String)
        case location
        case player
        case audio
        case finished
    }

    /// Wizard steps in order, with the step names the device records (`PUT /setup`).
    static let steps: [Phase] = [.location, .player, .audio]

    @Published private(set) var phase: Phase = .connecting("Getting ready…")
    @Published private(set) var busy = false
    @Published var errorText: String?
    @Published var zip = ""
    @Published private(set) var settings: PigeonSettings?
    /// The device has started its on-screen search for the current step.
    @Published private(set) var searching = false
    @Published private(set) var skipped: [String] = []
    @Published private(set) var deviceName = "Pigeon"
    private(set) var deviceID: String?

    private var store: DeviceStore?
    private var client: PigeonClient? {
        guard let store, let id = deviceID, let d = store.devices.first(where: { $0.id == id }) else { return nil }
        return store.client(for: d)
    }

    static func stepName(_ p: Phase) -> String? {
        switch p {
        case .location: return "location"
        case .player: return "player"
        case .audio: return "audio"
        default: return nil
        }
    }

    var stepNumber: Int? { Self.steps.firstIndex(of: phase).map { $0 + 1 } }

    /// Time zone this iPhone uses, when the Pigeon offers it.
    var phoneTimeZone: String? {
        let tz = TimeZone.current.identifier
        return settings?.timezoneChoices.contains(tz) == true ? tz : nil
    }

    func start(_ request: SetupCoordinator.Request, store: DeviceStore, browser: DeviceBrowser) async {
        self.store = store
        switch request {
        case .device(let id):
            deviceID = id
            deviceName = store.devices.first { $0.id == id }?.name ?? "Pigeon"
            await beginWizard()
        case .link(let link):
            deviceName = link.name
            await connect(link, store: store, browser: browser)
        }
    }

    // MARK: Connect and pair

    private func connect(_ link: SetupLink, store: DeviceStore, browser: DeviceBrowser) async {
        phase = .connecting("Looking for \(link.name)…")
        browser.start()
        var addr: (host: String, port: Int)?
        // The address on the Pigeon's screen first: no mDNS lookup to wait on. Checked by id here and by
        // the certificate pin when pairing, so a stale address can't reach the wrong device.
        if let host = link.host {
            let port = link.port ?? 8780
            let hello: Hello? = try? await PigeonClient(host: host, port: port).send("GET", "/hello", timeout: 4)
            if hello?.id == link.deviceID { addr = (host, port) }
        }
        // Otherwise wait for its mDNS advertisement and an address; a lookup can time out, so keep trying.
        let deadline = Date().addingTimeInterval(25)
        while addr == nil, Date() < deadline {
            if let found = browser.devices.first(where: { $0.id == link.deviceID }) {
                addr = await DeviceBrowser.resolve(found.endpoint)
                if addr != nil { break }
            }
            try? await Task.sleep(for: .milliseconds(400))
            if Task.isCancelled { return }
        }
        guard let addr else {
            phase = .failed("Couldn't find \(link.name). Make sure this iPhone is on the same Wi-Fi network as "
                            + "the Pigeon, then scan the code again.")
            return
        }
        deviceID = link.deviceID

        // Already paired with this phone (setup was interrupted): pick up where it stopped.
        if store.devices.contains(where: { $0.id == link.deviceID }), store.token(for: link.deviceID) != nil {
            store.updateAddress(id: link.deviceID, host: addr.host, port: addr.port)
            if (try? await client?.setup()) != nil {
                await beginWizard()
                return
            }
        }

        phase = .connecting("Pairing with \(link.name)…")
        let hello: Hello
        do {
            hello = try await PigeonClient(host: addr.host, port: addr.port).hello()
        } catch {
            phase = .failed(error.localizedDescription)
            return
        }
        guard hello.id == link.deviceID else {
            phase = .failed("A different Pigeon answered. Scan the code again.")
            return
        }
        // The fingerprint came from the Pigeon's screen, so it is trusted as is; only the port comes
        // from the network (a wrong one just fails the pinned connection).
        var pin: TLSPin?
        if let fp = link.fingerprint {
            guard let tls = hello.tls else {
                phase = .failed("Couldn't connect to \(link.name) securely. Scan the code again.")
                return
            }
            pin = TLSPin(port: tls.port, fingerprint: fp)
        } else {
            pin = hello.tls?.pin
        }
        guard let code = link.code else {
            phase = .failed("\(link.name) is being set up from another iPhone. Finish there, or factory reset "
                            + "the Pigeon to start over.")
            return
        }
        do {
            let r = try await PigeonClient(host: addr.host, port: addr.port, pin: pin)
                .claim(code: code, controllerName: UIDevice.current.name, controllerID: store.controllerID)
            deviceName = r.device.name
            store.add(KnownDevice(id: r.device.id, name: r.device.name, product: hello.product,
                                  host: addr.host, port: addr.port, pin: pin), token: r.token)
        } catch PigeonError.transport {
            phase = .failed("Couldn't connect to \(link.name) securely. Scan the code again.")
            return
        } catch PigeonError.api(_, "not_claimed", _) {
            phase = .failed("That code has expired. Scan the code on the Pigeon's screen again.")
            return
        } catch {
            phase = .failed(error.localizedDescription)
            return
        }
        await beginWizard()
    }

    // MARK: Wizard

    private func beginWizard() async {
        guard let client else { phase = .failed("This Pigeon isn't paired with this iPhone."); return }
        do {
            let s = try await client.setup()
            skipped = s.skipped
            if s.isDone { phase = .finished; return }
            settings = try? await client.pigeonSettings()
            zip = settings?.zip ?? ""
            let resume = Self.steps.first { Self.stepName($0) == s.step } ?? .location
            await go(to: resume)
        } catch PigeonError.api(_, "unsupported", _) {
            phase = .finished  // firmware without setup: nothing to walk through
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    private func go(to next: Phase) async {
        searching = false
        errorText = nil
        if next == .finished {
            await run {
                guard let client = self.client else { return }
                // Record a skip of the last step too; complete keeps whatever was reported last.
                _ = try await client.setSetupProgress(step: "finish", skipped: self.skipped)
                self.skipped = try await client.completeSetup().skipped
            }
            if errorText == nil { phase = .finished }
            return
        }
        phase = next
        if let name = Self.stepName(next) {
            _ = try? await client?.setSetupProgress(step: name, skipped: skipped)
        }
    }

    private func advance() async {
        let i = Self.steps.firstIndex(of: phase) ?? Self.steps.count
        await go(to: i + 1 < Self.steps.count ? Self.steps[i + 1] : .finished)
    }

    func skip() async {
        if let name = Self.stepName(phase), !skipped.contains(name) { skipped.append(name) }
        await advance()
    }

    func next() async {
        if let name = Self.stepName(phase) { skipped.removeAll { $0 == name } }
        await advance()
    }

    func saveZip() async {
        let z = zip.trimmingCharacters(in: .whitespaces)
        guard z.count == 5, z.allSatisfy(\.isNumber) else { errorText = "Enter a 5-digit ZIP code."; return }
        await run {
            guard let client = self.client else { return }
            self.settings = try await client.patchPigeonSettings(.init(zip: z, timezone: nil, options: nil, uiColor: nil))
        }
        if errorText == nil { await next() }
    }

    func usePhoneTimeZone() async {
        guard let tz = phoneTimeZone else { return }
        await run {
            guard let client = self.client else { return }
            self.settings = try await client.patchPigeonSettings(.init(zip: nil, timezone: tz, options: nil, uiColor: nil))
        }
        if errorText == nil { await next() }
    }

    /// Starts the Pigeon's own search for a player or audio device in its current room.
    func search() async {
        let kind = phase == .audio ? "audio" : "player"
        await run {
            guard let client = self.client else { return }
            let rooms = try await client.rooms()
            try await client.startPairing(room: rooms.current, kind: kind)
            self.searching = true
        }
    }

    private func run(_ work: @escaping () async throws -> Void) async {
        busy = true
        defer { busy = false }
        do { try await work(); errorText = nil } catch { errorText = error.localizedDescription }
    }
}

struct SetupFlowView: View {
    let request: SetupCoordinator.Request
    @EnvironmentObject private var store: DeviceStore
    @EnvironmentObject private var browser: DeviceBrowser
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = SetupFlowModel()

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.canvas.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        if let n = model.stepNumber {
                            Text("STEP \(n) OF \(SetupFlowModel.steps.count)")
                                .font(Theme.uiBold(13)).foregroundStyle(Theme.accent)
                        }
                        content
                        if let e = model.errorText {
                            Text(e).font(Theme.ui(14)).foregroundStyle(Theme.bad)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(Theme.gutter)
                    .padding(.top, 12)
                }
            }
            .navigationTitle("Set up \(model.deviceName)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if model.phase != .finished {
                    ToolbarItem(placement: .cancellationAction) { Button("Later") { dismiss() } }
                }
            }
        }
        .interactiveDismissDisabled()
        .task { await model.start(request, store: store, browser: browser) }
    }

    @ViewBuilder private var content: some View {
        switch model.phase {
        case .connecting(let message):
            HStack(spacing: 12) {
                ProgressView()
                Text(message).font(Theme.ui(17)).foregroundStyle(.white)
            }
            .padding(.top, 40)
            .frame(maxWidth: .infinity)

        case .failed(let message):
            Heading(title: "Couldn't set up", text: message)
            PrimaryButton(title: "Close") { dismiss() }

        case .location:
            Heading(title: "Where is it?", text: "Enter ZIP code for timezone. Pigeon also uses it for the weather.")
            TextField("ZIP code", text: $model.zip)
                .font(Theme.lcd(44))
                .keyboardType(.numberPad)
                .textContentType(.postalCode)
                .onChange(of: model.zip) { _, v in model.zip = String(v.filter(\.isNumber).prefix(5)) }
                .tile()
            PrimaryButton(title: "Continue", busy: model.busy, disabled: model.zip.count != 5) {
                Task { await model.saveZip() }
            }
            if let tz = model.phoneTimeZone {
                SecondaryButton(title: "Use this iPhone's time zone (\(tz.replacingOccurrences(of: "_", with: " ")))") {
                    Task { await model.usePhoneTimeZone() }
                }
            }
            SecondaryButton(title: "Skip for now") { Task { await model.skip() } }

        case .player:
            pairingStep(
                title: "Connect a player",
                text: "Pigeon shows what's playing on your Apple TV, Roku or other streaming player.",
                noun: "players")

        case .audio:
            pairingStep(
                title: "Connect audio",
                text: "Pair your AV receiver so Pigeon can show its volume.",
                noun: "audio devices")

        case .finished:
            VStack(alignment: .leading, spacing: 14) {
                Image(systemName: "checkmark.circle.fill").font(.system(size: 56)).foregroundStyle(Theme.ok)
                Heading(title: "\(model.deviceName) is set up", text: finishedText)
            }
            .padding(.top, 24)
            PrimaryButton(title: "Done") {
                if let id = model.deviceID { store.selectedID = id }
                dismiss()
            }
        }
    }

    private var finishedText: String {
        let names = model.skipped.compactMap { ["location": "location", "player": "a player", "audio": "audio"][$0] }
        guard !names.isEmpty else { return "Everything's ready." }
        return "You can add \(names.joined(separator: " and ")) anytime from this Pigeon's settings in the app."
    }

    @ViewBuilder private func pairingStep(title: String, text: String, noun: String) -> some View {
        Heading(title: title, text: text)
        if model.searching {
            HStack(alignment: .top, spacing: 12) {
                ProgressView()
                Text("Pigeon is searching for \(noun). Pick yours on the Pigeon's screen with the knob, then tap Continue.")
                    .font(Theme.ui(15)).foregroundStyle(.white)
            }
            .tile()
            PrimaryButton(title: "Continue", busy: model.busy) { Task { await model.next() } }
            SecondaryButton(title: "Search again") { Task { await model.search() } }
        } else {
            PrimaryButton(title: "Search for \(noun)", busy: model.busy) { Task { await model.search() } }
        }
        SecondaryButton(title: "Skip for now") { Task { await model.skip() } }
    }
}

private struct Heading: View {
    let title: String
    let text: String
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(Theme.uiBold(28)).foregroundStyle(.white)
            Text(text).font(Theme.ui(16)).foregroundStyle(Theme.secondaryText)
        }
    }
}

private struct PrimaryButton: View {
    let title: String
    var busy = false
    var disabled = false
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            ZStack {
                Text(title).font(Theme.uiBold(17)).opacity(busy ? 0 : 1)
                if busy { ProgressView().tint(.black) }
            }
            .foregroundStyle(.black)
            .frame(maxWidth: .infinity).padding(.vertical, 15)
            .background(Theme.accent.opacity(disabled ? 0.4 : 1),
                        in: RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
        }
        .disabled(busy || disabled)
    }
}

private struct SecondaryButton: View {
    let title: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title).font(Theme.uiBold(16)).foregroundStyle(.white)
                .frame(maxWidth: .infinity).padding(.vertical, 13)
                .background(Theme.tile, in: RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
        }
    }
}
