import SwiftUI

@MainActor
final class SearchModel: ObservableObject {
    @Published var query = ""
    @Published private(set) var results: [Suggestion] = []
    @Published private(set) var current = ManualSearchState(active: false, entry: nil)
    @Published private(set) var isSearching = false
    @Published private(set) var nowPlaying: NowPlaying?
    @Published var errorText: String?

    private var client: PigeonClient?
    private var debounce: Task<Void, Never>?
    private var events: Task<Void, Never>?

    func attach(_ client: PigeonClient?) {
        self.client = client
        results = []
        current = ManualSearchState(active: false, entry: nil)
        nowPlaying = nil
        errorText = nil
        events?.cancel()
        guard let client else { return }
        Task { await refreshCurrent() }
        Task { if let st = try? await client.status() { self.nowPlaying = st.nowPlaying } }
        events = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    for try await ev in client.events() {
                        guard let self else { return }
                        switch ev {
                        case .snapshot(let s): self.current = s.manualSearch; self.nowPlaying = s.nowPlaying
                        case .manualSearch(let m): self.current = m
                        case .nowPlaying(let np): self.nowPlaying = np
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
    @State private var showFix = false
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
        .sheet(isPresented: $showFix) {
            if let d = store.selected {
                NavigationStack { NowPlayingFixView(client: store.client(for: d), deviceName: d.name) }
            }
        }
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
                    if let np = model.nowPlaying, np.source == "detected", model.query.isEmpty {
                        Button { showFix = true } label: { DetectedCard(nowPlaying: np) }
                            .buttonStyle(.plain)
                    }
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
            .scrollBounceBehavior(.always)  // short lists still drag-dismiss the keyboard
        }
        .contentShape(Rectangle())
        .onTapGesture { focused = false }
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

struct DetectedCard: View {
    let nowPlaying: NowPlaying
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 6) {
                LCDLabel(text: "Playing now", size: 18, color: Theme.accent)
                Text(nowPlaying.title ?? "Unknown title").font(Theme.uiBold(20)).foregroundStyle(.white)
                    .multilineTextAlignment(.leading)
                Text("Wrong title? Tap to see what Pigeon heard and fix it.")
                    .font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
                    .multilineTextAlignment(.leading)
            }
            Spacer()
            Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
    }
}

// MARK: Fix a wrong match

@MainActor
final class NowPlayingFixModel: ObservableObject {
    @Published private(set) var detail: NowPlayingDetail?
    @Published var edits: [String: String] = [:]
    @Published var year = ""
    @Published var kind = "auto"
    @Published private(set) var previewQuery: String?
    @Published private(set) var candidates: [Suggestion] = []
    @Published var freeQuery = "" { didSet { freeQueryChanged() } }
    @Published private(set) var freeResults: [Suggestion] = []
    @Published private(set) var busy = false
    @Published var errorText: String?
    @Published private(set) var notice: String?

    private let client: PigeonClient
    private var original: [String: String] = [:]
    private var debounce: Task<Void, Never>?

    init(client: PigeonClient) { self.client = client }

    /// Only the fields the user actually changed are sent.
    var changedFields: [String: String] {
        edits.filter { original[$0.key] != $0.value && $0.value.trimmingCharacters(in: .whitespaces) != "" }
    }

    var hasEdits: Bool {
        !changedFields.isEmpty || !year.trimmingCharacters(in: .whitespaces).isEmpty || kind != "auto"
    }

    func load() async {
        do {
            let d = try await client.nowPlayingDetail()
            absorb(d, resetEdits: true)
            errorText = nil
        } catch { errorText = error.localizedDescription }
    }

    private func absorb(_ d: NowPlayingDetail, resetEdits: Bool) {
        detail = d
        guard resetEdits else { return }
        original = Dictionary(uniqueKeysWithValues: d.inputs.filter(\.editable).map { ($0.key, $0.value) })
        edits = original
        year = d.override.year ?? ""
        kind = d.override.prefer ?? "auto"
        previewQuery = nil
        candidates = []
    }

    func preview() async {
        await run {
            let r = try await self.client.previewOverride(fields: self.changedFields,
                                                          year: self.year.isEmpty ? nil : self.year)
            self.previewQuery = r.query
            self.candidates = r.candidates
            if r.candidates.isEmpty { self.notice = "TMDb has no matches for “\(r.query)”." }
        }
    }

    func applyEdits() async {
        await run {
            let d = try await self.client.applyFields(self.changedFields,
                                                      year: self.year.isEmpty ? nil : self.year, kind: self.kind)
            self.absorb(d, resetEdits: false)
            self.notice = "Searching again with your changes."
        }
    }

    func pick(_ s: Suggestion) async {
        await run {
            let d = try await self.client.applyPick(s)
            self.absorb(d, resetEdits: false)
            self.freeQuery = ""
            self.notice = "Now showing “\(s.title)”."
        }
    }

    func reset() async {
        await run {
            let d = try await self.client.clearOverride()
            self.absorb(d, resetEdits: true)
            self.notice = "Back to what Pigeon detected."
        }
    }

    private func run(_ work: @escaping () async throws -> Void) async {
        busy = true
        notice = nil
        defer { busy = false }
        do { try await work(); errorText = nil } catch { errorText = error.localizedDescription }
    }

    private func freeQueryChanged() {
        debounce?.cancel()
        let q = freeQuery.trimmingCharacters(in: .whitespaces)
        guard q.count >= 2 else { freeResults = []; return }
        debounce = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled, let self else { return }
            if let r = try? await self.client.suggest(q), !Task.isCancelled { self.freeResults = r }
        }
    }
}

struct NowPlayingFixView: View {
    @StateObject private var model: NowPlayingFixModel
    @Environment(\.dismiss) private var dismiss
    let deviceName: String

    init(client: PigeonClient, deviceName: String) {
        _model = StateObject(wrappedValue: NowPlayingFixModel(client: client))
        self.deviceName = deviceName
    }

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let d = model.detail {
                        matchCard(d)
                        pickCard      // first: its results must sit above the keyboard
                        heardCard(d)
                        adjustCard
                    } else if model.errorText == nil {
                        ProgressView().frame(maxWidth: .infinity).padding(.top, 40)
                    }
                    if let n = model.notice { Text(n).font(Theme.ui(14)).foregroundStyle(Theme.ok) }
                    if let e = model.errorText { Text(e).font(Theme.ui(14)).foregroundStyle(Theme.bad) }
                }
                .padding(Theme.gutter)
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .navigationTitle("Fix match")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        .task { await model.load() }
    }

    // What Pigeon is showing right now.
    private func matchCard(_ d: NowPlayingDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            LCDLabel(text: "Showing on \(deviceName)", size: 18, color: Theme.accent)
            Text(d.match?.title ?? "Nothing matched yet").font(Theme.uiBold(22)).foregroundStyle(.white)
            let bits = [d.match?.kind == "tv" ? "TV" : (d.match?.kind == "movie" ? "Movie" : nil), d.match?.year]
                .compactMap { $0 }.filter { !$0.isEmpty }
            if !bits.isEmpty {
                Text(bits.joined(separator: " · ")).font(Theme.ui(15)).foregroundStyle(Theme.secondaryText)
            }
            if d.override.active {
                HStack {
                    LCDLabel(text: d.override.pick != nil ? "Picked by you · remembered" : "Edited by you · remembered", size: 16, color: Theme.ok)
                    Spacer()
                    Button("Reset") { Task { await model.reset() } }.font(Theme.uiBold(15))
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile(selected: d.override.active)
    }

    // The metadata that fed the search; editable ones can be changed.
    private func heardCard(_ d: NowPlayingDetail) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            LCDLabel(text: "What Pigeon heard", size: 18, color: Theme.accent)
            if let app = d.app {
                row("App", app)
            }
            ForEach(d.inputs) { f in
                if f.editable {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(f.label).font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
                        TextField("—", text: Binding(
                            get: { model.edits[f.key] ?? "" },
                            set: { model.edits[f.key] = $0 }))
                            .font(Theme.uiBold(17))
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .padding(10)
                            .background(Theme.tileRaised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                } else if f.key != "app_name" {
                    row(f.label, f.value)
                }
            }
            if let s = d.query.searched {
                Divider().overlay(Theme.inactive)
                row("Last searched", s)
                if let r = d.query.resolved, r != s { row("Would search", r) }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
    }

    private var adjustCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            LCDLabel(text: "Search again", size: 18, color: Theme.accent)
            HStack {
                Text("Year").font(Theme.ui(15)).foregroundStyle(Theme.secondaryText)
                TextField("optional", text: $model.year)
                    .keyboardType(.numberPad).font(Theme.uiBold(17)).frame(width: 90)
                    .padding(8).background(Theme.tileRaised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                Spacer()
            }
            Picker("Type", selection: $model.kind) {
                Text("Any").tag("auto"); Text("Movie").tag("movie"); Text("TV").tag("tv")
            }.pickerStyle(.segmented)
            HStack(spacing: 10) {
                actionButton("See matches", filled: false) { Task { await model.preview() } }
                actionButton("Apply", filled: true) { Task { await model.applyEdits() } }
            }
            .disabled(!model.hasEdits || model.busy)
            .opacity(model.hasEdits ? 1 : 0.4)

            if let q = model.previewQuery {
                Text("Would search for “\(q)”").font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
                ForEach(model.candidates) { c in
                    Button { Task { await model.pick(c) } } label: { SuggestionRow(suggestion: c) }
                        .buttonStyle(.plain)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
    }

    private var pickCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            LCDLabel(text: "Or pick the title yourself", size: 18, color: Theme.accent)
            HStack {
                Image(systemName: "magnifyingglass").foregroundStyle(Theme.secondaryText)
                TextField("Search TMDb", text: $model.freeQuery)
                    .font(Theme.ui(18)).autocorrectionDisabled()
            }
            .padding(10).background(Theme.tileRaised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            ForEach(model.freeResults) { c in
                Button { Task { await model.pick(c) } } label: { SuggestionRow(suggestion: c) }
                    .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
    }

    private func row(_ k: String, _ v: String) -> some View {
        HStack(alignment: .top) {
            Text(k).font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
            Spacer()
            Text(v).font(Theme.uiBold(14)).foregroundStyle(.white).multilineTextAlignment(.trailing)
        }
    }

    private func actionButton(_ title: String, filled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(Theme.uiBold(16)).frame(maxWidth: .infinity).padding(.vertical, 12)
                .foregroundStyle(filled ? Color.black : Color.white)
                .background(filled ? Theme.accent : Theme.tileRaised, in: Capsule())
        }
    }
}
