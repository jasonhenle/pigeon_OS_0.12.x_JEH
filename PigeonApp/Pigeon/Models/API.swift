import Foundation

/// Wire types for the Pigeon Control API v1 (docs/control_api_v1.md).
/// The decoder uses `.convertFromSnakeCase`, so `tmdb_id` maps to `tmdbId`.

struct Hello: Codable, Equatable {
    var id: String
    var name: String
    var product: String
    var api: Int
    var version: String
    var claimed: Bool
    var setupMode: Bool
}

struct ClaimRequest: Codable {
    struct Controller: Codable { var name: String; var id: String }
    var code: String
    var controller: Controller
}

struct ClaimResponse: Codable {
    struct Device: Codable { var id: String; var name: String }
    var token: String
    var device: Device
}

struct DeviceInfo: Codable, Equatable {
    var id: String
    var name: String
    var product: String
    var version: String
    var api: Int
    var claimed: Bool
}

struct Capabilities: Codable, Equatable {
    var product: String
    var hasLocalUi: Bool
    var capabilities: [String]
}

struct ManualEntry: Codable, Equatable {
    var title: String
    var kind: String?
    var tmdbId: Int?
    var year: String?
}

struct ManualSearchState: Codable, Equatable {
    var active: Bool
    var entry: ManualEntry?
}

struct NowPlaying: Codable, Equatable {
    var title: String?
    var kind: String?
    var tmdbId: Int?
    var source: String?
    var app: String?
}

struct DeviceStatus: Codable, Equatable {
    var state: String
    var nowPlaying: NowPlaying?
    var manualSearch: ManualSearchState
}

struct Suggestion: Codable, Equatable, Identifiable {
    var tmdbId: Int?
    var kind: String?
    var title: String
    var year: Int?
    var id: String { "\(tmdbId ?? 0)-\(kind ?? "")-\(title)-\(year ?? 0)" }

    var subtitle: String {
        let k = kind == "tv" ? "TV" : (kind == "movie" ? "Movie" : "")
        return [k, year.map(String.init)].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

struct SuggestResponse: Codable {
    var query: String
    var results: [Suggestion]
}

struct SetCurrentRequest: Codable {
    var title: String
    var kind: String?
    var tmdbId: Int?
    var year: String?
}

struct APIErrorEnvelope: Codable {
    struct Body: Codable { var code: String; var message: String }
    var error: Body
}

enum DeviceEvent: Equatable {
    case snapshot(DeviceStatus)
    case nowPlaying(NowPlaying?)
    case manualSearch(ManualSearchState)
    case device
    case other(String)
}

struct PairStartResponse: Codable {
    var expiresInS: Int
}

// MARK: Now playing: inspect and correct the match

struct OverrideInput: Codable, Equatable, Identifiable {
    var key: String
    var label: String
    var value: String
    var editable: Bool
    var id: String { key }
}

struct QueryInfo: Codable, Equatable {
    var appleTv: String?
    var resolved: String?
    var candidates: [String]
    var searched: String?
    var prefer: String?
    var inFlight: Bool
}

struct MatchInfo: Codable, Equatable {
    var title: String?
    var kind: String?
    var tmdbId: Int?
    var year: String?
    var outcome: String?
    var forced: Bool
}

struct PickInfo: Codable, Equatable {
    var title: String
    var kind: String
    var tmdbId: Int
    var year: String?
}

struct OverrideState: Codable, Equatable {
    var active: Bool
    var query: String?
    var prefer: String?
    var fields: [String: String]?
    var year: String?
    var pick: PickInfo?
}

struct NowPlayingDetail: Codable, Equatable {
    var contentActive: Bool
    var app: String?
    var inputs: [OverrideInput]
    var query: QueryInfo
    var match: MatchInfo?
    var `override`: OverrideState
}

struct PreviewResponse: Codable {
    var query: String
    var candidates: [Suggestion]
}

struct PreviewRequest: Codable {
    var fields: [String: String]
    var year: String?
}

struct OverrideRequest: Codable {
    struct Pick: Codable {
        var title: String
        var kind: String
        var tmdbId: Int
        var year: String?
    }
    var fields: [String: String]?
    var year: String?
    var kind: String?
    var pick: Pick?
}
