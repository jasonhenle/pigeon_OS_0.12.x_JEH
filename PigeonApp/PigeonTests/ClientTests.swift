import XCTest
@testable import Pigeon

final class StubURLProtocol: URLProtocol {
    static var handler: ((URLRequest) -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let (status, data) = StubURLProtocol.handler?(request) ?? (500, Data())
        let resp = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

final class ClientTests: XCTestCase {
    private func client(token: String? = "pgt_x") -> PigeonClient {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.protocolClasses = [StubURLProtocol.self]
        return PigeonClient(host: "10.0.0.5", port: 8780, token: token, session: URLSession(configuration: cfg))
    }

    func testURLBuilding() {
        let u = PigeonClient(host: "pi.local", port: 8780).url("/search/suggest", query: [.init(name: "q", value: "blade run")])
        XCTAssertEqual(u.absoluteString, "http://pi.local:8780/api/v1/search/suggest?q=blade%20run")
    }

    func testBearerHeaderAndDecoding() async throws {
        StubURLProtocol.handler = { req in
            XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer pgt_x")
            XCTAssertEqual(req.url?.path, "/api/v1/status")
            return (200, #"{"state":"manual","now_playing":{"title":"Heat","source":"manual","tmdb_id":949},"manual_search":{"active":true,"entry":{"title":"Heat","kind":"movie","tmdb_id":949}}}"#.data(using: .utf8)!)
        }
        let s = try await client().status()
        XCTAssertEqual(s.state, "manual")
        XCTAssertEqual(s.nowPlaying?.tmdbId, 949)
        XCTAssertEqual(s.manualSearch.entry?.title, "Heat")
    }

    func testSetCurrentSearchSendsSnakeCase() async throws {
        StubURLProtocol.handler = { req in
            XCTAssertEqual(req.httpMethod, "PUT")
            let body = req.httpBodyStream.map { s -> Data in
                s.open(); defer { s.close() }
                var d = Data(); var buf = [UInt8](repeating: 0, count: 1024)
                while s.hasBytesAvailable { let n = s.read(&buf, maxLength: 1024); if n <= 0 { break }; d.append(buf, count: n) }
                return d
            } ?? req.httpBody ?? Data()
            let obj = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
            XCTAssertEqual(obj?["tmdb_id"] as? Int, 78)
            XCTAssertEqual(obj?["title"] as? String, "Blade Runner")
            XCTAssertEqual(obj?["year"] as? String, "1982")
            return (200, #"{"active":true,"entry":{"title":"Blade Runner","kind":"movie","tmdb_id":78}}"#.data(using: .utf8)!)
        }
        let s = Suggestion(tmdbId: 78, kind: "movie", title: "Blade Runner", year: 1982)
        let r = try await client().setCurrentSearch(s)
        XCTAssertTrue(r.active)
    }

    func testUnauthorizedAndAPIError() async {
        StubURLProtocol.handler = { _ in (401, Data()) }
        do { _ = try await client().status(); XCTFail() } catch { XCTAssertEqual(error as? PigeonError, .unauthorized) }

        StubURLProtocol.handler = { _ in (400, #"{"error":{"code":"bad_request","message":"q must be at least 2 characters.","details":{}}}"#.data(using: .utf8)!) }
        do { _ = try await client().suggest("a"); XCTFail() } catch {
            XCTAssertEqual(error as? PigeonError, .api(status: 400, code: "bad_request", message: "q must be at least 2 characters."))
        }
    }

    func testSSEParser() {
        var p = SSEParser()
        XCTAssertNil(p.feed(line: ": keepalive"))
        XCTAssertNil(p.feed(line: "event: manual_search"))
        XCTAssertNil(p.feed(line: #"data: {"active":true,"entry":{"title":"Heat","tmdb_id":949}}"#))
        let ev = p.feed(line: "")
        XCTAssertEqual(ev, .manualSearch(ManualSearchState(active: true, entry: ManualEntry(title: "Heat", kind: nil, tmdbId: 949, year: nil))))
    }

    func testPairStartAndCancel() async throws {
        var paths: [String] = []
        StubURLProtocol.handler = { req in
            paths.append("\(req.httpMethod ?? "") \(req.url?.path ?? "")")
            XCTAssertNil(req.value(forHTTPHeaderField: "Authorization"))
            return req.url?.path.hasSuffix("start") == true
                ? (200, #"{"expires_in_s":120}"#.data(using: .utf8)!) : (204, Data())
        }
        let c = client(token: nil)
        try await c.pairStart()
        await c.pairCancel()
        XCTAssertEqual(paths, ["POST /api/v1/pair/start", "POST /api/v1/pair/cancel"])
    }

    func testPairStartRefusedWhenClaimed() async {
        StubURLProtocol.handler = { _ in
            (403, #"{"error":{"code":"already_claimed","message":"Device already has a controller.","details":{}}}"#.data(using: .utf8)!)
        }
        do { try await client(token: nil).pairStart(); XCTFail() } catch {
            XCTAssertEqual(error as? PigeonError, .api(status: 403, code: "already_claimed", message: "Device already has a controller."))
        }
    }

    func testSuggestionSubtitle() {
        XCTAssertEqual(Suggestion(tmdbId: 1, kind: "tv", title: "X", year: 2020).subtitle, "TV · 2020")
        XCTAssertEqual(Suggestion(tmdbId: 1, kind: nil, title: "X", year: nil).subtitle, "")
    }
}
