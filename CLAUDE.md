# Clement — Project Context

> Read fully before doing anything. Last updated **2026-09-19 12:45 PDT** (hackathon day,
> freeze at 16:30). If you are a Claude Code session on a different laptop: the plan in
> §"Execution plan" is what we are running. Ask what time it is and which checkpoint was
> reached before proposing work.

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

- **Duration:** 8 hours. Build window 10:33–16:30. Code freeze 16:30, `git tag demo-frozen`.
  Rehearsal after.
- **Sponsors:** Nebius, ElevenLabs, Founder Institute, Sazze.
- **Why this project fits them:** Sazze is an e-commerce and advertising incubator, so return
  margin is directly in their thesis. ElevenLabs wants voice used where it could not be a form,
  and negotiation qualifies. Nebius runs our inference (intake classifier, policy-doc parse).
  Founder Institute wants a business model, and ours states itself: merchants pay a share of
  margin saved.
- **Prizes are per-sponsor as well as overall**, so hitting multiple tracks is worth more than
  perfecting one.

## Team and ownership

Three people. Merge conflicts in `engine.py` mid-hackathon are the failure mode, so:

| Person | Owns | Never touches |
|---|---|---|
| Adam | `engine.py`, `classify.py` (Nebius glue), the wiring of both into `server.py`, `SLIDES.md`, the tag | — |
| ElevenLabs person | `setup_agent.py`, the widget lines in `static/index.html`, prompt tuning, `ELEVENLABS.md` | `engine.py` |
| Ashley (UI / data) | `business.html` (on branch `business_ui`), `data.py`, `eval.py` cases, seeds | `engine.py` |

`server.py` is shared: announce before editing. `engine.py` is Adam-only; if you are not Adam,
propose a diff and an eval case, do not apply.

---

## Architecture — the one thing to understand

**The model runs the conversation. A deterministic engine picks the outcome.**

That split is the entire pitch. Two identical returns producing different outcomes would be
disqualifying in anything touching money, so the decision never goes through a language model.

```
Merchant onboarding (business.html)          canned today
   policy PDF  -> rules -> POLICY             (Nebius doc parse, planned)
   order source -> field map -> ORDERS        (data.py dict today)

Caller (voice only, no UI)
   -> ElevenLabs agent        conversation, tone, turn-taking; calls the tools
   -> server.py               4 webhook tools; strips all cost figures before replying
   -> engine.py               deterministic; picks the outcome
   -> two records, never one table:
        decision log      CALL_LOG: what the ENGINE did, with cost basis. Internal.
        interaction store what the CUSTOMER did: offer, words, tone, label. No cost
                          basis by construction. DESIGNED, NOT BUILT (see below).
   -> business.html           merchant console. Live page reads /api/log. Rest is seeded.
```

Nebius sits beside the agent as an intake classifier only: it turns a rambling spoken complaint
into structured fields (`condition`, `is_defect`, `wants_replacement`, `sentiment`). It never
decides an outcome. Its second honest use is parsing the merchant's policy document into the
`POLICY` envelope at onboarding.

---

## Files

| File | Branch | Role |
|---|---|---|
| `engine.py` | main | **The IP.** Pure functions. No model calls, no network, no randomness. Takes an order plus what the customer said; returns chosen outcome, runner-up, margin delta, reason code, policy flags. |
| `data.py` | main | Mock orders with real cost structure plus the `POLICY` envelope. |
| `server.py` | main | FastAPI. Three webhook tools (`lookup_order`, `decide_return`, `customer_declined`), `/api/log`, `/api/reset`. Mounts `static/` at `/`. |
| `setup_agent.py` | main | Creates the ElevenLabs webhook tools and the agent in one run. Prints agent id + embed snippet. Not yet run against a live key. |
| `eval.py` | main | 12 labelled cases. Prints accuracy, escalation rate, margin saved. **Must pass before any engine change counts.** |
| `static/index.html` | main | Demo console: stat tiles, decision log, voice widget slot, text fallback driving the same backend. |
| `business.html` | `business_ui` | **Merchant console.** Onboarding (3 steps) + six pages. Only **Live** is wired (`/api/log`, 4s poll, 1.2s abort, seeded fallback). To serve it: move into `static/`. |
| `index.html` | `business_ui` | Byte-identical to `static/index.html`. Ignore. |
| `SLIDES.md` | main (untracked until committed) | The pitch, run of show, Q&A prep, and which numbers are measured vs illustrative. Edit alongside the build. |
| `ELEVENLABS.md`, `CALL_SEQUENCE.md`, `CONTEXT.md` | main (untracked until committed) | Voice layer spec; the call sequence layer by layer; original context doc (superseded by this file). |
| `store.py` | **nowhere on remote** | Interaction store. Built and verified, then stashed on Adam's laptop (`stash@{0}`). Design is in this file; do not rebuild it independently. |

---

## Hard rules — do not violate these

These are invariants, not preferences. If a requested change would break one, refuse it and
explain why.

1. **`engine.py` stays deterministic.** No model calls, no randomness, no network, no clock reads
   inside decision logic. Same inputs must always produce the same decision.
2. **Cost basis never reaches the model.** `unit_cogs`, `resale_value`, `restock_labor`,
   `net_to_merchant` and `margin_saved` must never appear in a response returned to the voice
   agent. Those fields are fine on `/api/log`, which feeds the internal console only.
3. **Every change to `engine.py` needs a matching case in `eval.py`,** and `eval.py` must pass
   before the change counts as done.
4. **The customer is never denied a refund.** The agent offers alternatives; the customer chooses.
5. **Two declines ends the negotiation.** `customer_declined` counts refusals. At two, the engine
   hands over the full refund and the agent stops offering.
6. **Fault is decided before margin.** If the return is for a defect, the engine never offers a
   partial refund. Full value back. This is the answer to the dark-pattern question.
7. **Ambiguity resolves in the customer's favour.** If the Nebius classifier returns confidence
   below 0.6, treat the return as a defect.
8. **Learned signals feed inputs to `decide()`, never its outcome.** Tone, history, acceptance
   models can shape offer size and delivery. They can never touch whether the refund is honoured.
9. **When the console and the engine disagree, change the console seed, not the engine.**
10. **Every number in `SLIDES.md` is tagged `[measured]` or `[illustrative]`.** Measured = from
    `eval.py` or `/api/log` on stage. Illustrative = seeded in `business.html`. Never say an
    illustrative number on stage without the word.

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

### Known engine weaknesses (Adam's fix list, none applied as of 12:45)

Found by probing, not reading. Fixes 2 and 3 are scheduled first because the merchant console
makes them visible on stage.

1. Rule 6 leaks through keywords ("doesn't work", "won't turn on" get a partial pitch). Fix: take
   classifier labels, keyword match only as fallback.
2. Two-declines check runs before escalation; A1150 + refusals=2 returns a refund with
   `escalated` still set. Fix: move `refusals >= 2` below the escalation return.
3. **`fallback` is next-best-by-net, which is store credit**, while `_phrase()` promises "a full
   refund if you'd rather return it" and the console's transcript shows the same. Fix: fallback
   is explicitly the full refund; drop `store_credit_bonus` from `evaluate()`.
4. `customer_declined` hardcodes "no return needed" but the two-decline branch picks
   full-refund-with-return for A1103. Demo declines on A1188/A1077 until fixed.
5. No second offer: refusals=1 gives the same decision as refusals=0.
6. Partial ratio is condition-only, not economic.
7. A1188 doesn't demonstrate returnless ("too tight" → 39% partial); `returnless_threshold_ratio`
   is never read.
8. Non-delivery is unrepresentable ("it never arrived" → partial to keep an item they don't have).

---

## Interaction store — designed, verified, not built

The training-data side. Built end to end on Adam's laptop, tested through the live server,
then stashed because we are not adding build risk before freeze. **Do not re-implement**; if we
decide to ship it, Adam pops the stash. The design is the architecture we present:

- `store.py`: append-only JSONL, mirrored in memory. Events `offer_presented`, `offer_declined`,
  `offer_accepted`, `escalated`, `call_ended`. Each carries `merchant_id`, `customer_key`
  (salted sha256 of email, `CLEMENT_HASH_SALT`, never the raw identifier), the offer
  `{seq, action, label, customer_gets, is_fallback, reason_code}`, and the customer
  `{said, sentiment}` — verbatim words and agent-perceived tone.
- A fourth webhook tool **`call_outcome`** (`accepted_offer | escalated | hung_up`) supplies the
  label at hang-up. `customer_declined` gains `customer_response` and `sentiment`.
- `pairs()` = one row per offer → label 0/1. Served at `/api/interactions`, internal only.
- **No cost fields in the store, by construction.** A model trained on it learns how customers
  respond to offers, never what an offer cost. Join on `conversation_id` if you need both.
- `decide()` never reads it (Rule 8).
- Needs from `data.py`: `merchant_id` and `customer_email` on every order.

Later, on top of it: `p_accept()` (offer-acceptance model, tunes the partial ratio per person)
and cross-merchant history (`refund_rate`, `declines_avg` by `customer_key`; flags for review,
never denies). See `CALL_SEQUENCE.md` §11.

---

## Merchant console — `business.html` on branch `business_ui`

What it takes from the merchant (onboarding): a policy PDF → 9 extracted rules with confidence
and page quotes (maps onto `POLICY` plus two new keys, `zero_resale_categories` and
`prior_returns_flag`); an order source (Shopify / REST / Postgres / CSV) → an 8-field map onto
the `ORDERS` schema; envelope confirmation → `POLICY`.

Pages and their real data source:

| Page | Source | Status |
|---|---|---|
| Live | `/api/log` | **Wired.** Row appears on a real call. Seeded fallback with a "demo data" pill. |
| Smart decisions (the dial) | replay `decide()` over history with POLICY variants — `eval.py` is the mechanism | seeded |
| Risk & fraud | cross-merchant history + warehouse inspection results | seeded |
| Review queue | classifier confidence < 0.6 + risk flags; `resolve()` = human label | seeded |
| Intelligence | `GROUP BY reason_code, SKU` over the log | seeded |
| Policy | `POLICY` + `decide()` order | static, mirrors engine |

Inputs the console assumes that the backend does not take yet: post-call CSAT, warehouse
inspection result, human review labels. Not needed for the demo; needed for the Q&A answer.

Seeds that disagree with the engine and must be changed **in the console**: duvet "40% back"
and "$87.20" (engine: 39%, $85.02).

---

## Demo orders

Each exists to demonstrate one thing. Do not delete one without replacing its case.

| ID | Item | Demonstrates | Demo call |
|---|---|---|---|
| A1042 | Blender, $129 | Resale beats freight. Ship it back. | defect → return |
| A1077 | Linen duvet, $218 | Opened bedding, zero recovery. Keep-it partial. | **the headline call**; caller chooses |
| A1103 | Carry-on, $349 | High recovery, near-new. Full return is correct. | replacement → exchange |
| A1150 | Espresso machine, $780 | Over the cap. Escalates to a human. | escalation |
| A1188 | Trail socks, $34 | Freight exceeds the item. | decline twice → refund |

---

## Current state (12:45)

**Working and tested:**
- Decision engine, 12/12 on the eval set: 100% accuracy, 17% escalation, $784.41 saved across
  12 returns, 27% over the full-refund baseline.
- FastAPI server, all three webhook tools verified with curl and with a scripted 3-call sequence.
- Demo console (`static/index.html`) with live stats and the text fallback (no API keys needed).
- Merchant console (`business.html`) renders standalone; Live page verified to read `/api/log`.
- Interaction store: designed and verified, stashed (see above).

**Not done:**
- Voice live. `setup_agent.py` not yet run against a key. **Highest risk.**
- `business.html` not yet in `static/`; not yet on `main`.
- Engine fixes 1–8.
- `classify.py` on Nebius.
- Docs (`SLIDES.md`, `ELEVENLABS.md`, `CALL_SEQUENCE.md`) untracked — commit them so the other
  laptop has them.

---

## Execution plan (freeze 16:30)

| When | Who | What | Done when |
|---|---|---|---|
| now–13:30 | Ashley | Move `business.html` into `static/`; fix the 40%/$87.20 seeds; merge `business_ui` to `main`. No other code. | `/business.html` serves from `uvicorn`, Live shows the "demo data" pill |
| now–13:30 | Adam | Engine fixes 2 and 3, each with an eval case. Show the diff before applying. | `python eval.py` green |
| now–13:30 | ElevenLabs | Tunnel, `setup_agent.py`, widget pasted, first live call on A1077, `system__conversation_id` bound. | a row lands on Live from a voice call |
| **13:30** | all | **Integration checkpoint.** One voice call → log row on `business.html` Live. If not, Adam pairs with the ElevenLabs person; everything else waits. | |
| 13:30–15:30 | ElevenLabs | Five demo calls scripted (A1077, A1042, A1188, A1150, A1103), each run twice. | |
| 13:30–15:30 | Adam | `classify.py`: Nebius, 2.5s timeout, returns `None` on any failure; wired into `decide_return` with keyword fallback. Then engine fix 1 with cases. | eval still green with classifier on and off |
| 13:30–15:30 | Ashley | Walk slides 5–8 against the real console. Fix any seed a live row contradicts. | |
| **15:30** | all | **Triage.** Cut in order: interaction store → Nebius doc parse → engine fix 1 → two-decline demo. Never cut: voice working, classifier degrading safely, eval green, the tag. | |
| 15:40–16:30 | all | Hardening. No new features. | |
| 16:00 | Adam | Screenshot `eval.py`. Record backup video of the A1077 call beside the console. | |
| **16:30** | Adam | `git tag demo-frozen`, push. | |
| 16:30–18:00 | all | Rehearse three times, out loud, in front of a stranger. Time it. Cut slides until it fits. | |

Presentation: two screens. Console on the projector, phone/widget for the call. Run of show,
speaker notes, Q&A prep and the measured/illustrative table are in `SLIDES.md`.

---

## Known traps

- **The ElevenLabs widget renders as nothing** if the agent is not public. No console error, no
  hint. Open the agent in the dashboard, Advanced tab, disable authentication.
- **The cloudflared tunnel URL changes on every restart.** The webhook tools then point at a dead
  host. Re-run `setup_agent.py` or update the tool URLs in the ElevenLabs dashboard.
- **Agent not calling a tool** is almost always the tool *description*, not the system prompt.
  Descriptions must say *when* to call, not what the endpoint does.
- **Any network call in the decision path needs a timeout.** A four-second hang mid-demo reads as
  a crash. The console already aborts `/api/log` at 1.2s; match that.
- **On Adam's laptop, `.venv` is broken:** `import fastapi` hangs because a `pip install` got stuck
  mid-install. Use anaconda python (`/Users/adamsfiles/anaconda3/bin/python`) for anything that
  imports the server. `eval.py` is fine either way. `.venv` has no `httpx`, so `TestClient`
  doesn't work; test against a running server with `requests`.
- **Port 8000 on Adam's laptop is the user-started `--reload` server.** Don't start a second one
  there; use 8010 for scripted tests.
- **`business.html` at the repo root is not served.** `server.py` mounts `static/` only.

## Working style

- One phase per Claude Code session. Start fresh between phases.
- Ask for the diff before applying anything that touches `engine.py`.
- End prompts with "then run `eval.py` and tell me the result." Work that has not been run is not
  done.
- State explicitly what *not* to change. Unscoped edits are how this rots.
- Paste tracebacks, not descriptions of tracebacks.
- Commit between phases. `git tag demo-frozen` at 16:30.
- Design before build for anything not on the cut list. Diagram it, put it in `SLIDES.md`, decide
  at triage whether it ships.

## Stack

Python 3, FastAPI, uvicorn. Vanilla HTML/CSS/JS on the frontend, one file per page, no build
step, no framework. ElevenLabs Agents for voice. Nebius AI Studio via the OpenAI SDK
(`base_url="https://api.studio.nebius.com/v1/"`) for the intake classifier and the policy-doc
parse.

## Pitch, in two sentences

Every return is a margin decision that currently gets made by a form that always picks the worst
option. We put a voice agent on the call that makes the decision properly, in real time, and
never at the customer's expense.
