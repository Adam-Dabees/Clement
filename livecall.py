"""
Drive the REAL ElevenLabs agent over its WebSocket with typed text, so the
webhook tools, the tunnel, the engine and the log get exercised without a
microphone. This is the integration checkpoint you can run from a shell.

    .venv/bin/python livecall.py                      # A1077 accept path
    .venv/bin/python livecall.py --decline            # A1188 two-decline path
    .venv/bin/python livecall.py --human              # A1042, asks for a human mid-call -> handoff
    .venv/bin/python livecall.py "A1150" "it's leaking from the group head"

Needs ELEVENLABS_AGENT_ID in .env (written by setup_agent.py) and the agent
public (auth disabled). Prints every non-audio event, then the /api/log row.
"""

import asyncio
import json
import os
import sys
import time

import requests
import websockets
from dotenv import load_dotenv

load_dotenv(".env")

AID = os.environ.get("ELEVENLABS_AGENT_ID") or sys.exit("ELEVENLABS_AGENT_ID not in .env")
WS = f"wss://api.elevenlabs.io/v1/convai/conversation?agent_id={AID}"
LOCAL = os.environ.get("LOCAL_URL", "http://localhost:8000")

SCRIPTS = {
    "accept": ["A1077",
               "It's just the wrong shade of grey, way darker than the photo. I opened it and slept "
               "under it one night. It's not damaged.",
               "I'll take the money and keep it, thanks. Bye."],
    "human": ["A1042",
              "It's broken.",
              "One of the speed buttons doesn't do anything. I'd like you to fix it.",
              "Actually no. I want to speak to a human now."],
    "decline": ["A1188",
                "They're too tight. I've worn them once.",
                "No, I'd rather have all of my money back.",
                "No. I'm not shipping anything back either."],
}


async def run(lines):
    conv_id = None
    async with websockets.connect(WS, max_size=None) as ws:
        await ws.send(json.dumps({"type": "conversation_initiation_client_data"}))

        async def wait_for_agent(timeout=45):
            """Collect events until the agent has spoken and gone quiet for 1.5 s."""
            nonlocal conv_id
            spoke, last = False, time.time()
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), 1.5 if spoke else timeout)
                except asyncio.TimeoutError:
                    if spoke:
                        return
                    raise
                ev = json.loads(raw)
                t = ev.get("type")
                if t == "ping":
                    await ws.send(json.dumps({"type": "pong", "event_id": ev["ping_event"]["event_id"]}))
                elif t == "audio":
                    pass
                elif t == "conversation_initiation_metadata":
                    conv_id = ev["conversation_initiation_metadata_event"]["conversation_id"]
                    print(f"conversation_id {conv_id}")
                elif t == "agent_response":
                    print(f"[agent] {ev['agent_response_event']['agent_response'].strip()}")
                    spoke = True
                elif t == "agent_response_correction":
                    print(f"[agent, corrected] {ev['agent_response_correction_event']['corrected_agent_response'].strip()}")
                elif t == "user_transcript":
                    print(f"[user ] {ev['user_transcription_event']['user_transcript'].strip()}")
                elif t == "agent_tool_response":
                    e = ev.get("agent_tool_response", ev)
                    print(f"        tool {e.get('tool_name')} error={e.get('is_error')}")
                elif t == "interruption":
                    pass
                else:
                    print(f"        ({t}) {raw[:160]}")

        try:
            await wait_for_agent()
            for line in lines:
                print(f"[me   ] {line}")
                await ws.send(json.dumps({"type": "user_message", "text": line}))
                await wait_for_agent()
        except websockets.exceptions.ConnectionClosed:
            print("[call ] ended by the agent (end_call)")
    return conv_id


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    lines = (SCRIPTS["decline"] if "--decline" in sys.argv else
             SCRIPTS["human"] if "--human" in sys.argv else (args or SCRIPTS["accept"]))
    t0 = time.time()
    conv_id = asyncio.run(run(lines))
    print(f"\ncall took {time.time() - t0:.0f}s")
    try:
        log = requests.get(LOCAL + "/api/log", timeout=5).json()
    except Exception as e:
        print("could not read /api/log:", e)
        return 1
    rows = [c for c in log["calls"] if c["conversation_id"] == conv_id]
    if not rows:
        print(f"NO LOG ROW for {conv_id}. Rows present: {[c['conversation_id'] for c in log['calls']]}")
        print("Is the tunnel up and are the tool URLs current? ./tunnel.sh")
        return 1
    r = rows[0]
    print(f"log row: {r['order_id']} {r['decision']} customer_gets={r['customer_gets']} "
          f"margin_saved={r['margin_saved']} reason={r['reason_code']} refusals={r['refusals']} "
          f"classifier_fallback={r['classifier_fallback']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
