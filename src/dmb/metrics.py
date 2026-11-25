"""Ranking and accept/abstain metrics.

Conventions
- expected: gold RxCUI if the concept is in the catalog, None if it was held out (NIL).
- A query is "answerable" when expected is not None.
- Decision at threshold t: accept the top-1 candidate if its score >= t, otherwise abstain.
- Accept precision = correct accepts / accepts.
- Accept recall    = correct accepts / answerable queries.
- Abstention (NIL detection): precision = abstained NIL / abstentions, recall = abstained NIL / NIL.
"""

from __future__ import annotations

from collections.abc import Sequence

Candidates = Sequence[tuple[str, float]]


def _safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None or p + r == 0:
        return None if p is None or r is None else 0.0
    return 2 * p * r / (p + r)


def ranking_metrics(
    expected: Sequence[str | None], candidates: Sequence[Candidates], ks=(1, 5)
) -> dict:
    """accuracy@1 and recall@k over answerable queries."""
    answerable = [(e, c) for e, c in zip(expected, candidates, strict=True) if e is not None]
    out: dict = {"n_answerable": len(answerable)}
    for k in ks:
        hits = sum(1 for e, c in answerable if e in [r for r, _ in c[:k]])
        key = "accuracy@1" if k == 1 else f"recall@{k}"
        out[key] = _safe_div(hits, len(answerable))
    return out


def _top1(candidates: Candidates) -> tuple[str | None, float]:
    return (candidates[0][0], float(candidates[0][1])) if candidates else (None, float("-inf"))


def decision_metrics(
    expected: Sequence[str | None], candidates: Sequence[Candidates], threshold: float
) -> dict:
    n = len(expected)
    n_nil = sum(e is None for e in expected)
    n_ans = n - n_nil
    tp = fp = abst = abst_nil = 0
    for e, c in zip(expected, candidates, strict=True):
        top, score = _top1(c)
        if top is not None and score >= threshold:
            if e is not None and top == e:
                tp += 1
            else:
                fp += 1
        else:
            abst += 1
            abst_nil += e is None
    p, r = _safe_div(tp, tp + fp), _safe_div(tp, n_ans)
    return {
        "threshold": threshold,
        "n_accepted": tp + fp,
        "n_abstained": abst,
        "accept_precision": p,
        "accept_recall": r,
        "accept_f1": _f1(p, r),
        "abstain_precision": _safe_div(abst_nil, abst),
        "abstain_recall": _safe_div(abst_nil, n_nil),
        "end_to_end_accuracy": _safe_div(tp + abst_nil, n),
    }


def pr_curve(expected: Sequence[str | None], candidates: Sequence[Candidates]) -> list[dict]:
    """Precision/recall of the accept decision for every distinct top-1 score as threshold."""
    n_ans = sum(e is not None for e in expected)
    scored = []
    for e, c in zip(expected, candidates, strict=True):
        top, score = _top1(c)
        if top is not None:
            scored.append((score, e is not None and top == e))
    scored.sort(key=lambda x: -x[0])
    rows, tp, fp = [], 0, 0
    for i, (score, correct) in enumerate(scored):
        tp += correct
        fp += not correct
        if i + 1 < len(scored) and scored[i + 1][0] == score:
            continue  # emit one point per distinct threshold
        p, r = tp / (tp + fp), _safe_div(tp, n_ans)
        rows.append(
            {
                "threshold": score,
                "n_accepted": tp + fp,
                "precision": p,
                "recall": r,
                "f1": _f1(p, r),
            }
        )
    return rows


def pick_threshold(curve: list[dict], target_precision: float) -> dict | None:
    """Highest-recall point whose precision >= target (ties -> higher precision)."""
    ok = [row for row in curve if row["precision"] >= target_precision]
    if not ok:
        return None
    return max(ok, key=lambda r: (r["recall"] or 0.0, r["precision"]))


def best_f1(curve: list[dict]) -> dict | None:
    rows = [r for r in curve if r["f1"] is not None]
    return max(rows, key=lambda r: r["f1"]) if rows else None
