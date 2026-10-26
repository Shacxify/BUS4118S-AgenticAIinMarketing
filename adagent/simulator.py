"""A small, seeded ad market used to generate mock data and to test policies.

A plain CSV only records what happened under the budget that was actually run,
so it cannot say what Social would have done with more money. This simulator
gives every channel hidden "true" rates, so any allocation can be scored fairly.

Response model per channel and day:
    clicks      ~ Poisson( spend / cpc / (1 + spend / saturation) )   # diminishing returns
    impressions ~ Poisson( clicks / ctr )
    conversions ~ Binomial( clicks, cvr )
cpc and cvr also get a small daily multiplicative noise. The noise for a given
(seed, day, channel) is identical for every policy (common random numbers), so
differences between policies come from their decisions, not luck.

On SHIFT_DAY, Social's conversion rate doubles (e.g. a new creative launches),
which changes the best channel mid-run. A good agent has to notice.
"""
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config

SHIFT_DAY = 15
NOISE_SIGMA = 0.15


@dataclass(frozen=True)
class ChannelParams:
    cpc: float          # cost per click at low spend ($)
    ctr: float          # clicks / impressions
    cvr: float          # conversions / clicks
    saturation: float   # spend ($) at which click efficiency halves


BASE_PARAMS = {
    "Search":  ChannelParams(cpc=1.60, ctr=0.040, cvr=0.060, saturation=2500),
    "Social":  ChannelParams(cpc=0.80, ctr=0.012, cvr=0.020, saturation=3000),
    "Display": ChannelParams(cpc=0.50, ctr=0.004, cvr=0.012, saturation=3000),
}
SOCIAL_CVR_AFTER_SHIFT = 0.050


class Market:
    def __init__(self, seed=config.SEED, start_date=config.START_DATE):
        self.seed = seed
        self.start = date.fromisoformat(start_date)

    def date_of(self, day):
        return (self.start + timedelta(days=day)).isoformat()

    def true_params(self, day, channel):
        p = BASE_PARAMS[channel]
        if channel == "Social" and day >= SHIFT_DAY:
            p = ChannelParams(p.cpc, p.ctr, SOCIAL_CVR_AFTER_SHIFT, p.saturation)
        return p

    def expected_conversions(self, day, channel, spend):
        """Noise-free conversions for a given spend; used by the oracle."""
        p = self.true_params(day, channel)
        clicks = spend / p.cpc / (1 + spend / p.saturation)
        return clicks * p.cvr

    def step(self, day, allocation):
        """Run one day. `allocation` maps channel -> dollars. Returns CSV-shaped rows."""
        rows = []
        for i, channel in enumerate(config.CHANNELS):
            p = self.true_params(day, channel)
            rng = np.random.default_rng([self.seed, day, i])
            cpc = p.cpc * rng.lognormal(0, NOISE_SIGMA)
            cvr = min(p.cvr * rng.lognormal(0, NOISE_SIGMA), 1.0)
            spend = float(allocation.get(channel, 0.0))
            clicks = int(rng.poisson(spend / cpc / (1 + spend / p.saturation))) if spend > 0 else 0
            impressions = int(rng.poisson(clicks / p.ctr)) if clicks > 0 else 0
            conversions = int(rng.binomial(clicks, cvr)) if clicks > 0 else 0
            rows.append({
                "date": self.date_of(day),
                "channel": channel,
                "spend": round(spend, 2),
                "impressions": impressions,
                "clicks": clicks,
                "conversions": conversions,
            })
        return rows


def equal_split(budget=config.DAILY_BUDGET):
    share = budget / len(config.CHANNELS)
    return {c: share for c in config.CHANNELS}


def generate_dataset(seed=config.SEED, days=config.DAYS):
    """The mock dataset: what an equal-split campaign produced over `days` days."""
    market = Market(seed)
    rows = []
    for day in range(days):
        rows.extend(market.step(day, equal_split()))
    return pd.DataFrame(rows)
