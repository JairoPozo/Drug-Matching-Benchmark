"""Run a matcher on a split and write metrics, PR curve and predictions to reports/.

The test split is frozen: it can only be evaluated with --final, and only once
(a second run needs --force-rerun and is logged).
"""

from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from dmb.config import TARGET_PRECISION, TOP_K, Paths, read_json, write_json
from dmb.matchers import get_matcher
from dmb.metrics import best_f1, decision_metrics, pick_threshold, pr_curve, ranking_metrics

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
    log=print,
) -> Path:
    if split not in ("dev", "test"):
        raise ValueError("split must be 'dev' or 'test'")
    _guard_test(paths, split, final, force_rerun)

    split_path = paths.processed / f"{split}.parquet"
    if not split_path.exists():
        raise FileNotFoundError(f"{split_path} not found. Run `make build` first.")
    df = pl.read_parquet(split_path)
    if limit:
        df = df.head(limit)
    catalog = pl.read_parquet(paths.processed / "catalog.parquet")

    matcher = get_matcher(matcher_name)
    log(
        f"[eval] matcher={matcher_name} split={split} queries={df.height:,} "
        f"catalog={catalog.height:,}"
    )
    t0 = time.perf_counter()
    matcher.fit(catalog)
    t_fit = time.perf_counter() - t0
    t0 = time.perf_counter()
    candidates = matcher.match_many(df["query_text"].to_list(), k=k)
    t_match = time.perf_counter() - t0

    expected = df["expected_rxcui"].to_list()
    ranking = ranking_metrics(expected, candidates, ks=(1, k))
    curve = pr_curve(expected, candidates)
    op = pick_threshold(curve, target_precision)
    bf = best_f1(curve)
    at_target = decision_metrics(expected, candidates, op["threshold"]) if op else None
    at_best_f1 = decision_metrics(expected, candidates, bf["threshold"]) if bf else None

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = paths.reports / f"{stamp}_{matcher_name}_{split}"
    run_dir.mkdir(parents=True, exist_ok=True)

    metrics = {
        "matcher": matcher_name,
        "split": split,
        "final": final,
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
        "timing_seconds": {
            "fit": round(t_fit, 3),
            "match_total": round(t_match, 3),
            "match_per_query_ms": round(1000 * t_match / max(df.height, 1), 3),
        },
        "data": (read_json(paths.processed / "build_stats.json", {}) or {}).get("sources"),
    }
    write_json(run_dir / "metrics.json", metrics)
    pl.DataFrame(curve).write_csv(run_dir / "pr_curve.csv")
    _write_predictions(df, candidates, run_dir / "predictions.parquet")
    _plot_pr(curve, op, run_dir / "pr_curve.png", f"{matcher_name} on {split}")

    if split == "test":
        with (paths.reports / TEST_LOG).open("a", encoding="utf-8") as f:
            f.write(f"{metrics['created_at']}\t{matcher_name}\t{run_dir.name}\n")

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
    log(f"match time            {m['timing_seconds']['match_per_query_ms']:.2f} ms/query")
    log(f"report -> {run_dir}")
