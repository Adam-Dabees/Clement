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
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python eval.py                              # verify the engine: 25/25
.venv/bin/uvicorn server:app --reload --port 8000     # consoles at localhost:8000
```

- `http://localhost:8000/` — demo console: stat tiles, voice widget slot, **text fallback**
  that drives the identical backend with no API keys.
- `http://localhost:8000/business.html` — merchant console. **Live** reads `/api/log`;
  the other pages are seeded.

Get this far first. Everything after this is the voice layer.

```bash
.venv/bin/uvicorn server:app --port 8010 &          # scripted wiring test
.venv/bin/python smoke.py --port 8010                # five demo call sequences, Rule 2 check
```

## Add voice

Put the keys in `.env` (gitignored, never committed):

```
ELEVENLABS_API_KEY=sk_...
NEBIUS_API_KEY=...            # optional; without it the engine uses keyword fallback
```

Then, with the server running on 8000:

```bash
brew install cloudflared      # once
./tunnel.sh                   # tunnel -> PUBLIC_URL in .env -> setup_agent.py
```

`tunnel.sh` starts a cloudflared quick tunnel, writes the URL to `.env`, and runs
`setup_agent.py`, which creates the agent and three webhook tools the first time and
**updates them in place** every time after (ids in `.clement_agent.json`). It writes
`ELEVENLABS_AGENT_ID` to `.env`; restart uvicorn and the widget mounts itself on the
console from `/api/agent`.

**If the widget renders as nothing:** open the agent in the ElevenLabs dashboard,
Advanced tab, disable authentication. `setup_agent.py` asks for that via the API, but
the dashboard is the fallback.

`python setup_agent.py --dry-run` prints every payload without a key.

## Nebius

`classify.py` is the intake classifier: it turns a rambling spoken complaint into
labels (`is_defect`, `item_status`, `condition`, `wants_replacement`, `requests_human`,
per-field confidence) before the engine runs. It runs on Nebius Token Factory
(formerly AI Studio) through the OpenAI SDK with a 2.5 s timeout and returns `None` on
any failure, at which point the engine falls back to keyword matching. It never decides
an outcome. Below 0.6 confidence the engine treats the return as a defect: ambiguity
resolves in the customer's favour.

```bash
.venv/bin/python classify.py "one speed stopped working and I want a manager"
```

---

## What's here

| File | What it does |
|---|---|
| `engine.py` | The IP. Deterministic. Same input, same decision, every time. |
| `data.py` | Five mock orders with real cost structure, and the policy envelope. |
| `classify.py` | Nebius intake classifier. Labels only, degrades to `None`. |
| `server.py` | Three webhook tools the agent calls, plus `/api/log`, `/api/agent`, `/api/health`. |
| `setup_agent.py` | Creates or updates the ElevenLabs agent and tools. Idempotent. |
| `tunnel.sh` | cloudflared quick tunnel + `setup_agent.py` in one command. |
| `eval.py` | 25 labelled cases with ground truth. Run it, screenshot it. |
| `smoke.py` | Scripted call sequences against a running server. |
| `static/index.html` | Demo console, voice widget, and the text fallback. |
| `static/business.html` | Merchant console. Live page is wired; the rest is seeded. |

## The five demo orders

| ID | Item | What it demonstrates |
|---|---|---|
| A1042 | Blender, $129 | Resale beats freight. Ship it back. |
| A1077 | Duvet, $218 | Opened bedding, zero recovery. Keep-it partial. |
| A1103 | Carry-On, $349 | High recovery, near-new. Full return is correct. |
| A1150 | Espresso, $780 | Over the cap. Escalates to a human. |
| A1188 | Socks, $34 | Decline twice: full refund, no return, agent stops. |

---

## The guardrails, which you demo on purpose

1. **It never denies a refund.** It offers alternatives. The customer picks.
2. **Two declines and it stops.** `customer_declined` counts refusals; at two
   the engine hands over the full refund and the agent stops negotiating.
   Escalation still wins over the decline counter.
3. **Fault before margin.** If the item is defective, the engine never offers
   a partial. Full value back. This is the answer to "is this a dark pattern?"
4. **A hard cap.** Above $400 it escalates rather than deciding.
5. **The model never sees cost basis.** Margin figures stay server-side, out
   of the transcript; `server.py` refuses to return them and `smoke.py` checks.
6. **Ambiguity favours the customer.** Classifier confidence under 0.6 is a defect.

## When it breaks

- **Tool never fires:** the agent is not calling it. Check the tool is
  attached to the agent, and that its description says *when* to call it.
- **Widget doesn't render:** authentication is still enabled on the agent.
- **Long silence mid-call:** your webhook is slow. The engine returns in under
  a millisecond; the classifier is capped at 2.5 s. Check `/api/log` for
  `classifier_fallback: true` and `latency_ms`.
- **Tunnel URL changed:** it does, every restart. Run `./tunnel.sh` again.
- **Decline counter carries across calls:** `conversation_id` is not bound to
  `system__conversation_id`. `setup_agent.py` binds it; re-run it.
