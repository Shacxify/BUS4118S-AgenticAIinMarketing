"""Build supplychain/supplychain_demo.ipynb from the cells below (run, then execute with nbconvert).

    python scripts/build_supplychain_notebook.py
    jupyter nbconvert --to notebook --execute --inplace supplychain/supplychain_demo.ipynb

The notebook runs both in Google Colab (clones the repo, reads the key from Colab Secrets) and locally
(uses the repo checkout and .env).
"""
import nbformat as nbf

REPO = "Shacxify/BUS4118S-AgenticAIinMarketing"
BRANCH = "main"
PATH = "supplychain/supplychain_demo.ipynb"
COLAB_URL = f"https://colab.research.google.com/github/{REPO}/blob/{BRANCH}/{PATH}"

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell

cells = [
    md(f"""# Ridgeline Coffee Co. Supply Chain Assistant

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)]({COLAB_URL})

A multi-agent supply chain assistant built with **LangGraph** and **Google Gemini**. "Atlas" helps the
operations team at Ridgeline Coffee Co. (the same fictional roaster as our ad agent and customer service
chatbot) keep green coffee and packaging in stock. This notebook shows:

1. **System prompt** that defines the assistant's role (Atlas, the supply chain analyst)
2. **Three supply chain request types handled by different agents:** Inventory & Demand, Logistics, Procurement
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
elif os.path.basename(os.getcwd()) == "supplychain":
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
    md("## 3. The system prompt\n\nEvery agent shares this operations persona. Each specialist adds its own role "
       "prompt on top (see `supplychain/prompts.py`)."),
    code("""from supplychain.prompts import OPS_SYSTEM_PROMPT
print(OPS_SYSTEM_PROMPT)"""),
    md("## 4. The supply chain data\n\nMock data in `supplychain/data.py`: six inventory items, approved suppliers, "
       "and four inbound purchase orders. \"Today\" is fixed at Oct 26, 2026 so results are reproducible. "
       "Brazil Cerrado, the base of the house blend, is the item to watch."),
    code("""from supplychain.tools import inventory_status
from supplychain.data import INVENTORY

print(f"{'item':<9}{'name':<30}{'on hand':>9}{'use/day':>9}{'days cover':>12}  status")
for item in INVENTORY:
    s = inventory_status(item)
    print(f"{item:<9}{s['name']:<30}{s['on_hand']:>9,}{s['daily_usage']:>9}{s['days_of_cover']:>12}  {s['status']}")"""),
    md("## 5. Build the multi-agent graph\n\nA **router** classifies each message and hands it to one specialist. "
       "Specialists loop with their own tools until they can answer. The graph is compiled with a "
       "`MemorySaver` checkpointer."),
    code("""from IPython.display import Image, display
from supplychain.graph import AGENTS, build_graph

graph = build_graph()
for name, (_, tools) in AGENTS.items():
    print(f"{name:<13} tools: {', '.join(t.name for t in tools) or 'none'}")
try:
    display(Image(graph.get_graph().draw_mermaid_png()))
except Exception:   # the PNG is rendered by an online service; fall back to the Mermaid source
    print(graph.get_graph().draw_mermaid())"""),
    md("## 6. A five-turn conversation across all three agents\n\nEach turn shows which agent handled it, "
       "which tools it called, and how many messages `MemorySaver` has stored for this conversation "
       "(`thread_id`). Later turns say \"that shipment\" and \"the fastest option\"; the agents resolve them "
       "from memory."),
    code("""import time
from chatbot.chat import ask

def turn(thread_id, text):
    reply, route, tools = ask(graph, thread_id, text)
    saved = len(graph.get_state({"configurable": {"thread_id": thread_id}}).values["messages"])
    print(f"Ops manager: {text}\\n")
    print(f"[{route} agent | tools: {', '.join(tools) or 'none'} | {saved} messages in memory]\\n")
    print(f"Atlas: {reply}")
    time.sleep(20)   # a turn can make 4-5 Gemini calls; the free tier allows 15 per minute"""),
    md("**Turn 1: inventory.** The inventory agent checks stock and projects a stockout, counting inbound "
       "shipments and holiday demand."),
    code("""turn("ops-morning", "Morning Atlas. How are we looking on Brazil Cerrado green coffee? Are we going to run out?")"""),
    md("**Turn 2: logistics.** \"That Brazil shipment\" is never named; the logistics agent gets PO-2211 from "
       "turn 1 and tracks it."),
    code("""turn("ops-morning", "That Brazil shipment, is it still on schedule? What's going on with it?")"""),
    md("**Turn 3: procurement.** The procurement agent compares suppliers against the stockout date and "
       "shortfall found earlier."),
    code("""turn("ops-morning", "We can't miss house blend orders. Who can get us enough Brazil to bridge the gap, "
                    "and what will it cost?")"""),
    md("**Turn 4: procurement action.** The manager approves, so the agent calls `create_purchase_order`."),
    code("""turn("ops-morning", "Go with the fastest option. Place an order for 500 lb.")"""),
    md("**Turn 5: memory check.** No tools: the answer comes from the conversation `MemorySaver` kept."),
    code("""turn("ops-morning", "Quick recap for my notes: the new PO number, when it lands, and when the delayed "
                    "shipment arrives.")"""),
    md("## 7. What `MemorySaver` stored\n\nThe checkpoint for this thread holds every message: manager turns, "
       "tool calls, tool results and replies."),
    code("""state = graph.get_state({"configurable": {"thread_id": "ops-morning"}})
for i, m in enumerate(state.values["messages"], 1):
    kind = type(m).__name__.replace("Message", "")
    calls = ", ".join(c["name"] for c in getattr(m, "tool_calls", None) or [])
    text = (f"calls {calls}" if calls else m.text).replace("\\n", " ")
    print(f"{i:>2}. {kind:<6} {text[:95]}")"""),
    md("## 8. The bridge order fixes the stockout\n\nRe-running the forecast now counts the new PO."),
    code("""from supplychain.tools import project_stock
print(project_stock("GC-BRZ")["verdict"])"""),
    md("## 9. Memory is per conversation\n\nA new `thread_id` starts empty, so Atlas doesn't know which PO "
       "\"my PO\" means. It can still see the purchasing system (including the new order), but not what was "
       "said in the other conversation."),
    code("""turn("new-shift", "When does my PO arrive?")"""),
    md("## 10. Try it yourself\n\nIn Colab this starts an interactive chat (type `quit` to stop). "
       "Try Brazil, Colombia, Ethiopia, Sumatra, decaf or bags, and POs PO-2207, PO-2211 or PO-2216. "
       "Locally, run `python -m supplychain.chat` instead."),
    code("""if IN_COLAB:
    while (text := input("You: ").strip()).lower() not in ("quit", "exit", ""):
        turn("colab-session", text)
        print()
else:
    print("Interactive chat runs in Colab. Locally: python -m supplychain.chat")"""),
]

nb = nbf.v4.new_notebook(cells=cells, metadata={
    "kernelspec": {"name": "python3", "display_name": "Python 3"},
    "colab": {"provenance": []},
})
nbf.write(nb, PATH)
print(f"Wrote {PATH}")
