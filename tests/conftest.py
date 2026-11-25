"""Synthetic raw data in the real NDC JSON / RxNorm RRF formats, so tests never hit the network."""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

import pytest

from dmb.config import Paths, write_json
from dmb.rxnorm import RXNCONSO_COLUMNS

INGREDIENTS = [
    "acetaminophen",
    "ibuprofen",
    "amoxicillin",
    "atorvastatin",
    "metformin",
    "lisinopril",
    "omeprazole",
    "sertraline",
    "losartan",
    "amlodipine",
]
STRENGTHS = [5, 10, 20, 50]
LEAK_SENTINEL = "OPENFDA_SENTINEL_DO_NOT_LEAK"


def conso_line(rxcui: str, tty: str, name: str, sab: str = "RXNORM", suppress: str = "N") -> str:
    row = dict.fromkeys(RXNCONSO_COLUMNS, "")
    row.update(
        RXCUI=rxcui,
        LAT="ENG",
        SAB=sab,
        TTY=tty,
        CODE=rxcui,
        STR=name,
        SUPPRESS=suppress,
        CVF="4096",
    )
    return "|".join(row[c] for c in RXNCONSO_COLUMNS) + "|"


def make_concepts() -> list[dict]:
    """40 SCDs (10 ingredients x 4 strengths), each with a branded SBD."""
    concepts = []
    for i, ing in enumerate(INGREDIENTS):
        for j, s in enumerate(STRENGTHS):
            scd = str(1000 + 10 * i + j)
            concepts.append(
                {
                    "scd": scd,
                    "sbd": str(5000 + 10 * i + j),
                    "ing": ing,
                    "strength": s,
                    "name": f"{ing} {s} MG Oral Tablet",
                }
            )
    return concepts


def ndc_record(n: int, concept: dict | None, rxcuis: list[str]) -> dict:
    ing = concept["ing"] if concept else "mystery"
    s = concept["strength"] if concept else 1
    ndc = f"{10000 + n:05d}-{n % 1000:03d}"
    return {
        "product_ndc": ndc,
        "product_type": "HUMAN PRESCRIPTION DRUG",
        "finished": True,
        "brand_name": f"Brand{n}",
        "generic_name": ing.upper(),
        "dosage_form": "TABLET",
        "route": ["ORAL"],
        "labeler_name": f"Lab {n % 7}",
        "active_ingredients": [{"name": ing.upper(), "strength": f"{s} mg/1"}],
        "packaging": [
            {"package_ndc": f"{ndc}-01", "description": f"100 TABLET in 1 BOTTLE ({ndc}-01)"}
        ],
        "openfda": {"rxcui": rxcuis, "manufacturer_name": [LEAK_SENTINEL]},
    }


def write_raw(root: Path, n_products: int = 120, n_dupes: int = 0) -> dict:
    """n_dupes adds copies of the first products under another labeler and package size,
    like repackagers do: same group, different product_ndc."""
    paths = Paths(root)
    concepts = make_concepts()
    lines = []
    for c in concepts:
        lines.append(conso_line(c["scd"], "SCD", c["name"]))
        lines.append(conso_line(c["sbd"], "SBD", f"{c['name']} [Brand]"))
    lines.append(conso_line("9", "IN", "acetaminophen"))
    lines.append(conso_line("317541", "DF", "Oral Tablet"))
    lines.append(conso_line("8888", "SCD", "obsolete 1 MG Oral Tablet", suppress="O"))
    lines.append(conso_line("7777", "SCD", "other source 1 MG Oral Tablet", sab="MTHSPL"))
    paths.rrf_dir.mkdir(parents=True)
    (paths.rrf_dir / "RXNCONSO.RRF").write_text("\n".join(lines) + "\n", encoding="utf-8")

    records = []
    for n in range(n_products):
        c = concepts[n % len(concepts)]
        records.append(ndc_record(n, c, [c["scd"], c["sbd"]]))
    # Exclusions, one of each kind
    records.append(ndc_record(900, None, []))  # no_rxcui
    records.append(ndc_record(901, None, ["8888"]))  # no_scd_in_release (suppressed)
    records.append(ndc_record(902, concepts[0], [concepts[0]["scd"], concepts[1]["scd"]]))  # multi
    records.append(dict(records[0]))  # duplicate_product_ndc
    for i in range(n_dupes):
        rec = copy.deepcopy(records[i])
        ndc = f"{20000 + i:05d}-{i:03d}"
        rec["product_ndc"] = ndc
        rec["labeler_name"] = f"Repackager {i}"
        rec["packaging"] = [
            {"package_ndc": f"{ndc}-02", "description": f"30 TABLET in 1 BOTTLE ({ndc}-02)"}
        ]
        records.append(rec)

    paths.ndc_dir.mkdir(parents=True)
    with zipfile.ZipFile(paths.ndc_dir / "drug-ndc-0001-of-0001.json.zip", "w") as zf:
        zf.writestr("drug-ndc-0001-of-0001.json", json.dumps({"meta": {}, "results": records}))
    write_json(
        paths.manifest,
        {
            "ndc": {"export_date": "2026-11-01", "files": [{"sha256": "x", "file": "f"}]},
            "rxnorm": {"release_date": "2026-10-05", "sha256": "y", "file": "z"},
        },
    )
    return {"concepts": concepts, "records": records}


@pytest.fixture
def raw_root(tmp_path: Path) -> Path:
    write_raw(tmp_path)
    return tmp_path


@pytest.fixture
def built_root(raw_root: Path) -> Path:
    from dmb.build import build

    build(Paths(raw_root), seed=42, n_dev=30, n_test=30, holdout_frac=0.1, log=lambda *_: None)
    return raw_root
