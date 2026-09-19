"""
FastAPI backend. Three jobs:
  1. Expose tools the ElevenLabs agent calls mid-conversation (webhook tools).
  2. Run the deterministic decision engine.
  3. Log every call so the dashboard can show margin saved.

Run:  uvicorn server:app --reload --port 8000
Tunnel: cloudflared tunnel --url http://localhost:8000
"""

import os
import json
import time
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from data import ORDERS, POLICY
from engine import decide

app = FastAPI(title="Clement")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

CALL_LOG = []          # in-memory. A database is not a demo feature.
SESSIONS = {}          # conversation_id -> {"refusals": int}


# ---------------------------------------------------------------- tools

class LookupReq(BaseModel):
    order_id: str


@app.post("/tool/lookup_order")
def lookup_order(req: LookupReq):
    """Agent calls this first. Returns ONLY what the agent should say out loud.
    Cost basis and resale value never reach the model."""
    o = ORDERS.get(req.order_id.strip().upper())
    if not o:
        return {"found": False, "message": "No order with that number. Ask them to read it again."}
    return {
        "found": True,
        "customer_name": o["customer_name"],
        "item": o["item"],
        "price_paid": o["price_paid"],
        "days_since_delivery": o["days_since_delivery"],
        "within_window": o["days_since_delivery"] <= POLICY["return_window_days"],
    }


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
    The engine, not the model, picks the outcome."""
    o = ORDERS.get(req.order_id.strip().upper())
    if not o:
        return {"error": "unknown_order"}

    sess = SESSIONS.setdefault(req.conversation_id, {"refusals": 0})
    d = decide(
        o,
        condition=req.condition,
        reason=req.reason,
        wants_replacement=req.wants_replacement,
        refusals=sess["refusals"],
        transcript=req.transcript,
    )

    d["_t"] = time.time()
    d["_when"] = datetime.now().strftime("%H:%M:%S")
    d["conversation_id"] = req.conversation_id
    d["reason"] = req.reason
    CALL_LOG.append(d)

    # What the agent is allowed to say. Cost figures stripped out.
    return {
        "offer": d["offer_label"],
        "customer_gets": d["customer_gets"],
        "say": _phrase(d),
        "fallback_offer": d["fallback"],
        "escalated": bool(d["escalated"]),
        "escalation_reason": d["escalated"],
    }


class RefuseReq(BaseModel):
    conversation_id: str = "demo"


@app.post("/tool/customer_declined")
def customer_declined(req: RefuseReq):
    """Agent calls this when the customer turns an offer down.
    Two declines and the refund is theirs. This is the guardrail, and
    you should demo it on purpose."""
    sess = SESSIONS.setdefault(req.conversation_id, {"refusals": 0})
    sess["refusals"] += 1
    if sess["refusals"] >= 2:
        return {"stop_negotiating": True,
                "say": "Understood. I'm processing the full refund now, no return needed."}
    return {"stop_negotiating": False,
            "say": "That's fair. Let me see what else I can do."}


def _phrase(d):
    a = d["decision"]
    if d["escalated"]:
        return "I'm connecting you with a specialist right now. One moment."
    if a == "returnless_refund":
        return (f"I can refund the full ${d['customer_gets']:.2f} today, and you don't need to "
                f"ship anything back. Keep it or pass it on.")
    if a == "partial_refund_keep_item":
        return (f"Shipping it back is a hassle for you. I can put ${d['customer_gets']:.2f} back "
                f"on your card today and you keep the item. Or a full refund if you'd rather return it.")
    if a == "exchange":
        return "I'll send a replacement out today with a prepaid label for the original."
    if a == "store_credit_bonus":
        return (f"I can do the full refund, or ${d['customer_gets']:.2f} in store credit, "
                f"which is more than you paid. Your call.")
    return f"I'll refund the full ${d['customer_gets']:.2f} once it's back with us. Label's on its way."


# ---------------------------------------------------------------- dashboard

@app.get("/api/log")
def get_log():
    saved = sum(c["margin_saved"] for c in CALL_LOG)
    retained = sum(1 for c in CALL_LOG if c["decision"] in
                   ("exchange", "store_credit_bonus", "partial_refund_keep_item"))
    return {
        "calls": [
            {k: v for k, v in c.items() if k != "all_options"} for c in reversed(CALL_LOG)
        ],
        "total_calls": len(CALL_LOG),
        "margin_saved": round(saved, 2),
        "retention_rate": round(retained / len(CALL_LOG) * 100, 1) if CALL_LOG else 0.0,
        "escalations": sum(1 for c in CALL_LOG if c["escalated"]),
    }


@app.post("/api/reset")
def reset():
    CALL_LOG.clear()
    SESSIONS.clear()
    return {"ok": True}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
