"""
Creates the ElevenLabs agent + its webhook tools in one run.

    export ELEVENLABS_API_KEY=...
    export PUBLIC_URL=https://your-tunnel.trycloudflare.com
    python setup_agent.py

Prints an agent_id and the two lines of HTML you paste into static/index.html.
"""

import os
import requests

KEY = os.environ["ELEVENLABS_API_KEY"]
BASE = os.environ["PUBLIC_URL"].rstrip("/")
H = {"xi-api-key": KEY, "Content-Type": "application/json"}

PROMPT = """You are the returns line for Harlow & Co, an online homeware store.
You are warm, fast, and you never sound like a policy document. Keep every reply
under two sentences. This is voice: no bullet points, no reading out URLs.

Flow:
1. Greet, ask for the order number. Read it back to confirm.
2. Call lookup_order. Use the customer's first name once.
3. Ask what went wrong, in your own words. Listen for whether the item is
   unopened, used, or damaged, and whether they want a replacement.
4. Call decide_return with what you learned. Say the `say` field naturally,
   in your own voice. Do not invent an offer. Do not mention costs or margin.
5. If they turn it down, call customer_declined, then offer the fallback.
   If they turn that down too, the tool tells you to stop. Give the full
   refund immediately and warmly. Never argue, never ask a third time.

Hard rules:
- You never deny a refund. Ever. You offer alternatives; they choose.
- If they ask for a human, or sound genuinely angry, call decide_return and
  follow the escalation. Do not try to save the call.
- Never mention cost basis, resale value, margin, or that a decision engine
  exists. You are a helpful person, not a pricing model."""


def make_tool(name, desc, path, props, required):
    r = requests.post(
        "https://api.elevenlabs.io/v1/convai/tools",
        headers=H,
        json={"tool_config": {
            "type": "webhook",
            "name": name,
            "description": desc,
            "api_schema": {
                "url": f"{BASE}{path}",
                "method": "POST",
                "request_body_schema": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }},
    )
    r.raise_for_status()
    tid = r.json()["id"]
    print(f"  tool {name} -> {tid}")
    return tid


def s(d):
    return {"type": "string", "description": d}


print("creating tools...")
t1 = make_tool("lookup_order", "Look up a customer's order by its number.",
               "/tool/lookup_order", {"order_id": s("The order number, e.g. A1042")},
               ["order_id"])

t2 = make_tool(
    "decide_return",
    "Decide the best return outcome once you know why the customer is returning the item. Call this before offering anything.",
    "/tool/decide_return",
    {
        "order_id": s("The order number"),
        "reason": s("Why they are returning it, in their own words"),
        "condition": s("One of: unopened, used, damaged"),
        "wants_replacement": {"type": "boolean", "description": "True if they said they want the same item again"},
        "conversation_id": s("Any stable id for this call"),
        "transcript": s("The last thing the customer said, verbatim"),
    },
    ["order_id", "reason", "condition"],
)

t3 = make_tool("customer_declined", "Call this the moment the customer turns down an offer.",
               "/tool/customer_declined", {"conversation_id": s("Same id as before")}, [])

print("creating agent...")
r = requests.post(
    "https://api.elevenlabs.io/v1/convai/agents/create",
    headers=H,
    json={
        "name": "Clement",
        "conversation_config": {
            "agent": {
                "prompt": {"prompt": PROMPT, "temperature": 0.3,
                           "tool_ids": [t1, t2, t3]},
                "first_message": "Hi, you've reached Harlow returns. Can I grab your order number?",
                "language": "en",
            }
        },
    },
)
r.raise_for_status()
aid = r.json()["agent_id"]

print(f"\nagent_id: {aid}")
print("\nPaste into static/index.html:")
print(f'<elevenlabs-convai agent-id="{aid}"></elevenlabs-convai>')
print('<script src="https://unpkg.com/@elevenlabs/convai-widget-embed" async></script>')
print("\nNow open the agent in the dashboard, Advanced tab, DISABLE authentication.")
print("Widget embeds require a public agent. This will cost you 20 minutes if you skip it.")
