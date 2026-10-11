import Foundation

@main
struct ProtocolCases {
    static func main() throws {
        let token = String(repeating: "t", count: 43)
        let workspace = "/Users/fixture/Project + Café #1"
        func form(_ value: String) -> String {
            value.utf8.map { byte in
                if byte == 32 { return "+" }
                if (48...57).contains(byte) || (65...90).contains(byte) || (97...122).contains(byte) || [45, 46, 95].contains(byte) {
                    return String(UnicodeScalar(byte))
                }
                return String(format: "%%%02X", byte)
            }.joined()
        }
        let validURL = "http://127.0.0.1:43210/?token=\(token)&workspace=\(form(workspace))"
        var count = 0
        func record(_ url: String, pid: Int32 = 42, version: String = "1.4.0", event: String = "ready") throws -> Data {
            try JSONSerialization.data(withJSONObject: ["event": event, "url": url, "pid": pid, "version": version])
        }
        func check(_ data: Data, expected: Bool, label: String) {
            count += 1
            let result = StartupProtocol.decode(data, pid: 42, version: "1.4.0", workspace: workspace)
            guard (result != nil) == expected else {
                fputs("FAIL: \(label)\n", stderr)
                exit(1)
            }
        }
        try check(record(validURL), expected: true, label: "Python form query preserves spaces, literal plus, Unicode and hash")
        try check(record(validURL.replacingOccurrences(of: "+", with: "%20")), expected: true, label: "percent-encoded spaces")
        try check(record("http://127.0.0.1:43210/?workspace=\(form(workspace))&token=\(token)"), expected: true, label: "query order")
        try check(record(validURL, pid: 43), expected: false, label: "another process")
        try check(record(validURL, version: "1.3.0"), expected: false, label: "different version")
        try check(record(validURL, event: "error"), expected: false, label: "non-ready event")
        try check(record(validURL.replacingOccurrences(of: "127.0.0.1", with: "example.com")), expected: false, label: "remote token exfiltration")
        try check(record(validURL.replacingOccurrences(of: "127.0.0.1", with: "127.0.0.1.example.com")), expected: false, label: "lookalike host")
        try check(record(validURL.replacingOccurrences(of: "127.0.0.1", with: "localhost")), expected: false, label: "non-literal loopback")
        try check(record(validURL.replacingOccurrences(of: "http:", with: "https:")), expected: false, label: "unexpected scheme")
        try check(record(validURL.replacingOccurrences(of: "127.0.0.1:", with: "user:secret@127.0.0.1:")), expected: false, label: "userinfo")
        try check(record(validURL + "#fragment"), expected: false, label: "fragment")
        try check(record(validURL.replacingOccurrences(of: ":43210/", with: ":0/")), expected: false, label: "zero port")
        try check(record(validURL.replacingOccurrences(of: ":43210/", with: ":70000/")), expected: false, label: "invalid port")
        try check(record(validURL.replacingOccurrences(of: ":43210/", with: "/")), expected: false, label: "missing port")
        try check(record(validURL.replacingOccurrences(of: "/?", with: "/redirect?")), expected: false, label: "unexpected endpoint")
        try check(record(validURL + "&token=other"), expected: false, label: "duplicate credential")
        try check(record(validURL + "&next=https%3A%2F%2Fexample.com"), expected: false, label: "unapproved query")
        try check(record(validURL.replacingOccurrences(of: token, with: "short")), expected: false, label: "short token")
        try check(record(validURL.replacingOccurrences(of: token, with: String(repeating: "a", count: 129))), expected: false, label: "oversized token")
        try check(record(validURL.replacingOccurrences(of: token, with: token + "%26")), expected: false, label: "token syntax")
        try check(record(validURL.replacingOccurrences(of: form(workspace), with: form("/Users/fixture/Other"))), expected: false, label: "wrong project")
        check(Data("{bad json}".utf8), expected: false, label: "malformed record")
        check(Data(repeating: 65, count: 16_385), expected: false, label: "bounded protocol")
        print("\(count) launcher protocol cases passed")
    }
}
