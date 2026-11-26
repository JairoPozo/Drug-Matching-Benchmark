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
  ECE (expected calibration error) is the size-weighted gap. Brier score = mean squared error
  between the top-1 score and 1 (right) / 0 (wrong). A score is only a probability if both are
  close to 0.
- Decision bands: accept the top-1 if score >= t_accept; abstain if score < t_abstain (or no
  candidate); otherwise send the query to review, where a person picks from the top k.
  t_abstain is the highest threshold below which at least MIN_USELESS of the queries have no
  right answer in their top k (nothing a reviewer could pick).
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


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a proportion (95% by default)."""
    import math

    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return center - half, center + half


THRESHOLD_RULES = ("point", "wilson", "ltt", "sgr")
# Rules with a finite-sample guarantee (ltt, sgr): with probability >= 1 - RISK_DELTA, the
# precision of the accepted products on new data from the same distribution meets the target.
RISK_DELTA = 0.05
# Candidate thresholds for ltt, fixed in advance and tested from the strictest down. The sequence
# starts at the target precision, 0.95. It first started at 0.99, where so few products score
# that one unlucky calibration sample fails the first test and stops the sequence with nothing
# accepted, as happened in some dev resamples. Changed on dev, before any ltt run on test2.
LTT_GRID = tuple(round(0.95 - i * 0.001, 3) for i in range(951))


def _errors(row: dict) -> int:
    return row["n_accepted"] - round(row["precision"] * row["n_accepted"])


def _ltt(curve: list[dict], target_precision: float, delta: float = RISK_DELTA) -> dict | None:
    """Learn then Test (Angelopoulos et al.) with fixed-sequence testing.

    For each grid threshold, from the strictest down, an exact binomial test of
    H0: error rate of the accepted products > 1 - target. The sequence continues while H0 is
    rejected at level delta and stops at the first threshold where it is not; the last rejected
    threshold is returned. Fixed-sequence testing needs no multiplicity correction.
    """
    import numpy as np
    from scipy.stats import binom

    if not curve:
        return None
    rows = sorted(curve, key=lambda r: r["threshold"])
    thresholds = np.array([r["threshold"] for r in rows])
    grid = np.array(LTT_GRID)
    # each grid threshold accepts the same products as the row with the smallest threshold above it
    idx = np.searchsorted(thresholds, grid, side="left")
    inside = idx < len(rows)
    safe = np.minimum(idx, len(rows) - 1)
    n = np.where(inside, np.array([r["n_accepted"] for r in rows])[safe], 0)
    e = np.where(inside, np.array([_errors(r) for r in rows])[safe], 0)
    p_values = np.where(n > 0, binom.cdf(e, np.maximum(n, 1), 1 - target_precision), 1.0)
    fails = np.flatnonzero(p_values > delta)
    stop = int(fails[0]) if fails.size else len(grid)
    if stop == 0:  # nothing accepted with enough evidence, or no evidence at all
        return None
    return {**rows[int(idx[stop - 1])], "threshold": float(grid[stop - 1])}


def _sgr(curve: list[dict], target_precision: float, delta: float = RISK_DELTA) -> dict | None:
    """Selection with guaranteed risk (Geifman and El-Yaniv, 2017, Algorithm 1).

    Binary search over the sorted scores for ceil(log2 m) steps. At each tested threshold the
    one-sided Clopper-Pearson upper bound of the error rate of the accepted products, at level
    delta / ceil(log2 m), is compared with the target risk. Returns the lowest tested threshold
    whose bound is below the target.
    """
    import bisect
    import math

    from scipy.stats import beta

    r_star = 1 - target_precision
    rows = sorted(curve, key=lambda r: -r["threshold"])
    if not rows:
        return None
    cumulative = [r["n_accepted"] for r in rows]
    m = cumulative[-1]
    steps = max(1, math.ceil(math.log2(m))) if m > 1 else 1
    level = delta / steps

    def row_at(z: int) -> dict:  # z-th lowest score (1-based) and every score above it
        return rows[bisect.bisect_left(cumulative, m - z + 1)]

    def bound(row: dict) -> float:
        n, e = row["n_accepted"], _errors(row)
        return 1.0 if e >= n else float(beta.ppf(1 - level, e + 1, n - e))

    z_min, z_max, best = 1, m, None
    for _ in range(steps):
        z = math.ceil((z_min + z_max) / 2)
        row = row_at(z)
        if bound(row) < r_star:
            z_max = z
            if best is None or row["threshold"] < best["threshold"]:
                best = row
        else:
            z_min = z
    return best


def pick_threshold(curve: list[dict], target_precision: float, rule: str = "point") -> dict | None:
    """Highest-recall point that meets the precision target (ties -> higher precision).

    rule "point": observed precision >= target.
    rule "wilson": the lower bound of the Wilson 95% interval of the precision >= target, so the
    target still holds, with 95% confidence, on the population the sample comes from. Every
    threshold is checked on its own, with no correction for checking many.
    rule "ltt": Learn then Test with fixed-sequence testing (see _ltt).
    rule "sgr": selection with guaranteed risk (see _sgr).
    """
    if rule not in THRESHOLD_RULES:
        raise ValueError(f"threshold rule must be one of {THRESHOLD_RULES}")
    if rule == "ltt":
        return _ltt(curve, target_precision)
    if rule == "sgr":
        return _sgr(curve, target_precision)

    def meets(row: dict) -> bool:
        if rule == "point":
            return row["precision"] >= target_precision
        n = row["n_accepted"]
        return wilson(round(row["precision"] * n), n)[0] >= target_precision

    ok = [row for row in curve if meets(row)]
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
    brier = sum(
        (min(max(_top1(c)[1], 0.0), 1.0) - (e is not None and _top1(c)[0] == e)) ** 2
        for e, c in zip(expected, candidates, strict=True)
        if c
    )
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
    return {
        "ece": ece if total else None,
        "brier": brier / total if total else None,
        "bins": rows,
    }


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


MIN_USELESS = 0.9


def _in_top(e: str | None, c: Candidates, k: int) -> bool:
    return e is not None and e in [r for r, _ in c[:k]]


def pick_abstain_threshold(
    expected: Sequence[str | None],
    candidates: Sequence[Candidates],
    k: int = 5,
    min_useless: float = MIN_USELESS,
) -> float | None:
    """Highest t such that, among queries scored below t, >= min_useless have nothing right in
    their top k. None when no such t exists (abstain only when there is no candidate)."""
    rows = sorted(
        (_top1(c)[1], not _in_top(e, c, k)) for e, c in zip(expected, candidates, strict=True) if c
    )
    best, n, useless, i = None, 0, 0, 0
    while i < len(rows):
        score = rows[i][0]
        while i < len(rows) and rows[i][0] == score:
            n += 1
            useless += rows[i][1]
            i += 1
        if i < len(rows) and useless / n >= min_useless:
            best = rows[i][0]  # abstain on everything scored below the next distinct score
    return best


def decision_bands(
    expected: Sequence[str | None],
    candidates: Sequence[Candidates],
    t_accept: float,
    t_abstain: float | None,
    k: int = 5,
) -> dict:
    """Accept / review / abstain, with what each band delivers."""
    t_abstain = min(t_abstain, t_accept) if t_abstain is not None else None
    bands: dict[str, list] = {"accept": [], "review": [], "abstain": []}
    for e, c in zip(expected, candidates, strict=True):
        top, score = _top1(c)
        if top is not None and score >= t_accept:
            bands["accept"].append((e, c))
        elif top is None or (t_abstain is not None and score < t_abstain):
            bands["abstain"].append((e, c))
        else:
            bands["review"].append((e, c))
    n = len(expected)
    acc, rev, abst = bands["accept"], bands["review"], bands["abstain"]
    rev_ans = [(e, c) for e, c in rev if e is not None]
    return {
        "t_accept": t_accept,
        "t_abstain": t_abstain,
        "accept": {
            "n": len(acc),
            "share": _safe_div(len(acc), n),
            "precision": _safe_div(
                sum(_top1(c)[0] == e for e, c in acc if e is not None), len(acc)
            ),
        },
        "review": {
            "n": len(rev),
            "share": _safe_div(len(rev), n),
            "n_nil": len(rev) - len(rev_ans),
            "top1_precision": _safe_div(sum(_top1(c)[0] == e for e, c in rev_ans), len(rev)),
            f"answer_in_top{k}": _safe_div(sum(_in_top(e, c, k) for e, c in rev_ans), len(rev_ans)),
        },
        "abstain": {
            "n": len(abst),
            "share": _safe_div(len(abst), n),
            "n_nil": sum(e is None for e, _ in abst),
            "useless_share": _safe_div(sum(not _in_top(e, c, k) for e, c in abst), len(abst)),
        },
    }
