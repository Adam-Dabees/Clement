# Clement — Project Context

> Read fully before doing anything. Last updated **2026-09-19 13:35 PDT** (hackathon day,
> freeze at 16:30). If you are a Claude Code session on a different laptop: the plan in
> §"Execution plan" is what we are running. Ask what time it is and which checkpoint was
> reached before proposing work. §"Current state" says what landed on `main` at 13:35.

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
propose a diff and an eval case, do not apply. **13:35 note:** on Roman's laptop all three roles
are being run by one person with Adam's sign-off assumed for the engine fixes listed below;
every engine change there shipped with eval cases (25/25).

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
| `engine.py` | main | **The IP.** Pure functions. No model calls, no network, no randomness. Takes an order, what the customer said, and optional classifier `labels`; returns chosen outcome, explicit fallback (always the full refund), margin delta, reason code, policy flags. |
| `data.py` | main | Mock orders with real cost structure (+ `merchant_id`, `customer_email`, `category`) plus the `POLICY` envelope (+ `min_classifier_confidence`). |
| `classify.py` | main | Nebius Token Factory intake classifier. Returns labels + per-field confidence, or `None` on any failure (no key, 2.5s timeout, bad JSON). Never decides. |
| `server.py` | main | FastAPI. Three webhook tools (`lookup_order`, `decide_return`, `customer_declined`), `/api/log`, `/api/agent`, `/api/health`, `/api/reset`. Tool responses are the ELEVENLABS.md §6.2 shape (`outcome`, `amount`, `alternative`, `next_step`, `say`…); `_safe()` refuses to return a cost field. One log row per conversation. Mounts `static/` at `/`. |
| `setup_agent.py` | main | Creates **or updates in place** the ElevenLabs tools and agent (`.clement_agent.json` holds ids). Binds `conversation_id` to `system__conversation_id`. `--dry-run` verified; **not yet run against a live key.** |
| `tunnel.sh` | main | cloudflared quick tunnel → `PUBLIC_URL` in `.env` → `setup_agent.py`. Re-run on every tunnel restart. |
| `eval.py` | main | 25 labelled cases (decision, reason code, fallback, escalation; labels on and off). **Must pass before any engine change counts.** |
| `smoke.py` | main | Scripted demo sequences against a running server (`--port 8010`). Asserts Rule 2 on every tool response. |
| `static/index.html` | main | Demo console: stat tiles, decision log, voice widget (mounts from `/api/agent`), text fallback driving the same backend. |
| `static/business.html` | main | **Merchant console.** Onboarding (3 steps) + six pages. Only **Live** is wired (`/api/log`, 4s poll, 1.2s abort, seeded fallback). Served at `/business.html`. |
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

`decide()` in `engine.py` runs in this order (as of 13:35):

1. **Guardrails first.** Escalate if the customer asks for a human (classifier label when
   confident, else keywords), or if order value exceeds `POLICY["max_autonomous_refund_usd"]`
   ($400). Flag orders outside the return window or on accounts with 3+ prior returns (flag for
   review, never confront the customer). **Escalation returns here**, before the decline check.
2. **Two declines** short-circuits everything below: hand over the refund (returnless if freight
   recovers nothing, else with return).
3. **Delivery.** `item_status == never_arrived` (label or keywords) → `returnless_refund`, or
   `exchange` if they want a replacement. Baseline for these is the returnless refund: you cannot
   ship back what never arrived.
4. **Fault axis.** Classifier `is_defect` when confident; below 0.6 confidence → defect (Rule 7);
   no labels → keyword match (now includes "doesn't work", "won't turn on", …).
   - Defect + resale below freight cost -> `returnless_refund`
   - Defect + resale above freight cost -> `full_refund_with_return`
   - Wants a replacement -> `exchange`
   - Preference, not defect -> `partial_refund_keep_item`, **fallback = full refund with return**
5. **One decline** turns the named fallback into the offer (`customer_declined_once_full_refund_offered`).
6. Every outcome is scored as **net to merchant** against the baseline every merchant runs today
   (full refund with return). The delta is `margin_saved`. Store credit is designed, not scored.

**Reason codes:** `our_defect_uneconomic_to_return`, `our_defect_resale_justifies_freight`,
`customer_asked_for_replacement`, `preference_return_offer_choice`, `escalated_to_human`,
`customer_declined_once_full_refund_offered`, `customer_declined_twice_honoring_refund`,
`not_delivered_full_refund`, `not_delivered_replacement_sent`.

A condition haircut scales recoverable value: `unopened` 1.0, `used` 0.7, `damaged` 0.25.

### Known engine weaknesses (status at 13:35)

Found by probing, not reading. **Applied on `main`, each with eval cases:** 1, 2, 3, 4, 5, 8.
**Deferred, need a policy decision, not code:** 6, 7.

1. ✅ Rule 6 leaked through keywords. Now: classifier labels first, keyword fallback widened.
2. ✅ Two-declines ran before escalation. Now: escalation returns first.
3. ✅ `fallback` was store credit. Now: explicitly the full refund; store credit not scored.
4. ✅ `customer_declined` hardcoded "no return needed". Now: it re-runs the engine and speaks
   the engine's phrase (A1103 says "once it's back with us"; A1077/A1188 say "no need to ship").
5. ✅ No second offer. Now: refusals=1 makes the named fallback the offer.
6. ⏸ Partial ratio is condition-only, not economic. Changing it moves the $85.02 that is baked
   into the slides, tape and console. Decide after the demo.
7. ⏸ `returnless_threshold_ratio` (0.65) is never read. Applying it as written flips A1042-used
   to returnless (28 / 40.60 = 69%), which kills the "resale beats freight" demo order. Either
   change the ratio or the blender's numbers; not a code fix.
8. ✅ Non-delivery is representable (`item_status`, keywords, own reason codes, honest baseline).

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

## Current state (13:35, on `main`)

**Working and tested:**
- Decision engine, **25/25** on the eval set: 100% accuracy, 16% escalation, $1,254.37 saved
  across 25 returns, 21.0% over the full-refund baseline. Labels-on and labels-off cases both
  pass. Determinism checked (every case run twice, identical records).
- FastAPI server: three webhook tools return the §6.2 shape with `next_step`; `smoke.py`
  passes 8 conversations with zero cost fields in any tool response.
- Demo console (`static/index.html`) verified in Chrome: Decide / Customer declines / Reset,
  one log row per conversation.
- Merchant console at `/business.html` verified in Chrome: Live shows the "demo data" pill,
  flips to "1 live" on a real decision, seeds agree with the engine (39% / $85.02 / +$180.98).
- `classify.py` written; returns `None` without a key (engine falls back to keywords).
- `setup_agent.py --dry-run` prints valid payloads; `tunnel.sh` ready; cloudflared installed.
- Interaction store: designed and verified, stashed (see above).

**Not done:**
- **Voice live.** No `ELEVENLABS_API_KEY` yet. When it arrives: put it in `.env`, run
  `./tunnel.sh`, restart uvicorn, call A1077. **Highest risk.**
- **Nebius live.** No `NEBIUS_API_KEY` yet. When it arrives: `.env`, then
  `.venv/bin/python classify.py` to see labels and latency. Engine is proven on both paths.
- Engine fixes 6 and 7 (deferred, see above).
- Nebius policy-doc parse (onboarding stays canned).

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
- **On Roman's laptop:** `.venv` was made with `uv` (Python 3.12) and works; the demo server
  runs on 8000 with `--reload`, scripted tests use 8010. `./tunnel.sh` owns the tunnel.
- **On Adam's laptop, `.venv` is broken:** `import fastapi` hangs because a `pip install` got stuck
  mid-install. Use anaconda python (`/Users/adamsfiles/anaconda3/bin/python`) for anything that
  imports the server. `eval.py` is fine either way. `.venv` has no `httpx`, so `TestClient`
  doesn't work; test against a running server with `requests`.
- **Port 8000 on Adam's laptop is the user-started `--reload` server.** Don't start a second one
  there; use 8010 for scripted tests.
- **`business.html` lives in `static/` now** and is served at `/business.html`.
- **`must_not_say` in tool responses is the list of words the model must avoid.** It is the one
  place "margin" and "resale" legitimately appear in a tool response; `smoke.py` skips that key.

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
