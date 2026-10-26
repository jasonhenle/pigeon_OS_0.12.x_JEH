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

    func testPinnedClientUsesHTTPSOnTLSPort() {
        let pin = TLSPin(port: 8781, fingerprint: "ab")
        let u = PigeonClient(host: "pi.local", port: 8780, pin: pin).url("/status")
        XCTAssertEqual(u.absoluteString, "https://pi.local:8781/api/v1/status")
    }

    func testHelloDecodesTLSAndToleratesItsAbsence() throws {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase
        let base = #""id":"pgn-1","name":"C","product":"clock","api":1,"version":"0.12","claimed":false,"setup_mode":false"#
        let old = try d.decode(Hello.self, from: Data("{\(base)}".utf8))
        XCTAssertNil(old.tls)
        let new = try d.decode(Hello.self, from: Data(#"{\#(base),"tls":{"port":8781,"fingerprint_sha256":"AB12"}}"#.utf8))
        XCTAssertEqual(new.tls?.pin, TLSPin(port: 8781, fingerprint: "ab12"))
    }

    func testKnownDeviceFromBeforeTLSStillDecodes() throws {
        let json = #"{"id":"a","name":"n","product":"clock","host":"h","port":8780}"#
        XCTAssertNil(try JSONDecoder().decode(KnownDevice.self, from: Data(json.utf8)).pin)
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

    func testNowPlayingDetailDecoding() async throws {
        StubURLProtocol.handler = { req in
            XCTAssertEqual(req.url?.path, "/api/v1/now-playing/detail")
            return (200, """
            {"content_active":true,"app":"Disney+",
             "inputs":[{"key":"title","label":"Title","value":"The Final Show","editable":true},
                       {"key":"app_name","label":"App","value":"Disney+","editable":false}],
             "query":{"apple_tv":"The Final Show","resolved":"The Final Show","candidates":["The Final Show"],
                      "searched":"The Final Show","prefer":"auto","in_flight":false},
             "match":{"title":"Taylor Swift | The Eras Tour","kind":"movie","tmdb_id":1114513,"year":"2023",
                      "outcome":"matched","forced":false},
             "override":{"active":true,"query":"Heat (1995)","prefer":"movie","fields":{"query":"Heat"},
                         "year":"1995","pick":{"title":"Heat","kind":"movie","tmdb_id":949,"year":"1995"}}}
            """.data(using: .utf8)!)
        }
        let d = try await client().nowPlayingDetail()
        XCTAssertTrue(d.contentActive)
        XCTAssertEqual(d.inputs.filter(\.editable).map(\.key), ["title"])
        XCTAssertEqual(d.query.searched, "The Final Show")
        XCTAssertEqual(d.match?.tmdbId, 1114513)
        XCTAssertEqual(d.override.pick?.tmdbId, 949)
        XCTAssertEqual(d.override.fields?["query"], "Heat")
    }

    func testApplyPickSendsSnakeCasePick() async throws {
        StubURLProtocol.handler = { req in
            XCTAssertEqual(req.httpMethod, "PUT")
            let body = req.httpBodyStream.map { s -> Data in
                s.open(); defer { s.close() }
                var d = Data(); var buf = [UInt8](repeating: 0, count: 1024)
                while s.hasBytesAvailable { let n = s.read(&buf, maxLength: 1024); if n <= 0 { break }; d.append(buf, count: n) }
                return d
            } ?? req.httpBody ?? Data()
            let obj = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
            let pick = obj?["pick"] as? [String: Any]
            XCTAssertEqual(pick?["tmdb_id"] as? Int, 949)
            XCTAssertEqual(pick?["kind"] as? String, "movie")
            XCTAssertEqual(pick?["year"] as? String, "1995")
            return (200, #"{"content_active":true,"inputs":[],"query":{"candidates":[],"in_flight":false},"match":null,"override":{"active":true}}"#.data(using: .utf8)!)
        }
        let d = try await client().applyPick(Suggestion(tmdbId: 949, kind: "movie", title: "Heat", year: 1995))
        XCTAssertTrue(d.override.active)
    }

    func testApplyPickRequiresTMDbID() async {
        do { _ = try await client().applyPick(Suggestion(tmdbId: nil, kind: nil, title: "X", year: nil)); XCTFail() }
        catch { XCTAssertTrue(error is PigeonError) }
    }

    func testRoomsDecodeAndRenameRequest() async throws {
        var seen: [String] = []
        StubURLProtocol.handler = { req in
            seen.append("\(req.httpMethod ?? "") \(req.url?.path ?? "")")
            return (200, #"{"current":"loc-1","rooms":[{"id":"loc-1","slot":1,"name":"Theater","current":true},{"id":"loc-2","slot":2,"name":"ROOM 2","current":false}],"presets":["Theater","Office"]}"#.data(using: .utf8)!)
        }
        let c = client()
        let r = try await c.rooms()
        XCTAssertEqual(r.rooms.map(\.name), ["Theater", "ROOM 2"])
        XCTAssertEqual(r.rooms.first(where: \.current)?.id, "loc-1")
        _ = try await c.switchRoom("loc-2")
        _ = try await c.renameRoom("loc-2", to: "Den")
        XCTAssertEqual(seen, ["GET /api/v1/rooms", "PUT /api/v1/rooms/current", "PATCH /api/v1/rooms/loc-2"])
    }

    func testPigeonSettingsDecodeAndPatchOmitsNil() async throws {
        StubURLProtocol.handler = { req in
            if req.httpMethod == "PATCH" {
                let body = req.httpBodyStream.map { s -> Data in
                    s.open(); defer { s.close() }
                    var d = Data(); var buf = [UInt8](repeating: 0, count: 1024)
                    while s.hasBytesAvailable { let n = s.read(&buf, maxLength: 1024); if n <= 0 { break }; d.append(buf, count: n) }
                    return d
                } ?? req.httpBody ?? Data()
                let obj = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
                XCTAssertEqual(Set(obj?.keys.map { $0 } ?? []), ["options", "ui_color"])
                XCTAssertEqual((obj?["options"] as? [String: String])?["time_format"], "24")
            }
            return (200, """
            {"version":"0.12.15","zip":"21710","timezone":"America/New_York","timezone_choices":["America/New_York"],
             "options":{"time_format":"24"},"option_values":{"time_format":["12","24"]},
             "ui_color":"green","ui_color_choices":["blue","green"]}
            """.data(using: .utf8)!)
        }
        let c = client()
        let s = try await c.pigeonSettings()
        XCTAssertEqual(s.zip, "21710")
        XCTAssertEqual(s.optionValues["time_format"], ["12", "24"])
        XCTAssertEqual(s.uiColor, "green")
        _ = try await c.patchPigeonSettings(.init(zip: nil, timezone: nil, options: ["time_format": "24"], uiColor: "green"))
    }

    func testDisplayBrightnessGetAndSet() async throws {
        var seen: [String] = []
        StubURLProtocol.handler = { req in
            seen.append("\(req.httpMethod ?? "") \(req.url?.path ?? "")")
            if req.httpMethod == "PATCH" {
                let body = req.httpBodyStream.map { s -> Data in
                    s.open(); defer { s.close() }
                    var d = Data(); var buf = [UInt8](repeating: 0, count: 256)
                    while s.hasBytesAvailable { let n = s.read(&buf, maxLength: 256); if n <= 0 { break }; d.append(buf, count: n) }
                    return d
                } ?? req.httpBody ?? Data()
                let obj = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
                XCTAssertEqual(obj?["brightness"] as? Int, 40)
            }
            return (200, #"{"brightness":40,"min":10,"max":100,"mode":"software"}"#.data(using: .utf8)!)
        }
        let c = client()
        let d = try await c.display()
        XCTAssertEqual(d.min, 10)
        XCTAssertEqual(d.mode, "software")
        let after = try await c.setBrightness(40)
        XCTAssertEqual(after.brightness, 40)
        XCTAssertEqual(seen, ["GET /api/v1/display", "PATCH /api/v1/display"])
    }

    func testFactoryResetPostsToDeviceReset() async throws {
        var seen: [String] = []
        StubURLProtocol.handler = { req in
            seen.append("\(req.httpMethod ?? "") \(req.url?.path ?? "")")
            return (202, #"{"state":"resetting"}"#.data(using: .utf8)!)
        }
        try await client().factoryReset()
        XCTAssertEqual(seen, ["POST /api/v1/device/reset"])
    }

    func testSuggestionSubtitle() {
        XCTAssertEqual(Suggestion(tmdbId: 1, kind: "tv", title: "X", year: 2020).subtitle, "TV · 2020")
        XCTAssertEqual(Suggestion(tmdbId: 1, kind: nil, title: "X", year: nil).subtitle, "")
    }

    // MARK: /search/suggest parameters and errors (control_api/server.py `_search`)

    func testSuggestSendsKindYearAndLogosOnlyWhenSet() async throws {
        var queries: [[String: String]] = []
        StubURLProtocol.handler = { req in
            let items = URLComponents(url: req.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
            queries.append(Dictionary(uniqueKeysWithValues: items.map { ($0.name, $0.value ?? "") }))
            return (200, #"{"query":"heat","results":[{"tmdb_id":949,"kind":"movie","title":"Heat","year":1995}]}"#.data(using: .utf8)!)
        }
        let r = try await client().suggest("heat")
        _ = try await client().suggest("heat", logos: true, kind: "tv", year: "1995")
        XCTAssertEqual(r.first?.year, 1995)
        XCTAssertEqual(queries[0], ["q": "heat", "limit": "12"])  // 12 = server SUGGEST_MAX
        XCTAssertEqual(queries[1], ["q": "heat", "limit": "12", "logos": "1", "kind": "tv", "year": "1995"])
    }

    func testSearchServiceErrorsKeepTheDevicesMessage() async {
        for (code, message) in [("tmdb_not_configured", "TMDb isn't configured on this Pigeon device."),
                                ("search_unavailable", "Pigeon couldn't get results from TMDb.")] {
            StubURLProtocol.handler = { _ in
                (503, #"{"error":{"code":"\#(code)","message":"\#(message)","details":{}}}"#.data(using: .utf8)!)
            }
            do { _ = try await client().suggest("heat"); XCTFail() } catch {
                XCTAssertEqual(error as? PigeonError, .api(status: 503, code: code, message: message))
                XCTAssertEqual(error.localizedDescription, message)
            }
        }
    }

    func testBadFilterErrorEnvelopeWithFieldDetails() async {
        StubURLProtocol.handler = { _ in
            (400, #"{"error":{"code":"bad_request","message":"year must be four digits.","details":{"fields":["year"]}}}"#.data(using: .utf8)!)
        }
        do { _ = try await client().suggest("heat", year: "19"); XCTFail() } catch {
            XCTAssertEqual(error as? PigeonError, .api(status: 400, code: "bad_request", message: "year must be four digits."))
        }
    }
}

// MARK: Fix-view search state

@MainActor
final class NowPlayingFixSearchTests: XCTestCase {
    private func model(_ search: @escaping NowPlayingFixModel.Search) -> NowPlayingFixModel {
        NowPlayingFixModel(client: PigeonClient(host: "10.0.0.5"), debounce: .zero, search: search)
    }
    private let heat = Suggestion(tmdbId: 949, kind: "movie", title: "Heat", year: 1995)

    func testResultsThenEmptyThenErrorStates() async {
        var reply: Result<[Suggestion], Error> = .success([heat])
        let m = model { _, _, _, _ in try reply.get() }
        XCTAssertEqual(m.searchState, .idle)

        m.query = "heat"
        XCTAssertEqual(m.searchState, .loading)
        await m.searchTask?.value
        XCTAssertEqual(m.searchState, .results)
        XCTAssertEqual(m.results, [heat])

        reply = .success([])
        m.query = "heat 2"
        XCTAssertTrue(m.results.isEmpty, "old results clear as soon as the query changes")
        await m.searchTask?.value
        XCTAssertEqual(m.searchState, .empty)

        reply = .failure(PigeonError.api(status: 503, code: "tmdb_not_configured", message: "TMDb isn't configured."))
        m.query = "heat 3"
        await m.searchTask?.value
        XCTAssertEqual(m.searchState, .failed("TMDb isn't configured."))
        XCTAssertTrue(m.results.isEmpty)

        m.query = "h"
        XCTAssertEqual(m.searchState, .idle)
    }

    func testYearAndTypeChangesClearAndResearchWithFilters() async {
        var calls: [[String?]] = []
        let m = model { q, kind, year, logos in
            if !logos { calls.append([q, kind, year]) }
            return [self.heat]
        }
        m.query = "heat"
        await m.searchTask?.value
        XCTAssertEqual(m.results.count, 1)

        m.kind = "tv"
        XCTAssertTrue(m.results.isEmpty)
        XCTAssertEqual(m.searchState, .loading)
        await m.searchTask?.value
        m.year = "1995"
        await m.searchTask?.value
        XCTAssertEqual(calls.last ?? [], ["heat", "tv", "1995"])

        m.year = "199"  // not searchable yet: the device would answer 400
        XCTAssertEqual(m.searchState, .needsYear)
        XCTAssertTrue(m.results.isEmpty)
        let before = calls.count
        await m.searchTask?.value
        XCTAssertEqual(calls.count, before)

        m.year = "19a5"
        XCTAssertEqual(m.searchState, .needsYear)
    }

    func testLogosFillInAfterTheFastResults() async {
        let withLogo = Suggestion(tmdbId: 949, kind: "movie", title: "Heat", year: 1995, logoUrl: "https://x/heat.png")
        let m = model { _, _, _, logos in logos ? [withLogo] : [self.heat] }
        m.query = "heat"
        await m.searchTask?.value
        XCTAssertEqual(m.results.first?.logoUrl, "https://x/heat.png")
        XCTAssertEqual(m.searchState, .results)
    }

    func testLateReplyForAnOldQueryIsIgnored() async {
        let old = Suggestion(tmdbId: 1, kind: "movie", title: "Old", year: 2000)
        let m = model { q, _, _, _ in
            if q == "old title" {
                // Deliberately ignores cancellation, like a reply already on the wire.
                try? await Task.sleep(for: .milliseconds(150))
                return [old]
            }
            return [self.heat]
        }
        m.query = "old title"
        let first = m.searchTask
        try? await Task.sleep(for: .milliseconds(30))
        m.query = "heat"
        await m.searchTask?.value
        await first?.value  // the old reply lands after the new one
        XCTAssertEqual(m.results, [heat])
        XCTAssertEqual(m.searchState, .results)
    }

    func testLateErrorForAnOldQueryIsIgnored() async {
        let m = model { q, _, _, _ in
            if q == "old title" {
                try? await Task.sleep(for: .milliseconds(100))
                throw PigeonError.transport("timed out")
            }
            return [self.heat]
        }
        m.query = "old title"
        let first = m.searchTask
        try? await Task.sleep(for: .milliseconds(20))
        m.query = "heat"
        await m.searchTask?.value
        await first?.value
        XCTAssertEqual(m.searchState, .results)
    }
}
