# Ad Optimization Agent (BUS4 118S: Agentic AI in Marketing)

An agent that splits a daily ad budget across **Search, Social and Display** to maximize conversions.
It reads channel performance from a CSV, proposes tomorrow's budget, enforces guardrails in code, and logs
a one-sentence rationale for every decision. Decisions come from **Gemini** (with a system prompt), and a
transparent rule-based agent takes over whenever the LLM isn't available.

**Group members:** _add names here_

| Deliverable | Where |
|---|---|
| Design doc (≤1 page) | [`docs/design_doc.md`](docs/design_doc.md) |
| System prompt | [`prompts/system_prompt.md`](prompts/system_prompt.md) |
| Working script / notebook | [`propose.py`](propose.py), [`evaluate.py`](evaluate.py), [`notebook.ipynb`](notebook.ipynb) |
| Results + decision logs | [`outputs/`](outputs/) |
| Scaling note (≤½ page) | [`docs/scaling_note.md`](docs/scaling_note.md) |

## How to run

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python generate_data.py      # writes data/ad_performance.csv (30 days x 3 channels)
python propose.py            # reads the CSV, proposes tomorrow's budget + rationale
python evaluate.py --gemini-seeds 3   # compares all strategies, writes outputs/ (~30 s; Gemini replays from cache)
pytest                       # guardrail tests
jupyter notebook notebook.ipynb   # the same pipeline, step by step
```

**Gemini (optional).** Copy `.env.example` to `.env` and set `GEMINI_API_KEY` (free key from Google AI
Studio). Everything runs without a key: Gemini decisions fall back to the heuristic, and the `source` column
in the logs says so. Gemini replies are cached in `outputs/gemini_cache.json`, so once one person has run
the evaluation, anyone can re-run it and get identical results without a key or any API cost.

`propose.py --policy heuristic|thompson|gemini|equal_split --budget 1500 --csv path.csv` works on any CSV
with the same columns.

## How it works

```
read_performance ─► compute_metrics ─► policy proposes split ─► apply_guardrails ─► check_rationale ─► log_decision
     (CSV)            (CTR, CVR, CPA,      (Gemini / heuristic /      (±20%/day, 10% floor,   (no personal data,   (outputs/*.csv)
                       conv per $100)       Thompson)                   total = budget)         neutral tone)
```

- **Heuristic agent:** ranks channels by recency-weighted conversions per $100. If the leader is at least
  10% ahead, it shifts 10–20% more budget its way, taken from the laggards; otherwise it holds.
- **Gemini agent:** gets the same metrics plus the system prompt and returns
  `{allocation, rationale, confidence}` as JSON. Code clips anything outside the guardrails and logs the clip.
- **Thompson sampling:** a standard explore/exploit algorithm, used as a stronger comparison.
- **Oracle:** knows the simulator's true rates. It's an upper bound for measuring regret, not a real strategy.

## Assumptions

- **Mock data from a simulator.** A plain CSV can't say what would have happened under a different budget,
  so `adagent/simulator.py` gives each channel hidden true rates (CPC, CTR, CVR) with diminishing returns
  and daily noise. `data/ad_performance.csv` is what an equal split produced in that market.
- **A mid-campaign change:** Social's conversion rate doubles on day 16 (think: a new creative). Search is
  best before that and Social after, so the agent has to notice and adapt.
- **Fair comparison:** every strategy sees identical market noise (common random numbers). Results are
  averaged over 20 market seeds as well as the main run.
- **Setup:** $1,000/day, 30 days, 2 warm-up days at an equal split. Conversions are counted on the day of
  spend (no attribution lag).
- **No exploration by default:** random exploration (boosting a random non-leader 10% of the time) cost
  about 2% of conversions in testing, because the 10% floor already keeps every channel learning. It
  remains available as `EXPLORE_RATE` in `adagent/config.py`.

## Results snapshot

Main run (seed 42, 30 days, $30,000 total spend). Full tables are in [`outputs/results.md`](outputs/results.md).

| Strategy | Conversions | vs. equal split | Avg CPA | Budget to best channel |
|---|---:|---:|---:|---:|
| Oracle (upper bound) | 1188 | +18.9% | $25.25 | 81% |
| Thompson sampling | 1102 | +10.3% | $27.22 | 58% |
| Gemini agent (`gemini-3.5-flash-lite`) | 1064 | +6.5% | $28.20 | 49% |
| Heuristic agent | 1012 | +1.3% | $29.64 | 47% |
| Equal split (baseline) | 999 | — | $30.03 | 33% |

Gemini made all 28 post-warm-up decisions itself (0 fallbacks); its replies are cached in
`outputs/gemini_cache.json`, so `python evaluate.py --gemini-seeds 3` reproduces these numbers with no key.

**Same 3 markets, like-for-like:** Gemini **+5.8%**, heuristic +4.4%, Thompson +8.0%, oracle +19.0% vs. equal split.
**Across 20 markets** (no Gemini, to stay within free-tier limits): heuristic **+4.8%**, Thompson **+9.3%**,
oracle +18.7%. Every learning strategy also lowers the average CPA.

![Cumulative conversions](outputs/cumulative_conversions.png)
![Budget allocation over time](outputs/allocation_over_time.png)

**What we learned**
- Learning beats a static split, mainly by moving money out of Display (the highest CPA).
- Scoring on a 3-day window chased noise and barely beat the equal split. Recency-weighted scoring, plus a
  "hold unless the lead is ≥10%" rule, fixed most of that.
- The guardrails have a real cost. A channel pushed down to the 10% floor can only grow 20% a day, so after
  Social improves on day 16 the agent needs about a week to move real budget there. That accounts for most
  of the gap to the oracle. It's a deliberate trade: stability and safety over speed.
- Gemini beat the heuristic by keeping more money in Social early on (15–20% vs. the 10% floor), so it moved
  into Social sooner after day 16, and its rationales cite the right numbers. But it stayed cautious: it kept
  about a third of the budget in Search even when Social's CPA was half of Search's, which is why Thompson
  sampling still did better. The guardrails clipped 7 of its 28 proposals, each a move bigger than ±20% in a day.
- Free-tier limits matter: `gemini-3.6-flash` allows only 20 requests a day, less than one 30-day run, so the
  default is `gemini-3.5-flash-lite`. On a daily-quota error the agent stops calling and logs why, and the
  heuristic covers the remaining days.

## Also in this repo: customer service chatbot

[`chatbot/`](chatbot/README.md) is a separate assignment: a LangGraph multi-agent chatbot (order status,
refunds, product recommendations) with Gemini and `MemorySaver` conversation memory. Run
`python -m chatbot.chat`; see [`chatbot/README.md`](chatbot/README.md).

## Repo layout

```
adagent/            config, simulator, tools, guardrails, policies, llm (Gemini), agent loop
prompts/            system_prompt.md
data/               ad_performance.csv
outputs/            decisions_log.csv, daily_results.csv, results.md, summary.json, charts, gemini_cache.json
docs/               design_doc.md, scaling_note.md
tests/              guardrail tests
scripts/            build_notebook.py
chatbot/            customer service chatbot (separate assignment)
generate_data.py    propose.py    evaluate.py    notebook.ipynb
```
