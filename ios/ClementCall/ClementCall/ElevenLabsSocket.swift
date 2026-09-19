import Foundation

/// Events the ElevenLabs Agents WebSocket sends us, reduced to what the call screen needs.
/// Mirrors the protocol that livecall.py drives from the shell.
enum AgentEvent {
    case metadata(conversationId: String, outputFormat: String, inputFormat: String)
    case audio(Data)                       // PCM16 little-endian at the agent's output rate
    case userTranscript(String)
    case agentResponse(String)
    case agentCorrection(String)           // what the agent actually got to say before an interruption
    case toolResponse(name: String, isError: Bool)
    case interruption
    case closed(reason: String?)
    case error(String)
}

/// Raw WebSocket client for `wss://api.elevenlabs.io/v1/convai/conversation`.
/// No SDK, no third-party dependency: URLSessionWebSocketTask and JSONSerialization.
final class ElevenLabsSocket: NSObject, URLSessionWebSocketDelegate {
    private let handler: (AgentEvent) -> Void
    private var task: URLSessionWebSocketTask?
    private lazy var session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
    private let stateLock = NSLock()
    private var open = false

    init(handler: @escaping (AgentEvent) -> Void) {
        self.handler = handler
    }

    var isOpen: Bool {
        stateLock.lock(); defer { stateLock.unlock() }
        return open
    }

    private func setOpen(_ value: Bool) -> Bool {
        stateLock.lock(); defer { stateLock.unlock() }
        let was = open
        open = value
        return was
    }

    func connect(agentId: String) {
        var comps = URLComponents(string: "wss://api.elevenlabs.io/v1/convai/conversation")!
        comps.queryItems = [URLQueryItem(name: "agent_id", value: agentId)]
        let t = session.webSocketTask(with: comps.url!)
        task = t
        t.resume()
        receiveLoop()
    }

    func close() {
        _ = setOpen(false)
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
    }

    /// One chunk of caller audio: PCM16 mono at the agent's `user_input_audio_format` rate.
    func sendAudio(_ pcm16: Data) {
        guard isOpen else { return }
        send(["user_audio_chunk": pcm16.base64EncodedString()])
    }

    /// Typed text in place of speech. Same path livecall.py uses.
    func sendText(_ text: String) {
        guard isOpen else { return }
        send(["type": "user_message", "text": text])
    }

    // MARK: URLSessionWebSocketDelegate

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        _ = setOpen(true)
        send(["type": "conversation_initiation_client_data"])
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        if setOpen(false) {
            handler(.closed(reason: reason.flatMap { String(data: $0, encoding: .utf8) }))
        }
    }

    // MARK: plumbing

    private func send(_ object: [String: Any]) {
        guard let t = task,
              let data = try? JSONSerialization.data(withJSONObject: object),
              let text = String(data: data, encoding: .utf8) else { return }
        t.send(.string(text)) { [weak self] error in
            if let error { self?.handler(.error(error.localizedDescription)) }
        }
    }

    private func receiveLoop() {
        task?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let error):
                // The agent's end_call closes the socket from its side; report it once.
                if self.setOpen(false) { self.handler(.closed(reason: error.localizedDescription)) }
            case .success(let message):
                switch message {
                case .string(let text): self.handle(text)
                case .data(let data): if let text = String(data: data, encoding: .utf8) { self.handle(text) }
                @unknown default: break
                }
                self.receiveLoop()
            }
        }
    }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = obj["type"] as? String else { return }
        switch type {
        case "conversation_initiation_metadata":
            let e = obj["conversation_initiation_metadata_event"] as? [String: Any] ?? [:]
            handler(.metadata(conversationId: e["conversation_id"] as? String ?? "",
                              outputFormat: e["agent_output_audio_format"] as? String ?? "pcm_16000",
                              inputFormat: e["user_input_audio_format"] as? String ?? "pcm_16000"))
        case "audio":
            if let e = obj["audio_event"] as? [String: Any],
               let b64 = e["audio_base_64"] as? String,
               let pcm = Data(base64Encoded: b64) {
                handler(.audio(pcm))
            }
        case "user_transcript":
            if let e = obj["user_transcription_event"] as? [String: Any],
               let t = e["user_transcript"] as? String { handler(.userTranscript(t)) }
        case "agent_response":
            if let e = obj["agent_response_event"] as? [String: Any],
               let t = e["agent_response"] as? String { handler(.agentResponse(t)) }
        case "agent_response_correction":
            if let e = obj["agent_response_correction_event"] as? [String: Any],
               let t = e["corrected_agent_response"] as? String { handler(.agentCorrection(t)) }
        case "agent_tool_response":
            let e = obj["agent_tool_response"] as? [String: Any] ?? obj
            handler(.toolResponse(name: e["tool_name"] as? String ?? "tool",
                                  isError: e["is_error"] as? Bool ?? false))
        case "ping":
            if let e = obj["ping_event"] as? [String: Any], let id = e["event_id"] {
                send(["type": "pong", "event_id": id])
            }
        case "interruption":
            handler(.interruption)
        default:
            break   // internal_* events, vad scores, tentative responses
        }
    }
}
