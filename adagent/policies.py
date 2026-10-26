"""Budget policies. Each one looks at past performance and proposes tomorrow's split.

All policies share one interface:
    decide(day, history, prev_alloc) -> Proposal(shares, rationale, source)
`shares` maps channel -> fraction of budget. Guardrails are applied afterwards by
the agent loop, so a policy can propose anything; only the guarded result is spent.
"""
from dataclasses import dataclass
from itertools import product

import numpy as np

from . import config
from .tools import compute_metrics


@dataclass
class Proposal:
    shares: dict
    rationale: str
    source: str


def _shares(alloc):
    total = sum(alloc.values()) or 1.0
    return {c: alloc.get(c, 0.0) / total for c in config.CHANNELS}


class EqualSplit:
    name = "equal_split"
    guarded = True

    def decide(self, day, history, prev_alloc):
        return Proposal({c: 1 / len(config.CHANNELS) for c in config.CHANNELS},
                        "Baseline: equal split across channels.", "rule")


class HeuristicAgent:
    """Explore/exploit rule: boost the channel with the most conversions per dollar.

    Channels are scored on recency-weighted history (DECAY), which is less noisy
    than a 3-day window but still reacts within a few days when a channel changes.
    If the leader beats the runner-up by at least MIN_LEAD, it gets a boost of
    10-20% of its current budget (larger for a larger lead); otherwise the split is
    held so the agent doesn't chase noise. Donor channels give up budget in
    proportion to how far behind they are. The MIN_SHARE floor keeps every channel
    funded so the agent keeps learning; optional random exploration (EXPLORE_RATE)
    boosts a non-leader instead.
    """
    name = "heuristic"
    guarded = True

    def __init__(self, explore_rate=config.EXPLORE_RATE, window=config.WINDOW, min_lead=config.MIN_LEAD,
                 decay=config.DECAY, seed=0):
        self.explore_rate = explore_rate
        self.window = window
        self.min_lead = min_lead
        self.decay = decay
        self.rng = np.random.default_rng(seed)

    def decide(self, day, history, prev_alloc):
        m = compute_metrics(history, self.window, self.decay)
        score = m["conv_per_100"].fillna(0.0)
        ranked = score.sort_values(ascending=False)
        top, runner_up = ranked.index[0], ranked.index[1]
        lead = (ranked[top] - ranked[runner_up]) / ranked[runner_up] if ranked[runner_up] > 0 else 1.0
        shift = float(np.clip(config.MIN_SHIFT + 0.5 * lead, config.MIN_SHIFT, config.MAX_SHIFT))

        exploring = self.rng.random() < self.explore_rate
        target = self.rng.choice([c for c in config.CHANNELS if c != top]) if exploring else top
        window = "recency-weighted" if self.decay else f"last {len(m.attrs['dates'])} days"

        alloc = {c: float(prev_alloc[c]) for c in config.CHANNELS}
        if not exploring and lead < self.min_lead:
            return Proposal(_shares(alloc), f"Holding split: no clear leader ({top} {score[top]:.2f} vs "
                                            f"{runner_up} {score[runner_up]:.2f} conversions per $100, {window}).",
                            "rule")
        add = alloc[target] * shift
        donors = [c for c in config.CHANNELS if c != target]
        weights = {d: alloc[d] * max(ranked[top] - score[d], 1e-6) for d in donors}
        for d in donors:
            alloc[d] -= add * weights[d] / sum(weights.values())
        alloc[target] += add

        worst = ranked.index[-1]
        t, w = m.loc[target], m.loc[worst]
        if exploring:
            why = (f"Exploration: {target} +{shift:.0%} to keep learning "
                   f"(CPA {_money(t.cpa)} vs leader {top} {_money(m.loc[top].cpa)}, {window}).")
        else:
            why = (f"{top} +{shift:.0%} due to the most conversions per $100 "
                   f"({score[top]:.2f} vs {score[runner_up]:.2f} for {runner_up}), "
                   f"CVR {t.cvr:.1%}, CPA {_money(t.cpa)} ({window}).")
            if worst != top:
                why += f" {worst} trimmed (CPA {_money(w.cpa)})."
        return Proposal(_shares(alloc), why, "rule")


def _money(x):
    return "n/a" if np.isnan(x) else f"${x:.0f}"


class ThompsonAgent:
    """Thompson sampling with forgetting, as a standard explore/exploit comparison.

    Each channel's conversions per $100 gets a Gamma posterior built from
    discounted history (older days count less, so the agent adapts to change).
    The budget follows each channel's probability of being best, above a floor.
    """
    name = "thompson"
    guarded = True

    def __init__(self, decay=0.8, draws=4000, seed=0):
        self.decay = decay
        self.draws = draws
        self.rng = np.random.default_rng(seed)

    def decide(self, day, history, prev_alloc):
        dates = sorted(history["date"].unique())
        age = {d: len(dates) - 1 - i for i, d in enumerate(dates)}
        h = history.assign(w=history["date"].map(lambda d: self.decay ** age[d]))
        alpha = 1 + (h.w * h.conversions).groupby(h.channel).sum().reindex(config.CHANNELS, fill_value=0)
        beta = 1 + (h.w * h.spend / 100).groupby(h.channel).sum().reindex(config.CHANNELS, fill_value=0)
        samples = self.rng.gamma(alpha.values, 1 / beta.values, size=(self.draws, len(config.CHANNELS)))
        p_best = np.bincount(samples.argmax(axis=1), minlength=len(config.CHANNELS)) / self.draws
        free = 1 - config.MIN_SHARE * len(config.CHANNELS)
        shares = {c: config.MIN_SHARE + free * p for c, p in zip(config.CHANNELS, p_best)}
        probs = ", ".join(f"{c} {p:.0%}" for c, p in zip(config.CHANNELS, p_best))
        return Proposal(shares, f"Thompson sampling: P(best) {probs}; budget follows P(best) "
                                f"above a {config.MIN_SHARE:.0%} floor.", "rule")


class Oracle:
    """Upper bound: knows the market's true rates and picks the best split each day.

    Not a real strategy (nobody knows the true rates) and not guardrailed; it only
    sets the ceiling that regret is measured against.
    """
    name = "oracle"
    guarded = False

    def __init__(self, market, budget=config.DAILY_BUDGET, step=0.01):
        self.market = market
        self.budget = budget
        n = round(1 / step)
        self.grid = [(i * step, j * step, (n - i - j) * step)
                     for i, j in product(range(n + 1), repeat=2) if i + j <= n]

    def decide(self, day, history, prev_alloc):
        def value(split):
            return sum(self.market.expected_conversions(day, c, s * self.budget)
                       for c, s in zip(config.CHANNELS, split))
        best = max(self.grid, key=value)
        shares = dict(zip(config.CHANNELS, best))
        desc = ", ".join(f"{c} {s:.0%}" for c, s in shares.items())
        return Proposal(shares, f"Oracle (knows true rates): {desc}.", "oracle")
