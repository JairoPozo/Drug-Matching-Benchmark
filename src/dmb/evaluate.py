"""Run a matcher on a split and write metrics, PR curve and predictions to reports/.

The test split is frozen: it can only be evaluated with --final, and only once
(a second run needs --force-rerun and is logged). Test never picks its own thresholds: it applies
the ones fixed on the matcher's latest full dev run, so the test numbers are not tuned to test.
"""

from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from dmb.config import TARGET_PRECISION, TOP_K, Paths, read_json, write_json
from dmb.matchers import get_matcher
from dmb.metrics import (
    best_f1,
    calibration,
    decision_bands,
    decision_metrics,
    pick_abstain_threshold,
    pick_threshold,
    pr_curve,
    ranking_metrics,
    subgroup_metrics,
)

TEST_LOG = "test_runs.log"


class FrozenSplitError(PermissionError):
    pass


def _guard_test(paths: Paths, split: str, final: bool, force_rerun: bool) -> None:
    if split != "test":
        return
    if not final:
        raise FrozenSplitError(
            "The test split is frozen. Evaluate it only once, at the end, with --final."
        )
    log_path = paths.reports / TEST_LOG
    if log_path.exists() and log_path.read_text(encoding="utf-8").strip() and not force_rerun:
        raise FrozenSplitError(
            f"Test was already evaluated (see {log_path}). Re-running needs --force-rerun, "
            "and the extra run stays in the log."
        )


def _dev_reference(paths: Paths, matcher_name: str) -> tuple[dict, str] | None:
    """Latest full (no --limit) dev run of this matcher: its thresholds are used on test."""
    for path in sorted(paths.reports.glob(f"*_{matcher_name}_dev/metrics.json"), reverse=True):
        m = read_json(path, {}) or {}
        if m.get("split") == "dev" and not m.get("limit"):
            return m, path.parent.name
    return None


_INJECTABLE = {
    "INTRAVENOUS",
    "INTRAMUSCULAR",
    "SUBCUTANEOUS",
    "INTRADERMAL",
    "INTRATHECAL",
    "EPIDURAL",
    "INTRAVITREAL",
    "INTRA-ARTICULAR",
    "INFILTRATION",
    "INTRACAVERNOUS",
    "INTRALESIONAL",
    "PERINEURAL",
}
_ROUTES = {
    "ORAL": "oral",
    "TOPICAL": "topical",
    "OPHTHALMIC": "ophthalmic",
    "NASAL": "nasal",
    "DENTAL": "dental",
    "RESPIRATORY (INHALATION)": "inhalation",
}


def _route_group(route: str | None) -> str:
    parts = [p.strip() for p in (route or "").split(",") if p.strip()]
    if not parts:
        return "unknown"
    kinds = {"injectable" if p in _INJECTABLE else _ROUTES.get(p, "other") for p in parts}
    return kinds.pop() if len(kinds) == 1 else "multiple"


def subgroup_labels(df: pl.DataFrame) -> dict[str, list[str]]:
    """Subgroups reported separately (computed from the split's own columns)."""
    types = {"HUMAN PRESCRIPTION DRUG": "prescription", "HUMAN OTC DRUG": "otc"}
    return {
        "ingredients": [
            "0 (kit, no ingredients)" if n == 0 else "1" if n == 1 else "2+"
            for n in df["n_ingredients"].fill_null(0).to_list()
        ],
        "route": [_route_group(r) for r in df["route"].to_list()],
        "catalog": [
            "in catalog" if x else "not in catalog (NIL)" for x in df["in_catalog"].to_list()
        ],
        "product_type": [types.get(t or "", "other") for t in df["product_type"].to_list()],
    }


def _git_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def evaluate(
    paths: Paths,
    matcher_name: str,
    split: str = "dev",
    final: bool = False,
    force_rerun: bool = False,
    limit: int | None = None,
    k: int = TOP_K,
    target_precision: float = TARGET_PRECISION,
    params: dict | None = None,
    log=print,
) -> Path:
    if split not in ("dev", "test"):
        raise ValueError("split must be 'dev' or 'test'")
    _guard_test(paths, split, final, force_rerun)
    matcher = get_matcher(matcher_name, **(params or {}))
    label = matcher.label  # name + params, e.g. "rules-stage2"
    dev_ref = None
    if split == "test":
        dev_ref = _dev_reference(paths, label)
        if dev_ref is None:
            raise FrozenSplitError(
                "Test applies the thresholds fixed on dev. Run a full dev evaluation of this "
                "matcher first (without --limit)."
            )

    split_path = paths.processed / f"{split}.parquet"
    if not split_path.exists():
        raise FileNotFoundError(f"{split_path} not found. Run `make build` first.")
    df = pl.read_parquet(split_path)
    if limit:
        df = df.head(limit)
    catalog = pl.read_parquet(paths.processed / "catalog.parquet")

    matcher.paths = paths
    log(f"[eval] matcher={label} split={split} queries={df.height:,} catalog={catalog.height:,}")
    t0 = time.perf_counter()
    matcher.fit(catalog)
    t_fit = time.perf_counter() - t0
    t0 = time.perf_counter()
    candidates = matcher.match_many(df["query_text"].to_list(), k=k)
    t_match = time.perf_counter() - t0

    expected = df["expected_rxcui"].to_list()
    ranking = ranking_metrics(expected, candidates, ks=(1, k))
    curve = pr_curve(expected, candidates)
    if dev_ref:  # test: thresholds come from dev, never from test itself
        ref = dev_ref[0]
        t_target = (ref.get("at_target_precision") or {}).get("threshold")
        t_f1 = (ref.get("at_best_f1") or {}).get("threshold")
    else:
        op, bf = pick_threshold(curve, target_precision), best_f1(curve)
        t_target = op["threshold"] if op else None
        t_f1 = bf["threshold"] if bf else None
    at_target = decision_metrics(expected, candidates, t_target) if t_target is not None else None
    at_best_f1 = decision_metrics(expected, candidates, t_f1) if t_f1 is not None else None
    op_name, t_op = ("target_precision", t_target) if t_target is not None else ("best_f1", t_f1)
    calib = calibration(expected, candidates)
    if dev_ref:  # test: the abstain threshold also comes from dev
        t_abstain = (dev_ref[0].get("bands") or {}).get("t_abstain")
    else:
        t_abstain = pick_abstain_threshold(expected, candidates, k=k)
    bands = decision_bands(expected, candidates, t_op, t_abstain, k=k) if t_op is not None else None
    subgroups = subgroup_metrics(subgroup_labels(df), expected, candidates, t_op)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = paths.reports / f"{stamp}_{label}_{split}"
    run_dir.mkdir(parents=True, exist_ok=True)

    metrics = {
        "matcher": label,
        "params": matcher.params,
        "split": split,
        "final": final,
        "limit": limit,
        "thresholds_from": dev_ref[1] if dev_ref else "this split",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(paths.root),
        "n_queries": df.height,
        "n_not_in_catalog": sum(e is None for e in expected),
        "catalog_size": catalog.height,
        "k": k,
        "ranking": ranking,
        "target_precision": target_precision,
        "at_target_precision": at_target,
        "at_best_f1": at_best_f1,
        "calibration": calib,
        "bands": bands,
        "training": getattr(matcher, "training_summary", None) or None,
        "subgroups": {"operating_point": op_name, "threshold": t_op, "groups": subgroups},
        "timing_seconds": {
            "fit": round(t_fit, 3),
            "match_total": round(t_match, 3),
            "match_per_query_ms": round(1000 * t_match / max(df.height, 1), 3),
        },
        "data": (read_json(paths.processed / "build_stats.json", {}) or {}).get("sources"),
    }
    write_json(run_dir / "metrics.json", metrics)
    pl.DataFrame(curve).write_csv(run_dir / "pr_curve.csv")
    if calib["bins"]:
        pl.DataFrame(calib["bins"]).write_csv(run_dir / "calibration.csv")
    _write_predictions(df, candidates, run_dir / "predictions.parquet")
    mark = None
    if at_target and at_target["accept_precision"] is not None:
        mark = {
            "threshold": t_target,
            "precision": at_target["accept_precision"],
            "recall": at_target["accept_recall"],
        }
    _plot_pr(curve, mark, run_dir / "pr_curve.png", f"{label} on {split}")

    if split == "test":
        with (paths.reports / TEST_LOG).open("a", encoding="utf-8") as f:
            f.write(f"{metrics['created_at']}\t{label}\t{run_dir.name}\n")

    _print_summary(metrics, run_dir, log)
    if matcher_name == "dummy" and (ranking.get("accuracy@1") or 0) > 0.9:
        log("[warn] the dummy matcher is suspiciously accurate: check the query text for leakage")
    return run_dir


def _write_predictions(df: pl.DataFrame, candidates, path: Path) -> None:
    rows = []
    for ndc, cands in zip(df["product_ndc"].to_list(), candidates, strict=True):
        for rank, (rxcui, score) in enumerate(cands, start=1):
            rows.append({"product_ndc": ndc, "rank": rank, "rxcui": rxcui, "score": score})
    preds = pl.DataFrame(
        rows,
        schema={
            "product_ndc": pl.String,
            "rank": pl.Int32,
            "rxcui": pl.String,
            "score": pl.Float64,
        },
    )
    keep = ["product_ndc", "query_text", "gold_rxcui", "gold_name", "expected_rxcui", "in_catalog"]
    preds.join(df.select(keep), on="product_ndc", how="left").write_parquet(path)


def _plot_pr(curve: list[dict], op: dict | None, path: Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5, 4), dpi=150)
    if curve:
        ax.plot([r["recall"] for r in curve], [r["precision"] for r in curve], lw=1.5)
    if op:
        ax.scatter(
            [op["recall"]],
            [op["precision"]],
            color="crimson",
            zorder=3,
            label=f"P>={op['precision']:.2f} at t={op['threshold']:.2f}",
        )
        ax.legend(loc="lower left", fontsize=8)
    ax.set(
        xlabel="recall (accepted & correct / answerable)",
        ylabel="precision",
        title=title,
        xlim=(0, 1),
        ylim=(0, 1.02),
    )
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _print_summary(m: dict, run_dir: Path, log) -> None:
    r = m["ranking"]
    log("")
    log(
        f"=== {m['matcher']} on {m['split']} ({m['n_queries']:,} queries, "
        f"{m['n_not_in_catalog']:,} NIL) ==="
    )
    log(f"accuracy@1            {_fmt(r.get('accuracy@1'))}")
    recall_key = f"recall@{m['k']}"
    log(f"{recall_key:<22}{_fmt(r.get(recall_key))}")
    for label, d in (
        (f"at precision>={m['target_precision']:.2f}", m["at_target_precision"]),
        ("at best F1", m["at_best_f1"]),
    ):
        if d is None:
            log(f"{label}: no threshold reaches it")
            continue
        log(
            f"{label} (t={d['threshold']:.3f}): "
            f"accept P={_fmt(d['accept_precision'])} R={_fmt(d['accept_recall'])} "
            f"F1={_fmt(d['accept_f1'])} | abstain P={_fmt(d['abstain_precision'])} "
            f"R={_fmt(d['abstain_recall'])}"
        )
    op = m["at_target_precision"] or m["at_best_f1"]
    if op:
        c = op["counts"]
        log(
            f"decisions (t={op['threshold']:.3f}): correct {c['correct_accept']}, "
            f"wrong {c['wrong_accept']}, accepted-but-NIL {c['accept_on_nil']}, "
            f"missed {c['missed']}, correct abstain {c['correct_abstain']} | "
            f"false accept rate {_fmt(op['false_accept_rate'])}, coverage {_fmt(op['coverage'])}"
        )
    cal = m["calibration"]
    log(
        f"calibration ECE       {_fmt(cal['ece'])}  Brier {_fmt(cal['brier'])} "
        "(0 = score is a probability)"
    )
    b = m["bands"]
    if b:
        a, r, x = b["accept"], b["review"], b["abstain"]
        top_key = next(key for key in r if key.startswith("answer_in_top"))
        log(
            f"bands: accept {a['n']} ({_fmt(a['share'])}) precision {_fmt(a['precision'])} | "
            f"review {r['n']} ({_fmt(r['share'])}) answer in top5 {_fmt(r[top_key])} | "
            f"abstain {x['n']} ({_fmt(x['share'])}) nothing to pick {_fmt(x['useless_share'])}"
        )
    log(f"thresholds from       {m['thresholds_from']}")
    sg = m["subgroups"]
    log(f"subgroups at {sg['operating_point']} threshold: n | acc@1 | end-to-end | false accept")
    for dim, rows in sg["groups"].items():
        for label, r in rows.items():
            log(
                f"  {dim:<13}{label:<26}{r['n']:>5} | {_fmt(r['accuracy@1'])} | "
                f"{_fmt(r['end_to_end_accuracy'])} | {_fmt(r['false_accept_rate'])}"
            )
    log(f"match time            {m['timing_seconds']['match_per_query_ms']:.2f} ms/query")
    log(f"report -> {run_dir}")
