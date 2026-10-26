"""Tools the specialist agents can call. Each agent only gets the tools for its own job."""
import json
from typing import Optional

from langchain_core.tools import tool

from .data import (DAMAGE_REPORT_DAYS, ORDERS, PRODUCTS, REFUND_POLICY, REFUND_WINDOW_DAYS, RETURNS, TODAY,
                   normalize_order_id)

REFUND_REASONS = ("unopened", "opened_taste", "damaged", "wrong_item", "cancel")


def _order_json(order_id, order):
    out = {"order_id": order_id, **order}
    out["order_total"] = round(sum(i["qty"] * i["price"] for i in order["items"]), 2)
    return json.loads(json.dumps(out, default=str))   # dates -> ISO strings


# ---- order status agent --------------------------------------------------------------
@tool
def lookup_order(order_id: str) -> str:
    """Look up an order by its number (e.g. RC-1001): status, items, carrier, tracking and dates."""
    oid = normalize_order_id(order_id)
    order = ORDERS.get(oid)
    if order is None:
        return json.dumps({"found": False, "order_id": oid})
    return json.dumps({"found": True, **_order_json(oid, order)})


# ---- refund agent --------------------------------------------------------------------
@tool
def get_refund_policy() -> str:
    """Return the store's full refund and return policy."""
    return REFUND_POLICY


def refund_eligibility(order_id, reason):
    oid = normalize_order_id(order_id)
    order = ORDERS.get(oid)
    if order is None:
        return {"eligible": False, "order_id": oid, "explanation": "Order not found."}
    if reason not in REFUND_REASONS:
        return {"eligible": False, "order_id": oid,
                "explanation": f"Unknown reason '{reason}'. Use one of: {', '.join(REFUND_REASONS)}."}

    status = order["status"]
    base = {"order_id": oid, "status": status, "reason": reason}
    if reason == "cancel":
        if status == "processing":
            return {**base, "eligible": True, "resolution": "cancel order, full refund",
                    "explanation": "The order hasn't shipped yet, so it can be cancelled for a full refund."}
        return {**base, "eligible": False,
                "explanation": f"The order is already {status}, so it can't be cancelled; it can be "
                               "returned after delivery."}
    if status != "delivered":
        return {**base, "eligible": False,
                "explanation": f"The order is {status}. Returns open once it's delivered."}

    days = (TODAY - order["delivered"]).days
    base["days_since_delivery"] = days
    if reason in ("damaged", "wrong_item"):
        ok = days <= DAMAGE_REPORT_DAYS
        return {**base, "eligible": ok, "resolution": "free replacement or full refund, no return needed" if ok else None,
                "explanation": f"Delivered {days} days ago; damaged or wrong items must be reported within "
                               f"{DAMAGE_REPORT_DAYS} days."}
    ok = days <= REFUND_WINDOW_DAYS
    resolution = {"unopened": "full refund after the unopened bags are returned (prepaid label)",
                  "opened_taste": "Taste Guarantee: refund or swap the opened bag, no need to send it back"}[reason]
    return {**base, "eligible": ok, "resolution": resolution if ok else None,
            "explanation": f"Delivered {days} days ago; the window is {REFUND_WINDOW_DAYS} days from delivery."}


@tool
def check_refund_eligibility(order_id: str, reason: str) -> str:
    """Check whether an order qualifies for a refund.

    reason must be one of: unopened, opened_taste (opened and didn't like it), damaged, wrong_item,
    cancel (cancel an order that hasn't shipped).
    """
    return json.dumps(refund_eligibility(order_id, reason))


@tool
def start_return(order_id: str, reason: str, product: Optional[str] = None) -> str:
    """Start a refund/return for an eligible order. Only call after the customer confirms they want it.

    product is the item being refunded (optional; defaults to the whole order).
    """
    check = refund_eligibility(order_id, reason)
    if not check["eligible"]:
        return json.dumps({"started": False, **check})
    oid = check["order_id"]
    return_id = f"RMA-{oid[3:]}-{len([r for r in RETURNS.values() if r['order_id'] == oid]) + 1:02d}"
    RETURNS[return_id] = {"order_id": oid, "reason": reason, "product": product or "whole order",
                          "resolution": check["resolution"]}
    return json.dumps({"started": True, "return_id": return_id, **RETURNS[return_id],
                       "next_steps": "Confirmation email within 1 hour; refund to original payment in 5-7 "
                                     "business days" + (" after the return is received." if reason == "unopened"
                                                        else ".")})


# ---- product recommendation agent ----------------------------------------------------
def find_products(roast=None, flavor=None, brew_method=None, decaf=None, max_price=None):
    hits = []
    for p in PRODUCTS:
        if roast and roast.lower() not in p["roast"]:
            continue
        if flavor and not any(flavor.lower() in n or n in flavor.lower() for n in p["notes"]):
            continue
        if brew_method and not any(brew_method.lower().replace("-", " ") in m.replace("-", " ")
                                   for m in p["brew_methods"]):
            continue
        if decaf is not None and p["decaf"] != decaf:
            continue
        if max_price is not None and p["price"] > max_price:
            continue
        hits.append(p)
    return hits


@tool
def search_products(roast: Optional[str] = None, flavor: Optional[str] = None,
                    brew_method: Optional[str] = None, decaf: Optional[bool] = None,
                    max_price: Optional[float] = None) -> str:
    """Search the coffee catalog. All filters are optional.

    roast: light, medium, medium-dark, or dark. flavor: one tasting note such as fruity, chocolate,
    citrus, floral, nutty, earthy. brew_method: pour-over, drip, espresso, french press, aeropress,
    cold brew, moka pot. decaf: true for decaf only. max_price: budget per 12 oz bag in USD.
    """
    hits = find_products(roast, flavor, brew_method, decaf, max_price)
    return json.dumps({"count": len(hits), "products": hits})


ORDER_TOOLS = [lookup_order]
REFUND_TOOLS = [get_refund_policy, check_refund_eligibility, start_return]
PRODUCT_TOOLS = [search_products]
