# Clement — pitch deck (working draft)

> Living document. Edit as we build. Every number on a slide is tagged **[measured]**
> (comes from `eval.py` or `/api/log` on stage) or **[illustrative]** (seeded demo data
> in `business.html`). Never say an illustrative number without the word "illustrative".
> A judge who catches one unlabelled number stops believing all of them.

Format: 6 minutes talk + demo, 4 minutes Q&A (adjust when the organisers confirm).
Two screens: **Screen A** = `business.html` merchant console. **Screen B** = phone or
widget the caller uses. The audience watches A while hearing B.

---

## 1. Title

**Clement** — the returns line that makes the margin decision.

Speaker: one line only. "Every return is a margin decision. Today a web form makes it,
and the form always picks the worst option. We put a voice agent on the call that makes
it properly, live, and never at the customer's expense."

---

## 2. The problem — a form that always picks the same answer

Visual: the default returns form → one arrow → "full refund + ship it back".

- Return freight + restock labour often exceeds what the item resells for.
- Opened bedding, worn apparel: resale value is **zero by law**. Merchant pays to
  receive something worthless.
- Nobody is making the decision. It's a form.

Speaker: use the socks. "Harlow pays $11.50 in freight and labour to receive a pair of
worn socks it then throws away. The customer waited a week for a label. Both lost."
**[measured — A1188 in data.py]**

---

## 3. The decision, made properly

Visual: the outcomes side by side — full refund + return, returnless refund,
partial + keep, exchange — each scored as net-to-merchant. (Store credit with a bonus is a
designed outcome, not yet scored; say so if asked.)

- Every outcome scored against the baseline every merchant runs today.
- Fault is decided **before** margin. Our defect → full value back, always.
- Customer is never denied a refund. We offer; they choose.

Speaker: "This is not haggling. If it's our fault, there is no negotiation. When it's a
preference, we give the customer a genuine choice — money now and keep it, or the full
refund. Most take the money now. Everyone is better off."

---

## 4. Architecture — the one thing to understand

Visual: the diagram from the session (voice layer → server → engine → two records).

**The model runs the conversation. A deterministic engine picks the outcome.**

- ElevenLabs: hears, speaks, tone. Calls three tools.
- Nebius: turns a rambling complaint into structured fields. Never decides.
- `engine.py`: pure functions. Same inputs → same decision, every time.
- Two records: the decision log (cost basis, internal) and the interaction store
  (what the customer said and did — no cost basis, by construction).

Speaker: "Two identical returns producing different outcomes would be disqualifying in
anything touching money. So the decision never goes through a language model. That's
what makes this payments-grade instead of a chatbot."

---

## 5. Live demo — one call, two screens

Screen A on **Live**. Screen B: call in. Order **A1077**, the duvet, "wrong shade of grey".

What the audience sees on A while the call runs:
1. Decision log row appears: `partial_refund_keep_item`, `preference_return_offer_choice`,
   margin saved **[measured]**.
2. Hero number and tiles update from `/api/log`.

Then, if time, the two-decline path on **A1188**: decline twice, agent hands over the full
refund and stops. Say out loud: "Two nos and the negotiation is over. By policy. Not by mood."

Fallback if voice fails: text fallback on `static/index.html` drives the identical backend.
Say so; it's a feature ("the decision doesn't care which channel it came from").

---

## 6. The dial — why a deterministic engine is worth more than a model

Screen A on **Smart decisions**. Drag the dial.

- Every position is the *same* engine replayed over the merchant's history.
- Margin peaks, then **falls**: harder offers → second refusals → full refund anyway,
  minus the goodwill.
- Curve, CSAT, decline rate: **[illustrative]** today. The replay mechanism is real —
  it's `eval.py` over the order history.

Speaker: "You can only replay history through an engine that gives the same answer
twice. This dial is impossible with a model in the decision path. That's the moat."

---

## 7. Trust — fraud, review, and the line we don't cross

Screen A on **Risk & fraud** → **Review queue**.

- Risk score changes **who takes the call and which offers are allowed**. Never whether
  the refund is honoured.
- Low-confidence classifier calls (< 0.6) → treated as a defect, paid in full, queued for
  a human. Ambiguity resolves in the customer's favour.
- Human resolutions feed back as labels.

Speaker: the Devin Marsh card — $4,120 lifetime value, real faults in the history. "The
right action is a person on the call and no returnless offers — not a closed account."
**[illustrative]**

---

## 8. Insights compound with every call

Screen A on **Intelligence**.

- Reasons for return, by category. Defect rate per SKU vs baseline, with the dominant
  phrase. Churn by outcome.
- All `GROUP BY` over the same log the judge just watched fill up.
- The duvet's "wrong shade" is a **listing photo** problem, not a returns problem.

Speaker: "The returns line is the only call type with a margin decision inside it, and
it's where customers tell you exactly what's wrong with your product. We're already on
that call." **[illustrative numbers, real mechanism]**

---

## 9. Business model

- **Merchants pay a share of margin saved.** Measured by the same log they watch —
  decision by decision, against the baseline they run today.
- Onboarding is three steps: upload the policy you have → connect orders → confirm the
  envelope. The dry-run replay of the last 90 days closes the sale.
- Wedge: Shopify homeware/apparel merchants, where zero-resale categories are common.

Worked example **[measured]**: eval set saves $1,501.44 across 28 returns ≈ $54 per return.
At a 20% share, ~$11 per call to us, ~$43 to the merchant, and the customer got money
faster without shipping anything. *(20% is a proposal, not a decision — say "for
example".)*

---

## 10. Sponsors — why this fits

| Sponsor | What we used it for | Where it shows |
|---|---|---|
| ElevenLabs | Voice where a form can't negotiate; tone as a signal | The call |
| Nebius | Intake classifier (live, ~1 s, gpt-oss-120b); policy-doc → envelope planned (never the decision) | Live page classifier column, review queue |
| Sazze | Return margin is the product | Every number on the console |
| Founder Institute | A business model that states itself | Slide 9 |

---

## 11. Ask / close

"Every merchant contributes to the history; each merchant sees only its own customers;
the decision engine sees all of it. We take the returns line."

---

## Appendix A — numbers we can defend

| Number | Source | Tag |
|---|---|---|
| 28/28 eval accuracy, 14% escalation, $1,501.44 saved, 23.2% over baseline | `python eval.py` (14:05) | measured |
| Live ElevenLabs call, A1077: tools fired through the tunnel, row +$180.98; A1188 two declines → +$11.50 | `livecall.py` 13:55 | measured |
| Nebius classifier (gpt-oss-120b): 0.55–1.2 s per call, 0 timeouts over 13 calls, labels correct | `classify.py`, `smoke.py`, `livecall.py` 14:25 | measured |
| A1077: 39% back = $85.02, +$180.98 vs baseline; two declines → $218 returnless, +$48.00 | `/api/log` on stage | measured |
| Per-order cost structure (A1042…A1188) | `data.py` | measured (mock, realistic) |
| $61,400 hero, 2,847 returns, CSAT 4.46, dial curve | `business.html` seeds | illustrative |
| Risk accounts, cohort, signals | `business.html` seeds | illustrative |
| Defect rates, churn exposure | `business.html` seeds | illustrative |

Consistency, fixed 13:35 (verified in Chrome against the running server):
- `business.html` seeds now say **39% / $85.02 / +$180.98**, matching the engine.
- The fallback is the full refund in the engine record, the tool response and the phrase.

## Appendix B — Q&A prep

- **"Isn't this a dark pattern?"** Fault before margin. A defect never gets a partial.
  Two nos ends it. The refund is never denied. Ambiguity → treated as a defect. Show
  `decide()` order on the Policy page.
- **"Why not just let the LLM decide?"** Two identical returns, two outcomes = a lawsuit.
  Determinism is what lets us replay history (the dial) and reconstruct any refund from
  the log months later.
- **"Privacy of cross-merchant history?"** Hashed `customer_key`, per-merchant consent at
  onboarding, customer can see and delete their record. History sizes an offer and flags
  for review; it never denies.
- **"What does the customer actually hear?"** Play the A1077 call. They hear a choice.
- **"Where do the console numbers come from?"** "Illustrative, held consistent with
  the five orders in `data.py`. The live ones are the log and the eval."
- **"What if the voice fails on stage?"** Text fallback on the same backend. Already
  rehearsed.
- **"How do you make money?"** Share of margin saved, measured by the log. Slide 9.

## Appendix C — run of show (freeze 16:30)

| When | Who | What |
|---|---|---|
| now–13:30 | UI | Move `business.html` into `static/` so `/business.html` is served by `server.py`; fix the 40%/$87.20 seeds to match the engine. No other code. |
| now–13:30 | Adam | Engine fixes 2 and 3 (escalation order, fallback = full refund) with eval cases. Fix 3 removes the store-credit mismatch the console would expose. |
| now–13:30 | ElevenLabs | First live call end-to-end on A1077. Bind `system__conversation_id`. |
| 13:30 | all | Integration checkpoint: one voice call, log row appears on **Live** in `business.html`. |
| 13:30–15:30 | all | Five demo calls scripted and run twice each. Slides 5–8 walked against the real console. |
| 15:30 | all | Triage. Cut in order: interaction store → Nebius doc parse → two-decline demo. Never cut: voice, eval green, the tag. |
| 16:00 | Adam | Screenshot `eval.py`. Record backup video of the A1077 call with the console. |
| 16:30 | Adam | `git tag demo-frozen`. |
| 16:30–18:00 | all | Rehearse three times out loud in front of a stranger. Time it. Cut slides until it fits. |
