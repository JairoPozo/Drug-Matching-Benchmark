"""Command line: `dmb download | build | eval`."""

from __future__ import annotations

import argparse
import sys

from dmb import config
from dmb.config import Paths


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dmb", description="Drug matching benchmark")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="Download NDC and RxNorm into data/raw")
    d.add_argument(
        "--rxnorm-release",
        help="RxNorm prescribe release MMDDYYYY (default: sources.json, else latest)",
    )
    d.add_argument("--force", action="store_true", help="Re-download even if files exist")

    b = sub.add_parser("build", help="Build catalog, queries, labels and splits")
    b.add_argument("--seed", type=int, default=config.SEED)
    b.add_argument("--n-dev", type=int, default=config.N_DEV)
    b.add_argument("--n-test", type=int, default=config.N_TEST)
    b.add_argument("--holdout-frac", type=float, default=config.HOLDOUT_FRAC)
    b.add_argument(
        "--resample-splits",
        action="store_true",
        help="Re-sample dev/test, overwriting splits/*.txt. Refused once test.txt is committed.",
    )

    e = sub.add_parser("eval", help="Evaluate a matcher on a split")
    e.add_argument("--matcher", default="dummy")
    e.add_argument("--split", default="dev", choices=["dev", "test"])
    e.add_argument("--final", action="store_true", help="Required to evaluate the test split")
    e.add_argument("--force-rerun", action="store_true", help="Allow a second test evaluation")
    e.add_argument("--limit", type=int, help="Only the first N queries (quick checks)")
    e.add_argument("--k", type=int, default=config.TOP_K)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = Paths.default()
    try:
        if args.cmd == "download":
            from dmb.download import run

            run(paths, rxnorm_release=args.rxnorm_release, force=args.force)
        elif args.cmd == "build":
            from dmb.build import build

            build(
                paths,
                args.seed,
                args.n_dev,
                args.n_test,
                args.holdout_frac,
                resample_splits=args.resample_splits,
            )
        elif args.cmd == "eval":
            from dmb.evaluate import evaluate

            evaluate(
                paths, args.matcher, args.split, args.final, args.force_rerun, args.limit, args.k
            )
    except (OSError, RuntimeError, ValueError, NotImplementedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
