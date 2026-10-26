"""The LangGraph multi-agent graph.

START -> router -> one specialist agent (order_status | refund | product_recommendation | general) -> END
Each specialist with tools loops agent -> tools -> agent until it has an answer.
MemorySaver checkpoints the full state after every step, keyed by thread_id, so each new
message continues the same conversation.
"""
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field

from .prompts import (BRAND_SYSTEM_PROMPT, GENERAL_PROMPT, ORDER_STATUS_PROMPT, PRODUCT_PROMPT, REFUND_PROMPT,
                      ROUTER_PROMPT)
from .tools import ORDER_TOOLS, PRODUCT_TOOLS, REFUND_TOOLS

Intent = Literal["order_status", "refund", "product_recommendation", "general"]

# name -> (role prompt, tools)
AGENTS = {
    "order_status": (ORDER_STATUS_PROMPT, ORDER_TOOLS),
    "refund": (REFUND_PROMPT, REFUND_TOOLS),
    "product_recommendation": (PRODUCT_PROMPT, PRODUCT_TOOLS),
    "general": (GENERAL_PROMPT, []),
}

KEYWORDS = {
    "refund": ("refund", "return", "money back", "cancel", "damaged", "broken", "wrong item", "send it back"),
    "order_status": ("order", "track", "shipping", "shipped", "deliver", "arrive", "where is"),
    "product_recommendation": ("recommend", "suggest", "try", "roast", "flavor", "espresso", "decaf",
                               "buy", "price", "pour-over", "which coffee"),
}


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]   # appended to, never overwritten
    route: str                                            # which specialist handled the latest turn


class Route(BaseModel):
    intent: Intent = Field(description="The specialist that should answer the latest customer message.")


def keyword_route(text):
    """Fallback router if the LLM classification fails."""
    text = text.lower()
    for intent, words in KEYWORDS.items():   # refund first: "return my order" is a refund, not order status
        if any(w in text for w in words):
            return intent
    return "general"


def conversation_context(messages, max_turns=10):
    """What a specialist sees: earlier turns as plain text, plus the current turn in full.

    Tool calls made by other agents in earlier turns are dropped (their results already live in the
    replies the customer saw), so each agent only ever sees calls to its own tools.
    """
    last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    earlier = []
    for m in messages[:last_human]:
        if isinstance(m, HumanMessage):
            earlier.append(m)
        elif isinstance(m, AIMessage) and not m.tool_calls and m.text:
            earlier.append(AIMessage(content=m.text))
    return earlier[-2 * max_turns:] + messages[last_human:]


def transcript(messages, last=8):
    lines = []
    for m in conversation_context(messages)[-last:]:
        if isinstance(m, HumanMessage):
            lines.append(f"Customer: {m.text}")
        elif isinstance(m, AIMessage) and m.text:
            lines.append(f"Assistant: {m.text}")
    return "\n".join(lines)


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
    system = SystemMessage(f"{BRAND_SYSTEM_PROMPT}\n\n{role_prompt}")

    def agent(state):
        return {"messages": [model.invoke([system] + conversation_context(state["messages"]))]}
    return agent


def build_graph(llm=None, checkpointer=None):
    if llm is None:
        from .llm import get_llm
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
