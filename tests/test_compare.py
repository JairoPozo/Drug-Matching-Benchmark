import pytest

from dmb.compare import bootstrap_diff, compare, freeze, mcnemar_p, wilson
from dmb.config import Paths, read_json
from dmb.evaluate import evaluate

QUIET = {"log": lambda *_: None}


def test_wilson_interval():
    lo, hi = wilson(95, 100)
    assert 0.88 < lo < 0.89 and 0.978 < hi < 0.979  # known values for 95/100
    assert wilson(0, 0) is None


def test_mcnemar_and_bootstrap():
    a = [True] * 50 + [False] * 50
    assert mcnemar_p(a, a) == 1.0
    b = [True] * 100  # b fixes all 50 of a's errors, breaks none
    assert mcnemar_p(a, b) < 1e-10
    point, lo, hi = bootstrap_diff([float(x) for x in a], [float(x) for x in b])
    assert point == 0.5 and lo < 0.5 < hi


def test_freeze_then_paired_test_comparison(built_root):
    p = Paths(built_root)
    for stage in ("3", "4"):
        evaluate(p, "rules", "dev", params={"stage": stage}, **QUIET)
    labels = ["rules-stage3", "rules-stage4"]
    out = freeze(p, "v0.0.1", labels, **QUIET)
    frozen = read_json(out / "freeze.json")
    assert set(frozen["matchers"]) == set(labels)
    assert "splits/test.txt" in frozen["files_sha256"]
    with pytest.raises(RuntimeError):
        freeze(p, "v0.0.1", labels, **QUIET)  # a freeze is never overwritten
    for stage in ("3", "4"):
        evaluate(p, "rules", "test", final=True, params={"stage": stage}, **QUIET)
    report = compare(p, labels, "test", "v0.0.1", **QUIET)
    assert all(ok for _, ok, _ in report["checks"]), report["checks"]
    assert set(report["paired"]) == {"rules-stage4 vs rules-stage3"}
    assert (out / "test_comparison.json").exists()
    # data changed after the freeze -> the check fails
    (p.splits / "test.txt").write_text("changed\n")
    bad = compare(p, labels, "dev", "v0.0.1", **QUIET)
    assert not bad["checks"][0][1]
