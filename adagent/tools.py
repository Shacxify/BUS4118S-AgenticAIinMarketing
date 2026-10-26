"""Agent tools: read performance data, score channels, and log decisions."""
import csv
import json
from pathlib import Path

import pandas as pd

from . import config

REQUIRED_COLUMNS = ["date", "channel", "spend", "impressions", "clicks", "conversions"]
LOG_FIELDS = ["run", "strategy", "day", "date", "source", *[f"proposed_{c}" for c in config.CHANNELS],
              *[f"final_{c}" for c in config.CHANNELS], "rationale", "guardrail_notes"]


def read_performance(path):
    """Load and validate a performance CSV (date,channel,spend,impressions,clicks,conversions)."""
    df = pd.read_csv(path)
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    df = df[REQUIRED_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for col in REQUIRED_COLUMNS[2:]:
        df[col] = pd.to_numeric(df[col], errors="raise").clip(lower=0)
    unknown = set(df["channel"]) - set(config.CHANNELS)
    if unknown:
        raise ValueError(f"Unknown channels in {path}: {sorted(unknown)}")
    return df.sort_values(["date", "channel"]).reset_index(drop=True)


def compute_metrics(history, window=config.WINDOW, decay=None):
    """Per-channel metrics over the last `window` dates in `history`.

    With `decay` set, all history is used instead, each day weighted by
    decay ** age (yesterday = 1, the day before = decay, ...), which is less
    noisy than a short window but still adapts when a channel changes.

    Returns a DataFrame indexed by channel with spend, clicks, conversions, CTR,
    CVR, CPA and conversions per $100 (the score the agent ranks on).
    """
    if history.empty:
        return pd.DataFrame(index=config.CHANNELS)
    dates = sorted(history["date"].unique())
    recent_dates = dates if decay else dates[-window:]
    recent = history[history["date"].isin(recent_dates)]
    cols = ["spend", "impressions", "clicks", "conversions"]
    if decay:
        age = {d: len(dates) - 1 - i for i, d in enumerate(dates)}
        w = recent["date"].map(lambda d: decay ** age[d])
        recent = recent.assign(**{c: recent[c] * w for c in cols})
    m = recent.groupby("channel")[cols].sum().reindex(config.CHANNELS, fill_value=0)
    m["ctr"] = m.clicks / m.impressions.where(m.impressions > 0)
    m["cvr"] = m.conversions / m.clicks.where(m.clicks > 0)
    m["cpa"] = m.spend / m.conversions.where(m.conversions > 0)
    m["conv_per_100"] = 100 * m.conversions / m.spend.where(m.spend > 0)
    m.attrs["dates"] = recent_dates
    return m


def last_allocation(history):
    """Dollar spend per channel on the most recent date in `history`."""
    last = history[history["date"] == history["date"].max()]
    return last.set_index("channel")["spend"].reindex(config.CHANNELS, fill_value=0.0).to_dict()


def metrics_summary(history, window=config.WINDOW):
    """A compact, JSON-friendly view of recent performance (what the LLM sees)."""
    m = compute_metrics(history, window)
    out = {}
    for ch in config.CHANNELS:
        row = m.loc[ch]
        daily = history[history.channel == ch].tail(7)
        out[ch] = {
            "spend": round(float(row.spend), 2),
            "clicks": int(row.clicks),
            "conversions": int(row.conversions),
            "ctr_pct": _round(row.ctr * 100, 2),
            "cvr_pct": _round(row.cvr * 100, 2),
            "cpa": _round(row.cpa, 2),
            "conversions_per_100_dollars": _round(row.conv_per_100, 2),
            "daily_cpa_last_7_days": [_round(s / c, 1) if c else None
                                      for s, c in zip(daily.spend, daily.conversions)],
        }
    return out


def _round(x, nd):
    return None if pd.isna(x) else round(float(x), nd)


def log_decision(path, record):
    """Append one decision record to a CSV log (header written on first use)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in record.items()})
