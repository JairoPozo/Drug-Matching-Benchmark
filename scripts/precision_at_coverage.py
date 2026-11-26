"""Precision of the products a method trusts most, at fixed coverages (v0.2.2, descriptive).

For each label, products are sorted by the score of their first candidate and the precision of
the top 5, 10, 20, 40 and 60% is reported. It shows how far a scorer is from a precision target
without choosing any threshold. Run from the repository root:
    python scripts/precision_at_coverage.py test2 rules-stage5@wilson <other labels>
Prints JSON; with --out, also writes it.
"""

import argparse
import json

from dmb.compare import _load, latest_run
from dmb.config import Paths, write_json

COVERAGES = (0.05, 0.10, 0.20, 0.40, 0.60)


def precision_at(paths: Paths, label: str, split: str) -> dict:
    run = latest_run(paths, label, split)
    if run is None:
        raise RuntimeError(f"No {split} run for {label}")
    _, expected, candidates = _load(paths, run, split)
    scored = sorted(
        (
            (c[0][1], e is not None and c[0][0] == e)
            for e, c in zip(expected, candidates, strict=True)
            if c
        ),
        key=lambda x: -x[0],
    )
    out = {}
    for cov in COVERAGES:
        k = round(cov * len(expected))
        top = scored[:k]
        out[f"{cov:.2f}"] = sum(ok for _, ok in top) / k if len(top) == k and k else None
    return {"run": run.name, "precision_at_coverage": out}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("split")
    parser.add_argument("labels", nargs="+")
    parser.add_argument("--out")
    args = parser.parse_args()
    paths = Paths.default()
    report = {label: precision_at(paths, label, args.split) for label in args.labels}
    print(json.dumps(report, indent=2))
    if args.out:
        write_json(paths.root / args.out, report)


if __name__ == "__main__":
    main()
