# Clement — Project Context

> Paste this whole file into a Claude conversation to bring it up to speed, or drop it in the
> repo root as `CLAUDE.md` so Claude Code picks it up automatically in every session.

---

## What we are building

A voice agent that answers inbound product-return calls and decides the outcome live, on the
call, based on the actual economics of that specific item.

Today a return is a web form, and the form always produces the same result: full refund, ship
the item back. For a large share of returns that is the worst available option for everyone.
Return freight plus restock labour frequently exceeds what the item can be resold for, and for
some categories (opened bedding, worn apparel) the resale value is zero by law. The merchant
pays to receive something worthless.

Every return is a margin decision. Nobody is currently making it. We make it.

The agent negotiates in real time between:

- full refund with the item returned
- returnless refund (full money back, customer keeps the item)
- partial refund, customer keeps the item
- exchange / replacement
- store credit with a bonus

## Hackathon context

- **Duration:** 8 hours. Code freeze at hour 6, rehearsal in hours 6–8.
- **Sponsors:** Nebius, ElevenLabs, Founder Institute, Sazze.
- **Why this project fits them:** Sazze is an e-commerce and advertising incubator, so return
  margin is directly in their thesis. ElevenLabs wants voice used where it could not be a form,
  and negotiation qualifies. Nebius runs our inference. Founder Institute wants a business model,
  and ours states itself: merchants pay a share of margin saved.
- **Prizes are per-sponsor as well as overall**, so hitting multiple tracks is worth more than
  perfecting one.

---

## Architecture — the one thing to understand

**The model runs the conversation. A deterministic engine picks the outcome.**

That split is the entire pitch. Two identical returns producing different outcomes would be
disqualifying in anything touching money, so the decision never goes through a language model.

```
Caller (voice)
   -> ElevenLabs agent        conversation, tone, turn-taking
   -> server.py webhooks      3 tools the agent calls mid-call
   -> engine.py               deterministic; picks the outcome
   -> dashboard               logs every decision + margin delta
```

Nebius sits beside the agent as an intake classifier only: it turns a rambling spoken complaint
into structured fields (`condition`, `is_defect`, `wants_replacement`). It never decides an
outcome.

---

## Files

| File | Role |
|---|---|
| `engine.py` | **The IP.** Pure functions. No model calls, no network, no randomness. Takes an order plus what the customer said; returns chosen outcome, runner-up, margin delta, reason code, policy flags. |
| `data.py` | Mock orders with real cost structure (unit cost, return freight, restock labour, resale value) plus the `POLICY` envelope. |
| `server.py` | FastAPI. Three webhook tools for the agent, plus `/api/log` for the dashboard. Strips all cost figures before responding to the agent. |
| `setup_agent.py` | Creates the three ElevenLabs webhook tools and the agent in one run. Prints an agent id and the embed snippet. |
| `eval.py` | 12 labelled cases with ground-truth outcomes. Prints accuracy, escalation rate, margin saved. |
| `static/index.html` | Dashboard: stat tiles, decision log, voice widget, and a text fallback that drives the same backend. |

---

## Hard rules — do not violate these

These are invariants, not preferences. If a requested change would break one, refuse it and
explain why.

1. **`engine.py` stays deterministic.** No model calls, no randomness, no network, no clock reads
   inside decision logic. Same inputs must always produce the same decision.
2. **Cost basis never reaches the model.** `unit_cogs`, `resale_value`, `restock_labor`,
   `net_to_merchant` and `margin_saved` must never appear in a response returned to the voice
   agent. Those fields are fine on `/api/log` and `/api/latest`, which feed the internal
   dashboard only.
3. **Every change to `engine.py` needs a matching case in `eval.py`,** and `eval.py` must pass
   before the change counts as done.
4. **The customer is never denied a refund.** The agent offers alternatives; the customer chooses.
5. **Two declines ends the negotiation.** `customer_declined` counts refusals. At two, the engine
   hands over the full refund and the agent stops offering.
6. **Fault is decided before margin.** If the return is for a defect, the engine never offers a
   partial refund. Full value back. This is the answer to the dark-pattern question.
7. **Ambiguity resolves in the customer's favour.** If the Nebius classifier returns confidence
   below 0.6, treat the return as a defect.

---

## Decision logic

`decide()` in `engine.py` runs in this order:

1. **Guardrails first.** Escalate if the customer asks for a human, or if order value exceeds
   `POLICY["max_autonomous_refund_usd"]` ($400). Flag orders outside the return window or on
   accounts with 3+ prior returns (flag for review, never confront the customer).
2. **Two declines** short-circuits everything: hand over the refund.
3. **Fault axis.** Keyword match on the reason decides `is_defect`.
   - Defect + resale below freight cost -> `returnless_refund`
   - Defect + resale above freight cost -> `full_refund_with_return`
   - Wants a replacement -> `exchange`
   - Preference, not defect -> `partial_refund_keep_item`, with the full refund as fallback
4. Every outcome is scored as **net to merchant** against the baseline every merchant runs today
   (full refund with return). The delta is `margin_saved`.

**Reason codes:** `our_defect_uneconomic_to_return`, `our_defect_resale_justifies_freight`,
`customer_asked_for_replacement`, `preference_return_offer_choice`, `escalated_to_human`,
`customer_declined_twice_honoring_refund`.

A condition haircut scales recoverable value: `unopened` 1.0, `used` 0.7, `damaged` 0.25.

---

## Demo orders

Each exists to demonstrate one thing. Do not delete one without replacing its case.

| ID | Item | Demonstrates |
|---|---|---|
| A1042 | Blender, $129 | Resale beats freight. Ship it back. |
| A1077 | Linen duvet, $218 | Opened bedding, zero recovery. Keep-it partial. |
| A1103 | Carry-on, $349 | High recovery, near-new. Full return is correct. |
| A1150 | Espresso machine, $780 | Over the cap. Escalates to a human. |
| A1188 | Trail socks, $34 | Freight exceeds the item. Obvious returnless. |

---

## Current state

**Working and tested:**
- Decision engine, 12/12 on the eval set
- FastAPI server, all three webhook tools verified with curl
- Dashboard with live stats and the text fallback (works with no API keys)
- `setup_agent.py` written but not yet run against a live key

**Current eval numbers:** 100% accuracy, 17% escalation rate, $784.41 saved across 12 returns,
27% improvement over the full-refund baseline.

**Not built yet:**
- Voice layer live (Phase 2)
- Nebius classifier (Phase 4)
- Two-column demo screen (Phase 5)

---

## Roadmap

| Phase | Hours | What |
|---|---|---|
| 0 | 0:00–0:20 | Run it. `pip install fastapi uvicorn requests openai`, `python eval.py`, `uvicorn server:app --port 8000`. Commit. |
| 1 | 0:20–1:00 | Write CLAUDE.md. Understand `decide()` well enough to defend it on stage. |
| 2 | 1:00–2:00 | Voice live. Tunnel, `setup_agent.py`, paste the embed. **Highest risk, do it early.** |
| 3 | 2:00–3:30 | Replace mock data with one real vertical, realistic freight and margin. Expand eval. |
| 4 | 3:30–4:30 | `classify.py` on Nebius. Must degrade safely to defaults on any failure. |
| 5 | 4:30–6:00 | Two-column demo screen: what the customer hears, beside what the business books. |
| 6 | 6:00–6:45 | **Freeze.** Record backup video, screenshot eval, tag the commit. |
| 7 | 6:45–8:00 | Rehearse three times, out loud, in front of a stranger. |

---

## Known traps

- **The ElevenLabs widget renders as nothing** if the agent is not public. No console error, no
  hint. Open the agent in the dashboard, Advanced tab, disable authentication.
- **The cloudflared tunnel URL changes on every restart.** The webhook tools then point at a dead
  host. Re-run `setup_agent.py` or update the tool URLs in the ElevenLabs dashboard.
- **Agent not calling a tool** is almost always the tool *description*, not the system prompt.
  Descriptions must say *when* to call, not what the endpoint does.
- **Any network call in the decision path needs a timeout.** A four-second hang mid-demo reads as
  a crash.

---

## Working style

- One phase per Claude Code session. Start fresh between phases.
- Ask for the diff before applying anything that touches `engine.py`.
- End prompts with "then run `eval.py` and tell me the result." Work that has not been run is not
  done.
- State explicitly what *not* to change. Unscoped edits are how this rots.
- Paste tracebacks, not descriptions of tracebacks.
- Commit between phases. `git tag demo-frozen` at hour 6.

## Stack

Python 3, FastAPI, uvicorn. Vanilla HTML/CSS/JS on the frontend, one file, no build step, no
framework. ElevenLabs Agents for voice. Nebius AI Studio via the OpenAI SDK
(`base_url="https://api.studio.nebius.com/v1/"`) for the intake classifier.

## Pitch, in two sentences

Every return is a margin decision that currently gets made by a form that always picks the worst
option. We put a voice agent on the call that makes the decision properly, in real time, and
never at the customer's expense.
