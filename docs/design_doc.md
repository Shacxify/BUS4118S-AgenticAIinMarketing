# Design Doc: Ad Optimization Agent

**Role.** Once a day, the agent splits a fixed ad budget ($1,000/day) across Search, Social and Display to
maximize total conversions at a reasonable CPA. It acts like a careful media buyer: it moves money toward
what is working, keeps every channel funded so it keeps learning, and explains each move in one sentence.

**Inputs.** A performance CSV (`date, channel, spend, impressions, clicks, conversions`), yesterday's
allocation, and the daily budget. The data is channel-level only, with no user-level or personal data.

**Outputs.** Tomorrow's dollars per channel, plus a log row per decision: proposed vs. final split, a
rationale string, which component decided (`gemini`, `heuristic fallback: <reason>`, `rule`), and any
guardrail edits. Example: *"Social +20% due to the most conversions per $100 (5.90 vs 3.94 for Search), CVR
5.4%, CPA $17 (recency-weighted). Display trimmed (CPA $43)."*

**Decision loop (tools).** `read_performance` (load and validate the CSV) → `compute_metrics` (CTR, CVR, CPA,
conversions per $100, recency-weighted) → **policy** proposes a split → `apply_guardrails` (hard limits) →
`check_rationale` (privacy and tone) → `log_decision`. Policies:
- **Gemini agent.** An LLM with a system prompt (`prompts/system_prompt.md`) that sees the metrics and
  returns JSON `{allocation, rationale, confidence}`. If there is no key, an API error, a malformed reply, or
  the call cap is hit, it falls back to the heuristic for that day.
- **Heuristic agent.** Rank channels by recency-weighted conversions per $100 (decay 0.6/day). If the leader
  is ≥10% ahead, boost it by 10–20% of its budget (more for a bigger lead), taken from the laggards;
  otherwise hold. The 10% floor is the exploration mechanism.
- **Thompson sampling.** A standard explore/exploit algorithm, used as a stronger comparison.

**Guardrails (enforced in code, not just requested in the prompt).**
| Rule | How it's enforced |
|---|---|
| Cost cap | Daily total always equals the budget exactly |
| Stability | Each channel moves at most ±20% vs. yesterday |
| Keep learning | Every channel keeps ≥10% of budget; a channel at $0 for 2 days gets 5% back |
| Privacy | Channel-level data only; emails and phone numbers are redacted from rationales; API key never logged |
| Brand tone | Rationales are neutral and factual, ≤280 chars; hype words ("guaranteed", "!!!") are stripped |
| LLM cost | ≤60 Gemini calls per run, throttled, responses cached |

Every edit is logged ("Search capped at +20% (proposed +200%)"), so a reviewer can see when the guardrails
overrode the model.

**Evaluation.** A seeded simulator gives each channel hidden true rates with diminishing returns, and on day
16 Social's conversion rate doubles. Every strategy faces identical noise. **Primary metric: total
conversions over 30 days** (and lift vs. an equal split). Secondary metrics: average CPA, CTR, CVR, share
of budget on the truly best channel, and regret vs. an oracle that knows the true rates. Results are
averaged over 20 market seeds.

**Known trade-off.** The ±20% cap and the 10% floor keep the agent from chasing noise, but they slow
recovery: a channel squeezed to the floor needs about a week to regain real budget after it improves.
This shows up as regret vs. the oracle.
