"""Blinded pharmacist review of the automatic accepts that disagree with the label on test2.

Cases: every product of test2 that rules-stage5@wilson or the v0.2.0 configuration accepted
automatically with a concept different from its openfda.rxcui label (the union of both
methods' false accepts). Written before any pharmacist answer is seen; the analysis plan is in
results/v0.2.0/revision_farmaceutica/protocolo.md.

Blinding: rows are shuffled, and in each row the label concept and the accepted concept are
shown as "Concepto 1" and "Concepto 2" in random order. The key that says which is which is
written to a separate file for the author only.

Run from the repository root:  python scripts/pharmacist_review.py
Writes data/review/revision_farmaceutica_test2/{casos.csv, clave.csv, casos.json}.
"""

import csv
import json
import random

import polars as pl
from test2_analysis import difference

from dmb.config import Paths
from dmb.ndc import format_ingredients, iter_ndc_records, strip_package_ndc
from dmb.parse import parse_catalog_name
from dmb.rxvocab import load_vocab

SEED = 20261125
BASE = "rules-stage5@wilson"
NEW = "rules-dropexpected_form_missing-featuresv2-scorergb-stage5@wilson"
DAILYMED = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="


def false_accepts(paths: Paths, run: str, expected: dict) -> dict:
    run_dir = paths.reports / run
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    threshold = metrics["at_target_precision"]["threshold"]
    top = pl.read_parquet(run_dir / "predictions.parquet").filter(pl.col("rank") == 1)
    out = {}
    for ndc, rxcui, score in top.select("product_ndc", "rxcui", "score").iter_rows():
        if score >= threshold and rxcui != expected[ndc]:
            out[ndc] = (rxcui, score)
    return out


def main() -> None:
    paths = Paths.default()
    comparison = json.loads((paths.root / "results/v0.2.0/test2_comparison.json").read_text())
    runs = {label: m["run"] for label, m in comparison["matchers"].items()}
    t2 = pl.read_parquet(paths.processed / "test2.parquet")
    expected = dict(zip(t2["product_ndc"], t2["expected_rxcui"], strict=True))
    gold = {r["product_ndc"]: r for r in t2.iter_rows(named=True)}
    catalog = dict(pl.read_parquet(paths.processed / "catalog.parquet").iter_rows())
    vocab = load_vocab(paths.rrf_dir)

    base = false_accepts(paths, runs[BASE], expected)
    new = false_accepts(paths, runs[NEW], expected)
    ndcs = sorted(set(base) | set(new))
    for ndc in set(base) & set(new):
        if base[ndc][0] != new[ndc][0]:
            raise RuntimeError(f"{ndc}: the two methods accepted different concepts")

    wanted = set(ndcs)
    records = {}
    for rec in iter_ndc_records(sorted(paths.ndc_dir.glob("*.zip"))):
        if rec.get("product_ndc") in wanted and rec["product_ndc"] not in records:
            records[rec["product_ndc"]] = rec

    rng = random.Random(SEED)
    rng.shuffle(ndcs)
    cases, key = [], []
    for i, ndc in enumerate(ndcs, start=1):
        rec, g = records[ndc], gold[ndc]
        accepted = (new.get(ndc) or base.get(ndc))[0]
        label_first = rng.random() < 0.5
        official = (g["gold_rxcui"], g["gold_name"])
        chosen = (accepted, catalog[accepted])
        c1, c2 = (official, chosen) if label_first else (chosen, official)
        packaging = rec.get("packaging") or []
        set_ids = (rec.get("openfda") or {}).get("spl_set_id") or []
        cases.append(
            {
                "id": i,
                "ndc": ndc,
                "marca": rec.get("brand_name") or "",
                "principios_activos": format_ingredients(rec.get("active_ingredients")),
                "forma_ndc": rec.get("dosage_form") or "",
                "via_ndc": ", ".join(rec.get("route") or []),
                "envase": strip_package_ndc(packaging[0].get("description")) if packaging else "",
                "laboratorio": rec.get("labeler_name") or "",
                "tipo": rec.get("product_type") or "",
                "dailymed": DAILYMED + set_ids[0] if set_ids else "",
                "concepto_1_rxcui": c1[0],
                "concepto_1": c1[1],
                "concepto_1_forma": parse_catalog_name(c1[1], vocab.dose_forms).dose_form,
                "concepto_2_rxcui": c2[0],
                "concepto_2": c2[1],
                "concepto_2_forma": parse_catalog_name(c2[1], vocab.dose_forms).dose_form,
            }
        )
        key.append(
            {
                "id": i,
                "ndc": ndc,
                "concepto_etiqueta": 1 if label_first else 2,
                "concepto_aceptado": 2 if label_first else 1,
                "etiqueta_rxcui": official[0],
                "etiqueta": official[1],
                "aceptado_rxcui": chosen[0],
                "aceptado": chosen[1],
                "etiqueta_en_catalogo": bool(g["in_catalog"]),
                "aceptado_por_v020": ndc in new,
                "aceptado_por_linea_base": ndc in base,
                "puntaje_v020": round(new[ndc][1], 4) if ndc in new else None,
                "puntaje_linea_base": round(base[ndc][1], 4) if ndc in base else None,
                "diferencia_automatica": difference(chosen[1], official[1], vocab.dose_forms),
            }
        )

    out_dir = paths.root / "data/review/revision_farmaceutica_test2"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("casos", cases), ("clave", key)):
        with (out_dir / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
    (out_dir / "casos.json").write_text(
        json.dumps({"cases": cases, "key": key}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        f"{len(cases)} cases: {sum(k['aceptado_por_v020'] for k in key)} accepted by v0.2.0, "
        f"{sum(k['aceptado_por_linea_base'] for k in key)} by the baseline, "
        f"{sum(not k['etiqueta_en_catalogo'] for k in key)} with the label concept not in "
        f"the catalog -> {out_dir}"
    )


if __name__ == "__main__":
    main()
