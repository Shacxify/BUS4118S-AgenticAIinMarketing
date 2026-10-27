"""Build chatbot/chatbot_demo.ipynb from the cells below (run, then execute with nbconvert).

    python scripts/build_chatbot_notebook.py
    jupyter nbconvert --to notebook --execute --inplace chatbot/chatbot_demo.ipynb

The notebook runs both in Google Colab (clones the repo, reads the key from Colab Secrets) and locally
(uses the repo checkout and .env).
"""
import nbformat as nbf

REPO = "Shacxify/BUS4118S-AgenticAIinMarketing"
BRANCH = "main"
PATH = "chatbot/chatbot_demo.ipynb"
COLAB_URL = f"https://colab.research.google.com/github/{REPO}/blob/{BRANCH}/{PATH}"

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell

cells = [
    md(f"""# Ridgeline Coffee Co. Customer Assistant

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)]({COLAB_URL})

A multi-agent customer service and sales chatbot built with **LangGraph** and **Google Gemini**.
This notebook shows the three assignment requirements in action:

1. **System prompt** that defines the chatbot's role ("Ridge", the Ridgeline Coffee assistant)
2. **Three inquiry types handled by different agents:** Order Status, Refunds & Returns, Product Recommendation
3. **Conversation memory** across turns with LangGraph `MemorySaver`

**To run in Colab:** click the 🔑 *Secrets* icon in the left sidebar, add a secret named `GEMINI_API_KEY`
with your [Google AI Studio](https://aistudio.google.com/apikey) key, and turn on *Notebook access*.
Then choose *Runtime → Run all*."""),
    md("## 1. Setup\n\nIn Colab this clones the repository and installs LangGraph and the Gemini integration. "
       "Locally it uses the existing checkout."),
    code(f"""import os, sys

IN_COLAB = "google.colab" in sys.modules
if IN_COLAB:
    if not os.path.exists("BUS4118S-AgenticAIinMarketing"):
        !git clone -q --branch {BRANCH} https://github.com/{REPO}.git
    %cd BUS4118S-AgenticAIinMarketing
    !pip install -q "langgraph>=1.0" "langchain-google-genai>=4.0" python-dotenv
elif os.path.basename(os.getcwd()) == "chatbot":
    os.chdir("..")   # work from the repo root
sys.path.insert(0, os.getcwd())
print("Running in", "Google Colab" if IN_COLAB else "a local checkout")"""),
    md("## 2. Gemini API key\n\nRead from Colab Secrets (or a hidden prompt) in Colab, and from `.env` locally. "
       "The key is never printed or saved in the notebook."),
    code("""if IN_COLAB:
    from google.colab import userdata
    try:
        os.environ["GEMINI_API_KEY"] = userdata.get("GEMINI_API_KEY")
    except Exception:
        from getpass import getpass
        os.environ["GEMINI_API_KEY"] = getpass("Gemini API key: ")
print("Gemini key loaded:", bool(os.getenv("GEMINI_API_KEY")) or os.path.exists(".env"))"""),
    md("## 3. The system prompt\n\nEvery agent shares this brand persona. Each specialist adds its own role "
       "prompt on top (see `chatbot/prompts.py`)."),
    code("""from chatbot.prompts import BRAND_SYSTEM_PROMPT
print(BRAND_SYSTEM_PROMPT)"""),
    md("## 4. Build the multi-agent graph\n\nA **router** classifies each message and hands it to one specialist. "
       "Specialists loop with their own tools until they can answer. The graph is compiled with a "
       "`MemorySaver` checkpointer."),
    code("""from IPython.display import Image, display
from chatbot.graph import AGENTS, build_graph

graph = build_graph()
for name, (_, tools) in AGENTS.items():
    print(f"{name:<24} tools: {', '.join(t.name for t in tools) or 'none'}")
try:
    display(Image(graph.get_graph().draw_mermaid_png()))
except Exception:   # the PNG is rendered by an online service; fall back to the Mermaid source
    print(graph.get_graph().draw_mermaid())"""),
    md("## 5. A five-turn conversation across all three agents\n\nEach turn shows which agent handled it, "
       "which tools it called, and how many messages `MemorySaver` has stored for this conversation "
       "(`thread_id`). Later turns never repeat the order number; the agents get it from memory."),
    code("""import time
from chatbot.chat import ask

def turn(thread_id, text):
    reply, route, tools = ask(graph, thread_id, text)
    saved = len(graph.get_state({"configurable": {"thread_id": thread_id}}).values["messages"])
    print(f"Customer: {text}\\n")
    print(f"[{route} agent | tools: {', '.join(tools) or 'none'} | {saved} messages in memory]\\n")
    print(f"Ridge: {reply}")
    time.sleep(3)   # stay under free-tier requests-per-minute limits"""),
    md("**Turn 1: order status.** The order agent looks the order up with `lookup_order`."),
    code("""turn("maya-session", "Hi! Can you check on my order RC-1001?")"""),
    md("**Turn 2: refund.** The router switches to the refund agent, which checks eligibility for the order "
       "from turn 1."),
    code("""turn("maya-session", "Thanks. I opened one of the Sumatra bags and honestly it's too earthy for me. "
                     "Can I get my money back?")"""),
    md("**Turn 3: refund action.** The customer confirms, so the agent calls `start_return`."),
    code("""turn("maya-session", "Yes please, go ahead and start that for the Sumatra.")"""),
    md("**Turn 4: product recommendation.** The sales agent searches the catalog and remembers the customer "
       "didn't like the Sumatra."),
    code("""turn("maya-session", "What should I try instead? I brew pour-over and like brighter, fruity coffee. "
                     "Ideally under $20.")"""),
    md("**Turn 5: memory check.** No tools: the answer comes from the conversation `MemorySaver` kept."),
    code("""turn("maya-session", "Quick recap before I go: what was my order number, and what's my return ID?")"""),
    md("## 6. What `MemorySaver` stored\n\nThe checkpoint for this thread holds every message: customer turns, "
       "tool calls, tool results and replies."),
    code("""state = graph.get_state({"configurable": {"thread_id": "maya-session"}})
for i, m in enumerate(state.values["messages"], 1):
    kind = type(m).__name__.replace("Message", "")
    calls = ", ".join(c["name"] for c in getattr(m, "tool_calls", None) or [])
    text = (f"calls {calls}" if calls else m.text).replace("\\n", " ")
    print(f"{i:>2}. {kind:<6} {text[:95]}")"""),
    md("## 7. Memory is per conversation\n\nA new `thread_id` starts empty, so the assistant doesn't know "
       "Maya's order."),
    code("""turn("new-visitor", "What's my order number?")"""),
    md("## 8. Try it yourself\n\nIn Colab this starts an interactive chat (type `quit` to stop). "
       "Try order numbers RC-1001 to RC-1004. Locally, run `python -m chatbot.chat` instead."),
    code("""if IN_COLAB:
    while (text := input("You: ").strip()).lower() not in ("quit", "exit", ""):
        turn("colab-session", text)
        print()
else:
    print("Interactive chat runs in Colab. Locally: python -m chatbot.chat")"""),
]

nb = nbf.v4.new_notebook(cells=cells, metadata={
    "kernelspec": {"name": "python3", "display_name": "Python 3"},
    "colab": {"provenance": []},
})
nbf.write(nb, PATH)
print(f"Wrote {PATH}")
