import SwiftUI

@main
struct ClementCallApp: App {
    var body: some Scene {
        WindowGroup {
            CallView()
        }
    }
}

enum ClementConfig {
    /// The public ElevenLabs agent (authentication disabled in the dashboard), so the app
    /// holds no API key. Override with the ELEVENLABS_AGENT_ID scheme environment variable.
    static var agentId: String {
        ProcessInfo.processInfo.environment["ELEVENLABS_AGENT_ID"] ?? "agent_0201m2xp7s21fcb9nh0nn7c62vcx"
    }
    /// The merchant the agent answers for ("Hi, you've reached Harlow returns").
    static let contactName = "Harlow Returns"
    static let contactDetail = "returns line · Clement voice agent"
    static let demoOrders = ["A1077", "A1042", "A1188", "A1150", "A1103"]
}
