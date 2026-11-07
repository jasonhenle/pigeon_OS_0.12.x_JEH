import XCTest
@testable import Pigeon

final class SetupTests: XCTestCase {
    private let fp = String(repeating: "ab", count: 32)

    func testParsesWelcomeScreenLink() throws {
        let url = URL(string: "pigeon://setup#v=1&id=pgn-7f3a91&name=Pigeon+Clock&code=482913&fp=\(fp.uppercased())")!
        let link = try XCTUnwrap(SetupLink(url: url))
        XCTAssertEqual(link, SetupLink(deviceID: "pgn-7f3a91", name: "Pigeon Clock", code: "482913", fingerprint: fp))
    }

    func testDirectAddress() throws {
        let link = try XCTUnwrap(SetupLink(url: URL(string: "pigeon://setup#id=pgn-1&host=10.0.4.44&port=8780")!))
        XCTAssertEqual(link.host, "10.0.4.44")
        XCTAssertEqual(link.port, 8780)
        let bad = try XCTUnwrap(SetupLink(url: URL(string: "pigeon://setup#id=pgn-1&host=a%2Fb&port=99999")!))
        XCTAssertNil(bad.host)
        XCTAssertNil(bad.port)
    }

    func testPercentEncodedNameAndMissingOptionalFields() throws {
        let link = try XCTUnwrap(SetupLink(url: URL(string: "pigeon://setup#v=1&id=pgn-1&name=Den%27s+Clock")!))
        XCTAssertEqual(link.name, "Den's Clock")
        XCTAssertNil(link.code)
        XCTAssertNil(link.fingerprint)
    }

    func testRejectsBadValues() throws {
        let link = try XCTUnwrap(SetupLink(url: URL(string: "pigeon://setup#id=pgn-1&code=12ab56&fp=xyz")!))
        XCTAssertNil(link.code)
        XCTAssertNil(link.fingerprint)
        XCTAssertEqual(link.name, "Pigeon")
    }

    func testOnlySetupLinks() {
        XCTAssertNil(SetupLink(url: URL(string: "pigeon://setup#name=x")!))  // no id
        XCTAssertNil(SetupLink(url: URL(string: "pigeon://other#id=pgn-1")!))
        XCTAssertNil(SetupLink(url: URL(string: "https://example.com/other#id=pgn-1")!))
        XCTAssertNotNil(SetupLink(url: URL(string: "https://example.com/setup#id=pgn-1")!))
    }

    @MainActor
    func testCoordinatorOpensOnlySetupLinks() {
        let c = SetupCoordinator()
        XCTAssertFalse(c.open(URL(string: "pigeon://other")!))
        XCTAssertNil(c.request)
        XCTAssertTrue(c.open(URL(string: "pigeon://setup#id=pgn-1&code=111111")!))
        XCTAssertEqual(c.request, .link(SetupLink(deviceID: "pgn-1", name: "Pigeon", code: "111111")))
    }

    func testHelloDecodesSetupAndToleratesItsAbsence() throws {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase
        let base = #""id":"pgn-1","name":"C","product":"clock","api":1,"version":"0.12","claimed":false,"setup_mode":false"#
        XCTAssertNil(try d.decode(Hello.self, from: Data("{\(base)}".utf8)).setup)
        let h = try d.decode(Hello.self, from: Data(
            #"{\#(base),"setup":{"state":"app","step":"player","skipped":["location"]}}"#.utf8))
        XCTAssertEqual(h.setup, SetupInfo(state: "app", step: "player", skipped: ["location"]))
        XCTAssertFalse(h.setup!.isDone)
    }

    func testSetupProgressRequest() async throws {
        StubURLProtocol.handler = { req in
            XCTAssertEqual(req.httpMethod, "PUT")
            XCTAssertEqual(req.url?.path, "/api/v1/setup")
            let body = try! JSONSerialization.jsonObject(with: req.bodyStreamData()) as! [String: Any]
            XCTAssertEqual(body["step"] as? String, "audio")
            XCTAssertEqual(body["skipped"] as? [String], ["player"])
            return (200, Data(#"{"state":"app","step":"audio","skipped":["player"]}"#.utf8))
        }
        let cfg = URLSessionConfiguration.ephemeral
        cfg.protocolClasses = [StubURLProtocol.self]
        let c = PigeonClient(host: "10.0.0.5", token: "pgt_x", session: URLSession(configuration: cfg))
        let s = try await c.setSetupProgress(step: "audio", skipped: ["player"])
        XCTAssertEqual(s.step, "audio")
    }

    @MainActor
    func testStepOrder() {
        XCTAssertEqual(SetupFlowModel.steps.compactMap { SetupFlowModel.stepName($0) }, ["location", "player", "audio"])
    }
}

private extension URLRequest {
    /// URLProtocol sees bodies as streams; read it back for assertions.
    func bodyStreamData() -> Data {
        if let httpBody { return httpBody }
        guard let s = httpBodyStream else { return Data() }
        s.open(); defer { s.close() }
        var data = Data()
        var buf = [UInt8](repeating: 0, count: 4096)
        while s.hasBytesAvailable {
            let n = s.read(&buf, maxLength: buf.count)
            if n <= 0 { break }
            data.append(buf, count: n)
        }
        return data
    }
}
