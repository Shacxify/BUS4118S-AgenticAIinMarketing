"""The daily agent loop: observe -> decide -> enforce guardrails -> act -> log."""
import pandas as pd

from . import config
from .guardrails import apply_guardrails, check_rationale, update_zero_streak
from .policies import Proposal
from .simulator import Market, equal_split
from .tools import REQUIRED_COLUMNS, log_decision

WARMUP_DAYS = 2   # hold the equal split until there are 2 days of data to compare


def decide_next(policy, day, history, prev_alloc, zero_streak, budget=config.DAILY_BUDGET):
    """One decision: ask the policy, then guardrail the result. Returns (alloc, record)."""
    if day < WARMUP_DAYS or history["date"].nunique() < WARMUP_DAYS:
        proposal = Proposal({c: prev_alloc[c] / budget for c in config.CHANNELS},
                            "Warm-up: holding the current split while collecting data.", "warm-up")
    else:
        proposal = policy.decide(day, history, prev_alloc)

    if policy.guarded:
        alloc, notes = apply_guardrails(proposal.shares, prev_alloc, zero_streak, budget)
    else:
        total = sum(proposal.shares.values())
        alloc, notes = {c: round(budget * proposal.shares[c] / total, 2) for c in config.CHANNELS}, []
    rationale, tone_notes = check_rationale(proposal.rationale)

    record = {
        "strategy": policy.name,
        "day": day + 1,
        "source": proposal.source,
        **{f"proposed_{c}": round(budget * proposal.shares[c] / (sum(proposal.shares.values()) or 1), 2)
           for c in config.CHANNELS},
        **{f"final_{c}": alloc[c] for c in config.CHANNELS},
        "rationale": rationale,
        "guardrail_notes": " ".join(notes + tone_notes),
    }
    return alloc, record


def run_campaign(policy, market=None, days=config.DAYS, budget=config.DAILY_BUDGET,
                 log_path=None, run_id="", verbose=False):
    """Simulate `days` days of `policy` in `market`. Returns (performance df, decision records)."""
    market = market or Market()
    history = pd.DataFrame(columns=REQUIRED_COLUMNS)
    prev = equal_split(budget)
    zero_streak = {c: 0 for c in config.CHANNELS}
    records = []
    for day in range(days):
        alloc, record = decide_next(policy, day, history, prev, zero_streak, budget)
        rows = market.step(day, alloc)
        today = pd.DataFrame(rows)
        history = today if history.empty else pd.concat([history, today], ignore_index=True)
        zero_streak = update_zero_streak(zero_streak, alloc)
        record.update(run=run_id, date=market.date_of(day))
        records.append(record)
        if log_path:
            log_decision(log_path, record)
        if verbose:
            split = " ".join(f"{c[:3]} ${alloc[c]:>6.0f}" for c in config.CHANNELS)
            print(f"  day {day + 1:>2}  {split}  conv {today.conversions.sum():>3}  [{record['source']}]")
        prev = alloc
    return history, records
