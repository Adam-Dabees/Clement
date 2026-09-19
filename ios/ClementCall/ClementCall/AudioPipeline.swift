import AVFoundation

/// Microphone in, agent voice out. One AVAudioEngine:
///   mic tap -> resample to PCM16 mono at `rate` -> `onMicChunk`
///   `enqueue(pcm16:)` -> Float32 buffers -> AVAudioPlayerNode -> speaker / earpiece
///
/// Voice processing (echo cancellation) is enabled on the input so the agent does not hear
/// itself. Order matters and is not documented: build the playback graph, THEN enable voice
/// processing, THEN install the tap in the voice-processed format, then start. If the tap
/// still delivers nothing (the simulator, some devices), the engine restarts without voice
/// processing and the mic is gated while the agent's audio plays instead.
final class AudioPipeline {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let queue = DispatchQueue(label: "clement.audio.mic")
    private var converter: AVAudioConverter?
    private var playFormat: AVAudioFormat?
    private let rate: Double
    private var graphBuilt = false
    private var chunkCount = 0
    private var playbackEnd = Date()
    private var speakerOn = true
    private var generation = 0

    var onMicChunk: ((Data) -> Void)?
    var onDiagnostic: ((String) -> Void)?
    var isMuted = false
    /// Echo cancellation via the voice-processing IO unit. Falls back to false on its own
    /// when the unit produces no input.
    var voiceProcessing = true

    init(sampleRate: Double = 16_000) {
        rate = sampleRate
    }

    func start(speaker: Bool) throws {
        speakerOn = speaker
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [])   // earpiece unless the speaker override is on
        try session.setActive(true)
        try? session.overrideOutputAudioPort(speaker ? .speaker : .none)

        guard let play = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate,
                                       channels: 1, interleaved: false),
              let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: rate,
                                         channels: 1, interleaved: true) else {
            throw NSError(domain: "AudioPipeline", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "no PCM format"])
        }
        playFormat = play

        // 1. Playback graph first. The voice-processing unit renders its output bus every
        //    cycle, so the mixer must already be its source.
        if !graphBuilt {
            engine.attach(player)
            graphBuilt = true
        }
        engine.connect(player, to: engine.mainMixerNode, format: play)
        _ = engine.mainMixerNode.outputVolume

        // 2. Voice processing on the input node, only now.
        let input = engine.inputNode
        do {
            try input.setVoiceProcessingEnabled(voiceProcessing)
        } catch {
            voiceProcessing = false
            onDiagnostic?("voice processing unavailable: \(error.localizedDescription)")
        }

        // 3. Tap in whatever format the (possibly voice-processed) input now has.
        let micFormat = input.outputFormat(forBus: 0)
        guard micFormat.sampleRate > 0 else {
            throw NSError(domain: "AudioPipeline", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "no microphone format"])
        }
        converter = AVAudioConverter(from: micFormat, to: target)
        onDiagnostic?("mic \(Int(micFormat.sampleRate)) Hz x\(micFormat.channelCount) vp=\(voiceProcessing) "
                      + "route=\(session.currentRoute.inputs.map(\.portType.rawValue).joined(separator: ","))")
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 2048, format: micFormat) { [weak self] buffer, _ in
            self?.queue.async { self?.captured(buffer) }
        }

        // 4. Go.
        engine.prepare()
        try engine.start()
        player.play()
        armWatchdog()
    }

    func stop() {
        generation += 1
        engine.inputNode.removeTap(onBus: 0)
        player.stop()
        engine.stop()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    func setSpeaker(_ on: Bool) {
        speakerOn = on
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
        queue.async { [self] in
            playbackEnd = max(playbackEnd, Date()).addingTimeInterval(Double(frames) / rate)
        }
        player.scheduleBuffer(buffer, completionHandler: nil)
        if !player.isPlaying { player.play() }
    }

    /// The caller talked over the agent: drop everything not yet played.
    func flushPlayback() {
        player.stop()
        player.play()
        queue.async { [self] in playbackEnd = Date() }
    }

    // MARK: private

    /// No input inside 2.5 s of starting with voice processing means the unit is not
    /// delivering (seen on the simulator). Restart plain, with the mic gated during playback.
    private func armWatchdog() {
        guard voiceProcessing else { return }
        let gen = generation
        queue.asyncAfter(deadline: .now() + 2.5) { [weak self] in
            guard let self, self.generation == gen, self.chunkCount == 0 else { return }
            self.onDiagnostic?("no input from voice processing after 2.5 s; restarting without it")
            self.voiceProcessing = false
            self.stop()
            do { try self.start(speaker: self.speakerOn) }
            catch { self.onDiagnostic?("restart failed: \(error.localizedDescription)") }
        }
    }

    private func captured(_ buffer: AVAudioPCMBuffer) {
        guard !isMuted, let converter, let onMicChunk else { return }
        // On speakerphone, or without echo cancellation, the agent would hear its own voice come
        // back as the caller: half duplex while its audio plays. Earpiece with voice processing
        // stays full duplex so the caller can interrupt.
        if (speakerOn || !voiceProcessing) && Date() < playbackEnd.addingTimeInterval(0.3) { return }
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
        guard status != .error else {
            onDiagnostic?("converter error: \(error?.localizedDescription ?? "?")")
            return
        }
        guard out.frameLength > 0, let channel = out.int16ChannelData?[0] else { return }
        chunkCount += 1
        if chunkCount == 1 || chunkCount % 200 == 0 {
            var peak: Int16 = 0
            for i in 0..<Int(out.frameLength) { peak = max(peak, abs(channel[i])) }
            onDiagnostic?("chunk #\(chunkCount): \(buffer.frameLength) in -> \(out.frameLength) out, peak \(peak)")
        }
        onMicChunk(Data(bytes: channel, count: Int(out.frameLength) * MemoryLayout<Int16>.size))
    }
}
