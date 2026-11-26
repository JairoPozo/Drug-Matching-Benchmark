"""Dev-only experiments for v0.2.0: ablations and scorer comparisons.

Reads train and dev only; never a test split. For a rules configuration it computes, once, the
cross-fitted features of every train candidate and the features of every dev candidate (cached in
data/experiments/<name>/), then trains the score on any subset of features in seconds. The full
feature set reproduces `dmb eval --matcher rules --param stage=5` on dev.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from dmb.config import TARGET_PRECISION, Paths, read_json, write_json
from dmb.matchers.rules import FEATURES, RulesMatcher
from dmb.metrics import (
    calibration,
    decision_metrics,
    pick_threshold,
    pr_curve,
    ranking_metrics,
    wilson,
)

RESULTS = Path("results") / "v0.2.0" / "dev_experiments"


def cache_dir(paths: Paths, name: str) -> Path:
    return paths.root / "data" / "experiments" / name


def build_cache(paths: Paths, name: str, params: dict | None = None, log=print) -> Path:
    """Candidate features for train (cross-fitted) and dev, for one rules configuration."""
    out = cache_dir(paths, name)
    if (out / "meta.json").exists():
        return out
    params = {k: v for k, v in (params or {}).items() if k not in ("stage", "drop")}
    m = RulesMatcher(stage=4, **params)  # stage 4 builds the same features as stage 5
    m.paths = paths
    m.fit(pl.read_parquet(paths.processed / "catalog.parquet"))
    train = m._train_rows(paths)
    log(f"[experiment] {name}: cross-fitted features for {train.height:,} train queries")
    tr = m.oof_examples(train)
    dev = pl.read_parquet(paths.processed / "dev.parquet").select("query_text", "expected_rxcui")
    dv = []
    for qid, (text, expected) in enumerate(dev.iter_rows()):
        for rxcui, feats in m._candidate_features(text):
            dv.append((qid, rxcui, feats, int(rxcui == expected)))
    out.mkdir(parents=True, exist_ok=True)
    for split, rows in (("train", tr), ("dev", dv)):
        pl.DataFrame(
            {
                "qid": [r[0] for r in rows],
                "rxcui": [r[1] for r in rows],
                "label": [r[3] for r in rows],
                **{f: [r[2][f] for r in rows] for f in FEATURES},
            }
        ).write_parquet(out / f"{split}.parquet")
    dev.with_row_index("qid").select("qid", "expected_rxcui").write_parquet(
        out / "dev_expected.parquet"
    )
    write_json(out / "meta.json", {"name": name, "params": params, "features": list(FEATURES)})
    return out


def _model(scorer: str):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if scorer == "lr":
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    if scorer == "gb":
        return HistGradientBoostingClassifier(random_state=0)
    raise ValueError("scorer must be lr or gb")


def summarize(expected: list, candidates: list, target: float = TARGET_PRECISION) -> dict:
    n_nil = sum(e is None for e in expected)
    curve = pr_curve(expected, candidates)
    out = {
        **{
            k: v
            for k, v in ranking_metrics(expected, candidates, ks=(1, 5)).items()
            if k != "n_answerable"
        },
        **{k: calibration(expected, candidates)[k] for k in ("ece", "brier")},
    }
    for rule in ("point", "wilson"):
        op = pick_threshold(curve, target, rule)
        if op is None:
            out[rule] = None
            continue
        d = decision_metrics(expected, candidates, op["threshold"])
        c = d["counts"]
        out[rule] = {
            "threshold": op["threshold"],
            "coverage": d["coverage"],
            "precision": d["accept_precision"],
            "precision_ci95": wilson(c["correct_accept"], d["n_accepted"]),
            "accepted": d["n_accepted"],
            "false_accepts": c["wrong_accept"] + c["accept_on_nil"],
            "nil_accepted": c["accept_on_nil"],
            "far_nil": c["accept_on_nil"] / n_nil if n_nil else None,
        }
    return out


def score_subset(cache: Path, features: list[str], scorer: str = "lr") -> dict:
    train = pl.read_parquet(cache / "train.parquet")
    dev = pl.read_parquet(cache / "dev.parquet")
    expected = pl.read_parquet(cache / "dev_expected.parquet")["expected_rxcui"].to_list()
    model = _model(scorer).fit(train.select(features).to_numpy(), train["label"].to_numpy())
    probs = model.predict_proba(dev.select(features).to_numpy())[:, 1]
    cands: list[list] = [[] for _ in expected]
    for qid, rxcui, p in zip(dev["qid"].to_list(), dev["rxcui"].to_list(), probs, strict=True):
        cands[qid].append((rxcui, float(p)))
    for c in cands:
        c.sort(key=lambda t: (-t[1], t[0]))
    return summarize(expected, [c[:5] for c in cands])


def heuristic_only(cache: Path) -> dict:
    """Stage 4 as is: the hand-weighted heuristic score, no model."""
    dev = pl.read_parquet(cache / "dev.parquet")
    expected = pl.read_parquet(cache / "dev_expected.parquet")["expected_rxcui"].to_list()
    cands: list[list] = [[] for _ in expected]
    for qid, rxcui, h in dev.select("qid", "rxcui", "heuristic").iter_rows():
        cands[qid].append((rxcui, float(h)))
    for c in cands:
        c.sort(key=lambda t: (-t[1], t[0]))
    return summarize(expected, [c[:5] for c in cands])


def run(paths: Paths, name: str, params: dict, ablate: bool, scorers: list[str], log=print) -> dict:
    cache = build_cache(paths, name, params, log=log)
    rows = {"stage4 heuristic (no model)": heuristic_only(cache)}
    for scorer in scorers:
        rows[f"{scorer}: all features"] = score_subset(cache, list(FEATURES), scorer)
    if ablate:
        rows["lr: heuristic only (calibrated stage 4)"] = score_subset(cache, ["heuristic"])
        for f in FEATURES:
            rows[f"lr: without {f}"] = score_subset(cache, [x for x in FEATURES if x != f])
    report = {"name": name, "params": read_json(cache / "meta.json")["params"], "rows": rows}
    write_json(paths.root / RESULTS / f"{name}.json", report)
    log(json.dumps({k: _short(v) for k, v in rows.items()}, indent=1))
    return report


def _short(r: dict) -> str:
    def f(x, pct=True):
        return "—" if x is None else (f"{100 * x:.1f}" if pct else f"{x:.3f}")

    w, pnt = r.get("wilson") or {}, r.get("point") or {}
    return (
        f"acc1 {f(r['accuracy@1'])} | cov point {f(pnt.get('coverage'))} | "
        f"cov wilson {f(w.get('coverage'))} P {f(w.get('precision'))} "
        f"nil_acc {w.get('nil_accepted', '—')} | ECE {f(r['ece'], False)}"
    )
