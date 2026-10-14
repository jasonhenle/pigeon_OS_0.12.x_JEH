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
