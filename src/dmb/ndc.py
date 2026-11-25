"""Read the openFDA NDC Directory and turn each product into a query text.

Field reference: https://open.fda.gov/apis/drug/ndc/searchable-fields/ (drugndc.yaml).

Leakage rule: the query text is built ONLY from NDC's own fields. Nothing under
`openfda.*` may reach it, because those fields are derived from RxNorm and would
give the answer away. `openfda.rxcui` is read separately, only to build labels.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path

import polars as pl

# Fields allowed in the query text (v0.2). Week 2 of the plan fixes the final format.
QUERY_FIELDS = ("brand_name", "active_ingredients", "dosage_form", "packaging", "labeler_name")

# Package NDC codes in parentheses, e.g. "(0363-7470-04)". A real catalog (e.g. a Chilean one)
# would not carry them, and a trained model could use them as a shortcut, so v0.2 drops them.
_PACKAGE_NDC = re.compile(r"\(\s*\d{4,5}-\d{3,4}-\d{1,2}\s*\)")


def iter_ndc_records(zip_paths: Iterable[Path]) -> Iterator[dict]:
    for zp in zip_paths:
        with zipfile.ZipFile(zp) as zf:
            for member in zf.namelist():
                if not member.endswith(".json"):
                    continue
                with zf.open(member) as f:
                    yield from json.load(f)["results"]


def _clean(value) -> str:
    return " ".join(str(value).split()) if value else ""


def format_ingredients(active_ingredients: list[dict] | None) -> str:
    parts = []
    for ing in active_ingredients or []:
        text = " ".join(p for p in (_clean(ing.get("name")), _clean(ing.get("strength"))) if p)
        if text:
            parts.append(text)
    return ", ".join(parts)


def strip_package_ndc(text: str) -> str:
    return _clean(_PACKAGE_NDC.sub(" ", text or ""))


def build_query_text(rec: dict) -> str:
    """Catalog-style line: {brand} {ingredients+strength} {dosage form} {package} {labeler}.

    The package description is kept without its NDC code (query format v0.2).
    """
    packaging = rec.get("packaging") or []
    package = strip_package_ndc(packaging[0].get("description")) if packaging else ""
    parts = [
        _clean(rec.get("brand_name")),
        format_ingredients(rec.get("active_ingredients")),
        _clean(rec.get("dosage_form")),
        package,
        _clean(rec.get("labeler_name")),
    ]
    return " ".join(p for p in parts if p)


def group_key(rec: dict) -> str:
    """Products that differ only in package or labeler share this key.

    It is brand + ingredients with strength + dosage form, lowercased. The same medicine sold by
    several repackagers, or in several package sizes, gets one key, and the split keeps each key
    on one side so a trained model cannot memorize a test answer from train.
    """
    parts = (
        _clean(rec.get("brand_name")),
        format_ingredients(rec.get("active_ingredients")),
        _clean(rec.get("dosage_form")),
    )
    return " | ".join(parts).lower()


def product_row(rec: dict) -> dict:
    openfda = rec.get("openfda") or {}
    return {
        "product_ndc": rec.get("product_ndc"),
        "query_text": build_query_text(rec),
        "group_key": group_key(rec),
        "product_type": rec.get("product_type"),
        "finished": rec.get("finished"),
        "dosage_form": rec.get("dosage_form"),
        "route": ", ".join(rec.get("route") or []),
        "labeler_name": rec.get("labeler_name"),
        "n_ingredients": len(rec.get("active_ingredients") or []),
        # Label source only. Never part of the query.
        "rxcuis": [str(x) for x in openfda.get("rxcui") or []],
    }


def load_products(zip_paths: Iterable[Path]) -> pl.DataFrame:
    rows = [product_row(r) for r in iter_ndc_records(zip_paths)]
    schema = {
        "product_ndc": pl.String,
        "query_text": pl.String,
        "group_key": pl.String,
        "product_type": pl.String,
        "finished": pl.Boolean,
        "dosage_form": pl.String,
        "route": pl.String,
        "labeler_name": pl.String,
        "n_ingredients": pl.Int32,
        "rxcuis": pl.List(pl.String),
    }
    return pl.DataFrame(rows, schema=schema)
