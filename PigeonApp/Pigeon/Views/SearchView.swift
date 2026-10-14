import SwiftUI

@MainActor
final class SearchModel: ObservableObject {
    @Published var query = ""
    @Published private(set) var results: [Suggestion] = []
    @Published private(set) var current = ManualSearchState(active: false, entry: nil)
    @Published private(set) var isSearching = false
    @Published var errorText: String?

    private var client: PigeonClient?
    private var debounce: Task<Void, Never>?
    private var events: Task<Void, Never>?

    func attach(_ client: PigeonClient?) {
        self.client = client
        results = []
        current = ManualSearchState(active: false, entry: nil)
        errorText = nil
        events?.cancel()
        guard let client else { return }
        Task { await refreshCurrent() }
        events = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    for try await ev in client.events() {
                        guard let self else { return }
                        switch ev {
                        case .snapshot(let s): self.current = s.manualSearch
                        case .manualSearch(let m): self.current = m
                        default: break
                        }
                    }
                } catch { /* reconnect below */ }
                try? await Task.sleep(for: .seconds(3))
            }
        }
    }

    func detach() { events?.cancel(); debounce?.cancel() }

    func refreshCurrent() async {
        guard let client else { return }
        do { current = try await client.currentSearch() }
        catch { errorText = error.localizedDescription }
    }

    func queryChanged() {
        debounce?.cancel()
        let q = query.trimmingCharacters(in: .whitespaces)
        guard q.count >= 2 else { results = []; isSearching = false; return }
        debounce = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled, let self, let client = self.client else { return }
            self.isSearching = true
            defer { self.isSearching = false }
            do {
                let r = try await client.suggest(q)
                if !Task.isCancelled { self.results = r; self.errorText = nil }
            } catch {
                if !Task.isCancelled { self.errorText = error.localizedDescription }
            }
        }
    }

    func choose(_ s: Suggestion) async {
        guard let client else { return }
        do {
            current = try await client.setCurrentSearch(s)
            query = ""
            results = []
            errorText = nil
        } catch { errorText = error.localizedDescription }
    }

    func clear() async {
        guard let client else { return }
        do { try await client.clearCurrentSearch(); current = .init(active: false, entry: nil) }
        catch { errorText = error.localizedDescription }
    }
}

struct SearchView: View {
    @EnvironmentObject private var store: DeviceStore
    @StateObject private var model = SearchModel()
    @FocusState private var focused: Bool
    var goToDevices: () -> Void

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.canvas.ignoresSafeArea()
                if let device = store.selected {
                    content(for: device)
                } else {
                    EmptyDevicesView(goToDevices: goToDevices)
                }
            }
            .toolbar(.hidden, for: .navigationBar)
        }
        .onAppear { reattach() }
        .onChange(of: store.selectedID) { _, _ in reattach() }
        .onChange(of: store.selected?.host) { _, _ in reattach() }
        .onDisappear { model.detach() }
    }

    private func reattach() {
        model.attach(store.selected.map { store.client(for: $0) })
    }

    @ViewBuilder
    private func content(for device: KnownDevice) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            DeviceChip(device: device)
            searchField
            if let text = model.errorText {
                Text(text).font(Theme.ui(14)).foregroundStyle(Theme.bad)
            }
            ScrollView {
                VStack(spacing: 10) {
                    if model.current.active, let e = model.current.entry, model.query.isEmpty {
                        CurrentCard(entry: e, deviceName: device.name) { Task { await model.clear() } }
                    }
                    ForEach(model.results) { s in
                        Button { Task { await model.choose(s); focused = false } } label: {
                            SuggestionRow(suggestion: s)
                        }
                        .buttonStyle(.plain)
                    }
                    if model.results.isEmpty, model.query.count >= 2, !model.isSearching {
                        Text("No matches").font(Theme.ui(15)).foregroundStyle(Theme.secondaryText)
                            .padding(.top, 24)
                    }
                }
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .padding(.horizontal, Theme.gutter)
        .padding(.top, 8)
    }

    private var searchField: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass").foregroundStyle(Theme.secondaryText)
            TextField("Search a movie or show", text: $model.query)
                .font(Theme.ui(20))
                .focused($focused)
                .submitLabel(.search)
                .textInputAutocapitalization(.words)
                .autocorrectionDisabled()
                .onChange(of: model.query) { _, _ in model.queryChanged() }
            if model.isSearching { ProgressView() }
            else if !model.query.isEmpty {
                Button { model.query = "" } label: { Image(systemName: "xmark.circle.fill") }
                    .foregroundStyle(Theme.secondaryText)
            }
        }
        .padding(16)
        .background(Theme.tile, in: RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
        .task { focused = true }  // search is the app's primary action: keyboard ready on launch
    }
}

struct DeviceChip: View {
    @EnvironmentObject private var store: DeviceStore
    let device: KnownDevice

    var body: some View {
        Menu {
            ForEach(store.devices) { d in
                Button { store.selectedID = d.id } label: {
                    if d.id == device.id { Label(d.name, systemImage: "checkmark") } else { Text(d.name) }
                }
            }
        } label: {
            HStack(spacing: 8) {
                Circle().fill(Theme.ok).frame(width: 8, height: 8)
                LCDLabel(text: device.name, size: 22)
                if store.devices.count > 1 {
                    Image(systemName: "chevron.down").font(.caption).foregroundStyle(Theme.secondaryText)
                }
            }
            .padding(.vertical, 8).padding(.horizontal, 14)
            .background(Theme.tile, in: Capsule())
        }
        .disabled(store.devices.count < 2)
    }
}

struct SuggestionRow: View {
    let suggestion: Suggestion
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(suggestion.title).font(Theme.uiBold(18)).foregroundStyle(.white)
                    .multilineTextAlignment(.leading)
                if !suggestion.subtitle.isEmpty {
                    Text(suggestion.subtitle).font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
                }
            }
            Spacer()
            Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
        }
        .tile()
    }
}

struct CurrentCard: View {
    let entry: ManualEntry
    let deviceName: String
    var onClear: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            LCDLabel(text: "Showing on \(deviceName)", size: 18, color: Theme.accent)
            Text(entry.title).font(Theme.uiBold(22)).foregroundStyle(.white)
            Button(role: .destructive, action: onClear) {
                Text("Clear").font(Theme.uiBold(16)).frame(maxWidth: .infinity).padding(.vertical, 10)
                    .background(Theme.tileRaised, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile(selected: true)
    }
}

struct EmptyDevicesView: View {
    var goToDevices: () -> Void
    var body: some View {
        VStack(spacing: 16) {
            LCDLabel(text: "Pigeon", size: 48)
            Text("Add a Pigeon to start searching.").font(Theme.ui(17)).foregroundStyle(Theme.secondaryText)
            Button(action: goToDevices) {
                Text("Add a device").font(Theme.uiBold(18))
                    .padding(.horizontal, 28).padding(.vertical, 14)
                    .background(Theme.accent, in: Capsule()).foregroundStyle(.black)
            }
        }
    }
}
