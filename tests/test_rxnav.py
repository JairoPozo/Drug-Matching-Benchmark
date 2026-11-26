"""RxNav baseline: query cleanup and the rules applied to cached responses (no network)."""

from __future__ import annotations

import json

import polars as pl
import pytest

from dmb.config import Paths, read_json
from dmb.evaluate import evaluate
from dmb.matchers import get_matcher
from dmb.rxnav import TRAIN_SAMPLE, rxnav_dir, short_query

QUIET = {"log": lambda *_: None}


def test_short_query_keeps_ingredients_form_and_route():
    rec = {
        "brand_name": "Catapres",
        "active_ingredients": [{"name": "CLONIDINE HYDROCHLORIDE", "strength": ".3 mg/1"}],
        "dosage_form": "TABLET",
        "route": ["ORAL"],
        "labeler_name": "Lab",
    }
    assert short_query(rec) == "CLONIDINE HYDROCHLORIDE 0.3 mg TABLET ORAL"
    insulin = {
        "active_ingredients": [{"name": "INSULIN LISPRO", "strength": "100 [iU]/mL"}],
        "dosage_form": "INJECTION, SUSPENSION",
        "route": ["SUBCUTANEOUS"],
    }
    assert short_query(insulin) == "INSULIN LISPRO 100 iU/mL INJECTION, SUSPENSION SUBCUTANEOUS"
    syrup = {
        "active_ingredients": [
            {"name": "X", "strength": "5 mg/10mL"},
            {"name": "Y", "strength": "1 mg/1.5mL"},
        ]
    }
    assert short_query(syrup) == "X 5 mg/10mL, Y 1 mg/1.5mL"


def _write_responses(root, name: str, df: pl.DataFrame, catalog: set[str]) -> None:
    """Each product: its true SCD through an RXNORM name, a label name (MTHSPL) of another concept
    scored higher, a branded concept (not in the catalog) and a wrong catalog SCD scored lower."""
    other = sorted(catalog)
    path = rxnav_dir(Paths(root)) / f"responses_{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for i, (ndc, gold) in enumerate(df.select("product_ndc", "gold_rxcui").iter_rows()):
            wrong = other[0] if other[0] != gold else other[1]
            cands = [
                ["99999", "A1", 14.0, 1, "MTHSPL", "label name"],
                ["5000", "A2", 12.0, 2, "RXNORM", "branded"],
                [gold, "A3", 10.0 + (i % 3), 3, "RXNORM", "true"],
                [wrong, "A4", 5.0, 4, "RXNORM", "wrong"],
            ]
            for variant in ("full", "short"):
                row = {"product_ndc": ndc, "variant": variant, "status": "ok", "candidates": cands}
                f.write(json.dumps(row) + "\n")


@pytest.fixture
def rxnav_root(built_root):
    p = Paths(built_root)
    catalog = set(pl.read_parquet(p.processed / "catalog.parquet")["rxcui"].to_list())
    train = pl.read_parquet(p.processed / "train.parquet").filter(pl.col("in_catalog"))
    _write_responses(built_root, TRAIN_SAMPLE, train, catalog)
    _write_responses(built_root, "dev", pl.read_parquet(p.processed / "dev.parquet"), catalog)
    return built_root


def test_rxnav_keeps_only_catalog_concepts_from_rxnorm_names(rxnav_root):
    p = Paths(rxnav_root)
    dev = pl.read_parquet(p.processed / "dev.parquet")
    matcher = get_matcher("rxnav", input="full", score="raw")
    matcher.paths, matcher.split = p, "dev"
    matcher.fit(pl.read_parquet(p.processed / "catalog.parquet"))
    cands = matcher.match_many(dev["query_text"].to_list())
    for (expected, gold), c in zip(
        dev.select("expected_rxcui", "gold_rxcui").iter_rows(), cands, strict=True
    ):
        assert all(r not in ("99999", "5000") for r, _ in c)  # label names and brands dropped
        if expected is not None:
            assert c[0][0] == gold
        else:  # held-out concept: never offered
            assert gold not in [r for r, _ in c]
        assert all(0 <= s <= 1 for _, s in c) and [s for _, s in c] == sorted(
            (s for _, s in c), reverse=True
        )


def test_rxnav_runs_end_to_end_and_needs_every_response(rxnav_root):
    p = Paths(rxnav_root)
    run = evaluate(
        p,
        "rxnav",
        "dev",
        params={"input": "short", "score": "cal"},
        threshold_rule="wilson",
        **QUIET,
    )
    m = read_json(run / "metrics.json")
    assert m["training"]["coefficients"] and run.name.endswith(
        "_rxnav-inputshort-scorecal@wilson_dev"
    )
    lines = (rxnav_dir(p) / "responses_dev.jsonl").read_text(encoding="utf-8").splitlines()
    (rxnav_dir(p) / "responses_dev.jsonl").write_text("\n".join(lines[2:]) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no RxNav response"):
        evaluate(p, "rxnav", "dev", params={"input": "full"}, **QUIET)
