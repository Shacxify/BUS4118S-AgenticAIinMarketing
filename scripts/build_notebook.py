"""Build notebook.ipynb from the cells below (run, then execute with nbconvert).

    python scripts/build_notebook.py
    jupyter nbconvert --to notebook --execute --inplace notebook.ipynb
"""
import nbformat as nbf

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell

cells = [
    md("""# Ad Optimization Agent: walkthrough

This notebook runs the whole pipeline end to end:

1. **Read** 30 days of channel performance from `data/ad_performance.csv`
2. **Score** each channel with the agent's tools (CTR, CVR, CPA, conversions per $100)
3. **Propose** tomorrow's budget split with a logged rationale (Gemini, with a rule-based fallback)
4. **Enforce guardrails** in code: ±20%/day per channel, 10% floor, fixed daily total, privacy and brand-tone checks
5. **Evaluate** every strategy on the same simulated market and compare against equal split and an oracle

See `README.md` for setup and `docs/design_doc.md` for the design."""),
    code("""import pandas as pd
from IPython.display import Image, Markdown, display

from adagent import config
from adagent.agent import decide_next, run_campaign
from adagent.guardrails import apply_guardrails
from adagent.llm import GeminiAgent
from adagent.policies import HeuristicAgent
from adagent.simulator import Market
from adagent.tools import compute_metrics, last_allocation, read_performance

pd.set_option("display.width", 160)
pd.set_option("display.max_colwidth", 140)"""),
    md("## 1. Read the performance data\n\n30 days × 3 channels, run with an equal $333/day split. "
       "Columns: `date, channel, spend, impressions, clicks, conversions`."),
    code("""history = read_performance("data/ad_performance.csv")
display(history.head(6))
totals = history.groupby("channel")[["spend", "impressions", "clicks", "conversions"]].sum()
totals["CTR %"] = (100 * totals.clicks / totals.impressions).round(2)
totals["CVR %"] = (100 * totals.conversions / totals.clicks).round(2)
totals["CPA $"] = (totals.spend / totals.conversions).round(2)
totals"""),
    md("Social improves sharply in the second half (a new creative doubles its conversion rate on day 16):"),
    code("""history["period"] = (history.date >= "2026-09-16").map({False: "days 1-15", True: "days 16-30"})
by_half = history.groupby(["period", "channel"])[["spend", "conversions"]].sum()
by_half["CPA $"] = (by_half.spend / by_half.conversions).round(2)
history = history.drop(columns="period")
by_half"""),
    md("## 2. Agent tools: score the channels\n\n`compute_metrics` is the agent's view of recent "
       "performance. The heuristic ranks on recency-weighted conversions per $100 "
       "(yesterday counts 1.0, the day before 0.6, then 0.36, ...)."),
    code("""cols = ["spend", "clicks", "conversions", "ctr", "cvr", "cpa", "conv_per_100"]
print("Last 3 days:")
display(compute_metrics(history, window=3)[cols].round(4))
print("Recency-weighted (decay 0.6):")
display(compute_metrics(history, decay=config.DECAY)[cols].round(4))"""),
    md("## 3. Propose tomorrow's budget\n\nThe Gemini agent receives the system prompt "
       "(`prompts/system_prompt.md`) plus the metrics above, and returns a split and a rationale as JSON. "
       "With no `GEMINI_API_KEY`, or on any API error, it falls back to the heuristic and logs why "
       "(see `source`)."),
    code("""prev = last_allocation(history)
zero_streak = {c: 0 for c in config.CHANNELS}
for name, policy in [("gemini", GeminiAgent()), ("heuristic", HeuristicAgent())]:
    alloc, record = decide_next(policy, history.date.nunique(), history, prev, zero_streak)
    print(f"--- {name}  (source: {record['source']})")
    for c in config.CHANNELS:
        print(f"  {c:<8} ${alloc[c]:>7.2f}  ({(alloc[c] - prev[c]) / prev[c]:+.0%} vs yesterday)")
    print("  Rationale:", record["rationale"])
    if record["guardrail_notes"]:
        print("  Guardrails:", record["guardrail_notes"])"""),
    md("## 4. Guardrails are enforced in code\n\nEven a reckless proposal (all money to Search) "
       "is clipped to the allowed range, and every change is explained:"),
    code("""final, notes = apply_guardrails({"Search": 1.0, "Social": 0.0, "Display": 0.0}, prev)
print(final)
print(*notes, sep="\\n")"""),
    md("## 5. Learning loop: 30 simulated days\n\nThe agent starts from an equal split, observes "
       "each day's results, and shifts budget. Every decision is logged with its rationale."),
    code("""perf, records = run_campaign(HeuristicAgent(seed=config.SEED), Market(config.SEED), verbose=True)
log = pd.DataFrame(records)
log[["day", "final_Search", "final_Social", "final_Display", "rationale", "guardrail_notes"]].iloc[[2, 3, 10, 16, 20, 29]]"""),
    md("## 6. Evaluation\n\nAll strategies face the same market noise. The oracle knows the true rates "
       "(an upper bound, not a real strategy). The robustness check repeats this over 20 market seeds."),
    code("""%run evaluate.py --seeds 20 --gemini-seeds 3"""),
    code("""display(Markdown(open("outputs/results.md", encoding="utf-8").read()))"""),
    code("""for f in ["cumulative_conversions.png", "allocation_over_time.png", "conversions_by_strategy.png"]:
    display(Image(f"outputs/{f}"))"""),
    md("""## Takeaways

- Every learning strategy beats the equal split, mainly by moving money out of Display (the highest CPA).
- On the same 3 markets: Gemini +5.8%, heuristic +4.4%, Thompson sampling +8.0%, oracle +19.0%.
- Gemini kept more budget in Social before day 16 (15-20% vs. the 10% floor), so it moved into Social sooner
  once Social improved. But it stayed cautious and kept about a third of the budget in Search afterwards, which is
  why Thompson sampling still did better.
- The guardrails have a cost: a channel pushed down to the 10% floor can only grow 20% a day, so when Social
  improves on day 16 it takes about a week to move real money there. That is the price of avoiding
  overreaction to noise, and it shows up as regret vs. the oracle.
- The `source` column in `outputs/decisions_log.csv` shows which decisions Gemini made (all 28 in the main run)
  and which fell back to the heuristic."""),
]

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
nbf.write(nb, "notebook.ipynb")
print("Wrote notebook.ipynb")
