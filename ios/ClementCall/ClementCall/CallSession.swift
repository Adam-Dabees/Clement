import AVFoundation
import Foundation

struct TranscriptLine: Identifiable, Equatable {
    enum Role { case caller, agent, system }
    let id = UUID()
    let role: Role
    var text: String
    let at = Date()
}

/// One call: owns the socket and the audio pipeline, publishes what the screen shows.
/// The agent runs the conversation; the server's engine picks the outcome. This app is the
/// caller's phone, so it never sees a cost figure: it only renders what the agent said.
@MainActor
final class CallSession: ObservableObject {
    enum Phase { case idle, connecting, active, ended }

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var lines: [TranscriptLine] = []
    @Published private(set) var elapsed: TimeInterval = 0
    @Published private(set) var agentSpeaking = false
    @Published private(set) var conversationId: String?
    @Published private(set) var endReason = "Call Ended"
    @Published var isMuted = false { didSet { audio?.isMuted = isMuted } }
    @Published var speakerOn = true { didSet { audio?.setSpeaker(speakerOn) } }

    private var socket: ElevenLabsSocket?
    private var audio: AudioPipeline?
    private var clock: Timer?
    private var startedAt: Date?
    private var speakingReset: DispatchWorkItem?

    // MARK: call control

    func startCall() {
        guard phase == .idle || phase == .ended else { return }
        lines = []
        elapsed = 0
        conversationId = nil
        phase = .connecting
        AVAudioApplication.requestRecordPermission { [weak self] granted in
            Task { @MainActor in
                guard let self else { return }
                if !granted { self.append(.system, "Microphone access denied. Use the keypad to type.") }
                self.openSocket()
            }
        }
    }

    func endCall(reason: String = "Call Ended") {
        guard phase != .idle else { return }
        socket?.close()
        socket = nil
        audio?.stop()
        audio = nil
        clock?.invalidate()
        clock = nil
        speakingReset?.cancel()
        agentSpeaking = false
        endReason = reason
        phase = .ended
    }

    func reset() {
        endCall()
        phase = .idle
        lines = []
    }

    /// Typed input, for the simulator or a quiet room. Goes down the same socket as speech.
    func sendText(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let socket, socket.isOpen else { return }
        socket.sendText(trimmed)
        append(.caller, trimmed)
        debugLog("[me   ] \(trimmed)")
    }

    var elapsedText: String {
        let s = Int(elapsed)
        return String(format: "%02d:%02d", s / 60, s % 60)
    }

    // MARK: plumbing

    private func openSocket() {
        let socket = ElevenLabsSocket { [weak self] event in
            guard let self else { return }
            if case .audio(let pcm) = event {
                self.audio?.enqueue(pcm16: pcm)     // straight to the player, off the main thread
            }
            Task { @MainActor in self.handle(event) }
        }
        self.socket = socket
        socket.connect(agentId: ClementConfig.agentId)

        let pipeline = AudioPipeline(sampleRate: 16_000)
        pipeline.isMuted = isMuted
        pipeline.voiceProcessing = !CommandLine.arguments.contains("-novp")
        pipeline.onMicChunk = { [weak socket] chunk in socket?.sendAudio(chunk) }
        pipeline.onDiagnostic = { [weak self] message in
            Task { @MainActor in self?.debugLog("[mic  ] " + message) }
        }
        do {
            try pipeline.start(speaker: speakerOn)
            audio = pipeline
        } catch {
            append(.system, "Audio unavailable: \(error.localizedDescription). Use the keypad to type.")
        }
    }

    private func handle(_ event: AgentEvent) {
        switch event {
        case .metadata(let id, let out, let inp):
            conversationId = id
            if phase == .connecting { becomeActive() }
            if out != "pcm_16000" || inp != "pcm_16000" {
                append(.system, "Agent audio is \(out) / \(inp); this app expects pcm_16000.")
            }
            debugLog("conversation_id \(id)")
        case .audio(let pcm):
            markSpeaking()
            // Chunks stream faster than real time; the player starts this one when the previous
            // ends (or now, if idle). PCM16 at 16 kHz is 32 000 bytes per second.
            playbackEnd = max(playbackEnd, Date()).addingTimeInterval(Double(pcm.count) / 32_000)
            scriptTick()
        case .userTranscript(let text):
            append(.caller, text)
            debugLog("[user ] \(text)")
        case .agentResponse(let text):
            append(.agent, text)
            markSpeaking()
            scriptTick()
            debugLog("[agent] \(text)")
        case .agentCorrection(let text):
            if let i = lines.lastIndex(where: { $0.role == .agent }) { lines[i].text = text }
            debugLog("[agent, corrected] \(text)")
        case .toolResponse(let name, let isError):
            append(.system, Self.toolLabel(name) + (isError ? " (error)" : ""))
            debugLog("        tool \(name) error=\(isError)")
        case .interruption:
            audio?.flushPlayback()
            playbackEnd = Date()
            agentSpeaking = false
        case .closed(let reason):
            debugLog("[call ] closed \(reason ?? "")")
            if phase == .connecting {
                endCall(reason: "Call Failed")
                append(.system, reason ?? "Could not reach the agent.")
            } else if phase == .active {
                endCall(reason: "Call Ended")
            }
        case .error(let message):
            debugLog("[error] \(message)")
        }
    }

    private func becomeActive() {
        phase = .active
        startedAt = Date()
        clock = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, let startedAt = self.startedAt else { return }
                self.elapsed = Date().timeIntervalSince(startedAt)
            }
        }
    }

    private func markSpeaking() {
        agentSpeaking = true
        speakingReset?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.agentSpeaking = false }
        speakingReset = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2, execute: work)
    }

    private func append(_ role: TranscriptLine.Role, _ text: String) {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { return }
        lines.append(TranscriptLine(role: role, text: clean))
    }

    private static func toolLabel(_ name: String) -> String {
        switch name {
        case "lookup_order": return "Order looked up"
        case "decide_return": return "Offer decided by the engine"
        case "customer_declined": return "Decline recorded, next offer"
        case "end_call": return "Agent ended the call"
        default: return name
        }
    }

    private func debugLog(_ line: String) {
        #if DEBUG
        // stderr is unbuffered, so `simctl launch --console` shows lines as they happen.
        FileHandle.standardError.write(Data((line + "\n").utf8))
        #endif
    }

    // MARK: scripted test drive (DEBUG only)
    //
    //   -autocall                 place the call on launch
    //   -script "A1077|line 2|…"  type each line once the agent goes quiet, mic muted
    //
    // The same idea as livecall.py, so a simulator without a microphone still exercises
    // the socket, the tools, the engine and the log.

    private var script: [String] = []
    private var scriptTimer: DispatchWorkItem?
    private var playbackEnd = Date()          // when the queued agent audio finishes playing

    func applyLaunchArguments() {
        #if DEBUG
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "-script"), i + 1 < args.count {
            script = args[i + 1].components(separatedBy: "|")
            isMuted = true
        }
        if args.contains("-autocall") { startCall() }
        #endif
    }

    /// Type the next line once the agent has finished *playing*, not just streaming: audio
    /// arrives faster than real time, and a message sent mid-playback counts as an interruption.
    private func scriptTick() {
        guard !script.isEmpty else { return }
        scriptTimer?.cancel()
        let remaining = playbackEnd.timeIntervalSinceNow
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.phase == .active, !self.script.isEmpty else { return }
            self.sendText(self.script.removeFirst())
        }
        scriptTimer = work
        DispatchQueue.main.asyncAfter(deadline: .now() + max(2.0, remaining + 1.5), execute: work)
    }
}
