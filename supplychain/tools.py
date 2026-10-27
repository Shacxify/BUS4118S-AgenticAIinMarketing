"""Tools the specialist agents can call. Each agent only gets the tools for its own job."""
import json
from datetime import date, timedelta
from typing import Optional

from langchain_core.tools import tool

from . import data
from .data import (HOLIDAY_END, HOLIDAY_START, HOLIDAY_UPLIFT, INVENTORY, NEW_ORDERS, SHIPMENTS, SUPPLIERS, TODAY,
                   normalize_item, normalize_po)


def _dumps(obj):
    return json.dumps(obj, default=str)   # dates -> ISO strings


def _unknown_item(item):
    return {"found": False, "item": item,
            "known_items": {code: info["name"] for code, info in INVENTORY.items()}}


def inbound_for(code):
    """Open (not yet delivered) purchase orders for an item, existing and newly created."""
    pos = {**SHIPMENTS, **NEW_ORDERS}
    return [{"po_number": po, **s} for po, s in pos.items() if s["item"] == code and s["status"] != "delivered"]


# ---- inventory & demand agent --------------------------------------------------------
def inventory_status(code):
    info = INVENTORY[code]
    cover = round(info["on_hand"] / info["daily_usage"], 1)
    if info["on_hand"] <= info["safety_stock"]:
        status = "critical: below safety stock"
    elif info["on_hand"] <= info["reorder_point"]:
        status = "low: below reorder point"
    else:
        status = "healthy"
    return {"found": True, "item_code": code, **info, "days_of_cover": cover, "status": status,
            "inbound": [{k: s[k] for k in ("po_number", "qty", "status", "eta")} for s in inbound_for(code)]}


def project_stock(code, horizon_days=30):
    """Walk forward day by day from TODAY: add arrivals on their ETA, subtract (holiday-adjusted) usage.

    Each run of out-of-stock days is a separate gap. The headline numbers describe the first gap (the one to
    act on now); later gaps, which no reorder has been planned for yet, are listed after it.
    """
    info = INVENTORY[code]
    horizon_days = max(1, min(int(horizon_days), 60))
    arrivals = {}
    for s in inbound_for(code):
        arrivals[s["eta"]] = arrivals.get(s["eta"], 0) + s["qty"]
    stock, gaps = info["on_hand"], []
    for d in range(horizon_days):
        day = TODAY + timedelta(days=d)
        stock += arrivals.get(day, 0)
        usage = info["daily_usage"] * (1 + HOLIDAY_UPLIFT if HOLIDAY_START <= day <= HOLIDAY_END else 1)
        if stock < usage:
            if not gaps or gaps[-1]["last_short_day"] != day - timedelta(days=1):
                gaps.append({"stockout_date": day, "days_short": 0, "shortfall": 0})
            gaps[-1]["last_short_day"] = day
            gaps[-1]["days_short"] += 1
            gaps[-1]["shortfall"] += usage - stock
            stock = 0
        else:
            stock -= usage
    for g in gaps:
        g["shortfall"] = round(g["shortfall"])
    first = gaps[0] if gaps else {"stockout_date": None, "days_short": 0, "shortfall": 0}
    return {"item_code": code, "name": info["name"], "unit": info["unit"], "horizon_days": horizon_days,
            "holiday_uplift": f"+{HOLIDAY_UPLIFT:.0%} demand from {HOLIDAY_START} to {HOLIDAY_END}",
            "arrivals_counted": [{"eta": eta, "qty": q} for eta, q in sorted(arrivals.items())],
            **first, "later_gaps": gaps[1:], "ending_stock": round(stock),
            "verdict": "no stockout in horizon" if not gaps else
                       f"first stockout on {first['stockout_date']:%b %d}: {first['days_short']} days short, "
                       f"about {first['shortfall']} {info['unit']} of unmet demand before stock recovers"
                       + (f"; {len(gaps) - 1} later gap(s) if nothing else is ordered" if len(gaps) > 1 else "")}


@tool
def check_inventory(item: str) -> str:
    """Current stock for one item: on hand, daily usage, days of cover, safety stock, reorder point, status,
    and open inbound purchase orders.

    item can be a code (GC-BRZ, GC-COL, GC-ETH, GC-SUM, GC-DEC, PK-12OZ) or a name like 'Brazil' or 'bags'.
    """
    code = normalize_item(item)
    return _dumps(inventory_status(code) if code else _unknown_item(item))


@tool
def forecast_stockout(item: str, horizon_days: int = 30) -> str:
    """Project stock day by day over the next horizon_days, counting inbound shipments on their current ETA
    and the holiday demand uplift (horizon_days up to 60; 30 is usually right). Returns the first stockout
    date, days short and unmet demand before stock recovers, plus any later gaps."""
    code = normalize_item(item)
    return _dumps(project_stock(code, horizon_days) if code else _unknown_item(item))


# ---- logistics agent -----------------------------------------------------------------
def shipment_status(po_number):
    po = normalize_po(po_number)
    s = {**SHIPMENTS, **NEW_ORDERS}.get(po)
    if s is None:
        return {"found": False, "po_number": po, "known_pos": sorted({**SHIPMENTS, **NEW_ORDERS})}
    out = {"found": True, "po_number": po, **s, "item_name": INVENTORY[s["item"]]["name"],
           "unit": INVENTORY[s["item"]]["unit"],
           "days_late": (s["eta"] - s["original_eta"]).days}
    if s["status"] != "delivered":
        out["days_until_arrival"] = (s["eta"] - TODAY).days
    return out


@tool
def track_shipment(po_number: str) -> str:
    """Track an inbound purchase order (e.g. PO-2211): item, quantity, carrier, origin, status,
    promised vs current ETA, days late, and the delay reason if any."""
    return _dumps(shipment_status(po_number))


@tool
def list_inbound_shipments(item: Optional[str] = None) -> str:
    """List all open inbound purchase orders, optionally for one item, with status and ETA."""
    code = normalize_item(item) if item else None
    if item and not code:
        return _dumps(_unknown_item(item))
    pos = [shipment_status(po) for po in {**SHIPMENTS, **NEW_ORDERS}]
    pos = [p for p in pos if p["status"] != "delivered" and (code is None or p["item"] == code)]
    return _dumps({"count": len(pos), "shipments": pos})


# ---- procurement agent ---------------------------------------------------------------
def supplier_options(code, qty=None, needed_by=None):
    options = []
    for s in SUPPLIERS.get(code, []):
        order_qty = max(qty or s["moq"], s["moq"])
        arrives = TODAY + timedelta(days=s["lead_time_days"])
        opt = {**s, "order_qty": order_qty, "total_cost": round(order_qty * s["price"], 2), "arrives": arrives}
        if needed_by:
            opt["arrives_in_time"] = arrives <= needed_by
        options.append(opt)
    return sorted(options, key=lambda o: o["arrives"])


@tool
def compare_suppliers(item: str, qty: Optional[int] = None, needed_by: Optional[str] = None) -> str:
    """Compare approved suppliers for an item: price per unit, lead time, on-time rate, minimum order,
    total cost and arrival date if ordered today. Sorted fastest first.

    qty: quantity you plan to order (raised to each supplier's minimum order if lower).
    needed_by: optional date (YYYY-MM-DD); each option is flagged with arrives_in_time.
    """
    code = normalize_item(item)
    if not code:
        return _dumps(_unknown_item(item))
    deadline = date.fromisoformat(needed_by) if needed_by else None
    return _dumps({"item_code": code, "name": INVENTORY[code]["name"], "unit": INVENTORY[code]["unit"],
                   "options": supplier_options(code, qty, deadline)})


@tool
def create_purchase_order(item: str, supplier: str, qty: int) -> str:
    """Place a purchase order with an approved supplier. Only call after the user confirms the order.
    Returns the new PO number, cost and expected arrival."""
    code = normalize_item(item)
    if not code:
        return _dumps({"created": False, **_unknown_item(item)})
    match = [s for s in SUPPLIERS.get(code, []) if supplier.lower() in s["supplier"].lower()]
    if not match:
        return _dumps({"created": False, "reason": f"{supplier} is not an approved supplier for {code}.",
                       "approved": [s["supplier"] for s in SUPPLIERS.get(code, [])]})
    s = match[0]
    if qty < s["moq"]:
        return _dumps({"created": False, "reason": f"Minimum order from {s['supplier']} is {s['moq']}."})
    po = f"PO-{data.NEXT_PO_NUMBER}"
    data.NEXT_PO_NUMBER += 1
    eta = TODAY + timedelta(days=s["lead_time_days"])
    NEW_ORDERS[po] = {"item": code, "qty": qty, "supplier": s["supplier"], "status": "processing",
                      "carrier": None, "origin": s["type"], "original_eta": eta, "eta": eta, "delay_reason": None}
    return _dumps({"created": True, "po_number": po, "item": INVENTORY[code]["name"], "qty": qty,
                   "unit": INVENTORY[code]["unit"], "supplier": s["supplier"], "unit_price": s["price"],
                   "total_cost": round(qty * s["price"], 2), "expected_arrival": eta})


INVENTORY_TOOLS = [check_inventory, forecast_stockout]
LOGISTICS_TOOLS = [track_shipment, list_inbound_shipments]
PROCUREMENT_TOOLS = [compare_suppliers, create_purchase_order]
