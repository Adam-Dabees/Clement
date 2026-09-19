"""Mock order + merchant policy data. Swap for a real DB later (you won't)."""

# Merchant-set policy envelope. The agent may NEVER act outside this.
POLICY = {
    "max_autonomous_refund_usd": 400.00,   # above this -> escalate to human
    "returnless_threshold_ratio": 0.65,    # if return logistics cost >= 65% of resale value, don't ship it back
    "store_credit_bonus": 0.15,            # 15% bonus if customer takes credit
    "max_partial_keep_ratio": 0.60,        # never offer more than 60% back on a keep-it partial
    "second_offer_step": 0.15,             # how much the keep-it partial improves after one decline
    "return_window_days": 45,
    "escalate_keywords": ["human", "manager", "supervisor", "agent", "person", "lawyer", "lawsuit"],
    "min_classifier_confidence": 0.6,      # below this, ambiguity resolves in the customer's favour (Rule 7)
}

ORDERS = {
    "A1042": {
        "order_id": "A1042",
        "customer_name": "Dana Whitfield",
        "customer_email": "dana.whitfield@example.com",
        "merchant_id": "harlow",
        "category": "small appliance",
        "item": "Vireo 900W Blender",
        "price_paid": 129.00,
        "unit_cogs": 47.00,          # what it cost the merchant
        "return_shipping": 22.00,    # inbound freight
        "restock_labor": 6.00,       # inspect + repackage
        "resale_value": 58.00,       # realistic recovery if returned in stated condition
        "days_since_delivery": 9,
        "customer_ltv": 840.00,
        "prior_returns": 0,
        "reason_hint": "one speed setting stopped working",
    },
    "A1077": {
        "order_id": "A1077",
        "customer_name": "Marcus Lee",
        "customer_email": "marcus.lee@example.com",
        "merchant_id": "harlow",
        "category": "bedding",
        "item": "Calder Linen Duvet, King",
        "price_paid": 218.00,
        "unit_cogs": 96.00,
        "return_shipping": 34.00,
        "restock_labor": 14.00,
        "resale_value": 0.00,        # opened bedding: legally unsellable
        "days_since_delivery": 5,
        "customer_ltv": 2100.00,
        "prior_returns": 1,
        "reason_hint": "wrong shade of grey",
    },
    "A1103": {
        "order_id": "A1103",
        "customer_name": "Priya Raman",
        "customer_email": "priya.raman@example.com",
        "merchant_id": "harlow",
        "category": "luggage",
        "item": "Nomad Carry-On 40L",
        "price_paid": 349.00,
        "unit_cogs": 138.00,
        "return_shipping": 28.00,
        "restock_labor": 9.00,
        "resale_value": 205.00,      # high recovery: worth shipping back
        "days_since_delivery": 3,
        "customer_ltv": 349.00,
        "prior_returns": 0,
        "reason_hint": "wheel is scuffed out of the box",
    },
    "A1150": {
        "order_id": "A1150",
        "customer_name": "Tom Okafor",
        "customer_email": "tom.okafor@example.com",
        "merchant_id": "harlow",
        "category": "appliance",
        "item": "Halden Espresso Machine",
        "price_paid": 780.00,        # over the autonomous cap -> escalation demo
        "unit_cogs": 390.00,
        "return_shipping": 62.00,
        "restock_labor": 25.00,
        "resale_value": 430.00,
        "days_since_delivery": 12,
        "customer_ltv": 780.00,
        "prior_returns": 0,
        "reason_hint": "leaking from the group head",
    },
    "A1188": {
        "order_id": "A1188",
        "customer_name": "Sofia Alvarez",
        "customer_email": "sofia.alvarez@example.com",
        "merchant_id": "harlow",
        "category": "apparel",
        "item": "Trail Runner Socks, 3-pack",
        "price_paid": 34.00,
        "unit_cogs": 9.00,
        "return_shipping": 8.50,
        "restock_labor": 3.00,
        "resale_value": 0.00,        # worn socks: zero recovery, obvious returnless
        "days_since_delivery": 21,
        "customer_ltv": 410.00,
        "prior_returns": 3,          # high prior returns -> abuse-check demo
        "reason_hint": "too tight",
    },
}
