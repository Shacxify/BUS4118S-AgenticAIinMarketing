"""Guardrail tests: whatever a policy proposes, the spent budget must obey the rules."""
import math

import numpy as np
import pytest

from adagent import config
from adagent.guardrails import apply_guardrails, check_rationale

B = config.DAILY_BUDGET
EQUAL = {c: B / 3 for c in config.CHANNELS}


def assert_valid(final, prev):
    assert math.isclose(sum(final.values()), B, abs_tol=0.01)
    for c in config.CHANNELS:
        assert final[c] >= config.MIN_SHARE * B - 0.01
        if prev[c] > 0:
            assert final[c] <= prev[c] * (1 + config.MAX_DAILY_CHANGE) + 0.01
            assert final[c] >= min(prev[c] * (1 - config.MAX_DAILY_CHANGE), config.MIN_SHARE * B) - 0.01


def test_extreme_proposal_is_capped():
    final, notes = apply_guardrails({"Search": 1.0, "Social": 0.0, "Display": 0.0}, EQUAL)
    assert_valid(final, EQUAL)
    assert math.isclose(final["Search"], EQUAL["Search"] * 1.2, abs_tol=0.01)
    assert any("capped" in n for n in notes)


def test_floor_holds():
    prev = {"Search": 800.0, "Social": 100.0, "Display": 100.0}
    final, notes = apply_guardrails({"Search": 0.98, "Social": 0.01, "Display": 0.01}, prev)
    assert final["Social"] >= 100 - 0.01 and final["Display"] >= 100 - 0.01
    assert math.isclose(sum(final.values()), B, abs_tol=0.01)


def test_valid_proposal_passes_unchanged():
    final, notes = apply_guardrails({"Search": 0.38, "Social": 0.31, "Display": 0.31}, EQUAL)
    assert math.isclose(final["Search"], 380, abs_tol=0.01)
    assert notes == []


@pytest.mark.parametrize("bad", [{}, {"Search": float("nan")}, {"Search": -1, "Social": -2, "Display": -3}])
def test_garbage_keeps_yesterday(bad):
    final, notes = apply_guardrails(bad, EQUAL)
    assert_valid(final, EQUAL)
    assert notes and "invalid" in notes[0]


def test_random_proposals_always_valid():
    rng = np.random.default_rng(0)
    prev = dict(EQUAL)
    for _ in range(500):
        proposal = dict(zip(config.CHANNELS, rng.random(3) ** 3))
        final, _ = apply_guardrails(proposal, prev)
        assert_valid(final, prev)
        prev = final


def test_zero_channel_reenters_after_two_days():
    prev = {"Search": 600.0, "Social": 400.0, "Display": 0.0}
    final, notes = apply_guardrails({"Search": 0.6, "Social": 0.4, "Display": 0.0}, prev,
                                    zero_streak={"Search": 0, "Social": 0, "Display": 2}, min_share=0.0)
    assert final["Display"] >= config.REENTRY_SHARE * B - 0.01
    assert any("restored" in n for n in notes)


def test_rationale_redacts_pii_and_hype():
    text, notes = check_rationale("Amazing!!! Social is guaranteed to win, ask jane@example.com or 408-555-1234.")
    assert "@" not in text and "555" not in text
    assert "guaranteed" not in text.lower() and "!!" not in text
    assert len(notes) == 2


def test_rationale_length_cap():
    text, _ = check_rationale("x " * 500)
    assert len(text) <= config.MAX_RATIONALE_CHARS
