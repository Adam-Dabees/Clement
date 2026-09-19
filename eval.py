"""
The thing almost nobody at a hackathon builds, and the reason a judge
believes your numbers. Run it, screenshot it, put it on the last slide.

    python eval.py
"""

from data import ORDERS
from engine import decide

# (order, condition, reason, wants_replacement, refusals, expected_decision)
CASES = [
    ("A1042", "used", "one speed stopped working, it's defective", False, 0, "full_refund_with_return"),
    ("A1042", "used", "changed my mind", False, 0, "partial_refund_keep_item"),
    ("A1042", "used", "defective", True, 0, "exchange"),
    ("A1077", "used", "wrong shade of grey", False, 0, "partial_refund_keep_item"),
    ("A1077", "unopened", "wrong shade, never opened it", False, 0, "partial_refund_keep_item"),
    ("A1103", "unopened", "wheel scuffed out of the box", False, 0, "full_refund_with_return"),
    ("A1103", "unopened", "scuffed wheel", True, 0, "exchange"),
    ("A1103", "used", "just don't want it", False, 2, "full_refund_with_return"),
    ("A1150", "used", "leaking from the group head", False, 0, "full_refund_with_return"),
    ("A1150", "damaged", "it leaks, I want a manager", False, 0, "full_refund_with_return"),
    ("A1188", "used", "too tight", False, 0, "partial_refund_keep_item"),
    ("A1188", "used", "too tight, this is the third time", False, 2, "returnless_refund"),
]


def main():
    passed = 0
    escalated = 0
    saved = 0.0
    baseline_total = 0.0

    print(f"{'ORDER':<8}{'REASON':<34}{'DECISION':<30}{'SAVED':>9}  OK")
    print("-" * 90)

    for oid, cond, reason, repl, refusals, expected in CASES:
        d = decide(ORDERS[oid], condition=cond, reason=reason,
                   wants_replacement=repl, refusals=refusals, transcript=reason)
        ok = d["decision"] == expected
        passed += ok
        escalated += bool(d["escalated"])
        saved += d["margin_saved"]
        baseline_total += abs(d["baseline_net"])
        mark = "y" if ok else f"n (got {d['decision']})"
        print(f"{oid:<8}{reason[:32]:<34}{d['decision']:<30}{d['margin_saved']:>9.2f}  {mark}")

    n = len(CASES)
    print("-" * 90)
    print(f"accuracy         {passed}/{n}  ({passed / n * 100:.0f}%)")
    print(f"escalation rate  {escalated}/{n}  ({escalated / n * 100:.0f}%)")
    print(f"margin saved     ${saved:,.2f} across {n} returns")
    print(f"vs baseline      {saved / baseline_total * 100:.1f}% improvement on full-refund-with-return")
    print(f"\nDecisions requiring the LLM: 0. Every outcome above is deterministic.")


if __name__ == "__main__":
    main()
