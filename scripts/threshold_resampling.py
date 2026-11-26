"""Resampling check of the threshold rules (v0.2.1, H7 in results/v0.2.1/plan.md).

The products of the given splits form a population, with the scores each model already gave
them; nothing is retrained. Each repetition draws a calibration sample of SAMPLE_SIZE products
with replacement from the population, picks the accept threshold with each rule, and measures
coverage, precision and acceptance of products not in the catalog on the whole population at
that threshold. The sample is i.i.d. from the population, so the guarantee of ltt and sgr
applies here as stated: the population precision falls below the target in at most RISK_DELTA
of the repetitions, up to Monte Carlo error.

Run from the repository root:
    python scripts/threshold_resampling.py dev test2    # pre-registered analysis (H7)
    python scripts/threshold_resampling.py dev          # dry run on dev only
Writes results/v0.2.1/resampling_<splits>.json.
"""

import json
import sys

import numpy as np

from dmb.compare import _load, latest_run
from dmb.config import Paths, write_json
from dmb.metrics import RISK_DELTA, _ltt, pick_threshold, pr_curve

SEED = 2026
REPETITIONS = 1000
SAMPLE_SIZE = 2000  # the size of dev, where the thresholds are picked
TARGET = 0.95
RULES = {
    "point": lambda curve: pick_threshold(curve, TARGET, "point"),
    "wilson": lambda curve: pick_threshold(curve, TARGET, "wilson"),
    "ltt": lambda curve: pick_threshold(curve, TARGET, "ltt"),
    "sgr": lambda curve: pick_threshold(curve, TARGET, "sgr"),
    # descriptive: on dev, the wilson rule accepted the same products as ltt at this level
    "ltt_delta_0.025": lambda curve: _ltt(curve, TARGET, delta=0.025),
}
MODELS = {
    "logistic regression (stage 5)": "rules-stage5@wilson",
    "gradient boosting (v0.2.0)": (
        "rules-dropexpected_form_missing-featuresv2-scorergb-stage5@wilson"
    ),
}


def population(paths: Paths, label: str, splits: list[str]):
    """The products of the splits with the scores of the model's latest full run on each."""
    expected, candidates = [], []
    for split in splits:
        run = latest_run(paths, label, split)
        if run is None:
            raise RuntimeError(f"No {split} run for {label}")
        _, e, c = _load(paths, run, split)
        expected += e
        candidates += c
    score = np.array([c[0][1] if c else -np.inf for c in candidates])
    right = np.array(
        [
            bool(c) and e is not None and c[0][0] == e
            for e, c in zip(expected, candidates, strict=True)
        ]
    )
    nil = np.array([e is None for e in expected])
    return expected, candidates, score, right, nil


def at_threshold(score, right, nil, threshold: float) -> dict:
    """What the whole population gets at this accept threshold."""
    accepted = score >= threshold
    n = int(accepted.sum())
    return {
        "threshold": float(threshold),
        "coverage": n / len(score),
        "precision": float(right[accepted].sum() / n) if n else None,
        "nil_accept_rate": float((accepted & nil).sum() / nil.sum()),
    }


def summarize(rows: list[dict | None]) -> dict:
    found = [r for r in rows if r is not None]
    coverage = [r["coverage"] if r else 0.0 for r in rows]
    precision = [r["precision"] for r in found]
    violations = sum(p < TARGET for p in precision) / len(rows)
    return {
        "violation_rate": violations,
        "violation_rate_mc_se": (violations * (1 - violations) / len(rows)) ** 0.5,
        "no_threshold_rate": 1 - len(found) / len(rows),
        "coverage_mean": float(np.mean(coverage)),
        "coverage_p2.5": float(np.percentile(coverage, 2.5)),
        "coverage_p97.5": float(np.percentile(coverage, 97.5)),
        "precision_mean": float(np.mean(precision)) if precision else None,
        "precision_p2.5": float(np.percentile(precision, 2.5)) if precision else None,
        "nil_accept_rate_mean": float(np.mean([r["nil_accept_rate"] if r else 0.0 for r in rows])),
    }


def main(splits: list[str]) -> None:
    paths = Paths.default()
    report = {
        "note": "Plan in results/v0.2.1/plan.md (H7).",
        "splits": splits,
        "seed": SEED,
        "repetitions": REPETITIONS,
        "sample_size": SAMPLE_SIZE,
        "target_precision": TARGET,
        "delta": RISK_DELTA,
        "models": {},
    }
    for model, label in MODELS.items():
        expected, candidates, score, right, nil = population(paths, label, splits)
        best = pick_threshold(pr_curve(expected, candidates), TARGET, "point")
        rng = np.random.default_rng(SEED)  # the same samples for every model
        rows = {rule: [] for rule in RULES}
        same, wilson_more = 0, 0
        for _ in range(REPETITIONS):
            idx = rng.integers(0, len(expected), SAMPLE_SIZE)
            curve = pr_curve([expected[i] for i in idx], [candidates[i] for i in idx])
            picked = {rule: pick(curve) for rule, pick in RULES.items()}
            for rule, op in picked.items():
                rows[rule].append(
                    None if op is None else at_threshold(score, right, nil, op["threshold"])
                )
            w, lt = picked["wilson"], picked["ltt_delta_0.025"]
            if w and lt:
                same += w["n_accepted"] == lt["n_accepted"]
                wilson_more += w["n_accepted"] > lt["n_accepted"]
        report["models"][model] = {
            "label": label,
            "population_size": len(expected),
            "population_not_in_catalog": int(nil.sum()),
            "population_best": at_threshold(score, right, nil, best["threshold"]),
            "rules": {rule: summarize(rows[rule]) for rule in RULES},
            "wilson_vs_ltt_delta_0.025": {
                "same_accepted_set": same / REPETITIONS,
                "wilson_accepts_more": wilson_more / REPETITIONS,
            },
        }
    out = paths.root / "results" / "v0.2.1" / f"resampling_{'_'.join(splits)}.json"
    write_json(out, report)
    print(json.dumps(report, indent=2))
    print(f"-> {out}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["dev"])
