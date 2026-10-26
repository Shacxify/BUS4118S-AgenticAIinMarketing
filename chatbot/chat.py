"""Interactive chat in the terminal:  python -m chatbot.chat

Commands: /new starts a fresh conversation (new thread_id), /quit exits.
"""
import uuid

from langchain_core.messages import HumanMessage

from .graph import build_graph


def ask(graph, thread_id, text):
    """Send one message on a thread; return (reply text, route, tools called this turn)."""
    config = {"configurable": {"thread_id": thread_id}}
    before = len(graph.get_state(config).values.get("messages", []))
    state = graph.invoke({"messages": [HumanMessage(text)]}, config)
    new = state["messages"][before:]
    tools = [c["name"] for m in new for c in (getattr(m, "tool_calls", None) or [])]
    return state["messages"][-1].text, state["route"], tools


def main():
    graph = build_graph()
    thread_id = f"customer-{uuid.uuid4().hex[:6]}"
    print("Ridge, Ridgeline Coffee Co. assistant. Ask about an order, refunds, or what to brew next.")
    print("(Try order numbers RC-1001 to RC-1004.  /new = new conversation, /quit = exit)\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/new":
            thread_id = f"customer-{uuid.uuid4().hex[:6]}"
            print(f"[new conversation: {thread_id}]\n")
            continue
        reply, route, tools = ask(graph, thread_id, text)
        print(f"[{route} agent{' | tools: ' + ', '.join(tools) if tools else ''}]")
        print(f"Ridge: {reply}\n")


if __name__ == "__main__":
    main()
