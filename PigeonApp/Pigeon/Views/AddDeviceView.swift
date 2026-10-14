import SwiftUI
import UIKit

struct AddDeviceView: View {
    @EnvironmentObject private var store: DeviceStore
    @EnvironmentObject private var browser: DeviceBrowser
    @Environment(\.dismiss) private var dismiss

    @State private var target: Target?
    @State private var manualAddress = ""
    @State private var manualError: String?

    /// Where a claim is headed once the user types the on-screen code.
    struct Target: Identifiable {
        var id: String { host + ":" + String(port) }
        var host: String
        var port: Int
        var name: String
        var product: String
        var deviceID: String
    }

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.canvas.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        LCDLabel(text: "Nearby", size: 18, color: Theme.accent)
                        let fresh = browser.devices.filter { d in !store.devices.contains { $0.id == d.id } }
                        if fresh.isEmpty {
                            HStack(spacing: 10) {
                                ProgressView()
                                Text("Looking for Pigeons on this network…").font(Theme.ui(15))
                                    .foregroundStyle(Theme.secondaryText)
                            }.tile()
                        }
                        ForEach(fresh) { d in
                            Button { Task { await pick(d) } } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 4) {
                                        LCDLabel(text: d.name, size: 24)
                                        Text(d.claimed ? "Needs a new code" : "Ready to add")
                                            .font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
                                    }
                                    Spacer()
                                    Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
                                }.tile()
                            }.buttonStyle(.plain)
                        }

                        LCDLabel(text: "By address", size: 18, color: Theme.accent).padding(.top, 12)
                        VStack(alignment: .leading, spacing: 10) {
                            TextField("192.168.1.42 or name.local", text: $manualAddress)
                                .font(Theme.ui(18))
                                .keyboardType(.URL)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                            Button { Task { await pickManual() } } label: {
                                Text("Connect").font(Theme.uiBold(16)).frame(maxWidth: .infinity).padding(.vertical, 10)
                                    .background(Theme.tileRaised, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                            }
                            .disabled(manualAddress.trimmingCharacters(in: .whitespaces).isEmpty)
                            if let manualError { Text(manualError).font(Theme.ui(14)).foregroundStyle(Theme.bad) }
                        }.tile()
                    }
                    .padding(Theme.gutter)
                }
            }
            .navigationTitle("Add device")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .sheet(item: $target) { t in
                ClaimView(target: t) { dismiss() }
            }
        }
    }

    private func pick(_ d: DiscoveredDevice) async {
        guard let r = await DeviceBrowser.resolve(d.endpoint) else {
            manualError = "Couldn't reach \(d.name). Try adding it by address."
            return
        }
        target = Target(host: r.host, port: r.port, name: d.name, product: d.product, deviceID: d.id)
    }

    private func pickManual() async {
        let raw = manualAddress.trimmingCharacters(in: .whitespaces)
        let parts = raw.split(separator: ":", maxSplits: 1).map(String.init)
        let host = parts[0]
        let port = parts.count > 1 ? Int(parts[1]) ?? 8780 : 8780
        do {
            let hello = try await PigeonClient(host: host, port: port).hello()
            manualError = nil
            target = Target(host: host, port: port, name: hello.name, product: hello.product, deviceID: hello.id)
        } catch { manualError = error.localizedDescription }
    }
}

struct ClaimView: View {
    @EnvironmentObject private var store: DeviceStore
    @Environment(\.dismiss) private var dismiss
    let target: AddDeviceView.Target
    var onDone: () -> Void

    @State private var code = ""
    @State private var busy = false
    @State private var errorText: String?
    @FocusState private var focused: Bool

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            VStack(spacing: 22) {
                LCDLabel(text: target.name, size: 34)
                Text("Enter the code on your Pigeon's screen.\nSettings → Pigeon → App code")
                    .font(Theme.ui(16)).foregroundStyle(Theme.secondaryText).multilineTextAlignment(.center)
                TextField("000000", text: $code)
                    .font(Theme.lcd(64))
                    .multilineTextAlignment(.center)
                    .keyboardType(.numberPad)
                    .focused($focused)
                    .onChange(of: code) { _, v in
                        code = String(v.filter(\.isNumber).prefix(6))
                        if code.count == 6 { Task { await claim() } }
                    }
                    .tile()
                if busy { ProgressView() }
                if let errorText { Text(errorText).font(Theme.ui(15)).foregroundStyle(Theme.bad).multilineTextAlignment(.center) }
                Spacer()
            }
            .padding(Theme.gutter)
            .padding(.top, 32)
        }
        .task { focused = true }
        .presentationDetents([.medium])
    }

    private func claim() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let r = try await PigeonClient(host: target.host, port: target.port)
                .claim(code: code, controllerName: UIDevice.current.name, controllerID: store.controllerID)
            store.add(KnownDevice(id: r.device.id, name: r.device.name, product: target.product,
                                  host: target.host, port: target.port), token: r.token)
            dismiss()
            onDone()
        } catch let PigeonError.api(_, code, message) {
            errorText = code == "rate_limited" ? "Too many tries. Wait a minute." : message
            self.code = ""
        } catch {
            errorText = error.localizedDescription
            code = ""
        }
    }
}
