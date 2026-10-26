"""Hard guardrails. Every policy's proposal passes through here before it is spent.

Budget rules:
  * total spend always equals the daily budget (hard cost cap)
  * each channel moves at most +/-MAX_DAILY_CHANGE vs. yesterday
  * each channel keeps at least MIN_SHARE of the budget
  * a channel at $0 for MAX_ZERO_DAYS days in a row gets REENTRY_SHARE back
Rationale rules (privacy + brand tone):
  * no emails / phone numbers in logged text
  * no hype or absolute claims; capped length; never empty
"""
import math
import re

from . import config

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
HYPE = re.compile(r"\b(guarantee[ds]?|amazing|insane|crushing|explod\w*|skyrocket\w*|viral|best ever|"
                  r"can't lose|no[- ]brainer|100% sure)\b|!{2,}", re.IGNORECASE)


def apply_guardrails(proposed_shares, prev_alloc, zero_streak=None, budget=config.DAILY_BUDGET,
                     max_change=config.MAX_DAILY_CHANGE, min_share=config.MIN_SHARE):
    """Project a proposed split onto the allowed set.

    proposed_shares: channel -> share of budget (any non-negative weights; normalised here)
    prev_alloc:      channel -> dollars spent yesterday
    zero_streak:     channel -> consecutive days at $0 so far
    Returns (final dollars per channel, list of human-readable notes).
    """
    chans = config.CHANNELS
    zero_streak = zero_streak or {c: 0 for c in chans}
    notes = []

    w = {c: proposed_shares.get(c, 0.0) for c in chans}
    w = {c: (v if isinstance(v, (int, float)) and math.isfinite(v) and v > 0 else 0.0) for c, v in w.items()}
    if sum(w.values()) == 0:
        notes.append("Proposal was empty or invalid; kept yesterday's split.")
        w = {c: max(prev_alloc.get(c, 0.0), 0.0) for c in chans}
        if sum(w.values()) == 0:
            w = {c: 1.0 for c in chans}
    total_w = sum(w.values())
    target = {c: budget * w[c] / total_w for c in chans}

    lo, hi = {}, {}
    for c in chans:
        prev = max(prev_alloc.get(c, 0.0), 0.0)
        lo[c] = max(min_share * budget, prev * (1 - max_change))
        hi[c] = max(prev * (1 + max_change), config.REENTRY_SHARE * budget if prev == 0 else 0.0)
        if zero_streak.get(c, 0) >= config.MAX_ZERO_DAYS:
            lo[c] = max(lo[c], config.REENTRY_SHARE * budget)
            notes.append(f"{c} was at $0 for {zero_streak[c]} days; restored to at least "
                         f"{config.REENTRY_SHARE:.0%} to keep learning.")
        hi[c] = max(hi[c], lo[c])
    if sum(lo.values()) > budget:      # bounds can't all be met: shrink floors proportionally
        scale = budget / sum(lo.values())
        lo = {c: v * scale for c, v in lo.items()}
    if sum(hi.values()) < budget:      # caps too tight to spend the budget: widen proportionally
        scale = budget / sum(hi.values())
        hi = {c: v * scale for c, v in hi.items()}

    final = _project(target, lo, hi, budget)

    for c in chans:
        prev = prev_alloc.get(c, 0.0)
        if abs(final[c] - target[c]) < 0.5:
            continue
        want = _pct(target[c], prev)
        got = _pct(final[c], prev)
        if target[c] > final[c] and math.isclose(final[c], hi[c], abs_tol=0.5):
            notes.append(f"{c} capped at {got} (proposed {want}; max +{max_change:.0%}/day).")
        elif target[c] < final[c] and math.isclose(final[c], lo[c], abs_tol=0.5):
            why = (f"{min_share:.0%} floor" if math.isclose(lo[c], min_share * budget, abs_tol=0.5)
                   else f"max -{max_change:.0%}/day")
            notes.append(f"{c} held at {got} (proposed {want}; {why}).")
        else:
            notes.append(f"{c} rebalanced to {got} (proposed {want}) to keep total at ${budget:,.0f}.")
    return final, notes


def _project(target, lo, hi, budget):
    """Find x = clip(target + lam, lo, hi) with sum(x) == budget (bisection on lam)."""
    a, b = -budget, budget
    for _ in range(100):
        lam = (a + b) / 2
        s = sum(min(max(target[c] + lam, lo[c]), hi[c]) for c in target)
        if s > budget:
            b = lam
        else:
            a = lam
    x = {c: round(min(max(target[c] + lam, lo[c]), hi[c]), 2) for c in target}
    residual = round(budget - sum(x.values()), 2)
    if residual:
        big = max(x, key=x.get)
        x[big] = round(x[big] + residual, 2)
    return x


def _pct(new, prev):
    if prev <= 0:
        return f"${new:,.0f}"
    return f"{(new - prev) / prev:+.0%}"


def update_zero_streak(zero_streak, alloc):
    return {c: (zero_streak.get(c, 0) + 1 if alloc.get(c, 0) <= 0 else 0) for c in config.CHANNELS}


def check_rationale(text):
    """Enforce privacy and brand tone on a rationale string. Returns (clean_text, notes)."""
    notes = []
    text = " ".join(str(text or "").split())
    if EMAIL.search(text) or PHONE.search(text):
        text = PHONE.sub("[redacted]", EMAIL.sub("[redacted]", text))
        notes.append("Personal data removed from rationale.")
    if HYPE.search(text):
        text = HYPE.sub("", text)
        text = " ".join(text.split())
        notes.append("Hype wording removed from rationale (brand tone).")
    if len(text) > config.MAX_RATIONALE_CHARS:
        text = text[: config.MAX_RATIONALE_CHARS - 3].rstrip() + "..."
        notes.append("Rationale truncated.")
    if not text:
        text = "No rationale given."
        notes.append("Empty rationale.")
    return text, notes
