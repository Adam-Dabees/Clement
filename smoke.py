"""
Scripted call sequences against a running server. Proves the wiring the
voice agent depends on, with no ElevenLabs and no Nebius in the loop.

    uvicorn server:app --port 8010
    python smoke.py --port 8010

Asserts, for each of the five demo orders plus non-delivery and a bad
order number: the outcome, next_step, the two-decline hand-over, one log
row per conversation, and Rule 2 (no cost field in any tool response).
"""

import argparse
import sys
import uuid

import requests

COST_FIELDS = {"unit_cogs", "resale_value", "restock_labor", "net_to_merchant", "margin_saved",
               "baseline_net", "all_options", "flags", "fallback_option", "rationale",
               "customer_ltv", "prior_returns"}
BANNED_WORDS = ("resale", "margin", "cost basis", "cogs")

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("   FAIL", msg)


def rule2(resp, where):
    def walk(x):
        if isinstance(x, dict):
            leak = COST_FIELDS & set(x)
            check(not leak, f"{where}: cost field leaked {sorted(leak)}")
            for k, v in x.items():
                if k != "must_not_say":       # the list of words the model must avoid, by design
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for w in BANNED_WORDS:
                check(w not in x.lower(), f"{where}: banned word {w!r} in {x!r}")
    walk(resp)


class Client:
    def __init__(self, base):
        self.base = base

    def post(self, path, **body):
        r = requests.post(self.base + path, json=body, timeout=5)
        check(r.status_code == 200, f"{path} -> HTTP {r.status_code}: {r.text[:200]}")
        j = r.json()
        rule2(j, path)
        return j

    def log(self):
        return requests.get(self.base + "/api/log", timeout=5).json()


def cid():
    return "smoke-" + uuid.uuid4().hex[:8]


def main(base):
    c = Client(base)
    c.post("/api/reset")
    n_expected_rows = 0

    print("1. A1077 duvet, wrong shade: partial keep-it, full refund alternative")
    k = cid()
    lo = c.post("/tool/lookup_order", order_id="a1077")
    check(lo["found"] and lo["first_name"] == "Marcus", "lookup A1077")
    d = c.post("/tool/decide_return", order_id="A1077", reason="wrong shade of grey", condition="used",
               conversation_id=k, transcript="it's just the wrong grey, I opened it")
    check(d["outcome"] == "partial_refund_keep_item" and d["amount"] == 85.02, f"A1077 outcome {d['outcome']} {d['amount']}")
    check(d["alternative"] == {"outcome": "full_refund_with_return", "amount": 218.0, "keeps_item": False}, f"A1077 alt {d['alternative']}")
    check(d["next_step"] == "present_offer" and d["customer_chooses"], "A1077 next_step")
    check("85.02" in d["say"] and "full refund" in d["say"], "A1077 say")
    n_expected_rows += 1

    print("2. A1042 blender, defect: full refund with return, no haggling")
    k = cid()
    d = c.post("/tool/decide_return", order_id="A1042", reason="one speed stopped working", condition="used",
               conversation_id=k, transcript="one of the speeds just stopped working")
    check(d["outcome"] == "full_refund_with_return" and d["amount"] == 129.0, f"A1042 outcome {d['outcome']}")
    check(d["alternative"] is None and not d["customer_chooses"], "A1042 no alternative")
    check(d["context"]["fault"] == "merchant_defect", "A1042 fault")
    n_expected_rows += 1

    print("3. A1188 socks: offer, decline, alternative, decline, refund without return")
    k = cid()
    d = c.post("/tool/decide_return", order_id="A1188", reason="too tight", condition="used",
               conversation_id=k, transcript="they're too tight")
    check(d["outcome"] == "partial_refund_keep_item", "A1188 opening")
    r1 = c.post("/tool/customer_declined", conversation_id=k, customer_response="no I want all of it", sentiment="calm")
    check(not r1["stop_negotiating"] and r1["next_step"] == "present_alternative", f"A1188 decline 1 {r1}")
    check(r1["outcome"] == "full_refund_with_return" and "34.00" in r1["say"], f"A1188 decline 1 say {r1['say']}")
    r2 = c.post("/tool/customer_declined", conversation_id=k, customer_response="I'm not shipping anything", sentiment="frustrated")
    check(r2["stop_negotiating"] and r2["next_step"] == "close_with_refund", f"A1188 decline 2 {r2}")
    check(r2["outcome"] == "returnless_refund" and "ship anything back" in r2["say"], f"A1188 decline 2 say {r2['say']}")
    row = next(x for x in c.log()["calls"] if x["conversation_id"] == k)
    check(row["reason_code"] == "customer_declined_twice_honoring_refund" and row["margin_saved"] == 11.5,
          f"A1188 final row {row['reason_code']} {row['margin_saved']}")
    n_expected_rows += 1

    print("4. A1103 carry-on, wants replacement: exchange with full refund alternative")
    k = cid()
    d = c.post("/tool/decide_return", order_id="A1103", reason="wheel scuffed out of the box", condition="unopened",
               wants_replacement=True, conversation_id=k, transcript="wheel is scuffed, can I get a replacement")
    check(d["outcome"] == "exchange" and d["alternative"]["amount"] == 349.0, f"A1103 {d['outcome']} {d['alternative']}")
    n_expected_rows += 1

    print("5. A1150 espresso, over the cap: handoff, and still handoff after two declines")
    k = cid()
    d = c.post("/tool/decide_return", order_id="A1150", reason="leaking from the group head", condition="used",
               conversation_id=k, transcript="it's leaking")
    check(d["escalated"] and d["next_step"] == "handoff" and d["escalation_reason"] == "above_autonomous_refund_cap", f"A1150 {d}")
    c.post("/tool/customer_declined", conversation_id=k)
    r2 = c.post("/tool/customer_declined", conversation_id=k)
    check(r2["escalated"] and r2["next_step"] == "handoff" and "specialist" in r2["say"], f"A1150 after declines {r2}")
    n_expected_rows += 1

    print("6. A1103 two declines on a high-resale item: full refund, WITH return (phrase agrees)")
    k = cid()
    c.post("/tool/decide_return", order_id="A1103", reason="just don't want it", condition="used", conversation_id=k)
    c.post("/tool/customer_declined", conversation_id=k)
    r2 = c.post("/tool/customer_declined", conversation_id=k)
    check(r2["outcome"] == "full_refund_with_return" and "back with us" in r2["say"], f"A1103 declines {r2}")
    n_expected_rows += 1

    print("7. A1077 never arrived: full refund, nothing to return")
    k = cid()
    d = c.post("/tool/decide_return", order_id="A1077", reason="it never arrived", condition="used",
               conversation_id=k, transcript="it never arrived, tracking says delivered")
    check(d["outcome"] == "returnless_refund" and d["context"]["fault"] == "not_delivered", f"never arrived {d}")
    check("never made it" in d["say"], f"never arrived say {d['say']}")
    n_expected_rows += 1

    print("8. Unknown order and stray condition strings never 422")
    d = c.post("/tool/decide_return", order_id="Z9999", reason="x", condition="brand new")
    check(d.get("error") == "unknown_order" and d["next_step"] == "ask_order_number", f"unknown {d}")
    lo = c.post("/tool/lookup_order", order_id="zz")
    check(lo["found"] is False, "lookup unknown")
    k = cid()
    d = c.post("/tool/decide_return", order_id="A1077", reason="wrong shade", condition="Brand New", conversation_id=k)
    check(d["outcome"] == "partial_refund_keep_item" and d["amount"] == 65.4, f"condition normalised {d['amount']}")
    n_expected_rows += 1

    print("9. Log: one row per conversation, totals add up")
    lg = c.log()
    check(lg["total_calls"] == n_expected_rows, f"rows {lg['total_calls']} != {n_expected_rows}")
    check(len({x["conversation_id"] for x in lg["calls"]}) == lg["total_calls"], "duplicate conversation rows")
    check(lg["escalations"] == 1, f"escalations {lg['escalations']}")
    check(abs(lg["margin_saved"] - sum(x["margin_saved"] for x in lg["calls"])) < 0.01, "margin sum")
    check(all("classifier_fallback" in x for x in lg["calls"]), "classifier field on rows")

    print()
    if failures:
        print(f"{len(failures)} FAILED")
        return 1
    print(f"all sequences passed; {n_expected_rows} conversations, zero cost fields in tool responses")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--base", default=None)
    a = ap.parse_args()
    sys.exit(main(a.base or f"http://localhost:{a.port}"))
