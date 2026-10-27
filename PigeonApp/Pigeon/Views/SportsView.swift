import SwiftUI

/// The device's Settings > Pigeon > SPORTS page: SCORES show / hide, FOLLOWED TEAMS
/// auto / off (only while scores are shown), the teams to follow, and today's games.
@MainActor
final class SportsModel: ObservableObject {
    @Published private(set) var data: SportsSettings?
    @Published private(set) var busy = false
    @Published var errorText: String?
    let client: PigeonClient
    init(client: PigeonClient) { self.client = client }

    func load() async {
        do { data = try await client.sports(); errorText = nil }
        catch { errorText = error.localizedDescription }
    }

    func setScoresShown(_ on: Bool) async { await send(SportsPatch(scoresShown: on, followedAuto: nil)) }
    func setFollowedAuto(_ on: Bool) async { await send(SportsPatch(scoresShown: nil, followedAuto: on)) }

    func clearGame() async {
        busy = true
        defer { busy = false }
        do { try await client.clearGame(); await load() }
        catch { errorText = error.localizedDescription }
    }

    private func send(_ patch: SportsPatch) async {
        busy = true
        defer { busy = false }
        do { data = try await client.patchSports(patch); errorText = nil }
        catch { errorText = error.localizedDescription }
    }
}

struct SportsView: View {
    @StateObject private var model: SportsModel

    init(client: PigeonClient) { _model = StateObject(wrappedValue: SportsModel(client: client)) }

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let d = model.data {
                        settings(d)
                        if let game = d.board { onPigeon(game) }
                        leagues(d)
                        NavigationLink {
                            TodaysGamesView(model: model)
                        } label: {
                            linkTile(title: "Today's Games", detail: "Put any game on the Pigeon")
                        }
                        .buttonStyle(.plain)
                    } else if model.errorText == nil {
                        ProgressView().frame(maxWidth: .infinity)
                    }
                    if let e = model.errorText { Text(e).font(Theme.ui(13)).foregroundStyle(Theme.bad) }
                }
                .padding(Theme.gutter)
            }
            .refreshable { await model.load() }
        }
        .navigationTitle("Sports")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { if model.busy { ToolbarItem(placement: .topBarTrailing) { ProgressView() } } }
        .task { await model.load() }
    }

    @ViewBuilder private func settings(_ d: SportsSettings) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            LCDLabel(text: "Scores", size: 18, color: Theme.accent)
            switchRow(
                selection: Binding(get: { d.scoresShown }, set: { v in Task { await model.setScoresShown(v) } }),
                on: "Show", off: "Hide",
                note: d.scoresShown
                    ? "Games come up on the Pigeon with their scores."
                    : "Games still come up, without the scores, so nothing is spoiled.")
            Divider().overlay(Theme.inactive)
            LCDLabel(text: "Followed Teams", size: 18, color: d.scoresShown ? Theme.accent : Theme.inactive)
            switchRow(
                selection: Binding(get: { d.followedActive }, set: { v in Task { await model.setFollowedAuto(v) } }),
                on: "Auto", off: "Off",
                note: !d.scoresShown
                    ? "Show scores to use this."
                    : d.followedAuto
                        ? "When a team you follow plays, its game comes up on the Pigeon at kickoff."
                        : "Followed teams' games don't come up on their own.")
                .disabled(!d.scoresShown)
                .opacity(d.scoresShown ? 1 : 0.45)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
    }

    private func switchRow(selection: Binding<Bool>, on: String, off: String, note: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Picker(on, selection: selection) {
                Text(on).tag(true)
                Text(off).tag(false)
            }
            .pickerStyle(.segmented)
            Text(note).font(Theme.ui(12)).foregroundStyle(Theme.secondaryText)
        }
    }

    private func onPigeon(_ game: SportsGame) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            LCDLabel(text: "On the Pigeon", size: 18, color: Theme.accent)
            GameRow(game: game, framed: false)
            Button { Task { await model.clearGame() } } label: {
                Text("Take it off").font(Theme.uiBold(15))
                    .frame(maxWidth: .infinity).padding(.vertical, 10)
                    .background(Theme.tileRaised, in: Capsule())
            }
            .buttonStyle(.plain)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
    }

    private func leagues(_ d: SportsSettings) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            LCDLabel(text: "Teams to Follow", size: 18, color: Theme.accent)
                .padding(.bottom, 6)
            ForEach(d.leagues) { league in
                NavigationLink {
                    LeagueTeamsView(client: model.client, league: league) { await model.load() }
                } label: {
                    HStack {
                        Text(league.name).font(Theme.uiBold(17)).foregroundStyle(.white)
                        Spacer()
                        if !league.followed.isEmpty {
                            Text("\(league.followed.count) following").font(Theme.ui(14)).foregroundStyle(Theme.accent)
                        }
                        Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
                    }
                    .padding(.vertical, 10)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
    }

    private func linkTile(title: String, detail: String) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                LCDLabel(text: title, size: 18, color: Theme.accent)
                Text(detail).font(Theme.ui(13)).foregroundStyle(Theme.secondaryText)
            }
            Spacer()
            Image(systemName: "chevron.right").foregroundStyle(Theme.inactive)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .tile()
    }
}

// MARK: Teams

@MainActor
final class LeagueTeamsModel: ObservableObject {
    @Published private(set) var data: SportsTeamsResponse?
    @Published var errorText: String?
    private let client: PigeonClient
    let leagueID: String
    init(client: PigeonClient, leagueID: String) { self.client = client; self.leagueID = leagueID }

    func load() async {
        do { data = try await client.sportsTeams(league: leagueID); errorText = nil }
        catch { errorText = error.localizedDescription }
    }

    /// Flips the check at once; puts it back if the device says no.
    func toggle(_ team: SportsTeam) async {
        guard let i = data?.teams.firstIndex(where: { $0.id == team.id }) else { return }
        let on = !team.followed
        data?.teams[i].followed = on
        do { try await client.setFollow(league: leagueID, team: team.id, on); errorText = nil }
        catch {
            data?.teams[i].followed = !on
            errorText = error.localizedDescription
        }
    }
}

struct LeagueTeamsView: View {
    @StateObject private var model: LeagueTeamsModel
    @State private var query = ""
    /// Letter picked on the bar; the list scrolls to its section.
    @State private var jump: String?
    let league: SportsLeague
    let onChange: () async -> Void

    init(client: PigeonClient, league: SportsLeague, onChange: @escaping () async -> Void) {
        _model = StateObject(wrappedValue: LeagueTeamsModel(client: client, leagueID: league.id))
        self.league = league
        self.onChange = onChange
    }

    private var teams: [SportsTeam] {
        let all = model.data?.teams ?? []
        let q = query.trimmingCharacters(in: .whitespaces)
        return q.isEmpty ? all : all.filter { $0.name.localizedCaseInsensitiveContains(q) }
    }

    private var letters: [String] {
        // A→Z, with "#" (names starting with a digit) last.
        let found = Set(teams.map(\.letter))
        return found.sorted { a, b in
            if (a == "#") != (b == "#") { return b == "#" }
            return a < b
        }
    }

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            VStack(spacing: 0) {
                jumpBar
                // Only the list is inside the reader: the bar's letters share its ids.
                ScrollViewReader { proxy in
                    ScrollView { list.padding(Theme.gutter) }
                        .onChange(of: jump) { _, letter in
                            guard let letter else { return }
                            withAnimation { proxy.scrollTo(letter, anchor: .top) }
                            jump = nil
                        }
                }
            }
        }
        .navigationTitle(league.name)
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: "Find a team")
        .task { await model.load() }
        .onDisappear { Task { await onChange() } }
    }

    /// NCAA lists run to hundreds of teams: jump by letter, like the device.
    @ViewBuilder private var jumpBar: some View {
        if league.byLetter && query.isEmpty && !letters.isEmpty {
            LetterBar(letters: letters) { jump = $0 }
        }
    }

    private var list: some View {
        LazyVStack(alignment: .leading, spacing: 8, pinnedViews: league.byLetter ? [.sectionHeaders] : []) {
            if let e = model.errorText { Text(e).font(Theme.ui(13)).foregroundStyle(Theme.bad) }
            if model.data == nil && model.errorText == nil { ProgressView().frame(maxWidth: .infinity) }
            if league.byLetter {
                ForEach(letters, id: \.self) { letter in
                    Section { letterRows(letter) } header: { letterHeader(letter) }
                }
            } else {
                ForEach(teams) { row($0) }
            }
        }
    }

    private func letterRows(_ letter: String) -> some View {
        ForEach(teams.filter { $0.letter == letter }) { row($0) }
    }

    private func letterHeader(_ letter: String) -> some View {
        LCDLabel(text: letter, size: 22, color: Theme.accent)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 4)
            .background(Theme.canvas)
    }

    private func row(_ team: SportsTeam) -> some View {
        Button { Task { await model.toggle(team) } } label: {
            HStack {
                Text(team.name).font(Theme.uiBold(16)).foregroundStyle(.white)
                Spacer()
                Image(systemName: team.followed ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 22))
                    .foregroundStyle(team.followed ? Theme.accent : Theme.inactive)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .tile(selected: false)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(team.followed ? .isSelected : [])
    }
}

private struct LetterBar: View {
    let letters: [String]
    let jump: (String) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(letters, id: \.self) { l in
                    Button { jump(l) } label: {
                        LCDLabel(text: l, size: 22)
                            .frame(minWidth: 34).padding(.vertical, 6)
                            .background(Theme.tile, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Jump to \(l)")
                }
            }
            .padding(.horizontal, Theme.gutter)
            .padding(.vertical, 8)
        }
        .background(Theme.canvas)
    }
}

// MARK: Today's games

struct TodaysGamesView: View {
    @ObservedObject var model: SportsModel
    @State private var games: SportsGamesResponse?
    @State private var errorText: String?
    @State private var shownID: String?

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    if let g = games {
                        if g.busy {
                            note("TheSportsDB is busy, so some games may be missing. Pull to try again soon.")
                        }
                        if g.games.isEmpty {
                            if g.loading { ProgressView().frame(maxWidth: .infinity) }
                            else { note(g.failed ? "The Pigeon couldn't reach TheSportsDB." : "No games today.") }
                        }
                        ForEach(g.games) { game in
                            Button { Task { await show(game) } } label: {
                                GameRow(game: game, selected: game.id == (shownID ?? model.data?.board?.id))
                            }
                            .buttonStyle(.plain)
                        }
                    } else if errorText == nil {
                        ProgressView().frame(maxWidth: .infinity)
                    }
                    if let errorText { Text(errorText).font(Theme.ui(13)).foregroundStyle(Theme.bad) }
                }
                .padding(Theme.gutter)
            }
            .refreshable { await load() }
        }
        .navigationTitle("Today's Games")
        .navigationBarTitleDisplayMode(.inline)
        .task { await poll() }
    }

    /// The device fills the list league by league; keep asking while it's still loading.
    private func poll() async {
        await load()
        var tries = 0
        while games?.loading == true, tries < 40, !Task.isCancelled {
            try? await Task.sleep(for: .seconds(3))
            await load()
            tries += 1
        }
    }

    private func load() async {
        do { games = try await model.client.sportsGames(); errorText = nil }
        catch { errorText = error.localizedDescription }
    }

    private func show(_ game: SportsGame) async {
        do {
            _ = try await model.client.showGame(game.id)
            shownID = game.id
            errorText = nil
            await model.load()
        } catch { errorText = error.localizedDescription }
    }

    private func note(_ text: String) -> some View {
        Text(text).font(Theme.ui(14)).foregroundStyle(Theme.secondaryText)
    }
}

struct GameRow: View {
    let game: SportsGame
    var selected = false
    /// Off when the row already sits inside a tile.
    var framed = true

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                team(game.home, game.homeScore)
                team(game.away, game.awayScore)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 6) {
                HStack(spacing: 6) {
                    if game.phase == "live" { Circle().fill(Theme.bad).frame(width: 8, height: 8) }
                    Text(game.status).font(Theme.uiBold(14)).foregroundStyle(.white)
                }
                Text(game.league).font(Theme.ui(12)).foregroundStyle(Theme.secondaryText)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .modifier(GameRowFrame(framed: framed, selected: selected))
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func team(_ name: String, _ score: String?) -> some View {
        HStack(spacing: 10) {
            Text(name).font(Theme.uiBold(16)).foregroundStyle(.white).lineLimit(1)
            if let score { LCDLabel(text: score, size: 22, color: Theme.accent) }
        }
    }
}

private struct GameRowFrame: ViewModifier {
    let framed: Bool
    let selected: Bool

    func body(content: Content) -> some View {
        if framed { content.tile(selected: selected) } else { content }
    }
}
