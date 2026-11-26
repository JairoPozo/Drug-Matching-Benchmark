import pytest

from dmb.metrics import best_f1, decision_metrics, pick_threshold, pr_curve, ranking_metrics

# 5 queries: 4 answerable (A, B, C, D) and 1 NIL
EXPECTED = ["A", "B", "C", "D", None]
CANDIDATES = [
    [("A", 0.9), ("X", 0.5)],  # correct at 1
    [("X", 0.8), ("B", 0.7)],  # correct at 2
    [("C", 0.6)],  # correct at 1, low score
    [("X", 0.95), ("Y", 0.4)],  # wrong, gold not in top 5
    [("Z", 0.3)],  # NIL query
]


def test_ranking_metrics():
    m = ranking_metrics(EXPECTED, CANDIDATES, ks=(1, 5))
    assert m["n_answerable"] == 4
    assert m["accuracy@1"] == pytest.approx(2 / 4)
    assert m["recall@5"] == pytest.approx(3 / 4)


def test_decision_metrics_at_threshold():
    m = decision_metrics(EXPECTED, CANDIDATES, threshold=0.7)
    # accepted: A(0.9 ok), X(0.8 wrong), X(0.95 wrong); abstained: C(0.6), Z(0.3 NIL)
    assert m["n_accepted"] == 3 and m["n_abstained"] == 2
    assert m["accept_precision"] == pytest.approx(1 / 3)
    assert m["accept_recall"] == pytest.approx(1 / 4)
    assert m["abstain_precision"] == pytest.approx(1 / 2)
    assert m["abstain_recall"] == pytest.approx(1.0)
    assert m["end_to_end_accuracy"] == pytest.approx(2 / 5)


def test_pr_curve_and_threshold_selection():
    curve = pr_curve(EXPECTED, CANDIDATES)
    assert [r["threshold"] for r in curve] == [0.95, 0.9, 0.8, 0.6, 0.3]
    assert [r["n_accepted"] for r in curve] == [1, 2, 3, 4, 5]
    assert curve[0]["precision"] == 0.0
    assert curve[3]["precision"] == pytest.approx(2 / 4)
    assert curve[3]["recall"] == pytest.approx(2 / 4)
    assert pick_threshold(curve, 0.95) is None
    assert pick_threshold(curve, 0.5)["threshold"] == 0.6
    assert best_f1(curve)["threshold"] == 0.6


def test_ties_produce_one_point():
    curve = pr_curve(["A", "B"], [[("A", 0.5)], [("X", 0.5)]])
    assert len(curve) == 1 and curve[0]["precision"] == 0.5


def test_empty_candidates_count_as_abstention():
    m = decision_metrics(["A", None], [[], []], threshold=0.0)
    assert m["n_abstained"] == 2 and m["abstain_recall"] == 1.0


def test_wilson_threshold_rule_is_stricter():
    from dmb.metrics import pick_threshold, wilson

    # 30 accepts at 100% precision, then precision decays as the threshold goes down
    curve = [
        {"threshold": 0.9, "n_accepted": 30, "precision": 1.0, "recall": 0.1},
        {"threshold": 0.8, "n_accepted": 400, "precision": 0.98, "recall": 0.4},
        {"threshold": 0.7, "n_accepted": 1000, "precision": 0.955, "recall": 0.8},
    ]
    assert pick_threshold(curve, 0.95, "point")["threshold"] == 0.7
    # 955/1000 has a Wilson lower bound under 0.95; 392/400 is above it
    assert wilson(955, 1000)[0] < 0.95 < wilson(392, 400)[0]
    assert pick_threshold(curve, 0.95, "wilson")["threshold"] == 0.8
    # 30/30 alone is not enough evidence: lower bound ~0.89
    assert pick_threshold(curve[:1], 0.95, "wilson") is None


def test_ltt_stops_at_the_first_threshold_that_fails():
    # high precision, then a bad stretch, then high again: the Wilson rule jumps over the bad
    # stretch, fixed-sequence testing stops before it
    curve = [
        {"threshold": 0.99, "n_accepted": 200, "precision": 1.0, "recall": 0.1},
        {"threshold": 0.95, "n_accepted": 400, "precision": 398 / 400, "recall": 0.2},
        {"threshold": 0.90, "n_accepted": 420, "precision": 390 / 420, "recall": 0.21},
        {"threshold": 0.85, "n_accepted": 2000, "precision": 1940 / 2000, "recall": 0.9},
    ]
    ltt = pick_threshold(curve, 0.95, "ltt")
    assert ltt["threshold"] == 0.901 and ltt["n_accepted"] == 400  # last grid value before 0.90
    assert pick_threshold(curve, 0.95, "wilson")["threshold"] == 0.85


def test_sgr_bound_meets_the_target():
    import math

    from scipy.stats import beta

    # 1000 products, scores from 1.0 down: the first 600 right, then 1 wrong in every 20
    expected = ["A"] * 1000
    candidates = [[("A" if i < 600 or i % 20 else "X", 1 - i / 1000)] for i in range(1000)]
    row = pick_threshold(pr_curve(expected, candidates), 0.95, "sgr")
    n = row["n_accepted"]
    e = n - round(row["precision"] * n)
    level = 0.05 / math.ceil(math.log2(1000))
    assert n >= 600 and beta.ppf(1 - level, e + 1, n - e) < 0.05
    # every answer wrong: no threshold can be guaranteed
    bad = pr_curve(["A"] * 50, [[("X", 1 - i / 50)] for i in range(50)])
    assert pick_threshold(bad, 0.95, "sgr") is None
    assert pick_threshold(bad, 0.95, "ltt") is None
