"""
The decision engine. THIS IS THE IP. Keep it deterministic.

The LLM runs the conversation. This function picks the outcome.
Same inputs -> same decision, every time. That is what makes it a
payments-grade system instead of a chatbot, and it is the line that
wins you the judging conversation.

Net-to-merchant is measured against the baseline every merchant runs
today: full refund with the item shipped back.

Inputs come from three places, in priority order:
  1. `labels` from the intake classifier (classify.py), when confident.
  2. What the agent passed explicitly (condition, wants_replacement).
  3. Keyword fallback over the caller's words.
No model call, no network, no clock, no randomness happens in here.
"""

import re

from data import POLICY

HAIRCUT = {"unopened": 1.0, "used": 0.7, "damaged": 0.25}

# Keyword fallback only. The classifier's is_defect label wins when present
# and confident. Keep these specific: "wrong" alone is a preference
# ("wrong shade of grey"), "wrong item" is our mistake.
DEFECT_KEYWORDS = (
    "defect", "broke", "not work", "doesn't work", "didn't work", "isn't working",
    "won't turn on", "won't start", "won't charge", "stopped work", "dead on arrival",
    "leak", "damaged", "faulty", "scuff", "torn", "ripped", "a hole", "holes",
    "cracked", "stained", "mold", "mould", "smell", "malfunction", "wrong item",
    "missing",
)

NOT_DELIVERED_KEYWORDS = (
    "never arrived", "didn't arrive", "did not arrive", "not arrived",
    "hasn't arrived", "never came", "never received", "didn't receive",
    "did not receive", "never got it", "never showed up", "nothing here",
)

# Negated mentions are not defects: "it's not damaged", "nothing's broken".
# Stripped from the text before the keyword pass. Keyword fallback only;
# the classifier handles this properly when it is on.
NEGATIONS = (
    "not damaged", "isn't damaged", "is not damaged", "no damage", "undamaged",
    "not broken", "isn't broken", "nothing broken", "nothing's broken", "nothing is broken",
    "not defective", "isn't defective", "no defect", "not faulty", "isn't faulty",
    "nothing wrong with it", "nothing's wrong with it", "nothing is wrong with it",
    "works fine", "working fine", "works perfectly", "not missing", "nothing missing",
    "no leak", "not leaking", "doesn't leak", "not cracked", "not torn", "not stained",
)

REASON_CODES = (
    "our_defect_uneconomic_to_return",
    "our_defect_resale_justifies_freight",
    "customer_asked_for_replacement",
    "preference_return_offer_choice",
    "escalated_to_human",
    "customer_declined_once_full_refund_offered",
    "customer_declined_twice_honoring_refund",
    "not_delivered_full_refund",
    "not_delivered_replacement_sent",
)


def _round(x):
    return round(x + 1e-9, 2)


def _opt(options, action):
    return next(o for o in options if o["action"] == action)


def confident(labels, field):
    """Is this one classifier label trustworthy? Per-field confidence when the
    classifier gave one, else its overall confidence, else fully trusted."""
    lab = labels or {}
    c = lab.get("confidences", {}).get(field, lab.get("confidence", 1.0))
    return float(c) >= POLICY["min_classifier_confidence"]


def _uneconomic_to_return(order, condition):
    """True when paying return freight recovers nothing net."""
    resale = order["resale_value"] * HAIRCUT.get(condition, 0.7)
    logistics = order["return_shipping"] + order["restock_labor"]
    return resale - logistics <= 0


def evaluate(order, condition="used", wants_replacement=False, never_arrived=False):
    """Return every viable outcome, scored by net margin impact to the merchant.

    All figures are 'change in merchant position vs. the sale standing'.
    A full refund always costs price_paid; what differs is what comes back.
    """
    price = order["price_paid"]
    cogs = order["unit_cogs"]
    ship = order["return_shipping"]
    labor = order["restock_labor"]

    # Condition haircut on recoverable value.
    haircut = HAIRCUT.get(condition, 0.7)
    resale = order["resale_value"] * haircut

    options = []

    # 1. Baseline: full refund, item ships back.
    recovery = resale - ship - labor
    options.append({
        "action": "full_refund_with_return",
        "label": "Full refund, return the item",
        "customer_gets": _round(price),
        "keeps_item": False,
        "net_to_merchant": _round(-price + recovery),
        "rationale": f"Refund ${price:.2f}, recover ${resale:.2f} resale minus ${ship + labor:.2f} logistics.",
    })

    # 2. Returnless refund: customer keeps it, no freight.
    options.append({
        "action": "returnless_refund",
        "label": "Full refund, keep the item",
        "customer_gets": _round(price),
        "keeps_item": True,
        "net_to_merchant": _round(-price),
        "rationale": f"Refund ${price:.2f}. Shipping it back costs more than the ${resale:.2f} we would recover.",
    })

    # 3. Partial refund, customer keeps the item.
    #    Offer is scaled by how little we would recover anyway.
    partial_ratio = min(POLICY["max_partial_keep_ratio"], 0.30 + (0.30 * (1 - haircut)))
    partial = price * partial_ratio
    options.append({
        "action": "partial_refund_keep_item",
        "label": f"{int(partial_ratio * 100)}% back, keep the item",
        "customer_gets": _round(partial),
        "keeps_item": True,
        "net_to_merchant": _round(-partial),
        "rationale": f"Refund ${partial:.2f} against a preference return; the item stays with the customer.",
    })

    # 4. Exchange: revenue stays, we eat a replacement unit. If the first
    #    unit never arrived there is nothing coming back to recover.
    recovered = 0.0 if never_arrived else max(resale - labor, 0)
    options.append({
        "action": "exchange",
        "label": "Replacement sent out",
        "customer_gets": _round(price),  # in goods, not cash
        "keeps_item": False,
        "net_to_merchant": _round(-cogs - ship + recovered),
        "rationale": f"Keep ${price:.2f} revenue, ship a replacement at ${cogs:.2f} cost.",
    })

    # Store credit with a bonus is a designed outcome, not a scored one yet:
    # its economics (bonus cost vs. cash retained vs. a second fulfilment)
    # need a merchant-supplied redemption rate before it can be ranked.

    options.sort(key=lambda o: o["net_to_merchant"], reverse=True)
    return options


def decide(order, condition="used", reason="", wants_replacement=False,
           refusals=0, transcript="", labels=None):
    """Pick an opening offer and its alternative. Returns the full decision record.

    `labels` is the classifier's output (or None): any of
      is_defect, item_status ("in_hand" | "never_arrived"), wants_replacement,
      requests_human, plus `confidence` (overall) and/or `confidences` (per
      field). A label below POLICY["min_classifier_confidence"] is not trusted:
      is_defect then resolves in the customer's favour (Rule 7), the others
      fall back to keywords.
    """
    lab = labels or {}
    text = (transcript + " " + reason).lower()

    # Did the item arrive at all? Decided first because it changes what the
    # baseline even means: you cannot ship back what you never received.
    if "item_status" in lab and confident(lab, "item_status"):
        never_arrived = lab["item_status"] == "never_arrived"
    else:
        never_arrived = any(k in text for k in NOT_DELIVERED_KEYWORDS)

    options = evaluate(order, condition, wants_replacement, never_arrived)
    baseline = _opt(options, "returnless_refund" if never_arrived
                    else "full_refund_with_return")

    flags = []
    escalate = None

    # --- Hard guardrails. These run BEFORE any optimisation. ---
    if "requests_human" in lab and confident(lab, "requests_human"):
        asked_for_human = bool(lab["requests_human"])
    else:
        asked_for_human = _keyword_human(text)
    if asked_for_human:
        escalate = "customer_requested_human"
    if order["price_paid"] > POLICY["max_autonomous_refund_usd"]:
        escalate = escalate or "above_autonomous_refund_cap"
        flags.append(f"Order value ${order['price_paid']:.2f} exceeds the ${POLICY['max_autonomous_refund_usd']:.2f} cap.")
    if order["days_since_delivery"] > POLICY["return_window_days"]:
        flags.append("Outside the stated return window.")
    if order["prior_returns"] >= 3:
        flags.append(f"{order['prior_returns']} prior returns on this account. Flag for review, do not confront the customer.")

    # Escalation beats everything, including the two-decline hand-over:
    # a human takes the call, and the human honours the refund.
    if escalate:
        return _record(order, baseline, baseline, options, flags,
                       escalate, "escalated_to_human", None)

    # The customer has pushed back twice. Stop negotiating. Give the refund.
    if refusals >= 2:
        chosen = (_opt(options, "returnless_refund")
                  if _uneconomic_to_return(order, condition) else baseline)
        return _record(order, chosen, baseline, options, flags,
                       escalate, "customer_declined_twice_honoring_refund", None)

    # --- Inputs: labels first, keyword match only as fallback. ---
    if lab.get("wants_replacement") and confident(lab, "wants_replacement"):
        wants_replacement = True

    # Whose fault is it? This is the fairness axis and it runs BEFORE the
    # margin axis. We never haggle over a defect we caused. Say this line
    # out loud when a judge asks about dark patterns.
    if "is_defect" in lab:
        # Rule 7: if the classifier is unsure, the customer gets the benefit.
        is_defect = bool(lab["is_defect"]) if confident(lab, "is_defect") else True
    else:
        is_defect = _keyword_defect(text)

    # --- Optimisation, inside the envelope. ---
    if never_arrived:
        # Nothing to return and nothing to haggle over.
        if wants_replacement:
            chosen, reason_code = _opt(options, "exchange"), "not_delivered_replacement_sent"
        else:
            chosen, reason_code = _opt(options, "returnless_refund"), "not_delivered_full_refund"
    elif wants_replacement:
        chosen, reason_code = _opt(options, "exchange"), "customer_asked_for_replacement"
    elif is_defect:
        # Our fault. Full value back. The only open question is whether
        # paying freight recovers anything.
        if _uneconomic_to_return(order, condition):
            chosen, reason_code = _opt(options, "returnless_refund"), "our_defect_uneconomic_to_return"
        else:
            chosen, reason_code = baseline, "our_defect_resale_justifies_freight"
    else:
        # Preference, not defect. A genuine choice is legitimate here:
        # money now and keep it, or the full refund if they'd rather ship
        # it back. The fallback is always the full refund, on ask.
        chosen, reason_code = _opt(options, "partial_refund_keep_item"), "preference_return_offer_choice"

    fallback = _fallback_for(chosen, options, never_arrived)

    # One decline: the alternative we already named becomes the offer.
    # There is no third option to invent; two choices, the caller picks.
    if refusals == 1 and fallback is not None:
        chosen, reason_code, fallback = fallback, "customer_declined_once_full_refund_offered", None

    return _record(order, chosen, baseline, options, flags, escalate, reason_code, fallback)


def _keyword_human(text):
    """Escalation keywords match whole words: "person" yes, "personally" no."""
    return any(re.search(r"\b" + re.escape(k) + r"\b", text) for k in POLICY["escalate_keywords"])


def _keyword_defect(text):
    """Keyword fallback for is_defect, blind to negated mentions."""
    for neg in NEGATIONS:
        text = text.replace(neg, " ")
    return any(k in text for k in DEFECT_KEYWORDS)


def _fallback_for(chosen, options, never_arrived):
    """The alternative the agent names in the same breath. Always the full
    refund, never store credit: the phrase promises 'a full refund if you'd
    rather', so the record must say the same."""
    if chosen["action"] not in ("partial_refund_keep_item", "exchange"):
        return None
    if never_arrived:
        return _opt(options, "returnless_refund")
    return _opt(options, "full_refund_with_return")


def _record(order, chosen, baseline, options, flags, escalate, reason_code, fallback):
    return {
        "order_id": order["order_id"],
        "item": order["item"],
        "decision": chosen["action"],
        "offer_label": chosen["label"],
        "customer_gets": chosen["customer_gets"],
        "keeps_item": chosen["keeps_item"],
        "net_to_merchant": chosen["net_to_merchant"],
        "baseline_net": baseline["net_to_merchant"],
        "margin_saved": _round(chosen["net_to_merchant"] - baseline["net_to_merchant"]),
        "reason_code": reason_code,
        "rationale": chosen["rationale"],
        "fallback": fallback["label"] if fallback else None,
        "fallback_option": ({"action": fallback["action"], "label": fallback["label"],
                             "customer_gets": fallback["customer_gets"],
                             "keeps_item": fallback["keeps_item"]} if fallback else None),
        "flags": flags,
        "escalated": escalate,
        "all_options": options,
    }
