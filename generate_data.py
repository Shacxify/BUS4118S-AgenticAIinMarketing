"""Write the mock dataset: 30 days x 3 channels under an equal budget split.

    python generate_data.py            # -> data/ad_performance.csv
"""
import argparse
from pathlib import Path

from adagent import config
from adagent.simulator import generate_dataset


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--days", type=int, default=config.DAYS)
    ap.add_argument("--out", default="data/ad_performance.csv")
    args = ap.parse_args()

    df = generate_dataset(args.seed, args.days)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df)} rows ({args.days} days x {len(config.CHANNELS)} channels) to {args.out}")
    print(df.groupby("channel")[["spend", "clicks", "conversions"]].sum().assign(
        CPA=lambda t: (t.spend / t.conversions).round(2)))


if __name__ == "__main__":
    main()
