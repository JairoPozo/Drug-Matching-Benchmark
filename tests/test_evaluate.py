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


def test_test_split_requires_final_and_runs_once(built_root):
    p = Paths(built_root)
    with pytest.raises(FrozenSplitError):
        evaluate(p, "dummy", "test", **QUIET)
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


def test_unknown_and_unimplemented_matchers(built_root):
    with pytest.raises(ValueError):
        get_matcher("nope")
    with pytest.raises(NotImplementedError):
        evaluate(Paths(built_root), "rules", "dev", **QUIET)
