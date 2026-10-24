import SwiftUI

@MainActor
final class SearchModel: ObservableObject {
    @Published private(set) var current = ManualSearchState(active: false, entry: nil)
    @Published private(set) var nowPlaying: NowPlaying?
    @Published var errorText: String?

    private var client: PigeonClient?
    private var events: Task<Void, Never>?

    func attach(_ client: PigeonClient?) {
        self.client = client
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

    func detach() { events?.cancel() }

    func refreshCurrent() async {
        guard let client else { return }
        do { current = try await client.currentSearch() }
        catch { errorText = error.localizedDescription }
    }

    func clear() async {
        guard let client else { return }
        do { try await client.clearCurrentSearch(); current = .init(active: false, entry: nil) }
        catch { errorText = error.localizedDescription }
    }
}

/// "Playing now" for one device on its detail page.
struct PlayingNowSection: View {
    @EnvironmentObject private var store: DeviceStore
    @StateObject private var model = SearchModel()
    let device: KnownDevice

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let text = model.errorText {
                Text(text).font(Theme.ui(14)).foregroundStyle(Theme.bad)
            }
            LCDLabel(text: "Playing now", size: 18, color: Theme.accent)
            let detected = model.nowPlaying.flatMap { $0.source == "detected" ? $0 : nil }
            let manual = model.current.active ? model.current.entry : nil
            if let np = detected {
                NavigationLink {
                    NowPlayingFixView(client: store.client(for: device), deviceName: device.name)
                } label: { DetectedCard(nowPlaying: np) }
                    .buttonStyle(.plain)
            }
            if let e = manual {
                PinnedTitleRow(entry: e) { Task { await model.clear() } }
            }
            if detected == nil && manual == nil {
                Text("Nothing playing").font(Theme.ui(15)).foregroundStyle(Theme.secondaryText)
            }
            if detected == nil {
                NavigationLink {
                    NowPlayingFixView(client: store.client(for: device), deviceName: device.name, manual: true)
                } label: {
                    HStack {
                        Image(systemName: "magnifyingglass").foregroundStyle(Theme.accent)
                        Text(manual == nil ? "Search for a title to show" : "Search for a different title")
                            .font(Theme.uiBold(16)).foregroundStyle(.white)
                        Spacer()
                        Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .tile()
                }
                .buttonStyle(.plain)
            }
        }
        .onAppear { reattach() }
        .onChange(of: device.host) { _, _ in reattach() }
        .onDisappear { model.detach() }
    }

    private func reattach() { model.attach(store.client(for: device)) }
}

struct SuggestionRow: View {
    let suggestion: Suggestion
    /// Reserve the logo tile (search results, whose logos load a moment after the list).
    var logoSlot = false
    var body: some View {
        HStack(spacing: 12) {
            if logoSlot || suggestion.logoUrl != nil { artwork }
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

    /// The title's logo (title treatment) on a dark tile so versions can be told
    /// apart at a glance. With ``logoSlot`` the tile is reserved so rows line up while
    /// logos load; a title with no logo keeps an empty tile and its text.
    private var artwork: some View {
        ZStack {
            Color.black
            if let url = suggestion.logoUrl.flatMap(URL.init(string:)) {
                AsyncImage(url: url) { phase in
                    if let image = phase.image {
                        image.resizable().scaledToFit().padding(6)
                    } else {
                        Color.clear
                    }
                }
            }
        }
        .frame(width: 96, height: 56)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

/// A title pinned from elsewhere: just its name and a way to let go of it.
struct PinnedTitleRow: View {
    let entry: ManualEntry
    var onClear: () -> Void

    var body: some View {
        HStack {
            Text(entry.title).font(Theme.uiBold(20)).foregroundStyle(.white)
                .multilineTextAlignment(.leading)
            Spacer()
            Button("Clear", role: .destructive, action: onClear).font(Theme.uiBold(16))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile(selected: true)
    }
}

struct DetectedCard: View {
    let nowPlaying: NowPlaying
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 6) {
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

/// Where the TMDb search box stands. Anything but `.results` shows no rows.
enum SearchState: Equatable {
    case idle
    case needsYear
    case loading
    case results
    case empty
    case failed(String)
}

@MainActor
final class NowPlayingFixModel: ObservableObject {
    @Published private(set) var detail: NowPlayingDetail?
    @Published var year = "" { didSet { searchSettingsChanged() } }
    /// "auto" (any), "movie" or "tv".
    @Published var kind = "auto" { didSet { searchSettingsChanged() } }
    @Published var query = "" { didSet { searchSettingsChanged() } }
    @Published private(set) var results: [Suggestion] = []
    @Published private(set) var searchState: SearchState = .idle
    @Published private(set) var busy = false
    @Published var errorText: String?
    @Published private(set) var notice: String?

    typealias Search = (_ query: String, _ kind: String?, _ year: String?, _ logos: Bool) async throws -> [Suggestion]

    private let client: PigeonClient
    private let search: Search
    /// Pins a title directly (nothing detected) instead of overriding a detected one.
    let manual: Bool
    private let debounceDelay: Duration
    /// The in-flight (debounced) search; tests await it.
    private(set) var searchTask: Task<Void, Never>?
    /// Bumped on every change, so a reply for an older query is dropped.
    private var searchGeneration = 0

    init(client: PigeonClient, manual: Bool = false,
         debounce: Duration = .milliseconds(300), search: Search? = nil) {
        self.client = client
        self.manual = manual
        self.debounceDelay = debounce
        self.search = search ?? { q, kind, year, logos in
            try await client.suggest(q, logos: logos, kind: kind, year: year)
        }
    }

    func load() async {
        guard !manual else { return }
        do {
            detail = try await client.nowPlayingDetail()
            errorText = nil
        } catch { errorText = error.localizedDescription }
    }

    func pick(_ s: Suggestion) async {
        await run {
            if self.manual {
                _ = try await self.client.setCurrentSearch(s)
            } else {
                self.detail = try await self.client.applyPick(s)
            }
            self.query = ""
            self.notice = "Now showing “\(s.title)”."
        }
    }

    func reset() async {
        await run {
            self.detail = try await self.client.clearOverride()
            self.notice = "Back to what Pigeon detected."
        }
    }

    private func run(_ work: @escaping () async throws -> Void) async {
        busy = true
        notice = nil
        defer { busy = false }
        do { try await work(); errorText = nil } catch { errorText = error.localizedDescription }
    }

    /// Re-runs the TMDb search when the text, year or type changes. The old results go
    /// at once; a reply that arrives after a newer change is ignored.
    func searchSettingsChanged() {
        searchTask?.cancel()
        searchGeneration += 1
        let generation = searchGeneration
        results = []
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard q.count >= 2 else { searchState = .idle; return }
        let y = year.trimmingCharacters(in: .whitespaces)
        // The device only takes a four-digit year (anything else is a 400).
        guard y.isEmpty || (y.count == 4 && y.allSatisfy(\.isASCII) && y.allSatisfy(\.isNumber)) else {
            searchState = .needsYear
            return
        }
        let k = kind == "auto" ? nil : kind
        searchState = .loading
        searchTask = Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(for: self.debounceDelay)
            guard !Task.isCancelled, generation == self.searchGeneration else { return }
            do {
                let year = y.isEmpty ? nil : y
                let found = try await self.search(q, k, year, false)
                guard generation == self.searchGeneration else { return }
                self.results = found
                self.searchState = found.isEmpty ? .empty : .results
                // Logos cost the device one TMDb call per title, so they arrive a moment later.
                guard !found.isEmpty, let rich = try? await self.search(q, k, year, true),
                      generation == self.searchGeneration else { return }
                let logos = Dictionary(rich.compactMap { r in r.logoUrl.map { (r.id, $0) } },
                                       uniquingKeysWith: { a, _ in a })
                self.results = self.results.map { r in var r = r; r.logoUrl = logos[r.id]; return r }
            } catch {
                guard generation == self.searchGeneration else { return }
                self.searchState = .failed(error.localizedDescription)
            }
        }
    }
}

struct NowPlayingFixView: View {
    @StateObject private var model: NowPlayingFixModel
    @Environment(\.dismiss) private var dismiss
    let deviceName: String

    init(client: PigeonClient, deviceName: String, manual: Bool = false) {
        _model = StateObject(wrappedValue: NowPlayingFixModel(client: client, manual: manual))
        self.deviceName = deviceName
    }

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if model.manual {
                        pickCard(nil)
                    } else if let d = model.detail {
                        heardCard(d)
                        pickCard(d)
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
        .navigationTitle(model.manual ? "Show a title" : "Playing now")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        .task { await model.load() }
    }

    // The metadata that fed the search.
    private func heardCard(_ d: NowPlayingDetail) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            LCDLabel(text: "What Pigeon Heard", size: 18, color: Theme.accent)
            if let app = d.app {
                row("App", app)
            }
            ForEach(d.inputs) { f in
                if f.key != "app_name" { row(f.label, f.value) }
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

    private func pickCard(_ d: NowPlayingDetail?) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            LCDLabel(text: d == nil ? "Pick the title" : "Or pick the title yourself", size: 18, color: Theme.accent)
            if let d, d.override.active {
                HStack {
                    Text(d.override.pick != nil ? "Picked by you · remembered" : "Edited by you · remembered")
                        .font(Theme.ui(14)).foregroundStyle(Theme.ok)
                    Spacer()
                    Button("Reset") { Task { await model.reset() } }.font(Theme.uiBold(15))
                }
            }
            HStack {
                Image(systemName: "magnifyingglass").foregroundStyle(Theme.secondaryText)
                TextField("Search TMDb", text: $model.query)
                    .font(Theme.ui(18)).autocorrectionDisabled()
            }
            .padding(10).background(Theme.tileRaised, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
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
            switch model.searchState {
            case .idle, .results: EmptyView()
            case .needsYear:
                Text("Enter a four-digit year, or clear it.").font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
            case .loading:
                HStack(spacing: 8) {
                    ProgressView()
                    Text("Searching…").font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
                }
            case .empty:
                Text("No matches. Try fewer words, another year, or Any type.")
                    .font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
            case .failed(let message):
                Text(message).font(Theme.ui(14)).foregroundStyle(Theme.bad)
            }
            ForEach(model.results) { c in
                Button { Task { await model.pick(c) } } label: { SuggestionRow(suggestion: c, logoSlot: true) }
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
}
