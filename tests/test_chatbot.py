"""Offline tests for the chatbot: tools, routing fallback, context handling, and MemorySaver.

No API key needed. A fake chat model stands in for Gemini where a graph has to run.
"""
import json

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from chatbot.data import normalize_order_id
from chatbot.graph import build_graph, conversation_context, keyword_route
from chatbot.tools import find_products, lookup_order, refund_eligibility, start_return


def test_normalize_order_id():
    for raw in ("RC-1001", "rc1001", "#1001", "1001"):
        assert normalize_order_id(raw) == "RC-1001"


def test_lookup_order_found_and_missing():
    found = json.loads(lookup_order.invoke({"order_id": "1002"}))
    assert found["found"] and found["status"] == "in transit" and found["order_total"] == 38.0
    assert json.loads(lookup_order.invoke({"order_id": "RC-9999"}))["found"] is False


def test_refund_rules():
    assert refund_eligibility("RC-1001", "opened_taste")["eligible"]        # 14 days after delivery
    assert not refund_eligibility("RC-1004", "unopened")["eligible"]        # 46 days, outside 30-day window
    assert not refund_eligibility("RC-1002", "unopened")["eligible"]        # still in transit
    assert refund_eligibility("RC-1003", "cancel")["eligible"]              # processing -> cancellable
    assert not refund_eligibility("RC-1002", "cancel")["eligible"]          # already shipped
    assert refund_eligibility("RC-1001", "damaged")["eligible"]             # day 14: last day to report damage
    assert not refund_eligibility("RC-1004", "damaged")["eligible"]         # too late to report damage
    assert not refund_eligibility("RC-1001", "made_up")["eligible"]


def test_start_return_only_when_eligible():
    ok = json.loads(start_return.invoke({"order_id": "RC-1001", "reason": "opened_taste", "product": "Sumatra"}))
    assert ok["started"] and ok["return_id"].startswith("RMA-1001-")
    blocked = json.loads(start_return.invoke({"order_id": "RC-1004", "reason": "unopened"}))
    assert blocked["started"] is False


def test_product_search_filters():
    names = {p["name"] for p in find_products(flavor="fruity", brew_method="pour-over", max_price=20)}
    assert names == {"Colombia Huila"}
    assert all(p["decaf"] for p in find_products(decaf=True))
    assert find_products(roast="dark", max_price=5) == []


def test_keyword_route_fallback():
    assert keyword_route("Can I return my order?") == "refund"
    assert keyword_route("Where is my order RC-1002") == "order_status"
    assert keyword_route("Can you recommend a decaf?") == "product_recommendation"
    assert keyword_route("hello there") == "general"


def test_context_drops_old_tool_traffic_but_keeps_current_turn():
    msgs = [HumanMessage("where is RC-1001"),
            AIMessage("", tool_calls=[{"name": "lookup_order", "args": {"order_id": "RC-1001"}, "id": "1"}]),
            ToolMessage("{...}", tool_call_id="1"),
            AIMessage("It was delivered Oct 12."),
            HumanMessage("can I return it?"),
            AIMessage("", tool_calls=[{"name": "get_refund_policy", "args": {}, "id": "2"}]),
            ToolMessage("policy", tool_call_id="2")]
    ctx = conversation_context(msgs)
    assert [type(m).__name__ for m in ctx] == ["HumanMessage", "AIMessage", "HumanMessage", "AIMessage", "ToolMessage"]
    assert ctx[1].text == "It was delivered Oct 12."


class FakeLLM(GenericFakeChatModel):
    """Fake model: structured-output routing fails (so the keyword fallback routes), tools are ignored."""
    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        raise_on_invoke = type("Broken", (), {"invoke": lambda self, *_: (_ for _ in ()).throw(ValueError())})
        return raise_on_invoke()


def test_memorysaver_keeps_state_per_thread():
    llm = FakeLLM(messages=iter([AIMessage(f"reply {i}") for i in range(10)]))
    graph = build_graph(llm=llm)
    a = {"configurable": {"thread_id": "a"}}
    for text in ("hi", "where is my order RC-1001", "can I return it?"):
        state = graph.invoke({"messages": [HumanMessage(text)]}, a)
    assert len(state["messages"]) == 6          # 3 customer turns + 3 replies, all remembered
    assert state["route"] == "refund"
    b = graph.invoke({"messages": [HumanMessage("hi")]}, {"configurable": {"thread_id": "b"}})
    assert len(b["messages"]) == 2              # a new thread starts empty
