import AppKit
import Foundation
import SwiftUI
import CryptoKit

private struct ReadyRecord: Decodable {
    let event: String
    let url: String?
    let version: String?
    let pid: Int32?
}

enum StartupProtocol {
    static func decode(_ line: Data, pid: Int32, version: String, workspace: String) -> URL? {
        guard line.count <= 16_384,
              let record = try? JSONDecoder().decode(ReadyRecord.self, from: line),
              record.event == "ready", record.pid == pid, record.version == version,
              let value = record.url, value.utf8.count <= 8_192,
              let parts = URLComponents(string: value),
              parts.scheme == "http", parts.host == "127.0.0.1",
              let port = parts.port, port > 0, port < 65_536,
              parts.user == nil, parts.password == nil, parts.fragment == nil,
              parts.path == "/", let rawQuery = parts.percentEncodedQuery else { return nil }
        var query: [String: String] = [:]
        let fields = rawQuery.split(separator: "&", omittingEmptySubsequences: false)
        guard fields.count == 2 else { return nil }
        for field in fields {
            let pair = field.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard pair.count == 2,
                  let name = String(pair[0]).replacingOccurrences(of: "+", with: " ").removingPercentEncoding,
                  let value = String(pair[1]).replacingOccurrences(of: "+", with: " ").removingPercentEncoding,
                  query[name] == nil else { return nil }
            query[name] = value
        }
        guard Set(query.keys) == Set(["token", "workspace"]), let token = query["token"],
              token.utf8.count >= 32, token.utf8.count <= 128,
              token.unicodeScalars.allSatisfy({ CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_").contains($0) }),
              query["workspace"] == workspace else { return nil }
        return parts.url
    }
}

@MainActor
final class LauncherModel: ObservableObject {
    static let shared = LauncherModel()
    @Published var project: URL?
    @Published var phase = "idle"
    @Published var detail = "Choose the project you want to work on."
    @Published var isQuitting = false

    private var process: Process?
    private var input: Pipe?
    private var output: Pipe?
    private var errors: Pipe?
    private var launchID = UUID()
    private var outputBuffer = Data()
    private var readyURL: URL?
    private var startupDeadline: DispatchWorkItem?
    private var shutdownDeadline: DispatchWorkItem?
    private var openedOnReady = false
    private var receivedReady = false
    private var protocolFailed = false

    var isRunning: Bool { phase == "running" }
    var isBusy: Bool { phase == "starting" || phase == "stopping" }
    var hasProcess: Bool { process != nil }
    var stateDirectory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Parallax/Beta/projects", isDirectory: true)
        let identity = SHA256.hash(data: Data((project?.path ?? "").utf8))
            .map { String(format: "%02x", $0) }.joined()
        return base.appendingPathComponent(identity, isDirectory: true)
    }

    func chooseProject() {
        guard !hasProcess else { return }
        let panel = NSOpenPanel()
        panel.title = "Choose a project for Parallax"
        panel.prompt = "Choose project"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = false
        if let project { panel.directoryURL = project }
        if panel.runModal() == .OK, let selected = panel.url {
            project = selected.resolvingSymlinksInPath().standardizedFileURL
            phase = "idle"
            detail = "Ready to open this project in local Studio."
        }
    }

    func start() {
        guard !hasProcess, let project else { return }
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: project.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            phase = "failed"
            detail = "The selected folder is unavailable. Choose an existing project folder."
            return
        }
        guard let resources = Bundle.main.resourceURL else {
            failWithoutProcess("The bundled runtime is missing. Reinstall the complete Parallax Beta app.")
            return
        }
        let python = resources.appendingPathComponent("python/bin/python3")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            failWithoutProcess("The bundled runtime is missing. Reinstall the complete Parallax Beta app.")
            return
        }
        launchID = UUID()
        let currentID = launchID
        let child = Process()
        let incoming = Pipe(), outgoing = Pipe(), diagnostics = Pipe()
        child.executableURL = python
        child.arguments = ["-I", "-B", "-m", "parallax.desktop", "--workspace", project.path,
                           "--state-directory", stateDirectory.path]
        child.currentDirectoryURL = project
        // Finder does not provide the user's shell PATH. These common locations
        // locate installed agents without loading shell profiles or injecting
        // Python, Node, hosted deployment or dynamic-loader configuration.
        let home = NSHomeDirectory()
        child.environment = [
            "HOME": home, "USER": NSUserName(), "LOGNAME": NSUserName(),
            "PATH": [resources.appendingPathComponent("python/bin").path,
                     "/opt/homebrew/bin", "/usr/local/bin", home + "/.local/bin",
                     home + "/.npm-global/bin", home + "/.cargo/bin",
                     "/usr/bin", "/bin", "/usr/sbin", "/sbin"].joined(separator: ":"),
            "LANG": "en_US.UTF-8", "TMPDIR": NSTemporaryDirectory(), "SHELL": "/bin/zsh"
        ]
        child.standardInput = incoming
        child.standardOutput = outgoing
        child.standardError = diagnostics
        input = incoming; output = outgoing; errors = diagnostics
        outputBuffer = Data(); readyURL = nil
        receivedReady = false; openedOnReady = false; protocolFailed = false
        phase = "starting"
        detail = "Starting your private local runtime…"
        outgoing.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil }
            DispatchQueue.main.async { [weak self] in self?.receive(data, id: currentID) }
        }
        // Drain diagnostics without displaying or persisting untrusted output.
        // In particular, never copy a launch token into logs or error panels.
        diagnostics.fileHandleForReading.readabilityHandler = { handle in
            if handle.availableData.isEmpty { handle.readabilityHandler = nil }
        }
        child.terminationHandler = { [weak self] ended in
            DispatchQueue.main.async { [weak self] in self?.didExit(ended, id: currentID) }
        }
        process = child
        do {
            try child.run()
            try? outgoing.fileHandleForWriting.close()
            try? diagnostics.fileHandleForWriting.close()
            try? incoming.fileHandleForReading.close()
            let deadline = DispatchWorkItem { [weak self] in
                guard let self, self.launchID == currentID, self.phase == "starting" else { return }
                self.protocolFailed = true
                self.detail = "Studio did not become ready. Stop and try again. Your saved tasks stay on this Mac."
                self.stop()
            }
            startupDeadline = deadline
            DispatchQueue.main.asyncAfter(deadline: .now() + 30, execute: deadline)
        } catch {
            cleanHandles()
            process = nil
            failWithoutProcess("The bundled runtime could not launch. Reinstall Parallax Beta and try again.")
        }
    }

    private func receive(_ data: Data, id: UUID) {
        guard id == launchID, process != nil, !data.isEmpty else { return }
        guard outputBuffer.count + data.count <= 16_384 else {
            rejectProtocol()
            return
        }
        outputBuffer.append(data)
        while let end = outputBuffer.firstIndex(of: 10) {
            let line = outputBuffer.prefix(upTo: end)
            outputBuffer.removeSubrange(...end)
            guard !line.isEmpty, !receivedReady, let process, let project,
                  let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
                  let url = StartupProtocol.decode(Data(line), pid: process.processIdentifier,
                                                   version: version, workspace: project.path) else {
                rejectProtocol()
                return
            }
            receivedReady = true
            startupDeadline?.cancel(); startupDeadline = nil
            if phase == "stopping" { continue }
            readyURL = url
            phase = "running"
            detail = "Studio is ready. Keep Parallax open while your agents work."
            if !openedOnReady { openedOnReady = true; openStudio() }
        }
    }

    private func rejectProtocol() {
        guard !protocolFailed else { return }
        protocolFailed = true
        detail = "The local runtime returned an invalid startup response. Stop and reinstall the complete beta."
        stop()
    }

    func openStudio() {
        guard isRunning, let readyURL else { return }
        if !NSWorkspace.shared.open(readyURL) {
            detail = "Studio is running, but the browser could not open. Set a default browser and select Open Studio again."
        }
    }

    func openHelp() {
        guard let guide = Bundle.main.url(forResource: "BetaGuide", withExtension: "html"),
              NSWorkspace.shared.open(guide) else {
            detail = "The bundled beta guide could not open. Reinstall the complete app or use the Parallax issue tracker for support."
            return
        }
    }

    func stop() {
        guard let child = process, phase != "stopping" else { return }
        startupDeadline?.cancel(); startupDeadline = nil
        phase = "stopping"
        if !protocolFailed { detail = "Stopping agents and preserving task evidence…" }
        readyURL = nil
        if let handle = input?.fileHandleForWriting {
            try? handle.write(contentsOf: Data("{\"command\":\"stop\"}\n".utf8))
            try? handle.close()
        } else if child.isRunning { child.terminate() }
        let currentID = launchID
        let deadline = DispatchWorkItem { [weak self, weak child] in
            guard let self, self.launchID == currentID, let child, child.isRunning else { return }
            // Signal only the Process object we created. Never kill a saved PID
            // or a CLI/worker service owned by another launch.
            child.terminate()
        }
        shutdownDeadline = deadline
        DispatchQueue.main.asyncAfter(deadline: .now() + 10, execute: deadline)
    }

    private func didExit(_ ended: Process, id: UUID) {
        guard id == launchID, process === ended else { return }
        let requested = phase == "stopping"
        startupDeadline?.cancel(); shutdownDeadline?.cancel()
        startupDeadline = nil; shutdownDeadline = nil
        cleanHandles()
        process = nil; readyURL = nil
        if protocolFailed {
            phase = "failed"
        } else if requested && ended.terminationStatus != 0 {
            phase = "failed"
            detail = "Local Studio stopped during shutdown. Reopen this project to inspect recovered work. Saved data remains on this Mac."
        } else if requested {
            phase = "idle"
            detail = "Local Studio stopped. Saved tasks and provider settings stay on this Mac."
        } else if !receivedReady && ended.terminationStatus == 2 {
            phase = "failed"
            detail = "The project or beta state is unavailable or already open. Check the folder, close another beta instance, and try again. Saved data is preserved."
        } else {
            phase = "failed"
            detail = "The local runtime stopped (exit \(ended.terminationStatus)). Open Studio again to inspect saved tasks."
        }
        if isQuitting { NSApp.reply(toApplicationShouldTerminate: true) }
    }

    private func cleanHandles() {
        output?.fileHandleForReading.readabilityHandler = nil
        errors?.fileHandleForReading.readabilityHandler = nil
        try? input?.fileHandleForWriting.close()
        try? output?.fileHandleForReading.close()
        try? errors?.fileHandleForReading.close()
        input = nil; output = nil; errors = nil
        outputBuffer = Data()
    }

    private func failWithoutProcess(_ message: String) {
        phase = "failed"; detail = message
    }

    func requestQuit() -> NSApplication.TerminateReply {
        guard hasProcess else { return .terminateNow }
        let alert = NSAlert()
        alert.messageText = "Stop local Studio and quit Parallax?"
        alert.informativeText = "Active work will stop and its evidence will be preserved. Closing a browser tab alone keeps the runtime running."
        alert.addButton(withTitle: "Stop and Quit")
        alert.addButton(withTitle: "Keep Working")
        guard alert.runModal() == .alertFirstButtonReturn else { return .terminateCancel }
        isQuitting = true
        stop()
        return .terminateLater
    }
}

final class LauncherDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        MainActor.assumeIsolated { LauncherModel.shared.requestQuit() }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

private struct OrbitMark: View {
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 19).fill(Color(red: 0.09, green: 0.10, blue: 0.13))
            Circle().stroke(Color(red: 0.65, green: 0.60, blue: 0.91), lineWidth: 2.5).padding(13)
            Ellipse().stroke(Color(red: 0.41, green: 0.77, blue: 0.73), lineWidth: 2.5)
                .frame(width: 31, height: 58).rotationEffect(.degrees(-36))
            Circle().fill(Color(red: 0.94, green: 0.93, blue: 1)).frame(width: 10, height: 10)
        }.frame(width: 80, height: 80).accessibilityHidden(true)
    }
}

@MainActor
private struct LauncherView: View {
    @ObservedObject var model = LauncherModel.shared
    private let lavender = Color(red: 0.71, green: 0.65, blue: 0.98)
    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            HStack(spacing: 18) {
                OrbitMark()
                VStack(alignment: .leading, spacing: 7) {
                    Text("PARALLAX · BETA").font(.system(size: 11, weight: .semibold, design: .monospaced)).tracking(2).foregroundColor(lavender)
                    Text("Your project.\nA reviewed patch.").font(.system(size: 28, weight: .semibold)).fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
            }
            Text("Run your coding agents locally. Use Studio to delegate work, inspect changes and checks, and decide what to deliver.")
                .font(.system(size: 14)).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("PROJECT").font(.system(size: 10, weight: .semibold, design: .monospaced)).tracking(1.5).foregroundColor(.secondary)
                    Spacer()
                    Button(model.project == nil ? "Choose folder…" : "Change…") { model.chooseProject() }.disabled(model.hasProcess)
                }
                Text(model.project?.lastPathComponent ?? "Choose a project folder")
                    .font(.system(size: 17, weight: .medium)).lineLimit(1).truncationMode(.middle)
                Text(model.project?.path ?? "Parallax works in isolated copies of the project you select.")
                    .font(.system(size: 12)).foregroundColor(.secondary).lineLimit(2).truncationMode(.middle).textSelection(.enabled)
            }.padding(18).background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.045)))
            HStack(alignment: .top, spacing: 10) {
                if model.isBusy { ProgressView().controlSize(.small).padding(.top, 2) }
                else { Circle().fill(model.isRunning ? Color.green : model.phase == "failed" ? Color.orange : lavender).frame(width: 7, height: 7).padding(.top, 5) }
                Text(model.detail).font(.system(size: 13)).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            }.frame(minHeight: 38, alignment: .top)
            HStack(spacing: 12) {
                if model.isRunning {
                    Button("Open Studio") { model.openStudio() }.buttonStyle(.borderedProminent).tint(lavender).keyboardShortcut(.defaultAction)
                    Button("Stop local Studio") { model.stop() }
                } else if model.phase == "starting" {
                    Button("Starting Studio…") {}.disabled(true).buttonStyle(.borderedProminent).tint(lavender)
                    Button("Cancel") { model.stop() }
                } else if model.phase == "stopping" {
                    Button("Stopping Studio…") {}.disabled(true)
                } else {
                    Button(model.phase == "failed" ? "Try again" : "Open local Studio") { model.start() }
                        .buttonStyle(.borderedProminent).tint(lavender).disabled(model.project == nil || model.hasProcess).keyboardShortcut(.defaultAction)
                }
                Spacer()
                Text(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Beta")
                    .font(.system(size: 11, design: .monospaced)).foregroundColor(.secondary)
            }
            Divider()
            Text("Connect your signed-in coding agents or API providers in Studio. Git is required for changes. Provider usage and charges are yours. This beta uses local state and does not automatically pair or share your Mac.")
                .font(.system(size: 11)).foregroundColor(.secondary).fixedSize(horizontal: false, vertical: true)
            Button("Help · Getting started") { model.openHelp() }
                .font(.system(size: 12)).buttonStyle(.link)
        }.padding(30).frame(width: 540).background(Color(red: 0.065, green: 0.07, blue: 0.085)).preferredColorScheme(.dark)
    }
}

#if !PROTOCOL_TEST
@main
struct ParallaxBetaApp: App {
    @NSApplicationDelegateAdaptor(LauncherDelegate.self) var delegate
    @Environment(\.openWindow) private var openWindow
    var body: some Scene {
        Window("Parallax Beta", id: "parallax-launcher") { LauncherView() }
            .windowStyle(.hiddenTitleBar)
            .commands {
                CommandGroup(replacing: .newItem) {
                    Button("Show Parallax") { openWindow(id: "parallax-launcher") }
                        .keyboardShortcut("0", modifiers: .command)
                }
                CommandGroup(after: .appInfo) {
                    Button("Open Studio") { LauncherModel.shared.openStudio() }.disabled(!LauncherModel.shared.isRunning)
                }
                CommandGroup(replacing: .help) {
                    Button("Parallax Beta Help") { LauncherModel.shared.openHelp() }
                }
            }
    }
}
#endif
