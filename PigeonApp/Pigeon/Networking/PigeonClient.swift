import Foundation

enum PigeonError: LocalizedError, Equatable {
    case unauthorized
    case api(status: Int, code: String, message: String)
    case transport(String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .unauthorized: return "This device no longer recognizes this phone. Add it again."
        case .api(_, _, let message): return message
        case .transport(let m): return "Can't reach the device. \(m)"
        case .decoding(let m): return "Unexpected reply from the device. \(m)"
        }
    }
}

/// Talks to one device over HTTP. Stateless and cheap to create.
struct PigeonClient {
    var host: String
    var port: Int = 8780
    var token: String?
    var session: URLSession = .shared

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d
    }()
    private static let encoder: JSONEncoder = {
        let e = JSONEncoder(); e.keyEncodingStrategy = .convertToSnakeCase; return e
    }()

    func url(_ path: String, query: [URLQueryItem] = []) -> URL {
        var c = URLComponents()
        c.scheme = "http"
        c.host = host
        c.port = port
        c.path = "/api/v1" + path
        if !query.isEmpty { c.queryItems = query }
        return c.url!
    }

    func makeRequest(_ method: String, _ path: String, query: [URLQueryItem] = [], body: Encodable? = nil) throws -> URLRequest {
        var req = URLRequest(url: url(path, query: query), timeoutInterval: 8)
        req.httpMethod = method
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try Self.encoder.encode(AnyEncodable(body))
        }
        return req
    }

    @discardableResult
    private func perform(_ req: URLRequest) async throws -> Data {
        let data: Data, resp: URLResponse
        do { (data, resp) = try await session.data(for: req) }
        catch { throw PigeonError.transport(error.localizedDescription) }
        guard let http = resp as? HTTPURLResponse else { throw PigeonError.transport("No response") }
        if (200..<300).contains(http.statusCode) { return data }
        if http.statusCode == 401 { throw PigeonError.unauthorized }
        if let env = try? Self.decoder.decode(APIErrorEnvelope.self, from: data) {
            throw PigeonError.api(status: http.statusCode, code: env.error.code, message: env.error.message)
        }
        throw PigeonError.api(status: http.statusCode, code: "http_\(http.statusCode)", message: "The device returned an error.")
    }

    func send<T: Decodable>(_ method: String, _ path: String, query: [URLQueryItem] = [],
                            body: Encodable? = nil, as: T.Type = T.self) async throws -> T {
        let data = try await perform(try makeRequest(method, path, query: query, body: body))
        do { return try Self.decoder.decode(T.self, from: data) }
        catch { throw PigeonError.decoding(String(describing: error)) }
    }

    func sendNoContent(_ method: String, _ path: String) async throws {
        try await perform(try makeRequest(method, path))
    }

    // MARK: Endpoints

    func hello() async throws -> Hello { try await send("GET", "/hello") }

    func claim(code: String, controllerName: String, controllerID: String) async throws -> ClaimResponse {
        try await send("POST", "/claim", body: ClaimRequest(
            code: code, controller: .init(name: controllerName, id: controllerID)))
    }

    func device() async throws -> DeviceInfo { try await send("GET", "/device") }
    func capabilities() async throws -> Capabilities { try await send("GET", "/capabilities") }
    func status() async throws -> DeviceStatus { try await send("GET", "/status") }

    func suggest(_ q: String, limit: Int = 6) async throws -> [Suggestion] {
        let r: SuggestResponse = try await send("GET", "/search/suggest", query: [
            .init(name: "q", value: q), .init(name: "limit", value: String(limit))])
        return r.results
    }

    func currentSearch() async throws -> ManualSearchState { try await send("GET", "/search/current") }

    func setCurrentSearch(_ s: Suggestion) async throws -> ManualSearchState {
        try await send("PUT", "/search/current",
                       body: SetCurrentRequest(title: s.title, kind: s.kind, tmdbId: s.tmdbId,
                                               year: s.year.map(String.init)))
    }

    func clearCurrentSearch() async throws { try await sendNoContent("DELETE", "/search/current") }

    // MARK: Events (SSE)

    func events() -> AsyncThrowingStream<DeviceEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var req = try makeRequest("GET", "/events")
                    req.timeoutInterval = 60  // the device sends a keepalive every 15 s
                    req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    let (bytes, resp) = try await session.bytes(for: req)
                    guard let http = resp as? HTTPURLResponse else { throw PigeonError.transport("No response") }
                    if http.statusCode == 401 { throw PigeonError.unauthorized }
                    guard http.statusCode == 200 else {
                        throw PigeonError.api(status: http.statusCode, code: "events", message: "Event stream refused.")
                    }
                    var parser = SSEParser()
                    for try await line in bytes.lines {
                        if let ev = parser.feed(line: line) { continuation.yield(ev) }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

private struct AnyEncodable: Encodable {
    let value: Encodable
    init(_ v: Encodable) { value = v }
    func encode(to encoder: Encoder) throws { try value.encode(to: encoder) }
}

/// Incremental Server-Sent Events parser: feed it lines, get an event on each blank line.
struct SSEParser {
    private var event = ""
    private var data = ""
    private static let decoder: JSONDecoder = {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d
    }()

    mutating func feed(line: String) -> DeviceEvent? {
        if line.hasPrefix(":") { return nil }  // keepalive comment
        if line.isEmpty {
            defer { event = ""; data = "" }
            return event.isEmpty ? nil : Self.make(event: event, data: data)
        }
        if line.hasPrefix("event:") { event = line.dropFirst(6).trimmingCharacters(in: .whitespaces) }
        else if line.hasPrefix("data:") {
            let part = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
            data = data.isEmpty ? part : data + "\n" + part
        }
        return nil
    }

    private static func make(event: String, data: String) -> DeviceEvent {
        let raw = Data(data.utf8)
        switch event {
        case "snapshot":
            if let s = try? decoder.decode(DeviceStatus.self, from: raw) { return .snapshot(s) }
        case "now_playing":
            return .nowPlaying(try? decoder.decode(NowPlaying.self, from: raw))
        case "manual_search":
            if let m = try? decoder.decode(ManualSearchState.self, from: raw) { return .manualSearch(m) }
        case "device":
            return .device
        default: break
        }
        return .other(event)
    }
}
