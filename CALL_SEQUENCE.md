# Clement — Master Sequence of One Call

Every hop from the caller's first word to the dashboard tile, in order, with what
each layer receives, what it does, and what it passes on. This is the document to
trace when something breaks: find the hop where the data stops looking right.

Sections tagged **[built]** are in the repo. **[today]** is on the build plan.
**[later]** is a designed seam, not being built today. Today's goal is end to end
working, not optimised.

---

## 0. Layers

```
 L0  Caller            voice
 L1  ElevenLabs        STT → conversation LLM → tool calls → TTS
 L2  Tunnel            cloudflared, PUBLIC_URL → localhost:8000
 L3  server.py         webhook endpoints, session state, response filter
 L4  classify.py       Nebius intake labels                         [today]
 L5  engine.py         deterministic decision
 L6  store.py          append-only event log                        [today]
 L7  Dashboard         stat tiles, decision log, two-column screen
 L8  Customer history  cross-merchant refund record                 [later]
```

A call touches L0–L7 in a loop, several times. L8 is a read-only input into L5
once it exists.

---

## 1. Call opens

**L0 → L1.** Caller clicks the widget on the dashboard (or dials in, later).
ElevenLabs starts a session, assigns `system__conversation_id`, plays the first
message: *"Hi, you've reached Harlow returns. Can I grab your order number?"*

Nothing reaches our server yet. `SESSIONS` has no entry for this call.

---

## 2. Order lookup

**L0.** "A1077."

**L1.** STT → text. LLM reads the prompt's step 1, reads it back, calls `lookup_order`.

**L1 → L2 → L3.** `POST /tool/lookup_order` `{ "order_id": "A1077" }`

**L3.** `ORDERS.get("A1077")`. Returns the caller-safe subset:
```json
{ "found": true, "customer_name": "Marcus Lee", "item": "Calder Linen Duvet, King",
  "price_paid": 218.0, "days_since_delivery": 5, "within_window": true }
```
No cost fields. Not logged (nothing was decided).

**L3 → L1.** Tool result enters the LLM context.

**L1 → L0.** "Thanks Marcus. What went wrong with the duvet?"

Failure here: `found: false` → agent asks once more → second failure → handoff.

---

## 3. Reason capture

**L0.** "It's just the wrong shade of grey. I opened it, slept on it one night."

**L1.** LLM extracts what it can (`condition=used`, `wants_replacement=false`),
puts the caller's words verbatim in `transcript`, calls `decide_return`.

**L1 → L2 → L3.** `POST /tool/decide_return`
```json
{ "order_id": "A1077", "reason": "wrong shade of grey", "condition": "used",
  "wants_replacement": false, "conversation_id": "<system__conversation_id>",
  "transcript": "it's just the wrong shade of grey, I opened it, slept on it one night" }
```

---

## 4. Server assembles the decision inputs

**L3 [built].** `SESSIONS.setdefault(conversation_id, {"refusals": 0})` → `refusals = 0`.

**L3 → L4 [today].** `classify(reason, transcript, order_ctx)` with a 2.5 s timeout.
`order_ctx` = item, category, price, days since delivery. No cost fields, no name.

**L4 [today].** Nebius returns per-field labels with per-field confidence:
```json
{ "return_type": "changed_mind", "item_status": "in_hand", "condition": "used",
  "customer_intent": "undecided", "quantity_affected": null,
  "requests_human": false, "sentiment": "calm",
  "confidence": { "return_type": 0.91, "item_status": 0.97, "condition": 0.88, "customer_intent": 0.62 } }
```
Any exception, timeout, or malformed JSON → `None`. Server then falls back to the
`condition` the agent sent and the engine's keyword match. Any field with
confidence < 0.6 → the value that costs the customer nothing.

**L3 → L8 [later].** `customer_history(customer_key)` → see §11. Not built. Today
the engine reads `order["prior_returns"]` only.

---

## 5. Engine decides

**L3 → L5.** `decide(order, labels, refusals=0)`.

**L5 [built, with today's fixes]**, in fixed order:

1. `evaluate()` prices every outcome as net-to-merchant. Baseline = full refund with return.
2. Guardrails: `requests_human` (or keyword fallback) → escalate. `price_paid > 400` → escalate. Out of window / `prior_returns >= 3` → flag only.
3. Escalated → return baseline, `escalated_to_human`.
4. `refusals >= 2` → hand over the refund (returnless if resale − logistics ≤ 0, else with return). *Moved below escalation today.*
5. `item_status` [today]: `never_arrived` / `partially_received` → reship or refund, never partial.
6. Fault axis: `fault_party` from a fixed dict on `return_type`. Merchant or carrier fault → full value back (returnless if uneconomic to ship). Customer fault → partial keep-it offer with full refund as the explicit alternative.
7. `_record()` → chosen, baseline, `margin_saved`, reason code, flags, all options.

For A1077 today: `changed_mind` → customer fault → `partial_refund_keep_item`,
39% of $218 = **$85.02**, alternative full refund with return, reason code
`preference_return_offer_choice`, `margin_saved = 180.98`.

No network, no clock, no randomness inside this step.

---

## 6. Server logs and filters

**L3 → L6 [today].** `store.append("decisions", {...})` with everything: raw
`reason` and `transcript`, order snapshot including costs, classifier output and
whether fallback fired, full engine record, `refusals_at_decision`, engine version
hash, timestamp. *(Today [built]: appended to in-memory `CALL_LOG`.)*

**L3 response filter [built].** Drops `unit_cogs`, `resale_value`, `restock_labor`,
`net_to_merchant`, `margin_saved`, `all_options`, `flags`. Returns to L1:

Current shape:
```json
{ "offer": "39% back, keep the item", "customer_gets": 85.02,
  "say": "Shipping it back is a hassle for you. I can put $85.02 back on your card today and you keep the item. Or a full refund if you'd rather return it.",
  "fallback_offer": "...", "escalated": false, "escalation_reason": null }
```

Planned shape [today]:
```json
{ "outcome": "partial_refund_keep_item", "amount": 85.02, "keeps_item": true,
  "alternative": { "outcome": "full_refund_with_return", "amount": 218.0, "keeps_item": false },
  "customer_chooses": true,
  "context": { "first_name": "Marcus", "item": "Calder Linen Duvet, King", "fault": "customer_preference" },
  "must_say": ["the $85.02 amount", "that a full refund is available if they would rather return it"],
  "must_not_say": ["cost", "margin", "resale", "policy", "engine"],
  "escalated": false, "escalation_reason": null, "next_step": "present_offer" }
```

---

## 7. Offer is spoken

**L3 → L2 → L1.** Tool result enters context. LLM reads `next_step = present_offer`,
composes in its own words from the facts, temperature 0.2, ≤ 2 sentences.

**L1 → L0.** "Honestly, boxing a king duvet back up is a pain. I can put $85 on your
card today and you keep it, or do the full $218 if you'd rather send it back.
Which works?"

**L7 [built].** Dashboard polls `/api/log`, shows the new row: decision, reason
code, margin saved. Two-column screen [today] shows classifier labels beside the
engine's reason code.

---

## 8a. Caller accepts

**L0.** "I'll take the $85."

**L1 → L0.** Confirms, thanks, ends. No tool call.

**L1 → L3 [today, if time].** `call_outcome { final_outcome: "accepted_offer" }` →
`store.append("outcomes", ...)`. Or ElevenLabs data-collection field, no webhook.

Call ends. Skip to §10.

---

## 8b. Caller declines, once

**L0.** "No, I want the full amount."

**L1 → L3.** `POST /tool/customer_declined { conversation_id }`.

**L3.** `refusals = 1`. `store.append("declines", {refusal_index: 1, offer_declined: ...})` [today].
Returns `{ stop_negotiating: false, next_step: "present_alternative", say: "That's fair. Let me see what else I can do." }`

**L1 → L0.** Presents the alternative — the full refund with return — as the
thing they asked for. *There is no third offer; the "alternative" was already
named in §7. This is deliberate: two options, caller chooses.*

Most calls end here with the caller taking the full refund. `call_outcome:
took_alternative`.

---

## 8c. Caller declines, twice

**L0.** "No. Just refund me and I'm not shipping anything."

**L1 → L3.** `customer_declined` again. `refusals = 2`.
Returns `{ stop_negotiating: true, next_step: "close_with_refund", say: "Understood. I'm processing the full refund now, no return needed." }`

**L1 → L3 (optional).** If the agent calls `decide_return` again, the engine's
`refusals >= 2` branch returns `customer_declined_twice_honoring_refund` with
`returnless_refund` (A1077: resale 0). Logged with `margin_saved = 48.00`.

**L1 → L0.** "Understood, full $218 refund is going through now, nothing to send
back. Sorry it wasn't right." Ends. Never a third ask.

Known trap: the hardcoded "no return needed" disagrees with the engine on orders
with resale value (A1103 would be *with* return). Demo declines on A1077 or A1188.

---

## 9. Escalation path (replaces §5–§8)

Triggered at §5 step 2 by `requests_human` / keyword, or `price_paid > 400` (A1150).

**L5.** Returns baseline with `escalated = "above_autonomous_refund_cap"` or
`"customer_requested_human"`. `margin_saved = 0`.

**L3 → L1.** `{ escalated: true, escalation_reason: "...", next_step: "handoff", amount: 780.0, ... }`

**L1 → L0.** "I'm connecting you with a specialist right now, one moment." Ends.
The agent does not try to save the call.

---

## 10. After the call

**L6.** Three tables now hold the call: `decisions` (1–2 rows), `declines` (0–2),
`outcomes` (1). Keyed by `conversation_id`.

**L7.** Stat tiles update: calls, margin saved, retention rate, escalations.

**L1.** ElevenLabs evaluation criteria score the transcript (called `decide_return`
before offering, amounts match tool output, ≤ 3 sentences per turn, no banned
words, stopped after two declines). Data-collection fields extract `order_id`,
`offer_accepted`, `final_outcome`.

**L8 [later].** The outcome row becomes one entry in the customer's cross-merchant
history. See §11.

---

## 11. Cross-merchant customer history — the seam [later]

**Not built today. Documented so the seam exists in everyone's head and the store
schema leaves room for it.**

### What it is

Our own database of refund behaviour per customer *across every merchant on the
platform*. A single merchant sees only its own `prior_returns`. We see the
customer's return rate, decline pattern, and outcome history everywhere Clement
answers the phone. That is the information advantage no merchant can build alone,
and it is what makes the platform worth more than the sum of its merchants.

### Where it enters the sequence

§4, beside the classifier. A read-only lookup, before `decide()`:

```
customer_history(customer_key) -> {
  merchants_seen:          int,
  orders_total:            int,
  refunds_total:           int,
  refund_rate:             float,     # refunds / orders, all merchants
  returnless_taken:        int,       # times they kept the item and got money
  declines_avg:            float,     # how often they push past the first offer
  last_refund_days_ago:    int | null,
  confidence:              float      # how much history backs these numbers
} | None
```

`customer_key` = salted hash of the customer's email or phone, set per merchant at
ingest. Never the raw identifier, never the name. `None` when we have no history
or the lookup fails; the engine must run identically without it.

### How the engine uses it

As an **input to a flag and, later, to the offer size — never to a denial.**
Rule 4 is not negotiable: the customer is never denied a refund, and no cross-merchant
number changes that.

Today's equivalent is `order["prior_returns"] >= 3 → flag for review`. The history
signal replaces that single-merchant count with the platform-wide one:

- `refund_rate` above a policy threshold → flag `high_return_account`, dashboard
  only, never spoken.
- Later, `p_accept()` (the offer-acceptance model) takes `declines_avg` and
  `returnless_taken` as features, so the partial ratio is tuned to the person
  rather than fixed at 30/39/52.5%.
- Never: refuse, lower the fallback, or mention the history on the call.

### What it needs from today's build

Only two things, both cheap:

1. `merchant_id` on every order and every store row.
2. A `customer_key` column on `decisions` and `outcomes` (hash of what we have —
   the email on the mock order is fine for now).

Everything else — the lookup service, the thresholds, the acceptance model — is
post-hackathon. The pitch line: *every merchant contributes to the history; each
merchant sees only its own customers; the decision engine sees all of it.*

### Two things to have an answer for

- **Privacy / consent.** Sharing return behaviour across merchants is personal data
  processing. Hashed keys, per-merchant consent at onboarding, and the customer's
  right to see and delete their record. Say this before a judge asks.
- **Fairness.** History informs the *size* of an offer and a review flag. It never
  informs whether the refund is honoured. That is the same line as Rule 6:
  fault before margin, and refund before everything.

---

## 12. Where to look when it breaks

| Symptom | Hop | Check |
|---|---|---|
| Agent greets, never asks for order | L1 | Prompt step 1; first message |
| Agent asks, never calls `lookup_order` | L1 | Tool description |
| `lookup_order` 502 | L2 | Tunnel restarted; re-run `setup_agent.py` |
| Agent offers before `decide_return` | L1 | Tool description says "before offering anything" |
| Wrong `condition` on wire | L1→L3 | Enum in tool schema; classifier overrides anyway |
| Decision looks wrong for the words | L4/L5 | Was classifier `None`? Check `fallback_fired` in the log |
| Agent states an amount not in the log | L1 | Temperature; `must_say`; evaluation criteria |
| Decline counter wrong | L3 | `conversation_id` bound to `system__conversation_id`? |
| Call hangs 3–4 s | L4 | Classifier timeout; must be ≤ 2.5 s |
| Dashboard row missing | L6/L7 | Store append; `/api/log` reading the store |
