"""
The thing almost nobody at a hackathon builds, and the reason a judge
believes your numbers. Run it, screenshot it, put it on the last slide.

    python eval.py

Every engine change ships with a case here. Cases run with classifier
labels ("labels on") and without them ("labels off", keyword fallback),
so the engine is proven on both paths in one run. No network, no model.
"""

from data import ORDERS
from engine import decide

FULL = "Full refund, return the item"
KEEP = "Full refund, keep the item"

# (order, condition, reason, wants_replacement, refusals, labels,
#  expected_decision, expected_reason_code, expected_fallback_label)
CASES = [
    # --- the original twelve ---
    ("A1042", "used", "one speed stopped working, it's defective", False, 0, None,
     "full_refund_with_return", "our_defect_resale_justifies_freight", None),
    ("A1042", "used", "changed my mind", False, 0, None,
     "partial_refund_keep_item", "preference_return_offer_choice", FULL),
    ("A1042", "used", "defective", True, 0, None,
     "exchange", "customer_asked_for_replacement", FULL),
    ("A1077", "used", "wrong shade of grey", False, 0, None,
     "partial_refund_keep_item", "preference_return_offer_choice", FULL),
    ("A1077", "unopened", "wrong shade, never opened it", False, 0, None,
     "partial_refund_keep_item", "preference_return_offer_choice", FULL),
    ("A1103", "unopened", "wheel scuffed out of the box", False, 0, None,
     "full_refund_with_return", "our_defect_resale_justifies_freight", None),
    ("A1103", "unopened", "scuffed wheel", True, 0, None,
     "exchange", "customer_asked_for_replacement", FULL),
    ("A1103", "used", "just don't want it", False, 2, None,
     "full_refund_with_return", "customer_declined_twice_honoring_refund", None),
    ("A1150", "used", "leaking from the group head", False, 0, None,
     "full_refund_with_return", "escalated_to_human", None),
    ("A1150", "damaged", "it leaks, I want a manager", False, 0, None,
     "full_refund_with_return", "escalated_to_human", None),
    ("A1188", "used", "too tight", False, 0, None,
     "partial_refund_keep_item", "preference_return_offer_choice", FULL),
    ("A1188", "used", "too tight, this is the third time", False, 2, None,
     "returnless_refund", "customer_declined_twice_honoring_refund", None),

    # --- fix 2: escalation beats the two-decline hand-over ---
    ("A1150", "used", "it leaks", False, 2, None,
     "full_refund_with_return", "escalated_to_human", None),

    # --- fix 5: one decline turns the named alternative into the offer ---
    ("A1077", "used", "wrong shade of grey", False, 1, None,
     "full_refund_with_return", "customer_declined_once_full_refund_offered", None),
    ("A1042", "used", "it's defective", False, 1, None,
     "full_refund_with_return", "our_defect_resale_justifies_freight", None),

    # --- fix 1: rule 6 no longer leaks through phrasing (keyword fallback) ---
    ("A1042", "used", "it doesn't work", False, 0, None,
     "full_refund_with_return", "our_defect_resale_justifies_freight", None),
    ("A1042", "used", "it won't turn on anymore", False, 0, None,
     "full_refund_with_return", "our_defect_resale_justifies_freight", None),

    # --- escalation keywords match whole words ---
    ("A1077", "used", "I personally think the grey is off, not what I wanted", False, 0, None,
     "partial_refund_keep_item", "preference_return_offer_choice", FULL),
    ("A1077", "used", "let me talk to a person please", False, 0, None,
     "full_refund_with_return", "escalated_to_human", None),
    ("A1042", "used", "it's broken", True, 3, None,
     "full_refund_with_return", "escalated_to_human", None),                     # transcript below carries "human"

    # --- fix 1b: negated mentions are not defects (keyword fallback) ---
    ("A1077", "used", "wrong shade of grey, I slept under it one night, it's not damaged", False, 0, None,
     "partial_refund_keep_item", "preference_return_offer_choice", FULL),
    ("A1042", "used", "nothing's broken, I just don't need two blenders", False, 0, None,
     "partial_refund_keep_item", "preference_return_offer_choice", FULL),
    ("A1042", "used", "it's not damaged but the motor is broken", False, 0, None,
     "full_refund_with_return", "our_defect_resale_justifies_freight", None),

    # --- fix 1: classifier labels first ---
    ("A1042", "used", "changed my mind", False, 0, {"is_defect": False, "confidence": 0.5},
     "full_refund_with_return", "our_defect_resale_justifies_freight", None),      # rule 7: unsure -> defect
    ("A1077", "used", "it's broken, honestly just not my colour", False, 0, {"is_defect": False, "confidence": 0.9},
     "partial_refund_keep_item", "preference_return_offer_choice", FULL),           # label beats keyword
    ("A1077", "used", "the seam is split", False, 0, {"is_defect": True, "confidence": 0.95},
     "returnless_refund", "our_defect_uneconomic_to_return", None),
    ("A1077", "used", "not the right grey", False, 0, {"requests_human": True, "confidence": 0.9},
     "full_refund_with_return", "escalated_to_human", None),
    ("A1077", "used", "not the right grey", False, 0,
     {"is_defect": False, "wants_replacement": True, "confidences": {"is_defect": 0.9, "wants_replacement": 0.3}},
     "partial_refund_keep_item", "preference_return_offer_choice", FULL),           # per-field trust

    # --- fix 8: non-delivery is representable ---
    ("A1077", "used", "it never arrived", False, 0, None,
     "returnless_refund", "not_delivered_full_refund", None),
    ("A1042", "used", "never arrived, can you send another", True, 0, None,
     "exchange", "not_delivered_replacement_sent", KEEP),
    ("A1103", "unopened", "tracking says delivered but there's nothing here", False, 0,
     {"item_status": "never_arrived", "is_defect": False, "confidence": 0.9},
     "returnless_refund", "not_delivered_full_refund", None),
]


def main():
    passed = 0
    escalated = 0
    saved = 0.0
    baseline_total = 0.0
    with_labels = sum(1 for c in CASES if c[5])

    print(f"{'ORDER':<8}{'REASON':<34}{'DECISION':<28}{'SAVED':>9}  OK")
    print("-" * 90)

    for oid, cond, reason, repl, refusals, labels, exp_dec, exp_rc, exp_fb in CASES:
        transcript = reason if refusals < 3 else reason + " I want to speak to a human now"
        d = decide(ORDERS[oid], condition=cond, reason=reason,
                   wants_replacement=repl, refusals=refusals, transcript=transcript,
                   labels=labels)
        problems = []
        if d["decision"] != exp_dec:
            problems.append(f"decision={d['decision']}")
        if d["reason_code"] != exp_rc:
            problems.append(f"reason={d['reason_code']}")
        if d["fallback"] != exp_fb:
            problems.append(f"fallback={d['fallback']!r}")
        if bool(d["escalated"]) != (exp_rc == "escalated_to_human"):
            problems.append(f"escalated={d['escalated']!r}")
        ok = not problems
        passed += ok
        escalated += bool(d["escalated"])
        saved += d["margin_saved"]
        baseline_total += abs(d["baseline_net"])
        mark = "y" if ok else "n (" + ", ".join(problems) + ")"
        tag = "*" if labels else " "
        print(f"{oid:<7}{tag}{reason[:32]:<34}{d['decision']:<28}{d['margin_saved']:>9.2f}  {mark}")

    n = len(CASES)
    print("-" * 90)
    print(f"accuracy         {passed}/{n}  ({passed / n * 100:.0f}%)")
    print(f"escalation rate  {escalated}/{n}  ({escalated / n * 100:.0f}%)")
    print(f"margin saved     ${saved:,.2f} across {n} returns")
    print(f"vs baseline      {saved / baseline_total * 100:.1f}% improvement on full-refund-with-return")
    print(f"labels on        {with_labels} cases (*)   labels off (keyword fallback)  {n - with_labels} cases")
    print(f"\nDecisions requiring the LLM: 0. Every outcome above is deterministic.")
    return passed == n


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
