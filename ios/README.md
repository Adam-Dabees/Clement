# ClementCall — iPhone-style call demo

A native SwiftUI app that places a call to the Clement returns agent and shows the live
transcript, laid out like the iPhone in-call screen: contact header, timer, mute / keypad /
speaker, red end button.

It talks to the ElevenLabs agent directly over its WebSocket (the same protocol
`livecall.py` drives from the shell), so the tools, the tunnel, the engine and the merchant
console all see it as a normal call. No SDK, no third-party package, no API key in the app:
the agent is public.

```
cd ios/ClementCall
xcodegen generate            # brew install xcodegen, once
open ClementCall.xcodeproj   # pick your device, Run
```

Needs iOS 17 and a microphone. `ELEVENLABS_AGENT_ID` in the scheme's environment overrides
the built-in agent id. The keypad button types a message instead of speaking, which is how
you drive it in the simulator.

Scripted test drive (Debug builds), mirrors `livecall.py`:

```
xcrun simctl launch --console booted com.rovalapps.ClementCall \
  -autocall -script "A1077|It's the wrong shade of grey. I slept under it one night.|I'll keep it and take the money. Bye."
```

What the screen shows: what the agent said, what the caller said, and a one-line marker
when a tool ran (order looked up, offer decided, decline recorded). Never a cost figure:
this is the customer's phone.
