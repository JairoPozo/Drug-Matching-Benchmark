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
