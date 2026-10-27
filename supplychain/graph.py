"""The LangGraph multi-agent graph.

START -> router -> one specialist agent (inventory | logistics | procurement | general) -> END
Each specialist with tools loops agent -> tools -> agent until it has an answer.
MemorySaver checkpoints the full state after every step, keyed by thread_id, so each new
message continues the same conversation.

The router and conversation handling are the same as the customer service chatbot; only the
agents, prompts and tools change.
"""
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field

from chatbot.graph import conversation_context, transcript

from .prompts import (GENERAL_PROMPT, INVENTORY_PROMPT, LOGISTICS_PROMPT, OPS_SYSTEM_PROMPT, PROCUREMENT_PROMPT,
                      ROUTER_PROMPT)
from .tools import INVENTORY_TOOLS, LOGISTICS_TOOLS, PROCUREMENT_TOOLS

Intent = Literal["inventory", "logistics", "procurement", "general"]

# name -> (role prompt, tools)
AGENTS = {
    "inventory": (INVENTORY_PROMPT, INVENTORY_TOOLS),
    "logistics": (LOGISTICS_PROMPT, LOGISTICS_TOOLS),
    "procurement": (PROCUREMENT_PROMPT, PROCUREMENT_TOOLS),
    "general": (GENERAL_PROMPT, []),
}

KEYWORDS = {
    "procurement": ("supplier", "vendor", "purchase order", "place an order", "order more", "buy", "price",
                    "lead time", "cost", "quote"),
    "logistics": ("shipment", "po-", "track", "eta", "delay", "late", "arrive", "carrier", "inbound", "port"),
    "inventory": ("stock", "inventory", "on hand", "run out", "stockout", "days of cover", "reorder", "demand",
                  "forecast"),
}


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]   # appended to, never overwritten
    route: str                                            # which specialist handled the latest turn


class Route(BaseModel):
    intent: Intent = Field(description="The specialist that should answer the latest user message.")


def keyword_route(text):
    """Fallback router if the LLM classification fails."""
    text = text.lower()
    for intent, words in KEYWORDS.items():   # procurement first: "order more beans" is a purchase, not tracking
        if any(w in text for w in words):
            return intent
    return "general"


def make_router(llm):
    classifier = llm.with_structured_output(Route)

    def router(state):
        try:
            intent = classifier.invoke([SystemMessage(ROUTER_PROMPT),
                                        HumanMessage(transcript(state["messages"]))]).intent
        except Exception:
            intent = keyword_route(state["messages"][-1].text)
        return {"route": intent}
    return router


def make_agent(llm, role_prompt, tools):
    model = llm.bind_tools(tools) if tools else llm
    system = SystemMessage(f"{OPS_SYSTEM_PROMPT}\n\n{role_prompt}")

    def agent(state):
        return {"messages": [model.invoke([system] + conversation_context(state["messages"]))]}
    return agent


def build_graph(llm=None, checkpointer=None):
    if llm is None:
        from chatbot.llm import get_llm
        llm = get_llm()

    g = StateGraph(State)
    g.add_node("router", make_router(llm))
    g.add_edge(START, "router")
    g.add_conditional_edges("router", lambda s: s["route"], list(AGENTS))

    for name, (role_prompt, tools) in AGENTS.items():
        g.add_node(name, make_agent(llm, role_prompt, tools))
        if tools:
            g.add_node(f"{name}_tools", ToolNode(tools))
            g.add_conditional_edges(name, tools_condition, {"tools": f"{name}_tools", END: END})
            g.add_edge(f"{name}_tools", name)
        else:
            g.add_edge(name, END)

    return g.compile(checkpointer=checkpointer or MemorySaver())
