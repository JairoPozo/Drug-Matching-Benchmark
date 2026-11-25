import shutil
import subprocess

import polars as pl
import pytest
from conftest import LEAK_SENTINEL, write_raw

from dmb.build import build
from dmb.config import SPLIT_METHOD, Paths, read_json, write_json

QUIET = {"log": lambda *_: None}


def test_build_outputs_and_exclusions(built_root):
    out = Paths(built_root).processed
    for name in (
        "catalog",
        "catalog_heldout",
        "queries",
        "labels",
        "exclusions",
        "train",
        "dev",
        "test",
    ):
        assert (out / f"{name}.parquet").exists(), name
    stats = read_json(out / "build_stats.json")
    assert stats["ndc"]["products_total"] == 124
    assert stats["ndc"]["included"] == 120
    assert stats["ndc"]["excluded_by_reason"] == {
        "no_rxcui": 1,
        "no_scd_in_release": 1,
        "multiple_scd": 1,
        "duplicate_product_ndc": 1,
    }
    assert stats["sources"]["rxnorm_release"] == "2026-10-05"


def test_holdout_is_disjoint_and_defines_nil(built_root):
    out = Paths(built_root).processed
    cat = set(pl.read_parquet(out / "catalog.parquet")["rxcui"])
    held = set(pl.read_parquet(out / "catalog_heldout.parquet")["rxcui"])
    assert len(held) == 4 and not cat & held
    labels = pl.read_parquet(out / "labels.parquet")
    for row in labels.iter_rows(named=True):
        assert row["in_catalog"] == (row["gold_rxcui"] in cat)
        assert row["expected_rxcui"] == (row["gold_rxcui"] if row["in_catalog"] else None)


def test_splits_disjoint_sized_and_written(built_root):
    p = Paths(built_root)
    dev = pl.read_parquet(p.processed / "dev.parquet")
    test = pl.read_parquet(p.processed / "test.parquet")
    assert dev.height == 30 and test.height == 30
    assert not set(dev["product_ndc"]) & set(test["product_ndc"])
    assert (p.splits / "test.txt").read_text().split() == sorted(test["product_ndc"])


def test_train_is_the_rest_and_disjoint(built_root):
    p = Paths(built_root)
    frames = {s: pl.read_parquet(p.processed / f"{s}.parquet") for s in ("train", "dev", "test")}
    ids = {s: set(df["product_ndc"]) for s, df in frames.items()}
    assert not ids["train"] & ids["dev"] and not ids["train"] & ids["test"]
    queries = set(pl.read_parquet(p.processed / "queries.parquet")["product_ndc"])
    assert ids["train"] | ids["dev"] | ids["test"] == queries
    assert (p.splits / "train.txt").read_text().split() == sorted(ids["train"])
    stats = read_json(p.processed / "build_stats.json")
    assert stats["splits"]["train"]["n"] == len(ids["train"]) == 60
    assert set(stats["near_duplicate_rate_vs_train"]) == {"dev", "test"}


def test_frozen_splits_do_not_move_when_train_is_rebuilt(built_root):
    p = Paths(built_root)
    before = {s: (p.splits / f"{s}.txt").read_text() for s in ("dev", "test")}
    build(p, **QUIET)
    assert {s: (p.splits / f"{s}.txt").read_text() for s in ("dev", "test")} == before


def test_queries_never_contain_openfda(built_root):
    q = pl.read_parquet(Paths(built_root).processed / "queries.parquet")
    assert "rxcuis" not in q.columns
    assert not q["query_text"].str.contains(LEAK_SENTINEL).any()


def test_frozen_split_files_are_reused(built_root):
    p = Paths(built_root)
    before = (p.splits / "test.txt").read_text()
    build(p, seed=999, n_dev=10, n_test=10, **QUIET)  # different seed and sizes
    assert (p.splits / "test.txt").read_text() == before


def test_same_seed_same_split(tmp_path):
    from conftest import write_raw

    roots = [tmp_path / "a", tmp_path / "b"]
    for r in roots:
        write_raw(r)
        build(Paths(r), seed=7, n_dev=20, n_test=20, **QUIET)
    a, b = (Paths(r).splits / "test.txt" for r in roots)
    assert a.read_text() == b.read_text()


def test_only_one_split_file_is_an_error(built_root):
    p = Paths(built_root)
    (p.splits / "dev.txt").unlink()
    with pytest.raises(RuntimeError):
        build(p, n_dev=10, n_test=10, **QUIET)


def test_groups_never_cross_splits(tmp_path):
    write_raw(tmp_path, n_dupes=40)  # 40 products share a group with another product
    p = Paths(tmp_path)
    stats = build(p, seed=3, n_dev=30, n_test=30, **QUIET)
    frames = {s: pl.read_parquet(p.processed / f"{s}.parquet") for s in ("train", "dev", "test")}
    keys = {s: set(df["group_key"]) for s, df in frames.items()}
    assert not keys["dev"] & keys["test"]
    assert not keys["dev"] & keys["train"]
    assert not keys["test"] & keys["train"]
    for s in ("dev", "test"):  # one product per group
        assert frames[s]["group_key"].n_unique() == frames[s].height == 30
    assert stats["groups_shared_between_splits"] == 0
    in_splits = sum(df.height for df in frames.values())
    assert in_splits + stats["reserved_eval_group_members"] == stats["ndc"]["included"] == 160
    assert stats["split_method"] == SPLIT_METHOD
    assert read_json(p.splits / "meta.json")["method"] == SPLIT_METHOD


def test_old_split_method_is_refused_until_resampled(built_root):
    p = Paths(built_root)
    write_json(p.splits / "meta.json", {"method": "per-product-v0"})
    with pytest.raises(RuntimeError, match="resample-splits"):
        build(p, n_dev=30, n_test=30, **QUIET)
    build(p, n_dev=30, n_test=30, resample_splits=True, **QUIET)
    assert read_json(p.splits / "meta.json")["method"] == SPLIT_METHOD


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_resample_is_refused_once_test_is_committed(built_root):
    p = Paths(built_root)
    subprocess.run(["git", "init", "-q"], cwd=built_root, check=True)
    subprocess.run(["git", "add", "splits/test.txt"], cwd=built_root, check=True)
    before = (p.splits / "test.txt").read_text()
    with pytest.raises(RuntimeError, match="frozen"):
        build(p, n_dev=30, n_test=30, resample_splits=True, **QUIET)
    assert (p.splits / "test.txt").read_text() == before


def test_split_keeps_the_product_type_mix():
    from dmb.build import sample_grouped_splits

    # 600 OTC products in 600 small groups, 400 prescription products in 100 groups of 4:
    # uniform sampling over groups would give ~86% OTC; products are 60% OTC.
    rows = [(f"otc-{i}", f"otc group {i}", "HUMAN OTC DRUG") for i in range(600)]
    rows += [(f"rx-{i}", f"rx group {i // 4}", "HUMAN PRESCRIPTION DRUG") for i in range(400)]
    q = pl.DataFrame(rows, schema=["product_ndc", "group_key", "product_type"], orient="row")
    out = sample_grouped_splits(q, n_dev=50, n_test=50, seed=1)
    for s in ("dev", "test"):
        assert len(out[s]) == 50
        assert sum(i.startswith("otc") for i in out[s]) == 30  # 60% of 50
    groups = {
        s: {i if i.startswith("otc") else f"rx {int(i[3:]) // 4}" for i in out[s]} for s in out
    }
    assert not groups["dev"] & groups["test"]
    assert all(len(groups[s]) == 50 for s in out)  # one product per group


def test_extra_test_split_is_drawn_from_train_and_frozen(tmp_path):
    write_raw(tmp_path, n_dupes=40)
    p = Paths(tmp_path)
    before = build(p, seed=3, n_dev=20, n_test=20, **QUIET)
    train_before = before["splits"]["train"]["n"]
    dev_test = {s: (p.splits / f"{s}.txt").read_text() for s in ("dev", "test")}
    stats = build(p, add_split="test2", extra_size=15, extra_seed=7, **QUIET)
    frames = {
        s: pl.read_parquet(p.processed / f"{s}.parquet") for s in ("train", "dev", "test", "test2")
    }
    keys = {s: set(df["group_key"]) for s, df in frames.items()}
    for a in keys:
        for b in keys:
            if a < b:
                assert not keys[a] & keys[b], (a, b)  # no group crosses splits
    assert frames["test2"].height == 15 and frames["test2"]["group_key"].n_unique() == 15
    assert stats["splits"]["train"]["n"] < train_before  # its groups left train
    assert {s: (p.splits / f"{s}.txt").read_text() for s in ("dev", "test")} == dev_test
    assert read_json(p.splits / "meta.json")["extra_splits"]["test2"]["seed"] == 7
    frozen = (p.splits / "test2.txt").read_text()
    build(p, **QUIET)  # later builds reuse it
    assert (p.splits / "test2.txt").read_text() == frozen
    with pytest.raises(RuntimeError):
        build(p, add_split="test2", **QUIET)  # never redrawn
    with pytest.raises(ValueError):
        build(p, add_split="holdout", **QUIET)


def test_split_type_mix_can_be_overridden():
    from dmb.build import sample_grouped_splits

    rows = [(f"otc-{i}", f"otc {i}", "HUMAN OTC DRUG") for i in range(300)]
    rows += [(f"rx-{i}", f"rx {i}", "HUMAN PRESCRIPTION DRUG") for i in range(300)]
    q = pl.DataFrame(rows, schema=["product_ndc", "group_key", "product_type"], orient="row")
    shares = {"HUMAN OTC DRUG": 0.47, "HUMAN PRESCRIPTION DRUG": 0.53}
    out = sample_grouped_splits(q, 100, 0, seed=1, shares=shares)["dev"]
    assert sum(i.startswith("otc") for i in out) == 47  # global mix, not the pool's 50%
