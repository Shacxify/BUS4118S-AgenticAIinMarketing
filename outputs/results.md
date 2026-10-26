# Results

Main run: market seed 42, 30 days, $1,000/day,
3 channels. Social's conversion rate doubles on day 16.
All strategies face identical market noise (common random numbers).

| Strategy | Conversions | vs. equal split | Avg CPA | CTR | CVR | Budget to best channel | Regret vs. oracle | Guardrail edits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Oracle (upper bound) | 1188 | +18.9% | $25.25 | 1.03% | 4.36% | 81% | 0 | 0 |
| Gemini agent | 1064 | +6.5% | $28.20 | 0.75% | 3.43% | 49% | 124 | 7 |
| Heuristic agent | 1012 | +1.3% | $29.64 | 0.83% | 3.78% | 47% | 176 | 14 |
| Thompson sampling | 1102 | +10.3% | $27.22 | 0.74% | 3.48% | 58% | 86 | 20 |
| Equal split (baseline) | 999 | +0.0% | $30.03 | 0.61% | 2.64% | 33% | 189 | 0 |

Gemini made **28** of the 28 post-warm-up decisions in the main run; the heuristic fallback handled **0** (see the `source` column in `decisions_log.csv`).

## Robustness: 20 market seeds

Gemini runs on the first 3 seed(s) only, to stay within free-tier limits.

| strategy               |   Runs |   Conversions (mean) |   SD |   Lift vs. equal |   Avg CPA |   Regret (mean) |   Budget to best channel (%) |
|:-----------------------|-------:|---------------------:|-----:|-----------------:|----------:|----------------:|-----------------------------:|
| Oracle (upper bound)   |     20 |               1162   | 54.2 |             18.7 |      25.9 |             0   |                         81.4 |
| Gemini agent           |      3 |               1059   | 28.8 |              5.8 |      28.3 |           133   |                         49.1 |
| Heuristic agent        |     20 |               1025.3 | 47.6 |              4.8 |      29.3 |           136.7 |                         48.7 |
| Thompson sampling      |     20 |               1070   | 48.8 |              9.3 |      28.1 |            92   |                         55.6 |
| Equal split (baseline) |     20 |                978.8 | 35.3 |              0   |      30.7 |           183.2 |                         33.3 |

## Like-for-like: the 3 market(s) Gemini ran on

| strategy               |   Conversions (mean) |   Avg CPA |   Lift vs. equal (%) |
|:-----------------------|---------------------:|----------:|---------------------:|
| Oracle (upper bound)   |               1192   |      25.2 |                 19   |
| Gemini agent           |               1059   |      28.3 |                  5.8 |
| Heuristic agent        |               1045.7 |      28.7 |                  4.4 |
| Thompson sampling      |               1081.3 |      27.8 |                  8   |
| Equal split (baseline) |               1001.3 |      30   |                  0   |

"Regret" is conversions lost compared with the oracle, which knows the true rates and is not
bound by guardrails. "Budget to best channel" is the share of spend that went to the channel
with the most true conversions per dollar on that day.
