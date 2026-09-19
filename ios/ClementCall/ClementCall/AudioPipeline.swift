import AVFoundation

/// Microphone in, agent voice out. One AVAudioEngine:
///   mic tap -> resample to PCM16 mono at `rate` -> `onMicChunk`
///   `enqueue(pcm16:)` -> Float32 buffers -> AVAudioPlayerNode -> speaker / earpiece
/// Voice processing is enabled on the input so the agent does not hear itself.
final class AudioPipeline {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let queue = DispatchQueue(label: "clement.audio.mic")
    private var converter: AVAudioConverter?
    private var playFormat: AVAudioFormat?
    private let rate: Double

    var onMicChunk: ((Data) -> Void)?
    var isMuted = false

    init(sampleRate: Double = 16_000) {
        rate = sampleRate
    }

    func start(speaker: Bool) throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [])
        try session.setActive(true)
        try? session.overrideOutputAudioPort(speaker ? .speaker : .none)

        let input = engine.inputNode
        try? input.setVoiceProcessingEnabled(true)   // echo cancellation; unavailable on some simulators
        let micFormat = input.outputFormat(forBus: 0)
        guard micFormat.sampleRate > 0,
              let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: rate,
                                         channels: 1, interleaved: true),
              let play = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate,
                                       channels: 1, interleaved: false) else {
            throw NSError(domain: "AudioPipeline", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "no microphone format"])
        }
        converter = AVAudioConverter(from: micFormat, to: target)
        playFormat = play

        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: play)

        input.installTap(onBus: 0, bufferSize: 2048, format: micFormat) { [weak self] buffer, _ in
            self?.queue.async { self?.captured(buffer) }
        }
        engine.prepare()
        try engine.start()
        player.play()
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        player.stop()
        engine.stop()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    func setSpeaker(_ on: Bool) {
        try? AVAudioSession.sharedInstance().overrideOutputAudioPort(on ? .speaker : .none)
    }

    /// Agent audio: PCM16 little-endian mono at `rate`.
    func enqueue(pcm16: Data) {
        guard let playFormat else { return }
        let frames = pcm16.count / MemoryLayout<Int16>.size
        guard frames > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: playFormat, frameCapacity: AVAudioFrameCount(frames)),
              let out = buffer.floatChannelData?[0] else { return }
        buffer.frameLength = AVAudioFrameCount(frames)
        pcm16.withUnsafeBytes { raw in
            let samples = raw.bindMemory(to: Int16.self)
            for i in 0..<frames { out[i] = Float(Int16(littleEndian: samples[i])) / 32_768 }
        }
        player.scheduleBuffer(buffer, completionHandler: nil)
        if !player.isPlaying { player.play() }
    }

    /// The caller talked over the agent: drop everything not yet played.
    func flushPlayback() {
        player.stop()
        player.play()
    }

    private func captured(_ buffer: AVAudioPCMBuffer) {
        guard !isMuted, let converter, let onMicChunk else { return }
        let ratio = rate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 32
        guard let out = AVAudioPCMBuffer(pcmFormat: converter.outputFormat, frameCapacity: capacity) else { return }
        var supplied = false
        var error: NSError?
        let status = converter.convert(to: out, error: &error) { _, outStatus in
            if supplied {
                outStatus.pointee = .noDataNow
                return nil
            }
            supplied = true
            outStatus.pointee = .haveData
            return buffer
        }
        guard status != .error, out.frameLength > 0, let channel = out.int16ChannelData?[0] else { return }
        onMicChunk(Data(bytes: channel, count: Int(out.frameLength) * MemoryLayout<Int16>.size))
    }
}
