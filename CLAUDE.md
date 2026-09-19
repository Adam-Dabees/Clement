# Clement — Project Context

> Read fully before doing anything. Last updated **2026-09-19 13:35 PDT** (hackathon day,
> freeze at 16:30). If you are a Claude Code session on a different laptop: the plan in
> §"Execution plan" is what we are running. Ask what time it is and which checkpoint was
> reached before proposing work. §"Current state" says what landed on `main` at 15:25.
> **Voice is live (13:55)** and **Nebius is live (14:25):** a real ElevenLabs conversation calls all
> three tools through the tunnel, the classifier labels it in ~1 s, and a row lands on Live.

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
| `classify.py` | main | Nebius Token Factory intake classifier on `openai/gpt-oss-120b` (reasoning effort low, ~0.7 s median, 1.1 s max measured). Returns labels + per-field confidence, or `None` on any failure (no key, 2.5s timeout, bad JSON). Never decides. |
| `server.py` | main | FastAPI. Three webhook tools (`lookup_order`, `decide_return`, `customer_declined`), `/api/log`, `/api/agent`, `/api/health`, `/api/reset`. Tool responses are the ELEVENLABS.md §6.2 shape (`outcome`, `amount`, `alternative`, `next_step`, `say`…); `_safe()` refuses to return a cost field. One log row per conversation. Mounts `static/` at `/`. |
| `setup_agent.py` | main | Creates **or updates in place** the ElevenLabs tools and agent (`.clement_agent.json` holds ids). Binds `conversation_id` to `system__conversation_id`. `--dry-run` verified; **not yet run against a live key.** |
| `tunnel.sh` | main | cloudflared quick tunnel → `PUBLIC_URL` in `.env` → `setup_agent.py`. Re-run on every tunnel restart. |
| `eval.py` | main | 31 labelled cases (decision, reason code, fallback, escalation; labels on and off). **Must pass before any engine change counts.** |
| `smoke.py` | main | Scripted demo sequences against a running server (`--port 8010`). Asserts Rule 2 on every tool response. |
| `livecall.py` | main | Drives the **real** ElevenLabs agent over its WebSocket with typed text: exercises tools, tunnel, engine and log without a microphone. `--decline` (A1188), `--human` (A1042, asks for a person mid-call), `--vague` (A1077, "I don't like it", ambiguous "okay"). Run it after every `tunnel.sh`. |
| `static/index.html` | main | Demo console: stat tiles, decision log, voice widget (mounts from `/api/agent`), text fallback driving the same backend. |
| `static/business.html` | main | **Merchant console.** Onboarding (3 steps) + six pages. Only **Live** is wired (`/api/log`, 4s poll, 1.2s abort, seeded fallback). Served at `/business.html`. |
| `ios/ClementCall/` | main | **iPhone-style call demo.** Native SwiftUI app; dials the ElevenLabs agent over its WebSocket (same protocol as `livecall.py`), streams the mic, plays the voice, shows the live transcript plus a one-line marker per tool call. No SDK, no key (agent is public). Debug: `-autocall -script "A1077|…"` drives it from `simctl` like `livecall.py`. `xcodegen generate` then open. |
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
   The path to a full cash refund always exists; a person finalises it.
5. **Two declines ends the negotiation.** `customer_declined` counts refusals. At two, the engine
   records the full refund and hands the call to a specialist who finalises it. **The agent never
   pays out cash on its own** (judge feedback, 15:35: the bot must keep optimising; a person handles
   full refunds). Until then it climbs a ladder: keep-the-revenue offer, then a sweeter one.
6. **Fault is decided before margin.** If the return is for a defect, the engine never offers a
   partial refund: replacement first, then store credit for more than they paid, then a person and
   the full refund. This is the answer to the dark-pattern question.
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

`decide()` in `engine.py` runs in this order (as of 15:45, the ladder):

1. **Guardrails first.** Escalate if the customer asks for a human (classifier label when
   confident, else keywords), or if order value exceeds `POLICY["max_autonomous_refund_usd"]`
   ($400). Flag orders outside the return window or on accounts with 3+ prior returns (flag for
   review, never confront the customer). **Escalation returns here**, before the decline check.
2. **Two declines** short-circuits everything below: the record is the full refund (returnless if
   freight recovers nothing, else with return) with `escalated = refund_requires_human`,
   `next_step = handoff`. A specialist finalises it.
3. **Fault axis.** Classifier `is_defect` when confident; below 0.6 confidence → defect (Rule 7);
   no labels → keyword match. Never-arrived (`item_status`) is decided first; baseline for those
   is the returnless refund.
4. **Rung 1 (refusals = 0), keep the revenue:**
   - Never arrived -> `exchange` (reship), `not_delivered_replacement_sent`
   - Wants a replacement -> `exchange`, `customer_asked_for_replacement`
   - Defect -> `exchange`, `our_defect_replacement_first`
   - Preference -> `partial_refund_keep_item` at the base ratio, `preference_return_offer_choice`
   No alternative is volunteered. Asking for a full refund counts as a decline.
5. **Rung 2 (refusals = 1), sweeten:** preference → the partial improves by
   `POLICY["second_offer_step"]` (39% → 54%) with store credit +15% as the named alternative
   (`preference_second_offer`); everything else → store credit +15% (`store_credit_offered_before_refund`).
6. Every outcome is scored as **net to merchant** against the baseline every merchant runs today
   (full refund with return). The delta is `margin_saved`.

**Reason codes:** `our_defect_replacement_first`, `customer_asked_for_replacement`,
`not_delivered_replacement_sent`, `preference_return_offer_choice`, `preference_second_offer`,
`store_credit_offered_before_refund`, `escalated_to_human`, `customer_declined_twice_refund_via_human`.

A condition haircut scales recoverable value: `unopened` 1.0, `used` 0.7, `damaged` 0.25.

### Known engine weaknesses (status at 13:35)

Found by probing, not reading. **Applied on `main`, each with eval cases:** 1, 2, 3, 4, 5, 8.
**Deferred, need a policy decision, not code:** 6, 7.

1. ✅ Rule 6 leaked through keywords. Now: classifier labels first, keyword fallback widened and
   blind to negations ("it's not damaged" no longer reads as a defect; found on the first live call).
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

## Current state (15:50, on `main`)

**Working and tested:**
- **The ladder (15:45, judge feedback).** Judges found the negotiation weak: it named the full
  refund in the first breath and paid it out after one decline. Now: rung 1 keeps the revenue
  (partial keep-it, or a replacement), rung 2 sweetens (54% or store credit +15%), and two declines
  hand the full refund to a specialist. The agent never volunteers or pays a full cash refund.
  Eval 35/35, **44.0% over baseline** (was 23.7%). Smoke 9/9. Rules 5 and 6 reworded above.
- **Agent LLM is gpt-4.1 (15:20).** A spoken A1150 call on gpt-4o-mini contained zero tool calls:
  it said "let me check your order", waited, then claimed the order was found. A/B of eight models
  on the live agent (ELEVENLABS.md §4): gpt-4.1 passes accept / human / decline / vague; gpt-5-mini
  fabricated the customer's words; two others skipped `decide_return`. Prompt now says tools are
  actions ("never say you are checking something; check it") and forbids stating order facts that
  did not come from `lookup_order`.
- **Classifier `condition` is evidence-only.** `unknown` unless the words say opened/used/damaged;
  `damaged` only for visible physical damage (a dead button is `used`, so A1042 keeps its
  "ship it back" story). Verified live: A1042 dead button → full refund with return → handoff on
  "I want a human".
- **Escalation from anywhere in the call (14:45).** First spoken test showed "I want to speak to a
  human" mid-negotiation going to `customer_declined`, whose re-run never saw the new words. Now
  every decline carries the customer's words into the engine's transcript, the stale classifier
  `requests_human` label is dropped on re-runs, and escalation keywords match whole words
  ("personally" no longer escalates). Verified live with `livecall.py --human`: the agent asks
  what exactly is broken, clarifies repair vs replacement, then hands off. Eval 31/31, smoke 9/9.
- **`end_call` built-in tool** is on the agent; the prompt says to say the closing line once and
  end the call on `close_with_refund` / `handoff`, instead of looping "would you like to finalize".
- **Nebius live.** `classify.py` on `openai/gpt-oss-120b`, `reasoning_effort=low`, JSON mode,
  `max_tokens=400` (its hidden reasoning counts against the budget; 160 truncated it). Measured
  sequentially: 0.55–1.2 s per call, zero timeouts across the self-test, a live ElevenLabs call
  (labels `changed_mind / in_hand / used`, 1079 ms, `classifier_fallback=false`) and all eight
  smoke sequences. Llama 3.1 8B no longer exists on Nebius; Qwen3-30B-A3B was 1.8 s median and
  timed out under load; gemma reports meaningless confidences.
- **Voice live.** Agent `agent_0201m2xp7s21fcb9nh0nn7c62vcx` (gpt-4o-mini, 0.2, 120 tokens,
  auth disabled, widget renders on `/`). `livecall.py` ran the A1077 accept path (partial $85.02
  accepted, no spurious decline call, row +$180.98) and the A1188 two-decline path (partial →
  full refund with return → returnless, row +$11.50, `customer_declined_twice_honoring_refund`).
  `conversation_id` is the ElevenLabs conversation id. Tunnel URL is in `.env`; re-run
  `./tunnel.sh` if cloudflared restarts. Local DNS lags fresh tunnel names by minutes; the public
  internet (and ElevenLabs) sees them at once.
- Decision engine, **28/28** on the eval set: 100% accuracy, 14% escalation, $1,501.44 saved
  across 28 returns, 23.2% over the full-refund baseline. Labels-on and labels-off cases both
  pass. Determinism checked (every case run twice, identical records).
- FastAPI server: three webhook tools return the §6.2 shape with `next_step`; `smoke.py`
  passes 8 conversations with zero cost fields in any tool response.
- Demo console (`static/index.html`) verified in Chrome: Decide / Customer declines / Reset,
  one log row per conversation.
- Merchant console at `/business.html` verified in Chrome: Live shows the "demo data" pill,
  flips to "1 live" on a real decision, seeds agree with the engine (39% / $85.02 / +$180.98).
- `classify.py` written; returns `None` without a key (engine falls back to keywords).
- `setup_agent.py` has run for real and PATCHes in place (`.clement_agent.json` holds ids).
- Interaction store: designed and verified, stashed (see above).

**Not done:**
- **A real microphone call on stage.** Text over the WebSocket is proven; a spoken call adds ASR
  and TTS only. Do one before rehearsal.
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
- **Requests on one Nebius key queue up.** Two classifier calls in flight at once pushed latency
  from 0.8 s to 2.5 s+ and half of them timed out to keyword fallback. The demo is one call at a
  time, so this only bites if you run `smoke.py` while someone is on the phone. Don't.
- **The ElevenLabs simulate-conversation API mocks tools** (returns "Tool Called." without
  hitting the webhook). It proves nothing about wiring; use `livecall.py`.
- **The model can narrate instead of calling the tool** ("let me check", then nothing) and then
  hallucinate the result. Seen on gpt-4o-mini in a real spoken call. The prompt forbids it and the
  LLM is gpt-4.1 now; if it recurs, the A/B loop is `ELEVENLABS_LLM=<model> python setup_agent.py`
  then `livecall.py`.
- **A guessed condition lowers the offer.** On "I don't like it" both the agent and the classifier
  said `unopened` at 0.94 confidence with zero evidence, turning 39% ($85.02) into 30% ($65.40).
  Now the classifier answers `unknown` unless the words say opened/used/damaged (no override), and
  the prompt asks once, naturally, then defaults to `used`. Never let a guess move money.
- **The agent read the tool enum out loud** ("unopened, used, or damaged? replacement or refund?")
  and processed a partial on a bare "okay". Prompt now: one question per turn, acknowledge first,
  never voice tool options, and an ambiguous answer after two options gets "which one?" first.
  Replay with `livecall.py --vague`.
- **The agent may answer "I want a human" with `customer_declined`.** The server now folds decline
  words into the engine transcript so escalation fires anyway; the prompt also says to call
  `decide_return` for it. Never rely on the model picking the right tool for a guardrail.
- **The agent may call `customer_declined` on an acceptance** if the tool description is soft.
  The current description says NEVER on accept/thanks/goodbye; verified on the A1077 accept path.
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
