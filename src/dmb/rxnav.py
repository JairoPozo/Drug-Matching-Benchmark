"""RxNav approximate matching as an existing-tool baseline (v0.2.2).

The RxNav API of the National Library of Medicine is called by scripts/rxnav_fetch.py, a
standalone script that runs on any machine with internet access. This module writes its input and
reads its output:

- export_queries() writes data/rxnav/queries_<name>.jsonl with each product's query in two forms:
  "full" is the benchmark query text; "short" keeps only the ingredients with strength, the dose
  form and the route, lightly cleaned, which is closer to the drug names RxNav is built for.
- load_responses() reads data/rxnav/responses_<name>.jsonl back.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import polars as pl

from dmb.config import Paths
from dmb.ndc import _clean, format_ingredients, iter_ndc_records

API = "https://rxnav.nlm.nih.gov/REST/Prescribe/approximateTerm.json"  # Prescribable subset
MAX_ENTRIES = 100  # the API maximum
OPTION = 1  # atoms in active concepts
VARIANTS = ("full", "short")
TRAIN_SAMPLE = "train_sample"  # products whose responses fix the score scale and the calibration
TRAIN_SAMPLE_SIZE = 2000
TRAIN_SAMPLE_SEED = 2027


def rxnav_dir(paths: Paths) -> Path:
    return paths.root / "data" / "rxnav"


def short_query(rec: dict) -> str:
    """Ingredients with strength, dose form and route, e.g. 'CLONIDINE HYDROCHLORIDE 0.3 mg TABLET
    ORAL'. Per-unit denominators ('/1') and brackets ('[iU]') are dropped, and a leading zero is
    added to decimals ('.3' -> '0.3')."""
    parts = (
        format_ingredients(rec.get("active_ingredients")),
        _clean(rec.get("dosage_form")),
        _clean(", ".join(rec.get("route") or [])),
    )
    text = " ".join(p for p in parts if p)
    text = re.sub(r"/1(?![\d.])", "", text)
    text = text.replace("[", "").replace("]", "")
    text = re.sub(r"(?<![\d.])\.(\d)", r"0.\1", text)
    return " ".join(text.split())


def _products(paths: Paths, name: str) -> pl.DataFrame:
    if name == TRAIN_SAMPLE:
        # only products whose concept is in the catalog, like the rest of training
        train = pl.read_parquet(paths.processed / "train.parquet").filter(pl.col("in_catalog"))
        return train.sample(n=TRAIN_SAMPLE_SIZE, seed=TRAIN_SAMPLE_SEED).sort("product_ndc")
    return pl.read_parquet(paths.processed / f"{name}.parquet")


def export_queries(paths: Paths, names: list[str], log=print) -> None:
    frames = {name: _products(paths, name) for name in names}
    wanted = set().union(*(set(df["product_ndc"].to_list()) for df in frames.values()))
    records: dict[str, dict] = {}
    for rec in iter_ndc_records(sorted(paths.ndc_dir.glob("*.zip"))):
        ndc = rec.get("product_ndc")
        if ndc in wanted:
            records.setdefault(ndc, rec)
    out_dir = rxnav_dir(paths)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        path = out_dir / f"queries_{name}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for ndc, text in df.select("product_ndc", "query_text").iter_rows():
                line = {"product_ndc": ndc, "full": text, "short": short_query(records[ndc])}
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        log(f"[rxnav] {df.height} queries -> {path}")


def load_responses(paths: Paths, name: str, variant: str) -> dict[str, list]:
    """product_ndc -> candidates [rxcui, rxaui, score, rank, source, name], from the last
    successful response of each product (a resumed download may hold earlier failed lines)."""
    path = rxnav_dir(paths) / f"responses_{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run scripts/rxnav_fetch.py {name} first.")
    out: dict[str, list] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("variant") == variant and row.get("status") == "ok":
                out[row["product_ndc"]] = row["candidates"]
    return out
