"""Secondary, optional analysis from the v0.2.0 pre-registration (plan.md, section 6.5).

The v0.2.0 configuration is evaluated once on the v0.1.0 test split and compared with the
v0.1.0 test runs. Nothing here is used to decide anything.

Caveats, which are why the comparison is descriptive:
- The v0.1.0 matchers were trained before test2 left train (36,059 products). The v0.2.0
  trains on 30,375.
- The v0.1.0 stage 5 used the point threshold rule; the v0.2.0 uses the Wilson rule. The
  difference mixes scorer, threshold rule and train size.

Run from the repository root:  python scripts/test_secondary.py
Writes results/v0.2.0/test_secondary.json.
"""

import json

from dmb.compare import _load, _summary, band_of, bootstrap_diff, mcnemar_p, transitions
from dmb.config import Paths

V020 = "rules-dropexpected_form_missing-featuresv2-scorergb-stage5@wilson"
V010 = ("rules-stage4", "rules-stage5")
H4_ROUTES = ("dental", "inhalation")
H4_KITS = "0 (kit, no ingredients)"


def run_dir(paths: Paths, label: str):
    runs = sorted(paths.reports.glob(f"*_{label}_test/metrics.json"))
    if len(runs) != 1:
        raise RuntimeError(f"expected exactly one test run of {label}, found {len(runs)}")
    return runs[0].parent


def h4(metrics: dict) -> dict:
    groups = metrics["subgroups"]["groups"]
    rows = {f"route={r}": groups["route"][r] for r in H4_ROUTES}
    rows["kits"] = groups["ingredients"][H4_KITS]
    out = {}
    for name, v in rows.items():
        accepted = round(v["coverage"] * v["n"])
        far = v["false_accept_rate"]
        out[name] = {
            "n": v["n"],
            "n_nil": v["n_nil"],
            "accuracy@1": v["accuracy@1"],
            "accepted": accepted,
            "false_accepts": None if far is None else round(far * accepted),
        }
    return out


def main() -> None:
    paths = Paths.default()
    data, summaries, subgroups = {}, {}, {}
    for label in (*V010, V020):
        run = run_dir(paths, label)
        metrics = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
        ids, expected, cands = _load(paths, run, "test")
        data[label] = (metrics, ids, expected, cands)
        summaries[label] = {"run": run.name, "git_commit": metrics.get("git_commit")}
        summaries[label] |= _summary(metrics, expected, cands)
        subgroups[label] = h4(metrics)

    ref_ids, ref_expected = data[V020][1], data[V020][2]
    for label, (_, ids, expected, _) in data.items():
        if ids != ref_ids or expected != ref_expected:
            raise RuntimeError(f"{label}: products or labels differ from the v0.2.0 run")

    def per_product(label):
        metrics, _, expected, cands = data[label]
        t_accept = metrics["at_target_precision"]["threshold"]
        t_abstain = (metrics.get("bands") or {}).get("t_abstain")
        bands = [band_of(c, t_accept, t_abstain) for c in cands]
        accepted = [b == "accept" for b in bands]
        right = [a and c[0][0] == e for a, c, e in zip(accepted, cands, expected, strict=True)]
        top1 = [bool(c) and c[0][0] == e for c, e in zip(cands, expected, strict=True)]
        return bands, accepted, right, top1

    nil = [e is None for e in ref_expected]
    answerable = [i for i, x in enumerate(nil) if not x]
    nil_idx = [i for i, x in enumerate(nil) if x]
    paired = {}
    new_bands, new_acc, new_right, new_top1 = per_product(V020)
    for label in V010:
        bands, acc, right, top1 = per_product(label)
        a_top = [float(top1[i]) for i in answerable]
        b_top = [float(new_top1[i]) for i in answerable]
        a_nil = [acc[i] for i in nil_idx]
        b_nil = [new_acc[i] for i in nil_idx]
        extra_right = sum(new_right) - sum(right)
        extra_wrong = (sum(new_acc) - sum(new_right)) - (sum(acc) - sum(right))
        paired[f"{V020} vs {label} (v0.1.0)"] = {
            "accuracy@1_diff_ci95": bootstrap_diff(a_top, b_top),
            "mcnemar_p_top1": mcnemar_p([bool(x) for x in a_top], [bool(x) for x in b_top]),
            "coverage_diff_ci95": bootstrap_diff(
                [float(x) for x in acc], [float(x) for x in new_acc]
            ),
            "nil_accept_rate_diff_ci95": bootstrap_diff(
                [float(x) for x in a_nil], [float(x) for x in b_nil]
            ),
            "mcnemar_p_nil_accepted": mcnemar_p(a_nil, b_nil),
            "transitions": transitions(bands, new_bands, new_right),
            "extra_correct_accepts": extra_right,
            "extra_false_accepts": extra_wrong,
            # None when v0.2.0 adds correct accepts and removes false ones (it dominates)
            "dominates": extra_right >= 0 and extra_wrong <= 0,
            "incremental_precision": (
                round(extra_right / (extra_right + extra_wrong), 4) if extra_wrong > 0 else None
            ),
        }

    out = {
        "note": (
            "Secondary and optional (plan.md 6.5). Descriptive: the v0.1.0 runs used a larger "
            "train (36,059) and, for stage 5, the point threshold rule. Not used for decisions."
        ),
        "split": "test (v0.1.0)",
        "matchers": summaries,
        "paired": paired,
        "h4_subgroups": subgroups,
    }
    target = paths.root / "results/v0.2.0/test_secondary.json"
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"-> {target}")


if __name__ == "__main__":
    main()
