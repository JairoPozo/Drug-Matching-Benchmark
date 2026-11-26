"""Exploratory analysis of the v0.2.0 test2 runs (written after seeing test2).

Nothing here changes a pre-registered hypothesis: H1-H4 are read from
results/v0.2.0/test2_comparison.json. This script only explains them:
where the extra coverage comes from, what kind of not-in-catalog products
get accepted, and how clustered those errors are.

Run from the repository root:  python scripts/test2_analysis.py
Writes results/v0.2.0/test2_analysis.json.
"""

import collections
import json
from pathlib import Path

import polars as pl

from dmb.config import Paths
from dmb.parse import parse_catalog_name
from dmb.rxvocab import load_vocab

BASE = "rules-stage5@wilson"
NEW = "rules-dropexpected_form_missing-featuresv2-scorergb-stage5@wilson"
H4_ROUTES = ("dental", "inhalation")
H4_KITS = "0 (kit, no ingredients)"


def top1(run_dir: Path, threshold: float, ids: list[str]) -> dict:
    p = pl.read_parquet(run_dir / "predictions.parquet").filter(pl.col("rank") == 1)
    best = dict(zip(p["product_ndc"], zip(p["rxcui"], p["score"], strict=True), strict=True))
    out = {}
    for i in ids:
        x = best.get(i)
        out[i] = (x[0] if x else None, bool(x) and x[1] >= threshold)
    return out


def difference(cat_name: str, gold_name: str, dose_forms) -> str:
    a = parse_catalog_name(cat_name, dose_forms)
    g = parse_catalog_name(gold_name, dose_forms)
    diff = []
    if a.dose_form != g.dose_form:
        diff.append("dose form")
    if a.hours != g.hours:
        diff.append("hours")
    if a.quantity != g.quantity:
        diff.append("quantity")
    sa = sorted(round(s.value, 6) if s else -1 for _, s in a.components)
    sg = sorted(round(s.value, 6) if s else -1 for _, s in g.components)
    if sa != sg:
        diff.append("strength")
    if len(a.components) != len(g.components):
        diff.append("n ingredients")
    return " + ".join(diff) or "other (name, salt, qualifier)"


def main() -> None:
    paths = Paths.default()
    comparison = json.loads((paths.root / "results/v0.2.0/test2_comparison.json").read_text())
    ids = (paths.splits / "test2.txt").read_text().split()
    t2 = pl.read_parquet(paths.processed / "test2.parquet")
    expected = dict(zip(t2["product_ndc"], t2["expected_rxcui"], strict=True))
    gold = dict(zip(t2["product_ndc"], t2["gold_name"], strict=True))
    catalog = dict(pl.read_parquet(paths.processed / "catalog.parquet").iter_rows())
    vocab = load_vocab(paths.rrf_dir)

    runs, subgroups = {}, {}
    for label in (BASE, NEW):
        run_dir = paths.reports / comparison["matchers"][label]["run"]
        metrics = json.loads((run_dir / "metrics.json").read_text())
        runs[label] = top1(run_dir, metrics["at_target_precision"]["threshold"], ids)
        groups = metrics["subgroups"]["groups"]
        rows = {f"route={r}": groups["route"][r] for r in H4_ROUTES}
        rows["kits"] = groups["ingredients"][H4_KITS]
        for v in rows.values():
            v["accepted"] = round(v["coverage"] * v["n"])
            far = v["false_accept_rate"]
            v["false_accepts"] = None if far is None else round(far * v["accepted"])
        subgroups[label] = rows

    def right(label, i):
        rx, acc = runs[label][i]
        return acc and rx == expected[i]

    b, n = runs[BASE], runs[NEW]
    newly = [i for i in ids if n[i][1] and not b[i][1]]
    dropped = [i for i in ids if b[i][1] and not n[i][1]]
    correct = {lab: sum(right(lab, i) for i in ids) for lab in runs}
    wrong = {lab: sum(runs[lab][i][1] and not right(lab, i) for i in ids) for lab in runs}
    extra_right = correct[NEW] - correct[BASE]
    extra_wrong = wrong[NEW] - wrong[BASE]

    nil = [i for i in ids if expected[i] is None]
    nil_report = {}
    for label, run in runs.items():
        accepted = [i for i in nil if run[i][1]]
        kinds = collections.Counter(
            difference(catalog[run[i][0]], gold[i], vocab.dose_forms) for i in accepted
        )
        concepts = collections.Counter(gold[i] for i in accepted)
        nil_report[label] = {
            "accepted": len(accepted),
            "difference_to_held_out_concept": dict(kinds.most_common()),
            "distinct_held_out_concepts": len(concepts),
            "largest_clusters": concepts.most_common(3),
        }
    nil_b = {i for i in nil if b[i][1]}
    nil_n = {i for i in nil if n[i][1]}

    out = {
        "note": "Exploratory, written after seeing test2. Does not change H1-H4.",
        "baseline": BASE,
        "v0.2.0": NEW,
        "accept_transitions": {
            "newly_accepted": len(newly),
            "newly_accepted_right": sum(right(NEW, i) for i in newly),
            "newly_accepted_wrong_not_in_catalog": sum(
                expected[i] is None and not right(NEW, i) for i in newly
            ),
            "newly_accepted_wrong_in_catalog": sum(
                expected[i] is not None and not right(NEW, i) for i in newly
            ),
            "no_longer_accepted": len(dropped),
            "no_longer_accepted_were_right": sum(right(BASE, i) for i in dropped),
        },
        "net": {
            "correct_accepts": [correct[BASE], correct[NEW]],
            "false_accepts": [wrong[BASE], wrong[NEW]],
            "extra_correct": extra_right,
            "extra_false": extra_wrong,
            "incremental_precision": round(extra_right / (extra_right + extra_wrong), 4),
        },
        "not_in_catalog": {
            "products": len(nil),
            "distinct_held_out_concepts": len({gold[i] for i in nil}),
            "accepted_by_both": len(nil_b & nil_n),
            "only_baseline": len(nil_b - nil_n),
            "only_v0.2.0": len(nil_n - nil_b),
            "by_matcher": nil_report,
        },
        "h4_subgroups": subgroups,
    }
    target = paths.root / "results/v0.2.0/test2_analysis.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"-> {target}")


if __name__ == "__main__":
    main()
