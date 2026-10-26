"""Read a performance CSV and propose tomorrow's budget per channel, with a logged rationale.

    python propose.py                                  # Gemini (falls back to heuristic with no key)
    python propose.py --policy heuristic
    python propose.py --csv data/ad_performance.csv --budget 1500
"""
import argparse
from datetime import date, timedelta

from adagent import config
from adagent.agent import decide_next
from adagent.policies import EqualSplit, HeuristicAgent, ThompsonAgent
from adagent.tools import compute_metrics, last_allocation, log_decision, read_performance


def make_policy(name):
    if name == "gemini":
        from adagent.llm import GeminiAgent
        return GeminiAgent()
    return {"heuristic": HeuristicAgent, "thompson": ThompsonAgent, "equal_split": EqualSplit}[name]()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="data/ad_performance.csv")
    ap.add_argument("--policy", default="gemini", choices=["gemini", "heuristic", "thompson", "equal_split"])
    ap.add_argument("--budget", type=float, default=config.DAILY_BUDGET)
    ap.add_argument("--log", default="outputs/proposals_log.csv")
    args = ap.parse_args()

    history = read_performance(args.csv)
    prev = last_allocation(history)
    # Scale yesterday's split to the requested budget so the +/-20% cap compares like with like.
    prev_total = sum(prev.values()) or 1.0
    prev = {c: v * args.budget / prev_total for c, v in prev.items()}
    zero_streak = {c: 0 for c in config.CHANNELS}
    for d in sorted(history.date.unique()):
        spent = history[history.date == d].set_index("channel").spend
        zero_streak = {c: zero_streak[c] + 1 if spent.get(c, 0) <= 0 else 0 for c in config.CHANNELS}

    policy = make_policy(args.policy)
    day = history.date.nunique()
    alloc, record = decide_next(policy, day, history, prev, zero_streak, args.budget)
    next_date = (date.fromisoformat(history.date.max()) + timedelta(days=1)).isoformat()
    record.update(run="propose", date=next_date)
    log_decision(args.log, record)

    m = compute_metrics(history)
    print(f"Read {len(history)} rows, {day} days ({history.date.min()} .. {history.date.max()}) from {args.csv}")
    print(f"\nLast {config.WINDOW} days:")
    print(m[["spend", "clicks", "conversions", "ctr", "cvr", "cpa"]].round(
        {"spend": 0, "ctr": 4, "cvr": 4, "cpa": 2}).to_string())
    print(f"\nProposed budget for {next_date} (policy: {policy.name}, source: {record['source']}):")
    for c in config.CHANNELS:
        change = (alloc[c] - prev[c]) / prev[c] if prev[c] else float("nan")
        print(f"  {c:<8} ${alloc[c]:>8,.2f}  ({alloc[c] / args.budget:5.1%} of budget, {change:+.0%} vs yesterday)")
    print(f"\nRationale: {record['rationale']}")
    if record["guardrail_notes"]:
        print(f"Guardrails: {record['guardrail_notes']}")
    print(f"\nLogged to {args.log}")


if __name__ == "__main__":
    main()
