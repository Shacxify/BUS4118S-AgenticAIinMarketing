"""Interactive chat in the terminal:  python -m supplychain.chat

Commands: /new starts a fresh conversation (new thread_id), /quit exits.
"""
import uuid

from chatbot.chat import ask

from .graph import build_graph


def main():
    graph = build_graph()
    thread_id = f"ops-{uuid.uuid4().hex[:6]}"
    print("Atlas, Ridgeline Coffee Co. supply chain assistant. Ask about stock, shipments, or suppliers.")
    print("(Items: Brazil, Colombia, Ethiopia, Sumatra, decaf, bags. POs: PO-2207, PO-2211, PO-2216.  "
          "/new = new conversation, /quit = exit)\n")
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
            thread_id = f"ops-{uuid.uuid4().hex[:6]}"
            print(f"[new conversation: {thread_id}]\n")
            continue
        reply, route, tools = ask(graph, thread_id, text)
        print(f"[{route} agent{' | tools: ' + ', '.join(tools) if tools else ''}]")
        print(f"Atlas: {reply}\n")


if __name__ == "__main__":
    main()
