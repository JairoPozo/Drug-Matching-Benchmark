"""Freeze what will be evaluated on test, and compare matchers on the same products.

freeze   Before test: copy each matcher's dev reference run (thresholds, coefficients) into
         results/<version>/ and record sha256 hashes of the data and splits. Commit and tag it;
         after that, nothing seen on test may change thresholds, rules or coefficients.
compare  Paired comparison on one split: every matcher is scored on the same products with the
         thresholds fixed on dev. Reports a Wilson 95% interval for the precision of automatic
         accepts, McNemar's exact test on top-1 correctness and on accepting products that are
         not in the catalog, paired bootstrap 95% intervals for the differences in coverage,
         accuracy and the NIL accept rate, and the transitions between decision bands (how many
         products move from review to accept, and how many stop being accepted). If a freeze
         exists, checks that the data hashes and the dev reference runs are the frozen ones.
"""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from dmb.config import QUERY_FORMAT_VERSION, SEED, SPLIT_METHOD, Paths, read_json, write_json
from dmb.metrics import calibration, decision_bands, decision_metrics, ranking_metrics, wilson

N_BOOTSTRAP = 2000


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def frozen_files(paths: Paths) -> list[Path]:
    files = sorted(paths.splits.glob("*.txt")) + [paths.splits / "meta.json"]
    files += sorted(paths.processed.glob("*.parquet")) + [paths.processed / "build_stats.json"]
    files += [paths.manifest, paths.sources_file]
    return [f for f in files if f.exists()]


def file_hashes(paths: Paths) -> dict[str, str]:
    return {f.relative_to(paths.root).as_posix(): _sha256(f) for f in frozen_files(paths)}


def latest_run(paths: Paths, label: str, split: str) -> Path | None:
    runs = sorted(paths.reports.glob(f"*_{label}_{split}/metrics.json"))
    full = [r for r in runs if not (read_json(r, {}) or {}).get("limit")]
    return full[-1].parent if full else None


def freeze(paths: Paths, version: str, labels: list[str], log=print) -> Path:
    out = paths.root / "results" / version
    if (out / "freeze.json").exists():
        raise RuntimeError(f"{out / 'freeze.json'} already exists: a freeze is never overwritten")
    matchers = {}
    for label in labels:
        run = latest_run(paths, label, "dev")
        if run is None:
            raise RuntimeError(f"No full dev run for {label}: evaluate it on dev first")
        m = read_json(run / "metrics.json")
        write_json(out / "dev" / f"{label}.json", m)
        matchers[label] = {
            "dev_run": run.name,
            "t_accept_95": (m.get("at_target_precision") or {}).get("threshold"),
            "t_best_f1": (m.get("at_best_f1") or {}).get("threshold"),
            "t_abstain": (m.get("bands") or {}).get("t_abstain"),
            "coefficients": (m.get("training") or {}).get("coefficients"),
        }
    write_json(
        out / "freeze.json",
        {
            "version": version,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "query_format": QUERY_FORMAT_VERSION,
            "split_method": SPLIT_METHOD,
            "matchers": matchers,
            "files_sha256": file_hashes(paths),
        },
    )
    log(f"[freeze] {len(labels)} matchers and {len(file_hashes(paths))} data files -> {out}")
    return out


# ---------------------------------------------------------------------------------------------
def mcnemar_p(a: list[bool], b: list[bool]) -> float:
    """Exact two-sided McNemar test on paired right/wrong outcomes."""
    from scipy.stats import binomtest

    only_a = sum(x and not y for x, y in zip(a, b, strict=True))
    only_b = sum(y and not x for x, y in zip(a, b, strict=True))
    if only_a + only_b == 0:
        return 1.0
    return float(binomtest(only_a, only_a + only_b, 0.5).pvalue)


def bootstrap_diff(a: list[float], b: list[float], seed: int = SEED) -> tuple[float, float, float]:
    """Mean of b - a with a paired bootstrap 95% interval (products resampled together)."""
    n = len(a)
    rng = random.Random(seed)
    diffs = []
    for _ in range(N_BOOTSTRAP):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(b[i] - a[i] for i in idx) / n)
    diffs.sort()
    point = sum(y - x for x, y in zip(a, b, strict=True)) / n
    return point, diffs[int(0.025 * N_BOOTSTRAP)], diffs[int(0.975 * N_BOOTSTRAP) - 1]


def _load(paths: Paths, run: Path, split: str):
    split_df = pl.read_parquet(paths.processed / f"{split}.parquet").select(
        "product_ndc", "expected_rxcui"
    )
    preds = pl.read_parquet(run / "predictions.parquet").sort("product_ndc", "rank")
    cands: dict[str, list] = {}
    for ndc, rxcui, score in preds.select("product_ndc", "rxcui", "score").iter_rows():
        cands.setdefault(ndc, []).append((rxcui, score))
    ids = split_df["product_ndc"].to_list()
    return ids, split_df["expected_rxcui"].to_list(), [cands.get(i, []) for i in ids]


def _summary(m: dict, expected, candidates) -> dict:
    t95 = (m.get("at_target_precision") or {}).get("threshold")
    t_abstain = (m.get("bands") or {}).get("t_abstain")
    n_nil = sum(e is None for e in expected)
    out = {
        "accuracy@1": ranking_metrics(expected, candidates, ks=(1, 5))["accuracy@1"],
        "recall@5": ranking_metrics(expected, candidates, ks=(1, 5))["recall@5"],
        **{k: calibration(expected, candidates)[k] for k in ("ece", "brier")},
        "t_accept_95": t95,
        "t_abstain": t_abstain,
    }
    if t95 is None:
        return out
    d = decision_metrics(expected, candidates, t95)
    c = d["counts"]
    accepted, right = d["n_accepted"], c["correct_accept"]
    bands = decision_bands(expected, candidates, t95, t_abstain)
    abstain = bands["abstain"]
    out |= {
        "n_nil": n_nil,
        "nil_accept_rate": c["accept_on_nil"] / n_nil if n_nil else None,
        "coverage": d["coverage"],
        "accepted": accepted,
        "accept_precision": d["accept_precision"],
        "accept_precision_ci95": wilson(right, accepted),
        "false_accepts": c["wrong_accept"] + c["accept_on_nil"],
        "false_accepts_on_nil": c["accept_on_nil"],
        "nil_not_accepted": (n_nil - c["accept_on_nil"]) / n_nil if n_nil else None,
        "review_share": bands["review"]["share"],
        "review_answer_in_top5": bands["review"]["answer_in_top5"],
        "abstain_share": abstain["share"],
        "abstain_not_in_catalog": abstain["n_nil"],
        "abstain_in_catalog": abstain["n"] - abstain["n_nil"],
    }
    return out


def band_of(candidates: list, t_accept: float | None, t_abstain: float | None) -> str:
    """accept / review / abstain, as in metrics.decision_bands."""
    if not candidates:
        return "abstain"
    score = candidates[0][1]
    if t_accept is not None and score >= t_accept:
        return "accept"
    floor = (
        min(t_abstain, t_accept) if t_abstain is not None and t_accept is not None else t_abstain
    )
    if floor is not None and score < floor:
        return "abstain"
    return "review"


def transitions(bands_a: list[str], bands_b: list[str], right_b: list[bool]) -> dict:
    """How products move between decision bands from method a to method b."""
    moves: dict[str, int] = {}
    for x, y in zip(bands_a, bands_b, strict=True):
        moves[f"{x}->{y}"] = moves.get(f"{x}->{y}", 0) + 1
    new = [i for i, (x, y) in enumerate(zip(bands_a, bands_b, strict=True)) if x != "accept" == y]
    return {
        "moves": dict(sorted(moves.items())),
        "newly_accepted": len(new),
        "newly_accepted_right": sum(right_b[i] for i in new),
        "no_longer_accepted": sum(
            x == "accept" != y for x, y in zip(bands_a, bands_b, strict=True)
        ),
    }


def compare(paths: Paths, labels: list[str], split: str, version: str | None, log=print) -> dict:
    frozen = read_json(paths.root / "results" / version / "freeze.json") if version else None
    checks = []
    if frozen:
        changed = [f for f, h in file_hashes(paths).items() if frozen["files_sha256"].get(f) != h]
        checks.append(("data and splits match the freeze", not changed, changed))
    results, per_product = {}, {}
    ids_ref = None
    for label in labels:
        run = latest_run(paths, label, split)
        if run is None:
            raise RuntimeError(f"No {split} run for {label}")
        m = read_json(run / "metrics.json")
        ids, expected, candidates = _load(paths, run, split)
        if ids_ref is not None and ids != ids_ref:
            raise RuntimeError("Runs are not on the same products")
        ids_ref = ids
        if frozen and split.startswith("test"):
            want = frozen["matchers"][label]["dev_run"]
            checks.append(
                (f"{label} used the frozen dev thresholds", m["thresholds_from"] == want, want)
            )
            coef = frozen["matchers"][label].get("coefficients")
            if coef:
                same = (m.get("training") or {}).get("coefficients") == coef
                checks.append((f"{label} coefficients equal the frozen ones", same, None))
        results[label] = {"run": run.name, **_summary(m, expected, candidates)}
        t95 = results[label]["t_accept_95"]
        t_abs = results[label]["t_abstain"]
        answerable = [e is not None for e in expected]
        per_product[label] = {
            "answerable": answerable,
            "bands": [band_of(c, t95, t_abs) for c in candidates],
            "top1": [
                bool(c) and e is not None and c[0][0] == e
                for e, c in zip(expected, candidates, strict=True)
            ],
            "accepted": [bool(c) and t95 is not None and c[0][1] >= t95 for c in candidates],
        }
    pairs = {}
    for a, b in zip(labels, labels[1:], strict=False):
        pa, pb = per_product[a], per_product[b]
        nil = [not x for x in pa["answerable"]]
        nil_a = [acc for acc, n in zip(pa["accepted"], nil, strict=True) if n]
        nil_b = [acc for acc, n in zip(pb["accepted"], nil, strict=True) if n]
        moves = transitions(pa["bands"], pb["bands"], pb["top1"])
        # top-1 accuracy is defined on products whose concept is in the catalog
        ans = pa["answerable"]
        pa = pa | {"top1": [x for x, keep in zip(pa["top1"], ans, strict=True) if keep]}
        pb = pb | {"top1": [x for x, keep in zip(pb["top1"], ans, strict=True) if keep]}
        pairs[f"{b} vs {a}"] = {
            "accuracy@1_diff_ci95": bootstrap_diff(
                [float(x) for x in pa["top1"]], [float(x) for x in pb["top1"]]
            ),
            "mcnemar_p_top1": mcnemar_p(pa["top1"], pb["top1"]),
            "nil_accept_rate_diff_ci95": bootstrap_diff(
                [float(x) for x in nil_a], [float(x) for x in nil_b]
            )
            if nil_a
            else None,
            "mcnemar_p_nil_accepted": mcnemar_p(nil_a, nil_b) if nil_a else None,
            "transitions": moves,
            "coverage_diff_ci95": bootstrap_diff(
                [float(x) for x in pa["accepted"]], [float(x) for x in pb["accepted"]]
            ),
        }
    report = {
        "split": split,
        "version": version,
        "checks": checks,
        "matchers": results,
        "paired": pairs,
    }
    if version:
        write_json(paths.root / "results" / version / f"{split}_comparison.json", report)
    for name, ok, detail in checks:
        log(
            f"[check] {'OK  ' if ok else 'FAIL'} {name}"
            + ("" if ok or not detail else f": {detail}")
        )
    return report
