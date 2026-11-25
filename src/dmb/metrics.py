"""Ranking and accept/abstain metrics.

Conventions
- expected: gold RxCUI if the concept is in the catalog, None if it was held out (NIL).
- A query is "answerable" when expected is not None.
- Decision at threshold t: accept the top-1 candidate if its score >= t, otherwise abstain.
- Accept precision = correct accepts / accepts.
- Accept recall    = correct accepts / answerable queries.
- Abstention (NIL detection): precision = abstained NIL / abstentions, recall = abstained NIL / NIL.
- Decision counts: every query is exactly one of
    correct_accept   accepted the right concept
    wrong_accept     accepted a wrong concept although the right one is in the catalog
    accept_on_nil    accepted a concept although the right one is not in the catalog
    missed           abstained although the right concept is in the catalog
    correct_abstain  abstained and the right concept is not in the catalog
  false_accept_rate = (wrong_accept + accept_on_nil) / accepts; coverage = accepts / queries.
- Calibration: top-1 scores are binned; in each bin precision should equal the mean score.
  ECE (expected calibration error) is the size-weighted gap. A score is only a probability if
  ECE is close to 0.
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
    tp = wrong = on_nil = missed = abst_nil = 0
    for e, c in zip(expected, candidates, strict=True):
        top, score = _top1(c)
        if top is not None and score >= threshold:
            if e is not None and top == e:
                tp += 1
            elif e is None:
                on_nil += 1
            else:
                wrong += 1
        elif e is None:
            abst_nil += 1
        else:
            missed += 1
    fp, abst = wrong + on_nil, missed + abst_nil
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
        "false_accept_rate": _safe_div(fp, tp + fp),
        "coverage": _safe_div(tp + fp, n),
        "counts": {
            "correct_accept": tp,
            "wrong_accept": wrong,
            "accept_on_nil": on_nil,
            "missed": missed,
            "correct_abstain": abst_nil,
        },
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


def calibration(
    expected: Sequence[str | None], candidates: Sequence[Candidates], n_bins: int = 10
) -> dict:
    """Precision of the top-1 answer per score bin, and the expected calibration error."""
    bins = [[0, 0.0, 0] for _ in range(n_bins)]  # n, sum of scores, correct
    for e, c in zip(expected, candidates, strict=True):
        top, score = _top1(c)
        if top is None:
            continue
        s = min(max(score, 0.0), 1.0)
        b = bins[min(int(s * n_bins), n_bins - 1)]
        b[0] += 1
        b[1] += s
        b[2] += e is not None and top == e
    total = sum(b[0] for b in bins)
    rows, ece = [], 0.0
    for i, (n, ssum, correct) in enumerate(bins):
        if not n:
            continue
        conf, prec = ssum / n, correct / n
        ece += n / total * abs(prec - conf)
        rows.append(
            {
                "bin": f"{i / n_bins:.1f}-{(i + 1) / n_bins:.1f}",
                "n": n,
                "mean_score": conf,
                "precision": prec,
            }
        )
    return {"ece": ece if total else None, "bins": rows}


def subgroup_metrics(
    groups: dict[str, Sequence[str]],
    expected: Sequence[str | None],
    candidates: Sequence[Candidates],
    threshold: float | None,
) -> dict:
    """Ranking and decision metrics restricted to each value of each grouping."""
    out: dict = {}
    for dim, labels in groups.items():
        out[dim] = {}
        for label in sorted(set(labels)):
            idx = [i for i, lab in enumerate(labels) if lab == label]
            e = [expected[i] for i in idx]
            c = [candidates[i] for i in idx]
            d = decision_metrics(e, c, threshold) if threshold is not None else None
            out[dim][label] = {
                "n": len(idx),
                "n_nil": sum(x is None for x in e),
                "accuracy@1": ranking_metrics(e, c, ks=(1,))["accuracy@1"],
                "end_to_end_accuracy": d["end_to_end_accuracy"] if d else None,
                "false_accept_rate": d["false_accept_rate"] if d else None,
                "coverage": d["coverage"] if d else None,
            }
    return out
