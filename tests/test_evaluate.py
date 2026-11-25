import pytest

from dmb.config import Paths, read_json
from dmb.evaluate import FrozenSplitError, evaluate
from dmb.matchers import get_matcher

QUIET = {"log": lambda *_: None}


def test_dummy_end_to_end_on_dev(built_root):
    run_dir = evaluate(Paths(built_root), "dummy", "dev", **QUIET)
    m = read_json(run_dir / "metrics.json")
    assert m["n_queries"] == 30
    for key in ("accuracy@1", "recall@5"):
        assert 0.0 <= m["ranking"][key] <= 1.0
    assert m["at_best_f1"]["accept_precision"] is not None
    assert "abstain_recall" in m["at_best_f1"]
    for f in ("pr_curve.csv", "pr_curve.png", "predictions.parquet"):
        assert (run_dir / f).exists()
    assert m["thresholds_from"] == "this split"
    assert 0.0 <= m["calibration"]["ece"] <= 1.0
    groups = m["subgroups"]["groups"]
    assert set(groups) == {"ingredients", "route", "catalog", "product_type"}
    assert sum(r["n"] for r in groups["route"].values()) == 30
    counts = m["at_best_f1"]["counts"]
    assert sum(counts.values()) == 30


def test_test_split_requires_final_and_runs_once(built_root):
    p = Paths(built_root)
    with pytest.raises(FrozenSplitError):
        evaluate(p, "dummy", "test", **QUIET)
    evaluate(p, "dummy", "dev", **QUIET)  # test needs thresholds fixed on dev
    evaluate(p, "dummy", "test", final=True, **QUIET)
    with pytest.raises(FrozenSplitError):
        evaluate(p, "dummy", "test", final=True, **QUIET)
    evaluate(p, "dummy", "test", final=True, force_rerun=True, **QUIET)
    assert len((p.reports / "test_runs.log").read_text().splitlines()) == 2


def test_dummy_ranks_exact_name_first():
    import polars as pl

    m = get_matcher("dummy")
    m.fit(pl.DataFrame({"rxcui": ["1", "2"], "name": ["ibuprofen 200 MG Oral Tablet", "zinc"]}))
    cands = m.match("ibuprofen 200 MG Oral Tablet", k=5)
    assert cands[0] == ("1", 1.0) and len(cands) == 2
    assert all(0.0 <= s <= 1.0 for _, s in cands)


def test_unknown_matcher_and_bad_params():
    with pytest.raises(ValueError):
        get_matcher("nope")
    with pytest.raises(ValueError):
        get_matcher("rules", stage=9)
    with pytest.raises(ValueError):
        get_matcher("dummy", stage=1)


def test_rules_end_to_end_on_dev(built_root):
    run_dir = evaluate(Paths(built_root), "rules", "dev", params={"stage": "2"}, **QUIET)
    m = read_json(run_dir / "metrics.json")
    assert run_dir.name.endswith("_rules-stage2_dev")
    assert m["matcher"] == "rules-stage2" and m["params"] == {"stage": 2}
    assert m["ranking"]["accuracy@1"] >= 0.9  # synthetic names are unambiguous


def test_test_requires_a_dev_run_and_uses_its_thresholds(built_root):
    p = Paths(built_root)
    with pytest.raises(FrozenSplitError, match="dev"):
        evaluate(p, "dummy", "test", final=True, **QUIET)
    evaluate(p, "dummy", "dev", limit=5, **QUIET)  # partial runs do not count
    with pytest.raises(FrozenSplitError, match="dev"):
        evaluate(p, "dummy", "test", final=True, **QUIET)
    dev = read_json(evaluate(p, "dummy", "dev", **QUIET) / "metrics.json")
    test = read_json(evaluate(p, "dummy", "test", final=True, **QUIET) / "metrics.json")
    assert test["thresholds_from"].endswith("_dummy_dev")
    assert test["at_best_f1"]["threshold"] == dev["at_best_f1"]["threshold"]


def test_decision_counts_and_calibration():
    from dmb.metrics import calibration, decision_metrics, subgroup_metrics

    expected = ["a", "b", None, "c", None]
    candidates = [
        [("a", 0.9)],  # correct accept
        [("x", 0.9)],  # wrong accept
        [("y", 0.9)],  # accepted although NIL
        [("c", 0.1)],  # missed (below threshold)
        [("z", 0.1)],  # correct abstain
    ]
    d = decision_metrics(expected, candidates, 0.5)
    assert d["counts"] == {
        "correct_accept": 1,
        "wrong_accept": 1,
        "accept_on_nil": 1,
        "missed": 1,
        "correct_abstain": 1,
    }
    assert d["false_accept_rate"] == 2 / 3 and d["coverage"] == 3 / 5
    assert d["end_to_end_accuracy"] == 2 / 5

    perfect = calibration(["a", "a"], [[("a", 1.0)], [("b", 0.0)]])
    assert perfect["ece"] == 0.0
    overconfident = calibration(["a", "a"], [[("x", 0.95)], [("y", 0.95)]])
    assert overconfident["ece"] > 0.9

    sub = subgroup_metrics({"g": ["u", "u", "v", "v", "v"]}, expected, candidates, 0.5)
    assert sub["g"]["u"]["n"] == 2 and sub["g"]["v"]["n_nil"] == 2


def test_route_groups():
    from dmb.evaluate import _route_group

    assert _route_group("OPHTHALMIC") == "ophthalmic"
    assert _route_group("INTRAVENOUS, INTRAMUSCULAR") == "injectable"
    assert _route_group("ORAL, TOPICAL") == "multiple"
    assert _route_group("") == "unknown" and _route_group(None) == "unknown"


def test_brier_and_decision_bands():
    from dmb.metrics import calibration, decision_bands, pick_abstain_threshold

    assert calibration(["a"], [[("a", 1.0)]])["brier"] == 0.0
    assert calibration(["a", "a"], [[("x", 0.95)], [("y", 0.95)]])["brier"] > 0.8

    expected = ["a", "b", "c", None, None, "d"]
    candidates = [
        [("a", 0.97)],  # accept, right
        [("x", 0.6), ("b", 0.3)],  # review: right answer is 2nd
        [("c", 0.5)],  # review, right on top
        [("y", 0.04)],  # low score, nothing right: abstain
        [("z", 0.02)],  # low score, nothing right: abstain
        [],  # no candidate: abstain
    ]
    t_abstain = pick_abstain_threshold(expected, candidates, k=5, min_useless=0.9)
    assert t_abstain == 0.5  # below 0.5 every query has nothing right in its top 5
    b = decision_bands(expected, candidates, t_accept=0.9, t_abstain=t_abstain)
    assert (b["accept"]["n"], b["review"]["n"], b["abstain"]["n"]) == (1, 2, 3)
    assert b["accept"]["precision"] == 1.0
    assert b["review"]["answer_in_top5"] == 1.0 and b["review"]["top1_precision"] == 0.5
    assert b["abstain"]["useless_share"] == 1.0 and b["abstain"]["n_nil"] == 2


def test_rules_stage5_trains_and_evaluates(built_root):
    from dmb.matchers.rules import FEATURES

    run_dir = evaluate(Paths(built_root), "rules", "dev", params={"stage": "5"}, **QUIET)
    m = read_json(run_dir / "metrics.json")
    assert m["matcher"] == "rules-stage5"
    assert set(m["training"]["coefficients"]) == set(FEATURES)
    assert m["training"]["positives"] > 0 and m["training"]["folds"] == 5
    assert m["ranking"]["accuracy@1"] >= 0.9
    assert 0.0 <= m["calibration"]["brier"] <= 1.0
    assert sum(m["bands"][x]["n"] for x in ("accept", "review", "abstain")) == 30
