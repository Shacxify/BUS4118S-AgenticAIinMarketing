"""Mock supply chain data: inventory, suppliers, inbound shipments.

Everything is fictional. TODAY is fixed so days-of-cover and stockout math (and the demo transcript)
is reproducible no matter when the code runs.
"""
from datetime import date

BRAND = "Ridgeline Coffee Co."
TODAY = date(2026, 10, 26)

# Holiday gift season: Nov 15 to Dec 31 demand runs this much above normal.
HOLIDAY_START, HOLIDAY_END = date(2026, 11, 15), date(2026, 12, 31)
HOLIDAY_UPLIFT = 0.35

# Green (unroasted) coffee is tracked in pounds, packaging in units.
INVENTORY = {
    "GC-BRZ": {"name": "Brazil Cerrado (green)", "unit": "lb", "on_hand": 600, "daily_usage": 70,
               "safety_stock": 280, "reorder_point": 840, "used_in": ["Ridgeline House Blend", "Night Shift Espresso"]},
    "GC-COL": {"name": "Colombia Huila (green)", "unit": "lb", "on_hand": 2100, "daily_usage": 45,
               "safety_stock": 180, "reorder_point": 540, "used_in": ["Colombia Huila"]},
    "GC-ETH": {"name": "Ethiopia Yirgacheffe (green)", "unit": "lb", "on_hand": 420, "daily_usage": 30,
               "safety_stock": 120, "reorder_point": 450, "used_in": ["Ethiopia Yirgacheffe", "Sunrise Blend"]},
    "GC-SUM": {"name": "Sumatra Mandheling (green)", "unit": "lb", "on_hand": 900, "daily_usage": 20,
               "safety_stock": 80, "reorder_point": 260, "used_in": ["Sumatra Mandheling"]},
    "GC-DEC": {"name": "Swiss Water Decaf (green)", "unit": "lb", "on_hand": 480, "daily_usage": 12,
               "safety_stock": 50, "reorder_point": 140, "used_in": ["Swiss Water Decaf"]},
    "PK-12OZ": {"name": "12 oz valve bags", "unit": "units", "on_hand": 5200, "daily_usage": 480,
                "safety_stock": 1500, "reorder_point": 4000, "used_in": ["all 12 oz bags"]},
}

SUPPLIERS = {
    "GC-BRZ": [
        {"supplier": "Fazenda Alta Exports", "type": "direct from origin (Santos, Brazil)", "price": 3.20,
         "lead_time_days": 35, "on_time_rate": 0.82, "moq": 1500},
        {"supplier": "Bay Area Green Coffee", "type": "domestic importer (Oakland warehouse)", "price": 4.10,
         "lead_time_days": 3, "on_time_rate": 0.97, "moq": 150},
        {"supplier": "Pacific Bean Traders", "type": "domestic importer (Seattle warehouse)", "price": 3.85,
         "lead_time_days": 6, "on_time_rate": 0.91, "moq": 300},
    ],
    "GC-COL": [
        {"supplier": "Huila Growers Cooperative", "type": "direct from origin", "price": 4.60,
         "lead_time_days": 30, "on_time_rate": 0.88, "moq": 1000},
        {"supplier": "Bay Area Green Coffee", "type": "domestic importer (Oakland warehouse)", "price": 5.40,
         "lead_time_days": 3, "on_time_rate": 0.97, "moq": 150},
    ],
    "GC-ETH": [
        {"supplier": "Sidama Union", "type": "direct from origin", "price": 5.90,
         "lead_time_days": 45, "on_time_rate": 0.74, "moq": 1000},
        {"supplier": "Bay Area Green Coffee", "type": "domestic importer (Oakland warehouse)", "price": 6.80,
         "lead_time_days": 3, "on_time_rate": 0.97, "moq": 150},
    ],
    "GC-SUM": [
        {"supplier": "Aceh Highland Exports", "type": "direct from origin", "price": 4.40,
         "lead_time_days": 40, "on_time_rate": 0.79, "moq": 1000},
    ],
    "GC-DEC": [
        {"supplier": "Pacific Bean Traders", "type": "domestic importer (Seattle warehouse)", "price": 6.25,
         "lead_time_days": 6, "on_time_rate": 0.91, "moq": 150},
    ],
    "PK-12OZ": [
        {"supplier": "PackRight Supply", "type": "packaging manufacturer (Fresno)", "price": 0.22,
         "lead_time_days": 7, "on_time_rate": 0.95, "moq": 5000},
        {"supplier": "Valve Bag Direct", "type": "packaging manufacturer (overseas)", "price": 0.15,
         "lead_time_days": 28, "on_time_rate": 0.85, "moq": 20000},
    ],
}

# Inbound purchase orders. eta is the latest carrier estimate; original_eta is what was promised.
SHIPMENTS = {
    "PO-2207": {"item": "GC-ETH", "qty": 1000, "supplier": "Sidama Union", "status": "in transit",
                "carrier": "Maersk (ocean)", "origin": "Djibouti", "original_eta": date(2026, 11, 6),
                "eta": date(2026, 11, 6), "delay_reason": None},
    "PO-2211": {"item": "GC-BRZ", "qty": 1500, "supplier": "Fazenda Alta Exports", "status": "delayed",
                "carrier": "MSC (ocean)", "origin": "Santos, Brazil", "original_eta": date(2026, 11, 2),
                "eta": date(2026, 11, 9), "delay_reason": "port congestion at Santos; vessel departed 7 days late"},
    "PO-2214": {"item": "PK-12OZ", "qty": 10000, "supplier": "PackRight Supply", "status": "delivered",
                "carrier": "FedEx Freight", "origin": "Fresno, CA", "original_eta": date(2026, 10, 24),
                "eta": date(2026, 10, 24), "delay_reason": None},
    "PO-2216": {"item": "PK-12OZ", "qty": 10000, "supplier": "PackRight Supply", "status": "processing",
                "carrier": None, "origin": "Fresno, CA", "original_eta": date(2026, 11, 2),
                "eta": date(2026, 11, 2), "delay_reason": None},
}

# Purchase orders created during this process (a real system would write these to the ERP).
NEW_ORDERS = {}
NEXT_PO_NUMBER = 2231


def normalize_item(item):
    """Accept 'GC-BRZ', 'gc brz', 'brazil', 'Brazil Cerrado', 'bags' and return the item code (or None)."""
    text = str(item).strip().lower()
    compact = text.replace(" ", "-").upper()
    if compact in INVENTORY:
        return compact
    for code, info in INVENTORY.items():
        name = info["name"].lower()
        if text in name or name.split(" (")[0] in text:
            return code
    if "bag" in text or "packag" in text:
        return "PK-12OZ"
    if "decaf" in text:
        return "GC-DEC"
    return None


def normalize_po(po_number):
    """Accept '2211', '#2211', 'po2211', 'PO-2211' and return 'PO-2211'."""
    digits = "".join(ch for ch in str(po_number) if ch.isdigit())
    return f"PO-{digits}" if digits else str(po_number).strip().upper()
