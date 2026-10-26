"""Evaluate every strategy on the same simulated market and save results + charts.

    python evaluate.py                    # main run (seed 42) + 20-seed robustness check
    python evaluate.py --seeds 50 --gemini-seeds 3

Outputs (in outputs/):
    decisions_log.csv        every daily decision: proposed vs final split, rationale, guardrail notes
    daily_results.csv        simulated performance rows per strategy/day/channel (main run)
    results.md               results tables (main run + multi-seed)
    summary.json             the same numbers, machine-readable
    allocation_over_time.png, cumulative_conversions.png, conversions_by_strategy.png
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from adagent import config
from adagent.agent import run_campaign
from adagent.llm import GeminiAgent
from adagent.policies import EqualSplit, HeuristicAgent, Oracle, ThompsonAgent
from adagent.simulator import SHIFT_DAY, Market

OUT = Path("outputs")
ORDER = ["oracle", "gemini", "heuristic", "thompson", "equal_split"]
LABELS = {"oracle": "Oracle (upper bound)", "gemini": "Gemini agent", "heuristic": "Heuristic agent",
          "thompson": "Thompson sampling", "equal_split": "Equal split (baseline)"}

# Reference palette (dataviz skill): first three categorical slots + neutral grays.
CHANNEL_COLORS = {"Search": "#2a78d6", "Social": "#eb6834", "Display": "#1baf7a"}
STRATEGY_STYLE = {
    "gemini":      dict(color="#2a78d6", lw=2),
    "heuristic":   dict(color="#eb6834", lw=2),
    "thompson":    dict(color="#1baf7a", lw=2),
    "equal_split": dict(color="#8a8984", lw=2, ls="--"),
    "oracle":      dict(color="#52514e", lw=2, ls=":"),
}
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def make_policies(market, include_gemini, seed):
    policies = [Oracle(market), EqualSplit(), HeuristicAgent(seed=seed), ThompsonAgent(seed=seed)]
    if include_gemini:
        policies.insert(1, GeminiAgent(seed=seed))
    return policies


def best_channel_by_day(market):
    """The channel with the most true conversions per $ at an equal-split spend."""
    spend = config.DAILY_BUDGET / len(config.CHANNELS)
    return {market.date_of(d): max(config.CHANNELS, key=lambda c: market.expected_conversions(d, c, spend))
            for d in range(config.DAYS)}


def summarize(perf, records, best):
    spend, conv = perf.spend.sum(), perf.conversions.sum()
    perf = perf.assign(is_best=[best[d] == c for d, c in zip(perf.date, perf.channel)])
    sources = pd.Series([r["source"] for r in records])
    return {
        "conversions": int(conv),
        "spend": round(float(spend), 2),
        "cpa": round(float(spend / conv), 2),
        "ctr_pct": round(float(100 * perf.clicks.sum() / perf.impressions.sum()), 3),
        "cvr_pct": round(float(100 * conv / perf.clicks.sum()), 3),
        "share_to_best_channel_pct": round(float(100 * perf[perf.is_best].spend.sum() / spend), 1),
        "guardrail_interventions": int(sum(bool(r["guardrail_notes"]) for r in records)),
        "llm_decisions": int(sources.str.startswith("gemini").sum()),
        "fallback_decisions": int(sources.str.startswith("heuristic fallback").sum()),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--seeds", type=int, default=20, help="market seeds for the robustness check")
    ap.add_argument("--gemini-seeds", type=int, default=1, help="how many of those seeds also run Gemini")
    ap.add_argument("--no-gemini", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    # ---- main run --------------------------------------------------------
    log_path = OUT / "decisions_log.csv"
    log_path.unlink(missing_ok=True)
    market = Market(args.seed)
    best = best_channel_by_day(market)
    perf_all, main = [], {}
    for policy in make_policies(market, not args.no_gemini, seed=args.seed):
        print(f"Running {policy.name} (seed {args.seed}) ...")
        perf, records = run_campaign(policy, market, log_path=log_path, run_id=f"seed{args.seed}")
        perf_all.append(perf.assign(strategy=policy.name))
        main[policy.name] = summarize(perf, records, best)
        if policy.name == "gemini":
            g = main["gemini"]
            print(f"  Gemini made {g['llm_decisions']} decisions; fallback on {g['fallback_decisions']}.")
    oracle_conv = main["oracle"]["conversions"]
    for s in main.values():
        s["regret_vs_oracle"] = oracle_conv - s["conversions"]
    daily = pd.concat(perf_all, ignore_index=True)
    daily.to_csv(OUT / "daily_results.csv", index=False)

    # ---- robustness: many market seeds ----------------------------------
    rows = []
    for i, seed in enumerate(range(args.seed, args.seed + args.seeds)):
        m = Market(seed)
        b = best_channel_by_day(m)
        include_gemini = not args.no_gemini and i < args.gemini_seeds
        for policy in make_policies(m, include_gemini, seed=seed):
            perf, records = run_campaign(policy, m)
            rows.append({"seed": seed, "strategy": policy.name, **summarize(perf, records, b)})
    multi = pd.DataFrame(rows)
    multi["regret_vs_oracle"] = multi.conversions - multi.seed.map(
        multi[multi.strategy == "oracle"].set_index("seed").conversions)
    multi["regret_vs_oracle"] *= -1
    agg = (multi.groupby("strategy")
           .agg(runs=("seed", "count"), conversions_mean=("conversions", "mean"),
                conversions_sd=("conversions", "std"), cpa_mean=("cpa", "mean"),
                regret_mean=("regret_vs_oracle", "mean"),
                share_to_best_pct=("share_to_best_channel_pct", "mean"))
           .reindex([s for s in ORDER if s in set(multi.strategy)]).round(1))
    eq = multi[multi.strategy == "equal_split"].set_index("seed").conversions
    lift = {s: round(float(100 * (multi[multi.strategy == s].set_index("seed").conversions / eq - 1).mean()), 1)
            for s in agg.index}
    agg["lift_vs_equal_pct"] = pd.Series(lift)

    # Like-for-like: every strategy on only the seeds Gemini ran on.
    h2h = None
    gem_seeds = multi[multi.strategy == "gemini"].seed
    if len(gem_seeds):
        same = multi[multi.seed.isin(gem_seeds)]
        h2h = same.groupby("strategy").agg(conversions_mean=("conversions", "mean"), cpa_mean=("cpa", "mean"))
        h2h = h2h.reindex([s for s in ORDER if s in h2h.index])
        h2h["lift_vs_equal_pct"] = 100 * (h2h.conversions_mean / h2h.loc["equal_split", "conversions_mean"] - 1)
        h2h = h2h.round(1)

    write_results(main, agg, args, h2h)
    plot_allocation(daily)
    plot_cumulative(daily, main)
    plot_bars(agg)
    print(f"\nWrote results to {OUT}/results.md")
    print(results_table(main))


def results_table(main):
    eq = main["equal_split"]["conversions"]
    lines = ["| Strategy | Conversions | vs. equal split | Avg CPA | CTR | CVR | Budget to best channel | "
             "Regret vs. oracle | Guardrail edits |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name in ORDER:
        if name not in main:
            continue
        s = main[name]
        lines.append(f"| {LABELS[name]} | {s['conversions']} | {100 * (s['conversions'] / eq - 1):+.1f}% | "
                     f"${s['cpa']:.2f} | {s['ctr_pct']:.2f}% | {s['cvr_pct']:.2f}% | "
                     f"{s['share_to_best_channel_pct']:.0f}% | {s['regret_vs_oracle']} | "
                     f"{s['guardrail_interventions']} |")
    return "\n".join(lines)


def write_results(main, agg, args, h2h=None):
    g = main.get("gemini")
    gemini_note = ""
    if g:
        gemini_note = (f"\nGemini made **{g['llm_decisions']}** of the {config.DAYS - 2} post-warm-up decisions"
                       f" in the main run; the heuristic fallback handled **{g['fallback_decisions']}**"
                       " (see the `source` column in `decisions_log.csv`).")
        if g["llm_decisions"] == 0:
            gemini_note += (" With no API key every Gemini decision fell back to the heuristic, so the"
                            " Gemini row matches the heuristic row.")
    multi_cols = ["runs", "conversions_mean", "conversions_sd", "lift_vs_equal_pct", "cpa_mean",
                  "regret_mean", "share_to_best_pct"]
    multi = agg[multi_cols].rename(index=LABELS).rename(columns={
        "runs": "Runs", "conversions_mean": "Conversions (mean)", "conversions_sd": "SD",
        "lift_vs_equal_pct": "Lift vs. equal", "cpa_mean": "Avg CPA", "regret_mean": "Regret (mean)",
        "share_to_best_pct": "Budget to best channel (%)"})
    h2h_text = ""
    if h2h is not None:
        table = h2h.rename(index=LABELS).rename(columns={
            "conversions_mean": "Conversions (mean)", "cpa_mean": "Avg CPA", "lift_vs_equal_pct": "Lift vs. equal (%)"})
        h2h_text = (f"\n## Like-for-like: the {args.gemini_seeds} market(s) Gemini ran on\n\n"
                    f"{table.to_markdown()}\n")
    text = f"""# Results

Main run: market seed {args.seed}, {config.DAYS} days, ${config.DAILY_BUDGET:,.0f}/day,
{len(config.CHANNELS)} channels. Social's conversion rate doubles on day {SHIFT_DAY + 1}.
All strategies face identical market noise (common random numbers).

{results_table(main)}
{gemini_note}

## Robustness: {args.seeds} market seeds

Gemini runs on the first {args.gemini_seeds} seed(s) only, to stay within free-tier limits.

{multi.to_markdown()}
{h2h_text}
"Regret" is conversions lost compared with the oracle, which knows the true rates and is not
bound by guardrails. "Budget to best channel" is the share of spend that went to the channel
with the most true conversions per dollar on that day.
"""
    (OUT / "results.md").write_text(text, encoding="utf-8")
    summary = {"main_run": main, "multi_seed": agg.reset_index().to_dict(orient="records")}
    if h2h is not None:
        summary["gemini_seeds_like_for_like"] = h2h.reset_index().to_dict(orient="records")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def plot_allocation(daily):
    strategies = [s for s in ["gemini", "heuristic", "thompson", "oracle"] if s in set(daily.strategy)]
    fig, axes = plt.subplots(1, len(strategies), figsize=(3.6 * len(strategies), 3.6), sharey=True,
                             facecolor=SURFACE)
    for ax, name in zip(np.atleast_1d(axes), strategies):
        d = daily[daily.strategy == name].pivot(index="date", columns="channel", values="spend")[config.CHANNELS]
        shares = d.div(d.sum(axis=1), axis=0) * 100
        x = np.arange(1, len(shares) + 1)
        ax.stackplot(x, *[shares[c] for c in config.CHANNELS], colors=[CHANNEL_COLORS[c] for c in config.CHANNELS],
                     edgecolor=SURFACE, linewidth=1.5, labels=config.CHANNELS)
        ax.axvline(SHIFT_DAY + 1, color=INK, lw=1, ls="--")
        ax.text(SHIFT_DAY + 1.4, 97, "Social CVR\ndoubles", va="top", fontsize=8, color=INK,
                bbox=dict(boxstyle="round,pad=0.2", fc=SURFACE, ec="none", alpha=0.85))
        ax.set_title(LABELS[name], fontsize=10, color=INK, loc="left")
        ax.set_xlim(1, len(shares))
        ax.set_ylim(0, 100)
        ax.set_xlabel("Day", fontsize=9, color=INK_2)
        _style(ax)
    np.atleast_1d(axes)[0].set_ylabel("Share of daily budget (%)", fontsize=9, color=INK_2)
    handles, labels = np.atleast_1d(axes)[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", ncol=3, frameon=False, fontsize=9)
    fig.suptitle("Budget allocation over time", x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT / "allocation_over_time.png", dpi=160)
    plt.close(fig)


def plot_cumulative(daily, main):
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor=SURFACE)
    ends = []
    for name in ORDER:
        if name not in main:
            continue
        d = daily[daily.strategy == name].groupby("date").conversions.sum().cumsum()
        x = np.arange(1, len(d) + 1)
        ax.plot(x, d.values, label=LABELS[name], **STRATEGY_STYLE[name])
        ends.append((d.values[-1], name))
    # Direct labels at the line ends, nudged apart so they don't collide.
    ends.sort()
    gap = 0.05 * max(y for y, _ in ends)
    placed = []
    for y, name in ends:
        y_lab = max([y] + [p + gap for p in placed[-1:]])
        placed.append(y_lab)
        ax.text(len(x) + 0.4, y_lab, f"{LABELS[name].split(' (')[0]}  {int(y)}", va="center",
                fontsize=8.5, color=INK)
    ax.axvline(SHIFT_DAY + 1, color=INK_2, lw=1, ls="--")
    ax.text(SHIFT_DAY + 1.3, ax.get_ylim()[1] * 0.04, "Social CVR doubles", fontsize=8, color=INK_2)
    ax.set_xlim(1, len(x) + 7)
    ax.set_xlabel("Day", fontsize=9, color=INK_2)
    ax.set_ylabel("Cumulative conversions", fontsize=9, color=INK_2)
    ax.set_title("Cumulative conversions by strategy (main run)", loc="left", fontsize=12, color=INK)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "cumulative_conversions.png", dpi=160)
    plt.close(fig)


def plot_bars(agg):
    names = [s for s in ORDER if s in agg.index][::-1]
    fig, ax = plt.subplots(figsize=(8, 3.6), facecolor=SURFACE)
    vals = agg.loc[names, "conversions_mean"]
    sds = agg.loc[names, "conversions_sd"].fillna(0)   # a strategy run on one seed has no SD
    ax.barh([LABELS[n] for n in names], vals, xerr=sds, height=0.6,
            color=[STRATEGY_STYLE[n]["color"] for n in names], edgecolor=SURFACE, lw=2,
            error_kw=dict(ecolor=INK_2, lw=1, capsize=3))
    for i, n in enumerate(names):
        lift = agg.loc[n, "lift_vs_equal_pct"]
        runs = int(agg.loc[n, "runs"])
        tag = "" if n == "equal_split" else f"  ({lift:+.1f}% vs. equal)"
        if runs < agg["runs"].max():
            tag += f"  [{runs} run{'s' if runs > 1 else ''}]"
        ax.text(vals[n] + sds[n] + 8, i, f"{vals[n]:.0f}{tag}", va="center", fontsize=8.5, color=INK)
    ax.set_xlim(0, vals.max() * 1.3)
    ax.set_xlabel("Total conversions over 30 days (mean ± SD across seeds)", fontsize=9, color=INK_2)
    runs = int(agg["runs"].max())
    ax.set_title(f"Conversions by strategy, up to {runs} simulated markets", loc="left", fontsize=12, color=INK)
    _style(ax)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(OUT / "conversions_by_strategy.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
