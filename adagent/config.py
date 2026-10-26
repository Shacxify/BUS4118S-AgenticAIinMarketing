"""Shared settings for the simulator, agent, and evaluation."""

CHANNELS = ["Search", "Social", "Display"]
DAILY_BUDGET = 1000.0          # dollars per day, split across channels
DAYS = 30                      # length of every simulated run
START_DATE = "2026-09-01"
SEED = 42                      # market seed used for the CSV and the main evaluation run

# Agent behaviour
WINDOW = 3                     # days shown in metric summaries (and used when DECAY is None)
DECAY = 0.6                    # score channels on all history, each day weighted 0.6**age
                               # (yesterday 1.0, 2 days ago 0.6, 3 days ago 0.36, ...)
MIN_SHIFT, MAX_SHIFT = 0.10, 0.20   # relative budget boost for the top channel
MIN_LEAD = 0.10                # leader must beat the runner-up by >=10% to trigger a shift
EXPLORE_RATE = 0.0             # chance of boosting a random non-leader. Off by default: the
                               # MIN_SHARE floor already keeps every channel learning, and
                               # random boosts cost ~2% conversions in testing (see README)

# Guardrails (enforced in code, whatever the policy proposes)
MAX_DAILY_CHANGE = 0.20        # each channel may move at most +/-20% vs. yesterday
MIN_SHARE = 0.10               # floor: every channel keeps >=10% of the budget
MAX_ZERO_DAYS = 2              # a channel may sit at $0 for at most 2 days in a row
REENTRY_SHARE = 0.05           # share given back to a channel after that limit
MAX_RATIONALE_CHARS = 280
