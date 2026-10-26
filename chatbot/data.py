"""Mock store data: product catalog, orders, and the refund policy.

Everything is fictional. TODAY is fixed so refund-window math (and the demo transcript)
is reproducible no matter when the code runs.
"""
from datetime import date

BRAND = "Ridgeline Coffee Co."
TODAY = date(2026, 10, 26)

PRODUCTS = [
    {"name": "Sunrise Blend", "roast": "light", "price": 17.00,
     "notes": ["citrus", "honey", "bright"], "brew_methods": ["pour-over", "drip", "aeropress"],
     "decaf": False, "best_for": "a bright, easygoing morning cup"},
    {"name": "Ethiopia Yirgacheffe", "roast": "light", "price": 21.00,
     "notes": ["floral", "blueberry", "lemon", "fruity"], "brew_methods": ["pour-over", "aeropress"],
     "decaf": False, "best_for": "fans of fruity, tea-like single origins"},
    {"name": "Colombia Huila", "roast": "medium", "price": 18.00,
     "notes": ["caramel", "red apple", "fruity", "balanced"], "brew_methods": ["pour-over", "drip", "french press"],
     "decaf": False, "best_for": "a sweet, balanced everyday single origin"},
    {"name": "Ridgeline House Blend", "roast": "medium", "price": 16.00,
     "notes": ["milk chocolate", "toasted nut", "smooth"], "brew_methods": ["drip", "french press", "pour-over"],
     "decaf": False, "best_for": "a crowd-pleasing daily drinker"},
    {"name": "Night Shift Espresso", "roast": "dark", "price": 19.00,
     "notes": ["dark chocolate", "molasses", "bold"], "brew_methods": ["espresso", "moka pot"],
     "decaf": False, "best_for": "espresso and milk drinks"},
    {"name": "Sumatra Mandheling", "roast": "dark", "price": 19.00,
     "notes": ["earthy", "cedar", "spice", "bold"], "brew_methods": ["french press", "drip"],
     "decaf": False, "best_for": "people who like a heavy, earthy cup"},
    {"name": "Swiss Water Decaf", "roast": "medium", "price": 18.00,
     "notes": ["cocoa", "brown sugar", "smooth"], "brew_methods": ["drip", "pour-over", "french press"],
     "decaf": True, "best_for": "evening coffee without the caffeine"},
    {"name": "Cold Brew Coarse Grind", "roast": "medium-dark", "price": 20.00,
     "notes": ["chocolate", "cherry", "smooth"], "brew_methods": ["cold brew"],
     "decaf": False, "best_for": "batch cold brew at home"},
    {"name": "Explorer Sampler (4 x 4 oz)", "roast": "mixed", "price": 28.00,
     "notes": ["variety"], "brew_methods": ["pour-over", "drip", "french press", "aeropress"],
     "decaf": False, "best_for": "trying several roasts before committing to a full bag"},
]

ORDERS = {
    "RC-1001": {"first_name": "Maya", "placed": date(2026, 10, 8), "status": "delivered",
                "delivered": date(2026, 10, 12), "carrier": "USPS", "tracking": "9400 1000 0000 1001",
                "items": [{"product": "Sumatra Mandheling", "qty": 2, "price": 19.00},
                          {"product": "Ridgeline House Blend", "qty": 1, "price": 16.00}]},
    "RC-1002": {"first_name": "Jordan", "placed": date(2026, 10, 22), "status": "in transit",
                "delivered": None, "eta": date(2026, 10, 28), "carrier": "UPS",
                "tracking": "1Z999AA10000001002",
                "items": [{"product": "Night Shift Espresso", "qty": 2, "price": 19.00}]},
    "RC-1003": {"first_name": "Priya", "placed": date(2026, 10, 25), "status": "processing",
                "delivered": None, "eta": date(2026, 10, 30), "carrier": None, "tracking": None,
                "items": [{"product": "Explorer Sampler (4 x 4 oz)", "qty": 1, "price": 28.00}]},
    "RC-1004": {"first_name": "Sam", "placed": date(2026, 9, 5), "status": "delivered",
                "delivered": date(2026, 9, 10), "carrier": "USPS", "tracking": "9400 1000 0000 1004",
                "items": [{"product": "Colombia Huila", "qty": 1, "price": 18.00}]},
}

REFUND_WINDOW_DAYS = 30
DAMAGE_REPORT_DAYS = 14

REFUND_POLICY = f"""Ridgeline Coffee Co. refund and return policy
- Unopened bags: full refund within {REFUND_WINDOW_DAYS} days of delivery. Return shipping label provided.
- Taste Guarantee: if you opened a bag and don't love it, we refund that bag (or swap it for another roast)
  within {REFUND_WINDOW_DAYS} days of delivery. No need to send opened coffee back.
- Damaged or wrong item: report within {DAMAGE_REPORT_DAYS} days of delivery for a free replacement or full refund.
- Orders still processing can be cancelled for a full refund. Orders in transit can be returned once delivered.
- Refunds go to the original payment method within 5-7 business days.
- Original shipping is non-refundable unless the problem was our mistake.
- Subscriptions can be paused or cancelled anytime; already-shipped bags follow the rules above."""

# Returns started during this process (a real store would write these to a database).
RETURNS = {}


def normalize_order_id(order_id):
    """Accept '1001', '#1001', 'rc1001', 'RC-1001' and return 'RC-1001'."""
    digits = "".join(ch for ch in str(order_id) if ch.isdigit())
    return f"RC-{digits}" if digits else str(order_id).strip().upper()
