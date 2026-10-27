"""Offline tests for the supply chain assistant: tools, routing fallback, and MemorySaver.

No API key needed. A fake chat model stands in for Gemini where a graph has to run.
"""
import json
from datetime import date

from langchain_core.messages import AIMessage, HumanMessage

from supplychain import data
from supplychain.data import normalize_item, normalize_po
from supplychain.graph import build_graph, keyword_route
from supplychain.tools import (create_purchase_order, inventory_status, project_stock, shipment_status,
                               supplier_options)
from tests.test_chatbot import FakeLLM


def test_normalize_item_and_po():
    for raw in ("GC-BRZ", "gc brz", "Brazil", "brazil cerrado green coffee"):
        assert normalize_item(raw) == "GC-BRZ"
    assert normalize_item("bags") == "PK-12OZ"
    assert normalize_item("decaf") == "GC-DEC"
    assert normalize_item("tea") is None
    for raw in ("PO-2211", "po2211", "#2211", "2211"):
        assert normalize_po(raw) == "PO-2211"


def test_inventory_status_flags_low_stock():
    brz = inventory_status("GC-BRZ")
    assert brz["status"].startswith("low") and brz["days_of_cover"] == 8.6
    assert [s["po_number"] for s in brz["inbound"]] == ["PO-2211"]
    assert inventory_status("GC-COL")["status"] == "healthy"


def test_delayed_shipment_causes_brazil_stockout():
    ship = shipment_status("2211")
    assert ship["status"] == "delayed" and ship["days_late"] == 7
    proj = project_stock("GC-BRZ")
    assert proj["stockout_date"] == date(2026, 11, 3)      # 600 lb at 70 lb/day lasts 8 days
    assert proj["days_short"] == 6 and proj["shortfall"] == 380   # PO-2211 lands Nov 9
    assert project_stock("GC-SUM")["stockout_date"] is None


def test_holiday_uplift_raises_usage():
    # Bags: PO-2216 lands Nov 2, then holiday demand (+35% from Nov 15) drains stock by late November.
    assert project_stock("PK-12OZ")["stockout_date"] == date(2026, 11, 23)


def test_supplier_options_sorted_fastest_and_respect_moq():
    opts = supplier_options("GC-BRZ", qty=400, needed_by=date(2026, 11, 3))
    assert [o["supplier"] for o in opts] == ["Bay Area Green Coffee", "Pacific Bean Traders", "Fazenda Alta Exports"]
    assert opts[0]["arrives_in_time"] and not opts[-1]["arrives_in_time"]
    assert opts[-1]["order_qty"] == 1500                    # raised to the origin supplier's minimum


def test_create_purchase_order_and_it_counts_as_inbound():
    bad = json.loads(create_purchase_order.invoke({"item": "brazil", "supplier": "Fazenda", "qty": 500}))
    assert bad["created"] is False                          # below the 1,500 lb minimum
    po = json.loads(create_purchase_order.invoke({"item": "brazil", "supplier": "bay area", "qty": 500}))
    assert po["created"] and po["total_cost"] == 2050.0 and po["expected_arrival"] == "2026-10-29"
    assert po["po_number"] == "PO-2231"
    try:
        assert project_stock("GC-BRZ")["stockout_date"] is None    # the bridge order covers the gap
        assert shipment_status(po["po_number"])["status"] == "processing"
    finally:
        data.NEW_ORDERS.clear()
        data.NEXT_PO_NUMBER = 2231


def test_keyword_route_fallback():
    assert keyword_route("Which supplier should we buy from?") == "procurement"
    assert keyword_route("Is PO-2211 delayed?") == "logistics"
    assert keyword_route("Are we going to run out of Brazil stock?") == "inventory"
    assert keyword_route("thanks!") == "general"


def test_memorysaver_keeps_state_per_thread():
    llm = FakeLLM(messages=iter([AIMessage(f"reply {i}") for i in range(10)]))
    graph = build_graph(llm=llm)
    a = {"configurable": {"thread_id": "a"}}
    for text in ("hi", "how much Brazil stock do we have", "which supplier is fastest?"):
        state = graph.invoke({"messages": [HumanMessage(text)]}, a)
    assert len(state["messages"]) == 6          # 3 turns + 3 replies, all remembered
    assert state["route"] == "procurement"
    b = graph.invoke({"messages": [HumanMessage("hi")]}, {"configurable": {"thread_id": "b"}})
    assert len(b["messages"]) == 2              # a new thread starts empty
