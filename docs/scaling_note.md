# Scaling Note: running the agent reliably in the cloud

**Scheduling and idempotency.** Run the agent as a daily scheduled job (Cloud Scheduler → Cloud Run job,
or a GitHub Actions cron). Key each run by `date + account`, and write the decision before pushing budgets
to the ad platforms, so a retried job re-applies the same decision instead of making a new one.

**Retries and fallbacks.** Data pulls and ad-platform writes use exponential backoff with a retry limit.
After that the job fails loudly and keeps yesterday's budgets, which are always safe. LLM calls already
retry 429/5xx errors and fall back to the heuristic. In production the fallback rate is tracked and alerted
on, not hidden.

**Observability.** Emit structured logs (one JSON line per decision with run ID, model, prompt hash, proposed
vs. final split, guardrail edits, latency and tokens). Put on a dashboard: conversions, CPA per channel,
fallback rate, guardrail-edit rate, and LLM cost. Alert on missing data, a CPA spike above 2× the 7-day
median, a fallback rate above 20%, or any run that fails to finish.

**Cost caps.** Ad spend is hard-capped in code (daily total = budget) and again by a platform-side campaign
budget, as defense in depth. LLM spend is capped per run (≤60 calls today) and per month through billing
alerts and quotas. The cheapest capable model is the default, and responses are cached.

**Safety and change control.** Start in shadow mode: the agent logs proposals while humans keep control.
Then add human approval for moves above a threshold, then go autonomous. Keep secrets in a secret manager,
never in the repo. Version the system prompt and guardrail config, and replay them against the simulator
in CI before deploying.

**Data and privacy.** Ingest only aggregated channel metrics. Keep raw platform exports in a restricted
bucket with a retention limit, and never send personal data to the LLM.
