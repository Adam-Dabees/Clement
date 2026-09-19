"""
Intake classifier on Nebius (Token Factory, formerly AI Studio).

Turns a rambling spoken complaint into structured labels for the engine.
It never decides an outcome. It degrades to None on anything: no key,
timeout, bad JSON, missing field. The engine then runs on keywords.

    export NEBIUS_API_KEY=...
    python classify.py "one speed stopped working and I want a manager"

Env: NEBIUS_API_KEY, NEBIUS_BASE_URL (default Token Factory),
     NEBIUS_MODEL (default openai/gpt-oss-120b), CLASSIFY_TIMEOUT_S (2.5),
     CLASSIFY_MAX_TOKENS (400; gpt-oss reasoning counts against it).
"""

import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
# Llama 3.1 8B was retired from Nebius (2026-09). Measured 2026-09-19, sequential:
#   openai/gpt-oss-120b            ~0.8 s, valid JSON, correct labels  <- default
#   Qwen/Qwen3-30B-A3B-Instruct    ~1.8 s median, 2.5 s+ under load
#   gemma-3-27b                    ~1.6 s but meaningless confidences
# gpt-oss keeps its reasoning in a separate field that still counts against
# max_tokens, so the budget must stay well above the JSON itself.
# Requests on one key queue: never run two classifier calls concurrently.
MODEL = os.environ.get("NEBIUS_MODEL", "openai/gpt-oss-120b")
MAX_TOKENS = int(os.environ.get("CLASSIFY_MAX_TOKENS", "400"))
# "low" halves gpt-oss latency (0.7 s median vs 1.0 s) with identical labels.
REASONING_EFFORT = os.environ.get("CLASSIFY_REASONING_EFFORT", "low")
TIMEOUT_S = float(os.environ.get("CLASSIFY_TIMEOUT_S", "2.5"))

RETURN_TYPES = ("defect", "changed_mind", "wrong_item", "not_delivered", "other")
ITEM_STATUS = ("in_hand", "never_arrived")
CONDITIONS = ("unopened", "used", "damaged")      # "unknown" maps to None: no override
DEFECT_TYPES = {"defect", "wrong_item"}     # merchant's fault either way

SYSTEM = """You label one spoken product-return complaint for an online store's returns line.
Reply with exactly one JSON object and nothing else:
{"return_type": "defect" | "changed_mind" | "wrong_item" | "not_delivered" | "other",
 "item_status": "in_hand" | "never_arrived",
 "condition": "unopened" | "used" | "damaged" | "unknown",
 "wants_replacement": true | false,
 "requests_human": true | false,
 "confidence": {"return_type": 0.0-1.0, "item_status": 0.0-1.0, "condition": 0.0-1.0,
                "wants_replacement": 0.0-1.0, "requests_human": 0.0-1.0}}

Definitions:
- defect: the product is faulty, broken, damaged on arrival, leaking, missing parts, or otherwise
  not working as sold. Merchant's fault.
- wrong_item: the store shipped a different product than ordered. Merchant's fault.
- changed_mind: the product works as sold but the customer does not want it: wrong colour or shade
  for their room, wrong size or fit, no longer needed, did not like it. Customer preference.
  "Wrong shade of grey" or "too tight" is changed_mind, not defect.
- not_delivered: the package never arrived. item_status is then never_arrived.
- condition: ONLY from what they actually said. unopened if they say it is sealed, unopened, never used;
  damaged ONLY for visible physical damage to the item itself (cracked, torn, dented, ripped, stained,
  scuffed, leaking from a crack). A part that does not work, a dead button, a motor that stopped, is a
  defect with condition "used" if they have used it, otherwise "unknown"; it is not "damaged".
  used if they say they used, wore, washed or slept on it. "It's broken" alone says nothing about
  visible damage or use: condition "unknown".
  If the words say nothing about whether it was opened or used, condition is "unknown". Never guess:
  "I don't like it" or "wrong colour" alone is unknown.
- wants_replacement: true only if they ask for the same item again (replacement, exchange, another one).
- requests_human: true only if they ask for a person, manager, supervisor, or threaten legal action.
Give low confidence (below 0.6) whenever the words genuinely support more than one label."""

_client = None


def _get_client():
    global _client
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        return None
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url=BASE_URL, api_key=key, timeout=TIMEOUT_S, max_retries=0)
    return _client


def classify(reason, transcript="", order_ctx=None):
    """Return engine labels, or None. Never raises. Never exceeds TIMEOUT_S by much."""
    client = _get_client()
    if client is None:
        return None
    user = json.dumps({"reason": reason, "customer_words": transcript or reason,
                       "order": order_ctx or {}})
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_object"},
            reasoning_effort=REASONING_EFFORT,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": user}],
        )
        raw = _parse_json(r.choices[0].message.content or "")
        return _to_labels(raw, int((time.time() - t0) * 1000))
    except Exception:
        return None


def _parse_json(text):
    """The object itself, even if the model wrapped it in fences or a preamble."""
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def _to_labels(raw, latency_ms):
    """Map the classifier's JSON onto what engine.decide() reads.
    Raises on a malformed object so classify() returns None."""
    rt = raw["return_type"]
    status = raw["item_status"]
    if rt not in RETURN_TYPES or status not in ITEM_STATUS:
        raise ValueError("bad enum")
    conf = raw.get("confidence") or {}

    def c(k):
        try:
            return max(0.0, min(1.0, float(conf.get(k, 0.0))))
        except (TypeError, ValueError):
            return 0.0

    cond = raw.get("condition")
    confidences = {
        "is_defect": c("return_type"),
        "item_status": c("item_status"),
        "condition": c("condition"),
        "wants_replacement": c("wants_replacement"),
        "requests_human": c("requests_human"),
    }
    return {
        "is_defect": rt in DEFECT_TYPES,
        "item_status": status,
        "condition": cond if cond in CONDITIONS else None,
        "wants_replacement": bool(raw.get("wants_replacement")),
        "requests_human": bool(raw.get("requests_human")),
        "return_type": rt,
        "confidences": confidences,
        "confidence": confidences["is_defect"],
        "confidence_min": min(confidences.values()),
        "latency_ms": latency_ms,
        "model": MODEL,
    }


if __name__ == "__main__":
    phrases = sys.argv[1:] or [
        "one speed stopped working, it's defective",
        "it's just the wrong shade of grey, I opened it and slept on it one night",
        "the package never showed up and I want a manager",
        "wheel is scuffed out of the box, can you send another one",
    ]
    if not os.environ.get("NEBIUS_API_KEY"):
        print("NEBIUS_API_KEY not set: classify() returns None and the engine uses keywords.")
        sys.exit(0)
    print(f"model {MODEL} at {BASE_URL} (timeout {TIMEOUT_S}s)\n")
    for ph in phrases:
        lab = classify(ph, ph, {"item": "Calder Linen Duvet, King", "category": "bedding",
                                "price_paid": 218.0, "days_since_delivery": 5})
        if lab is None:
            print(f"  {ph!r}\n    -> None (fallback to keywords)\n")
            continue
        print(f"  {ph!r}\n    -> {lab['return_type']}, {lab['item_status']}, cond={lab['condition']}, "
              f"repl={lab['wants_replacement']}, human={lab['requests_human']}, "
              f"conf={lab['confidence']:.2f}, {lab['latency_ms']} ms\n")
