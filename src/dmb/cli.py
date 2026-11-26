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
        "--add-split",
        metavar="NAME",
        help="Draw and freeze an extra test split (test2, test3...) from the train pool",
    )
    b.add_argument("--extra-size", type=int, default=config.N_TEST)
    b.add_argument(
        "--resample-splits",
        action="store_true",
        help="Re-sample dev/test, overwriting splits/*.txt. Refused once test.txt is committed.",
    )

    e = sub.add_parser("eval", help="Evaluate a matcher on a split")
    e.add_argument("--matcher", default="dummy")
    e.add_argument("--split", default="dev", help="dev, test or an extra test split (test2...)")
    e.add_argument("--final", action="store_true", help="Required to evaluate the test split")
    e.add_argument("--force-rerun", action="store_true", help="Allow a second test evaluation")
    e.add_argument("--limit", type=int, help="Only the first N queries (quick checks)")
    e.add_argument("--k", type=int, default=config.TOP_K)
    e.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Matcher setting, e.g. --param stage=1 (repeatable)",
    )
    e.add_argument(
        "--threshold-rule",
        default="point",
        choices=["point", "wilson"],
        help="How the accept threshold is chosen on dev: observed precision (point) or the "
        "Wilson 95%% lower bound of the precision (wilson)",
    )
    x = sub.add_parser("experiment", help="Dev-only experiments (ablations, scorers)")
    x.add_argument("--name", required=True, help="Cache and result name, e.g. base")
    x.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    x.add_argument("--ablate", action="store_true", help="Feature ablation (drop one at a time)")
    x.add_argument("--scorer", action="append", default=[], choices=["lr", "gb"])

    f = sub.add_parser("freeze", help="Freeze dev thresholds and data hashes before test")
    f.add_argument("--version", required=True)
    f.add_argument("--matcher", action="append", required=True, metavar="LABEL")

    c = sub.add_parser("compare", help="Paired comparison of matchers on one split")
    c.add_argument("--split", default="test")
    c.add_argument("--version", help="Check against results/<version>/freeze.json and save there")
    c.add_argument("--matcher", action="append", required=True, metavar="LABEL")
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
                add_split=args.add_split,
                extra_size=args.extra_size,
            )
        elif args.cmd == "eval":
            from dmb.evaluate import evaluate

            params = dict(p.split("=", 1) for p in args.param)
            evaluate(
                paths,
                args.matcher,
                args.split,
                args.final,
                args.force_rerun,
                args.limit,
                args.k,
                params=params,
                threshold_rule=args.threshold_rule,
            )
        elif args.cmd == "experiment":
            from dmb.experiments import run

            params = dict(p.split("=", 1) for p in args.param)
            run(paths, args.name, params, args.ablate, args.scorer or ["lr"])
        elif args.cmd == "freeze":
            from dmb.compare import freeze

            freeze(paths, args.version, args.matcher)
        elif args.cmd == "compare":
            import json

            from dmb.compare import compare

            report = compare(paths, args.matcher, args.split, args.version)
            print(
                json.dumps({"matchers": report["matchers"], "paired": report["paired"]}, indent=2)
            )
    except (OSError, RuntimeError, ValueError, NotImplementedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
