"""
FastAPI backend. Three jobs:
  1. Expose the tools the ElevenLabs agent calls mid-conversation (webhooks).
  2. Run intake classification, then the deterministic decision engine.
  3. Log every decision so the consoles can show margin saved.

Run:    uvicorn server:app --reload --port 8000
Tunnel: ./tunnel.sh          (cloudflared + setup_agent.py, see README)

Rule 2 lives here: nothing with a cost basis leaves a /tool/* response.
Tool responses are built from an allowlist and checked again by _safe().
"""

import os
import time
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from data import ORDERS, POLICY          # noqa: E402
from engine import decide, confident     # noqa: E402
from classify import classify            # noqa: E402

app = FastAPI(title="Clement")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

CALL_LOG = []   # one row per conversation; the latest decision for a call wins
SESSIONS = {}   # conversation_id -> {"refusals": int, "last": inputs | None, "declines": [...]}

# Never in a tool response. _safe() raises if one slips through.
COST_FIELDS = {
    "unit_cogs", "resale_value", "restock_labor", "net_to_merchant", "margin_saved",
    "baseline_net", "all_options", "flags", "fallback_option", "rationale",
    "customer_ltv", "prior_returns",
}
MUST_NOT_SAY = ["cost", "margin", "resale", "policy", "engine"]

CONDITIONS = ("unopened", "used", "damaged")


# ---------------------------------------------------------------- helpers

def _safe(resp):
    """Belt and braces for Rule 2: refuse to return a cost field to the model."""
    def walk(x):
        if isinstance(x, dict):
            bad = COST_FIELDS & set(x)
            if bad:
                raise RuntimeError(f"cost field in tool response: {sorted(bad)}")
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(resp)
    return resp


def _norm_condition(c):
    c = (c or "").strip().lower()
    if c in CONDITIONS:
        return c
    if any(w in c for w in ("new", "unused", "sealed", "unopened", "never opened")):
        return "unopened"
    if any(w in c for w in ("broke", "damage", "crack", "torn")):
        return "damaged"
    return "used"


def _order_ctx(o):
    """What the classifier may see. No name, no cost basis."""
    return {"item": o["item"], "category": o["category"], "price_paid": o["price_paid"],
            "days_since_delivery": o["days_since_delivery"]}


def _session(cid):
    return SESSIONS.setdefault(cid, {"refusals": 0, "last": None, "declines": []})


def _run(o, sess, inputs):
    """Classifier (if any) -> engine -> log. Returns the engine record."""
    d = decide(o, refusals=sess["refusals"], **inputs)
    _log(d, sess, inputs)
    return d


def _log(d, sess, inputs):
    row = dict(d)
    row.update({
        "_t": time.time(),
        "_when": datetime.now().strftime("%H:%M:%S"),
        "conversation_id": sess["cid"],
        "reason": inputs["reason"],
        "condition": inputs["condition"],
        "refusals": sess["refusals"],
        "classifier": inputs["labels"],
        "classifier_fallback": inputs["labels"] is None,
    })
    for i, r in enumerate(CALL_LOG):
        if r["conversation_id"] == sess["cid"]:
            row["_t"] = r["_t"]          # keep the call's original position
            CALL_LOG[i] = row
            return
    CALL_LOG.append(row)


FAULT = {
    "our_defect_uneconomic_to_return": "merchant_defect",
    "our_defect_resale_justifies_freight": "merchant_defect",
    "customer_asked_for_replacement": "replacement_requested",
    "preference_return_offer_choice": "customer_preference",
    "customer_declined_once_full_refund_offered": "customer_preference",
    "customer_declined_twice_honoring_refund": "customer_preference",
    "escalated_to_human": "escalated",
    "not_delivered_full_refund": "not_delivered",
    "not_delivered_replacement_sent": "not_delivered",
}


def _next_step(d):
    if d["escalated"]:
        return "handoff"
    if d["reason_code"] == "customer_declined_twice_honoring_refund":
        return "close_with_refund"
    return "present_offer"


def _phrase(d):
    """A ready-made sentence. The prompt tells the model to say it in its own
    voice, but every number in it came from the engine."""
    a, rc, amt = d["decision"], d["reason_code"], d["customer_gets"]
    if d["escalated"]:
        return "I'm connecting you with a specialist right now. One moment."
    if a == "returnless_refund":
        if rc.startswith("not_delivered"):
            return (f"I'm sorry it never made it to you. I'm refunding the full ${amt:.2f} today; "
                    f"there's nothing you need to do.")
        return (f"I can refund the full ${amt:.2f} today, and you don't need to "
                f"ship anything back. Keep it or pass it on.")
    if a == "partial_refund_keep_item":
        return (f"Shipping it back is a hassle for you. I can put ${amt:.2f} back "
                f"on your card today and you keep the item. Or a full refund if you'd rather return it.")
    if a == "exchange":
        if rc.startswith("not_delivered"):
            return "I'm sending a replacement out today. Nothing for you to return."
        return "I'll send a replacement out today with a prepaid label for the original."
    if rc == "customer_declined_once_full_refund_offered":
        return f"The full ${amt:.2f} refund is yours once the item is back with us. I'll send the label now."
    return f"I'll refund the full ${amt:.2f} once it's back with us. Label's on its way."


def _tool_response(o, d):
    """The planned shape from ELEVENLABS.md §6.2: facts for the model to
    voice, plus `say` and the older keys the text fallback still reads."""
    fb = d["fallback_option"]
    must_say = [f"the ${d['customer_gets']:.2f} amount"]
    if fb:
        must_say.append("that a full refund is available instead" if fb["keeps_item"]
                        else "that a full refund is available if they would rather return it")
    return _safe({
        "outcome": d["decision"],
        "amount": d["customer_gets"],
        "keeps_item": d["keeps_item"],
        "alternative": ({"outcome": fb["action"], "amount": fb["customer_gets"],
                         "keeps_item": fb["keeps_item"]} if fb else None),
        "customer_chooses": fb is not None,
        "context": {"first_name": o["customer_name"].split()[0], "item": o["item"],
                    "fault": FAULT.get(d["reason_code"], "customer_preference")},
        "must_say": must_say,
        "must_not_say": MUST_NOT_SAY,
        "escalated": bool(d["escalated"]),
        "escalation_reason": d["escalated"],
        "next_step": _next_step(d),
        "say": _phrase(d),
        # kept for the text fallback and older prompts
        "offer": d["offer_label"],
        "customer_gets": d["customer_gets"],
        "fallback_offer": d["fallback"],
    })


# ---------------------------------------------------------------- tools

class LookupReq(BaseModel):
    order_id: str


@app.post("/tool/lookup_order")
def lookup_order(req: LookupReq):
    """Agent calls this first. Returns ONLY what the agent should say out loud.
    Cost basis and resale value never reach the model."""
    o = ORDERS.get(req.order_id.strip().upper().replace(" ", ""))
    if not o:
        return {"found": False, "next_step": "ask_order_number",
                "message": "No order with that number. Ask them to read it again."}
    return _safe({
        "found": True,
        "customer_name": o["customer_name"],
        "first_name": o["customer_name"].split()[0],
        "item": o["item"],
        "price_paid": o["price_paid"],
        "days_since_delivery": o["days_since_delivery"],
        "within_window": o["days_since_delivery"] <= POLICY["return_window_days"],
        "next_step": "ask_what_went_wrong",
    })


class DecideReq(BaseModel):
    order_id: str
    reason: str = ""
    condition: str = "used"           # unopened | used | damaged
    wants_replacement: bool = False
    conversation_id: str = "demo"
    transcript: str = ""


@app.post("/tool/decide_return")
def decide_return(req: DecideReq):
    """The agent calls this once it knows why the customer is returning.
    The classifier labels the words; the engine, not the model, picks the outcome."""
    o = ORDERS.get(req.order_id.strip().upper().replace(" ", ""))
    if not o:
        return {"error": "unknown_order", "next_step": "ask_order_number",
                "say": "I couldn't find that order number. Could you read it to me again?"}

    sess = _session(req.conversation_id)
    sess["cid"] = req.conversation_id

    condition = _norm_condition(req.condition)
    labels = classify(req.reason, req.transcript, _order_ctx(o))   # None on any failure, <= 2.5 s
    if labels and labels.get("condition") in CONDITIONS and confident(labels, "condition"):
        condition = labels["condition"]

    inputs = {
        "condition": condition,
        "reason": req.reason,
        "wants_replacement": req.wants_replacement,
        "transcript": req.transcript,
        "labels": labels,
    }
    sess["last"] = {"order_id": o["order_id"], **inputs}
    d = _run(o, sess, inputs)
    return _tool_response(o, d)


class RefuseReq(BaseModel):
    conversation_id: str = "demo"
    customer_response: str = ""       # their words, for the interaction store
    sentiment: str = ""               # agent-perceived tone


@app.post("/tool/customer_declined")
def customer_declined(req: RefuseReq):
    """Agent calls this when the customer turns an offer down.
    Two declines and the refund is theirs. This is the guardrail, and
    you should demo it on purpose. The phrase comes from the engine, so it
    says 'no return needed' only when the engine chose returnless."""
    sess = _session(req.conversation_id)
    sess["cid"] = req.conversation_id
    sess["refusals"] += 1
    sess["declines"].append({"n": sess["refusals"], "said": req.customer_response,
                             "sentiment": req.sentiment, "_t": time.time()})
    closing = sess["refusals"] >= 2

    last = sess["last"]
    if last is None:
        # Declined before anything was decided. Nothing to re-run.
        return {"stop_negotiating": closing,
                "next_step": "close_with_refund" if closing else "present_alternative",
                "say": ("Understood. I'm processing the full refund now." if closing
                        else "That's fair. Let me see what else I can do.")}

    o = ORDERS[last["order_id"]]
    inputs = {k: last[k] for k in ("condition", "reason", "wants_replacement", "transcript", "labels")}
    d = _run(o, sess, inputs)
    say = _phrase(d) if (closing or d["escalated"]) else "That's fair. " + _phrase(d)
    return _safe({
        "stop_negotiating": closing or bool(d["escalated"]),
        "next_step": _next_step(d) if (closing or d["escalated"]) else "present_alternative",
        "say": say,
        "outcome": d["decision"],
        "amount": d["customer_gets"],
        "keeps_item": d["keeps_item"],
        "escalated": bool(d["escalated"]),
        "escalation_reason": d["escalated"],
    })


# ---------------------------------------------------------------- dashboard

@app.get("/api/log")
def get_log():
    saved = sum(c["margin_saved"] for c in CALL_LOG)
    retained = sum(1 for c in CALL_LOG if c["decision"] in ("exchange", "partial_refund_keep_item"))
    return {
        "calls": [
            {k: v for k, v in c.items() if k != "all_options"}
            for c in sorted(CALL_LOG, key=lambda c: c["_t"], reverse=True)
        ],
        "total_calls": len(CALL_LOG),
        "margin_saved": round(saved, 2),
        "retention_rate": round(retained / len(CALL_LOG) * 100, 1) if CALL_LOG else 0.0,
        "escalations": sum(1 for c in CALL_LOG if c["escalated"]),
    }


@app.get("/api/agent")
def get_agent():
    """The voice widget mounts itself from this; no HTML edit per agent."""
    return {"agent_id": os.environ.get("ELEVENLABS_AGENT_ID") or None}


@app.get("/api/health")
def health():
    return {"ok": True,
            "classifier": bool(os.environ.get("NEBIUS_API_KEY")),
            "agent": bool(os.environ.get("ELEVENLABS_AGENT_ID")),
            "calls": len(CALL_LOG)}


@app.post("/api/reset")
def reset():
    CALL_LOG.clear()
    SESSIONS.clear()
    return {"ok": True}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
