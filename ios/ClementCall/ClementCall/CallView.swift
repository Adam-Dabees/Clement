import SwiftUI

struct CallView: View {
    @StateObject private var session = CallSession()
    @State private var showKeypad = false
    @State private var typed = ""

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.13, green: 0.14, blue: 0.19), .black],
                           startPoint: .top, endPoint: .bottom)
                .ignoresSafeArea()
            VStack(spacing: 0) {
                header
                    .padding(.top, 24)
                    .padding(.bottom, 12)
                if session.phase == .idle {
                    contactCard
                } else {
                    transcript
                }
                controls
                    .padding(.horizontal, 32)
                    .padding(.bottom, 28)
            }
        }
        .preferredColorScheme(.dark)
        .sheet(isPresented: $showKeypad) { keypadSheet }
        .onAppear { session.applyLaunchArguments() }
    }

    // MARK: header

    private var header: some View {
        VStack(spacing: 6) {
            Text(ClementConfig.contactName)
                .font(.system(size: 30, weight: .regular))
            Text(statusText)
                .font(.system(size: 17))
                .foregroundStyle(.secondary)
                .monospacedDigit()
        }
    }

    private var statusText: String {
        switch session.phase {
        case .idle: return ClementConfig.contactDetail
        case .connecting: return "calling…"
        case .active: return session.agentSpeaking ? "\(session.elapsedText) · speaking" : session.elapsedText
        case .ended: return "\(session.endReason) · \(session.elapsedText)"
        }
    }

    // MARK: idle

    private var contactCard: some View {
        VStack(spacing: 20) {
            Spacer()
            avatar(size: 120)
            Text("A voice agent answers the returns line, decides the outcome on the call and reads it back. Have an order number ready:")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
            HStack(spacing: 8) {
                ForEach(ClementConfig.demoOrders, id: \.self) { id in
                    Text(id)
                        .font(.system(.caption, design: .monospaced).weight(.semibold))
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(.white.opacity(0.12), in: Capsule())
                }
            }
            Spacer()
        }
    }

    private func avatar(size: CGFloat) -> some View {
        ZStack {
            Circle()
                .fill(LinearGradient(colors: [Color(red: 0.55, green: 0.58, blue: 0.66), Color(red: 0.36, green: 0.39, blue: 0.47)],
                                     startPoint: .top, endPoint: .bottom))
            Text("HR")
                .font(.system(size: size * 0.4, weight: .medium))
                .foregroundStyle(.white)
            Circle()
                .stroke(Color.green.opacity(session.agentSpeaking ? 0.9 : 0), lineWidth: 4)
                .scaleEffect(session.agentSpeaking ? 1.12 : 1.0)
                .animation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true), value: session.agentSpeaking)
        }
        .frame(width: size, height: size)
    }

    // MARK: transcript

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 10) {
                    if session.lines.isEmpty {
                        avatar(size: 88).padding(.top, 24)
                        Text(session.phase == .connecting ? "Connecting to the agent…" : "Transcript")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    ForEach(session.lines) { line in
                        TranscriptRow(line: line).id(line.id)
                    }
                    Color.clear.frame(height: 8).id("bottom")
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
            }
            .scrollIndicators(.hidden)
            .onChange(of: session.lines.count) { _, _ in
                withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo("bottom", anchor: .bottom) }
            }
        }
    }

    // MARK: controls

    @ViewBuilder
    private var controls: some View {
        switch session.phase {
        case .idle:
            VStack(spacing: 10) {
                roundButton(symbol: "phone.fill", tint: .green, size: 82) { session.startCall() }
                Text("call").font(.footnote).foregroundStyle(.secondary)
            }
        case .connecting, .active:
            VStack(spacing: 28) {
                HStack(spacing: 44) {
                    labelled("mute", symbol: session.isMuted ? "mic.slash.fill" : "mic.fill",
                             active: session.isMuted) { session.isMuted.toggle() }
                    labelled("keypad", symbol: "circle.grid.3x3.fill", active: false) { showKeypad = true }
                    labelled("speaker", symbol: session.speakerOn ? "speaker.wave.3.fill" : "speaker.fill",
                             active: session.speakerOn) { session.speakerOn.toggle() }
                }
                roundButton(symbol: "phone.down.fill", tint: .red, size: 82) { session.endCall() }
            }
        case .ended:
            HStack(spacing: 44) {
                VStack(spacing: 10) {
                    roundButton(symbol: "phone.fill", tint: .green, size: 72) { session.startCall() }
                    Text("call again").font(.footnote).foregroundStyle(.secondary)
                }
                VStack(spacing: 10) {
                    roundButton(symbol: "xmark", tint: .white.opacity(0.22), size: 72) { session.reset() }
                    Text("done").font(.footnote).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func labelled(_ label: String, symbol: String, active: Bool, action: @escaping () -> Void) -> some View {
        VStack(spacing: 10) {
            roundButton(symbol: symbol, tint: active ? .white : .white.opacity(0.22), size: 76,
                        symbolColor: active ? .black : .white, action: action)
            Text(label).font(.footnote).foregroundStyle(.secondary)
        }
    }

    private func roundButton(symbol: String, tint: Color, size: CGFloat, symbolColor: Color = .white,
                             action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: size * 0.4, weight: .medium))
                .foregroundStyle(symbolColor)
                .frame(width: size, height: size)
                .background(tint, in: Circle())
        }
        .buttonStyle(.plain)
    }

    // MARK: keypad sheet (type instead of speaking)

    private var keypadSheet: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                Text("Type what you would say. It goes to the agent the same way your voice does.")
                    .font(.footnote).foregroundStyle(.secondary)
                TextField("e.g. A1077", text: $typed, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(3...6)
                Button {
                    session.sendText(typed)
                    typed = ""
                    showKeypad = false
                } label: {
                    Text("Send").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(typed.trimmingCharacters(in: .whitespaces).isEmpty)
                Spacer()
            }
            .padding()
            .navigationTitle("Keypad")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { showKeypad = false } } }
        }
        .presentationDetents([.medium])
    }
}

private struct TranscriptRow: View {
    let line: TranscriptLine

    var body: some View {
        switch line.role {
        case .system:
            Text(line.text.uppercased())
                .font(.system(size: 11, weight: .semibold))
                .tracking(0.6)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 2)
        case .agent:
            HStack(alignment: .bottom) {
                bubble(Color.white.opacity(0.16), textColor: .white)
                Spacer(minLength: 48)
            }
        case .caller:
            HStack(alignment: .bottom) {
                Spacer(minLength: 48)
                bubble(Color.green, textColor: .white)
            }
        }
    }

    private func bubble(_ fill: Color, textColor: Color) -> some View {
        Text(line.text)
            .font(.system(size: 17))
            .foregroundStyle(textColor)
            .padding(.horizontal, 14).padding(.vertical, 9)
            .background(fill, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

#Preview {
    CallView()
}
