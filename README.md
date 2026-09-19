# Clement

Every return is a margin decision. Today it gets made by a web form that
always picks "full refund, ship it back" — frequently the worst option for
everyone. This is a voice agent that makes the decision properly, live, on
the call.

The model runs the conversation. A deterministic engine picks the outcome.
That split is the whole pitch.

---

## Run it

```bash
pip install fastapi uvicorn requests
python eval.py                          # verify the engine: 12/12
uvicorn server:app --reload --port 8000 # dashboard at localhost:8000
```

The text fallback on the dashboard works immediately, with no API keys.
Get this far first. Everything after this is the voice layer.

## Add voice

```bash
# 1. Expose the backend. ElevenLabs webhook tools need a public URL.
cloudflared tunnel --url http://localhost:8000     # or: ngrok http 8000

# 2. Create the agent and its three tools.
export ELEVENLABS_API_KEY=sk_...
export PUBLIC_URL=https://whatever-your-tunnel-printed.trycloudflare.com
python setup_agent.py
```

It prints two lines of HTML. Paste them into `static/index.html` where the
commented-out block is, and reload.

**Then do this or you will lose twenty minutes:** open the agent in the
ElevenLabs dashboard, Advanced tab, and disable authentication. The embed
widget only works with a public agent.

## Nebius

Point the reasoning at Nebius AI Studio. It is OpenAI-compatible, so it is a
base_url change:

```python
from openai import OpenAI
client = OpenAI(
    base_url="https://api.studio.nebius.com/v1/",
    api_key=os.environ["NEBIUS_API_KEY"],
)
```

Use it for the one genuinely fuzzy job: classifying a rambling spoken
complaint into `condition` and `is_defect` before the engine runs. Ten
seconds of stage time, and it is an honest use rather than a bolt-on.

---

## What's here

| File | What it does |
|---|---|
| `engine.py` | The IP. Deterministic. Same input, same decision, every time. |
| `data.py` | Five mock orders with real cost structure, and the policy envelope. |
| `server.py` | Three webhook tools the agent calls, plus the dashboard API. |
| `setup_agent.py` | Creates the ElevenLabs agent and tools in one run. |
| `eval.py` | Twelve labelled cases with ground truth. Run it, screenshot it. |
| `static/index.html` | Dashboard, voice widget, and the text fallback. |

## The five demo orders

| ID | Item | What it demonstrates |
|---|---|---|
| A1042 | Blender, $129 | Resale beats freight. Ship it back. |
| A1077 | Duvet, $218 | Opened bedding, zero recovery. Keep-it partial. |
| A1103 | Carry-On, $349 | High recovery, near-new. Full return is correct. |
| A1150 | Espresso, $780 | Over the cap. Escalates to a human. |
| A1188 | Socks, $34 | Freight exceeds the item. Obvious returnless. |

---

## The guardrails, which you demo on purpose

1. **It never denies a refund.** It offers alternatives. The customer picks.
2. **Two declines and it stops.** `customer_declined` counts refusals; at two
   the engine hands over the full refund and the agent stops negotiating.
3. **Fault before margin.** If the item is defective, the engine never offers
   a partial. Full value back. This is the answer to "is this a dark pattern?"
4. **A hard cap.** Above $400 it escalates rather than deciding.
5. **The model never sees cost basis.** Margin figures stay server-side, out
   of the transcript, so the agent cannot be talked into revealing them.

## Hour plan

| Hours | Do |
|---|---|
| 0–1 | Run the repo. Tunnel up, agent talking, one round trip working. |
| 1–3 | Your own product data and policy numbers in `data.py`. |
| 3–5 | Tune the prompt. Voice needs short sentences; read them aloud. |
| 5–6 | **Record the backup video.** Not at hour 8. |
| 6–7 | Expand `eval.py` to ~30 cases. The number goes on your last slide. |
| 7–8 | Rehearse the demo three times, out loud, with a stranger. |

## Demo order

Socks (obvious win) → duvet (the interesting one) → espresso (escalation,
shows restraint) → hand the judge a phone.

Give them a card with three suggested lines. They feel free, you control
the surface.

## When it breaks

- **Tool never fires:** the agent is not calling it. Check the tool is
  attached to the agent, and that its description says *when* to call it.
- **Widget doesn't render:** authentication is still enabled on the agent.
- **Long silence mid-call:** your webhook is slow. The engine is pure Python
  and returns in under a millisecond; if it's slow, something upstream is
  doing network I/O it shouldn't.
- **Tunnel URL changed:** it does, every restart. Re-run `setup_agent.py`
  or update the tool URLs in the dashboard.
