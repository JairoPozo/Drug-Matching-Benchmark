"""Build data/processed: catalog, queries, labels and dev/test splits.

Match definition (v0.1):
- Query unit: one NDC product (product_ndc), not each package.
- Label: the RxCUI in openfda.rxcui whose RxNorm term type is SCD.
- Exclusions: products with zero or more than one SCD (kits, multi-packs...). Counted by reason.
- Catalog: every active SCD with SAB=RXNORM in the Prescribable Content; 10% of concepts are
  held out so that "not in catalog" (NIL) is a valid, measurable answer.
- Splits (method "grouped-stratified-v1"): products are grouped by brand + ingredients with
  strength + dosage form (see ndc.group_key), so package sizes and repackagers of one medicine
  share a group. Dev and test each take one product from distinct groups, drawn with a fixed seed
  and stratified by product type so the prescription/OTC mix matches the data. The IDs are
  written to splits/*.txt and, once those files exist, they are reused instead of regenerated.
- Extra test splits (e.g. test2, for a later version): drawn the same way from the groups that
  were in train, then frozen like dev and test; recorded under "extra_splits" in meta.json.
- Train: every eligible product whose group is not used by dev, test or an extra split (derived,
  rebuilt on each run). The other members of dev/test groups are left out of every split, so no
  group crosses sides. Train is for stages 3-5; its rows whose concept was held out
  (in_catalog = False) are NIL examples, and their gold_rxcui must not be a training target.
"""

from __future__ import annotations

import random
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from dmb.config import (
    HOLDOUT_FRAC,
    N_DEV,
    N_TEST,
    QUERY_FORMAT_VERSION,
    SEED,
    SPLIT_METHOD,
    Paths,
    read_json,
    write_json,
)
from dmb.ndc import load_products
from dmb.rxnorm import read_rxnconso, scd_catalog, tty_counts

SPLITS = ("dev", "test")  # frozen, sampled once
EXTRA_SPLIT_SEED = 4242  # seed for extra test splits (distinct from the dev/test seed)
TRAIN = "train"  # derived: eligible products minus dev and test


def assign_labels(products: pl.DataFrame, scd_ids: set[str]) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Return (included products with gold_rxcui, exclusions with reason)."""
    seen: set[str] = set()
    included, excluded = [], []
    for row in products.iter_rows(named=True):
        ndc = row["product_ndc"]
        scds = sorted({r for r in row["rxcuis"] if r in scd_ids})
        if not ndc:
            reason = "missing_product_ndc"
        elif ndc in seen:
            reason = "duplicate_product_ndc"
        elif not row["query_text"]:
            reason = "empty_query_text"
        elif not row["rxcuis"]:
            reason = "no_rxcui"
        elif not scds:
            reason = "no_scd_in_release"
        elif len(scds) > 1:
            reason = "multiple_scd"
        else:
            reason = None
        if ndc:
            seen.add(ndc)
        if reason:
            excluded.append(
                {"product_ndc": ndc, "reason": reason, "product_type": row["product_type"]}
            )
        else:
            included.append({**{k: v for k, v in row.items() if k != "rxcuis"}, "gold": scds[0]})
    inc_schema = {k: v for k, v in products.schema.items() if k != "rxcuis"} | {"gold": pl.String}
    exc_schema = {"product_ndc": pl.String, "reason": pl.String, "product_type": pl.String}
    return (
        pl.DataFrame(included, schema=inc_schema).rename({"gold": "gold_rxcui"}),
        pl.DataFrame(excluded, schema=exc_schema),
    )


def holdout_concepts(scd_ids: list[str], frac: float, seed: int) -> set[str]:
    ids = sorted(scd_ids)
    return set(random.Random(seed).sample(ids, round(len(ids) * frac)))


def _read_ids(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_ids(path: Path, ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(ids) + "\n", encoding="utf-8")


def _test_split_is_committed(splits_dir: Path) -> bool:
    """True when splits/test.txt is tracked by git, i.e. the test split is frozen."""
    try:
        res = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "test.txt"],
            cwd=splits_dir,
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return res.returncode == 0


def _quotas(n: int, shares: dict[str, float]) -> dict[str, int]:
    """Split n across strata by share (largest remainder), so the quotas add up to n."""
    raw = {t: n * share for t, share in shares.items()}
    out = {t: int(v) for t, v in raw.items()}
    for t in sorted(raw, key=lambda t: (-(raw[t] - out[t]), t))[: n - sum(out.values())]:
        out[t] += 1
    return out


def sample_grouped_splits(
    queries: pl.DataFrame,
    n_dev: int,
    n_test: int,
    seed: int,
    shares: dict[str, float] | None = None,
) -> dict[str, list[str]]:
    """Dev and test: one product from each of n_dev + n_test distinct groups.

    Groups are drawn uniformly within each product type (prescription, OTC, ...), with quotas
    equal to that type's share of products. Drawing groups uniformly over everything would
    over-represent OTC products, whose store brands create many small groups. `shares` overrides
    the type mix (extra test splits use the mix of all eligible products, like dev and test).
    """
    members: dict[str, list[str]] = {}
    types: dict[str, Counter] = {}
    for ndc, key, ptype in queries.select("product_ndc", "group_key", "product_type").iter_rows():
        members.setdefault(key, []).append(ndc)
        types.setdefault(key, Counter())[ptype or ""] += 1
    # A group's type is its most common product type (ties broken by name).
    group_type = {g: min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0] for g, c in types.items()}
    if shares is None:
        n_products = Counter(t or "" for t in queries["product_type"].to_list())
        shares = {t: k / queries.height for t, k in n_products.items()}
    q_dev, q_test = _quotas(n_dev, shares), _quotas(n_test, shares)

    rng = random.Random(seed)
    out: dict[str, list[str]] = {"dev": [], "test": []}
    for t in sorted(shares):
        groups = sorted(g for g, gt in group_type.items() if gt == t)
        need = q_dev[t] + q_test[t]
        if need > len(groups):
            raise ValueError(f"Need {need} distinct groups of type {t!r}, only {len(groups)}")
        rng.shuffle(groups)
        out["dev"] += [rng.choice(sorted(members[g])) for g in groups[: q_dev[t]]]
        out["test"] += [rng.choice(sorted(members[g])) for g in groups[q_dev[t] : need]]
    return {s: sorted(ids) for s, ids in out.items()}


def make_or_load_splits(
    queries: pl.DataFrame,
    splits_dir: Path,
    n_dev: int,
    n_test: int,
    seed: int,
    resample: bool = False,
    log=print,
) -> dict[str, list[str]]:
    files = {s: splits_dir / f"{s}.txt" for s in SPLITS}
    meta_path = splits_dir / "meta.json"
    present = {s for s, p in files.items() if p.exists()}
    if resample and present:
        if _test_split_is_committed(splits_dir):
            raise RuntimeError(
                "splits/test.txt is committed in git: the test split is frozen and will not be "
                "re-sampled"
            )
        log("[splits] --resample-splits: overwriting the existing dev/test split files")
        present = set()
    if present == set(SPLITS):
        meta = read_json(meta_path, {}) or {}
        if meta.get("method") != SPLIT_METHOD:
            raise RuntimeError(
                f"The split files in {splits_dir} were made with method "
                f"{meta.get('method') or 'unknown (no meta.json)'}, but this code uses "
                f"{SPLIT_METHOD}. Re-sample them with `dmb build --resample-splits` "
                "(only allowed before the test split is frozen)."
            )
        eligible = set(queries["product_ndc"].to_list())
        out = {}
        for s, p in files.items():
            ids = _read_ids(p)
            missing = [i for i in ids if i not in eligible]
            if missing:
                log(
                    f"[warn] {len(missing)} of {len(ids)} {s} IDs are no longer eligible in this "
                    "data version and will be skipped"
                )
            out[s] = [i for i in ids if i in eligible]
        log(f"[splits] reusing frozen split files in {splits_dir}")
        return out
    if present:
        raise RuntimeError(
            f"Only {sorted(present)} found in {splits_dir}; "
            "dev.txt and test.txt must exist together"
        )
    out = sample_grouped_splits(queries, n_dev, n_test, seed)
    for s in SPLITS:
        _write_ids(files[s], out[s])
    write_json(
        meta_path,
        {
            "method": SPLIT_METHOD,
            "seed": seed,
            "n_dev": n_dev,
            "n_test": n_test,
            "group_key": "brand + ingredients with strength + dosage form, lowercased",
            "unit": "one product per group; a group never appears in two splits",
            "stratified_by": "product_type (quotas = share of products of each type)",
        },
    )
    log(f"[splits] created {files['dev'].name} and {files['test'].name} with seed={seed}")
    return out


def build(
    paths: Paths,
    seed: int = SEED,
    n_dev: int = N_DEV,
    n_test: int = N_TEST,
    holdout_frac: float = HOLDOUT_FRAC,
    resample_splits: bool = False,
    add_split: str | None = None,
    extra_size: int = N_TEST,
    extra_seed: int = EXTRA_SPLIT_SEED,
    log=print,
) -> dict:
    conso_path = paths.rrf_dir / "RXNCONSO.RRF"
    ndc_zips = sorted(paths.ndc_dir.glob("*.json.zip"))
    if not conso_path.exists() or not ndc_zips:
        raise FileNotFoundError("Raw data missing. Run `make data` (uv run dmb download) first.")

    log(f"[rxnorm] reading {conso_path}")
    conso = read_rxnconso(conso_path)
    catalog_full = scd_catalog(conso)
    scd_ids = set(catalog_full["rxcui"].to_list())
    held = holdout_concepts(list(scd_ids), holdout_frac, seed)
    catalog = catalog_full.filter(~pl.col("rxcui").is_in(list(held)))
    heldout = catalog_full.filter(pl.col("rxcui").is_in(list(held)))

    log(f"[ndc] reading {', '.join(p.name for p in ndc_zips)}")
    products = load_products(ndc_zips)
    included, excluded = assign_labels(products, scd_ids)

    names = dict(zip(catalog_full["rxcui"], catalog_full["name"], strict=True))
    labels = included.select(
        "product_ndc",
        "gold_rxcui",
        pl.col("gold_rxcui").replace_strict(names, return_dtype=pl.String).alias("gold_name"),
        (~pl.col("gold_rxcui").is_in(list(held))).alias("in_catalog"),
    ).with_columns(pl.when(pl.col("in_catalog")).then(pl.col("gold_rxcui")).alias("expected_rxcui"))
    queries = included.drop("gold_rxcui")

    split_ids = make_or_load_splits(
        queries, paths.splits, n_dev, n_test, seed, resample=resample_splits, log=log
    )
    split_ids |= load_or_make_extra_splits(
        queries, split_ids, paths.splits, add_split, extra_size, extra_seed, log=log
    )
    split_ids[TRAIN] = train_ids(queries, split_ids)
    reserved = queries.height - sum(len(v) for v in split_ids.values())
    _write_ids(paths.splits / f"{TRAIN}.txt", split_ids[TRAIN])

    out = paths.processed
    out.mkdir(parents=True, exist_ok=True)
    catalog.write_parquet(out / "catalog.parquet")
    heldout.write_parquet(out / "catalog_heldout.parquet")
    queries.write_parquet(out / "queries.parquet")
    labels.write_parquet(out / "labels.parquet")
    excluded.write_parquet(out / "exclusions.parquet")
    split_stats = {}
    for name, ids in split_ids.items():
        df = (
            pl.DataFrame({"product_ndc": ids}, schema={"product_ndc": pl.String})
            .join(queries, on="product_ndc", how="left")
            .join(labels, on="product_ndc", how="left")
        )
        df.write_parquet(out / f"{name}.parquet")
        split_stats[name] = {
            "n": df.height,
            "n_in_catalog": int(df["in_catalog"].sum()),
            "n_not_in_catalog": int((~df["in_catalog"]).sum()),
        }

    overlap = near_duplicate_rate(queries, split_ids)

    # Leakage indicator: how often the full normalized RxNorm name appears verbatim in the query.
    leak = (
        labels.join(queries.select("product_ndc", "query_text"), on="product_ndc")
        .select(
            pl.col("query_text")
            .str.to_lowercase()
            .str.contains(pl.col("gold_name").str.to_lowercase(), literal=True)
            .mean()
        )
        .item()
    )

    stats = {
        "seed": seed,
        "holdout_frac": holdout_frac,
        "query_format": QUERY_FORMAT_VERSION,
        "sources": _source_versions(paths),
        "rxnorm_tty_counts": tty_counts(conso),
        "catalog": {
            "scd_total": catalog_full.height,
            "in_catalog": catalog.height,
            "held_out": heldout.height,
        },
        "ndc": {
            "products_total": products.height,
            "included": included.height,
            "excluded": excluded.height,
            "excluded_by_reason": dict(Counter(excluded["reason"].to_list()).most_common()),
            "included_by_product_type": dict(
                Counter(included["product_type"].to_list()).most_common()
            ),
            "included_not_in_catalog": int((~labels["in_catalog"]).sum()),
        },
        "split_method": SPLIT_METHOD,
        "splits": split_stats,
        "groups_total": queries["group_key"].n_unique(),
        "groups_shared_between_splits": groups_shared_between_splits(queries, split_ids),
        "reserved_eval_group_members": reserved,
        "near_duplicate_rate_vs_train": overlap,
        "leak_rate_gold_name_in_query": round(float(leak or 0.0), 4),
    }
    write_json(out / "build_stats.json", stats)
    _print_stats(stats, out, log)
    return stats


def load_or_make_extra_splits(
    queries: pl.DataFrame,
    frozen: dict[str, list[str]],
    splits_dir: Path,
    add: str | None,
    n: int,
    seed: int,
    log=print,
) -> dict[str, list[str]]:
    """Reuse the extra test splits listed in meta.json and, if asked, draw a new one.

    A new split takes one product from each of n groups that are not used by any frozen split
    (the train pool), stratified by product type like dev and test. Its groups leave train.
    """
    meta_path = splits_dir / "meta.json"
    meta = read_json(meta_path, {}) or {}
    extras = meta.get("extra_splits", {})
    eligible = set(queries["product_ndc"].to_list())
    out: dict[str, list[str]] = {}
    for name in extras:
        ids = _read_ids(splits_dir / f"{name}.txt")
        missing = [i for i in ids if i not in eligible]
        if missing:
            log(f"[warn] {len(missing)} of {len(ids)} {name} IDs are no longer eligible; skipped")
        out[name] = [i for i in ids if i in eligible]
    if add:
        if not re.fullmatch(r"test\d+", add):
            raise ValueError("An extra split is named test2, test3, ...")
        if add in out or (splits_dir / f"{add}.txt").exists():
            raise RuntimeError(f"{add} already exists: frozen splits are never redrawn")
        used = {i for ids in (*frozen.values(), *out.values()) for i in ids}
        used_groups = set(queries.filter(pl.col("product_ndc").is_in(list(used)))["group_key"])
        pool = queries.filter(~pl.col("group_key").is_in(list(used_groups)))
        # Same product-type mix as dev and test (all eligible products), not the pool's.
        types = Counter(t or "" for t in queries["product_type"].to_list())
        shares = {t: k / queries.height for t, k in types.items()}
        picked = sample_grouped_splits(pool, n, 0, seed, shares=shares)["dev"]
        _write_ids(splits_dir / f"{add}.txt", picked)
        extras[add] = {
            "method": SPLIT_METHOD,
            "seed": seed,
            "n": n,
            "drawn_from": "groups not used by dev, test or earlier extra splits (the train pool)",
            "stratified_by": "product_type, with the mix of all eligible products (as dev/test)",
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        write_json(meta_path, meta | {"extra_splits": extras})
        log(f"[splits] created {add}.txt: {len(picked)} products from the train pool, seed={seed}")
        out[add] = picked
    return out


def train_ids(queries: pl.DataFrame, frozen: dict[str, list[str]]) -> list[str]:
    """Every eligible product whose group is not used by a frozen split."""
    used = {i for s, ids in frozen.items() if s != TRAIN for i in ids}
    eval_groups = set(queries.filter(pl.col("product_ndc").is_in(list(used)))["group_key"])
    return sorted(queries.filter(~pl.col("group_key").is_in(list(eval_groups)))["product_ndc"])


def groups_shared_between_splits(queries: pl.DataFrame, split_ids: dict[str, list[str]]) -> int:
    """Number of groups that appear in more than one split (must be 0)."""
    seen: dict[str, str] = {}
    shared = set()
    keys = dict(queries.select("product_ndc", "group_key").iter_rows())
    for name, ids in split_ids.items():
        for i in ids:
            g = keys[i]
            if seen.setdefault(g, name) != name:
                shared.add(g)
    return len(shared)


def _strip_labeler(df: pl.DataFrame) -> pl.Series:
    """Query text without the trailing labeler name, lowercased (for duplicate checks)."""
    return df.select(
        pl.col("query_text")
        .str.strip_suffix(pl.col("labeler_name").fill_null(""))
        .str.strip_chars()
        .str.to_lowercase()
    ).to_series()


def near_duplicate_rate(queries: pl.DataFrame, split_ids: dict[str, list[str]]) -> dict:
    """Share of dev/test queries whose text (labeler removed) also appears in train.

    The same product is often sold by several repackagers with an identical description. A
    trained model can memorize those, so stage 3 should report results with and without them.
    """
    by_split = {s: queries.filter(pl.col("product_ndc").is_in(ids)) for s, ids in split_ids.items()}
    train_texts = set(_strip_labeler(by_split[TRAIN]).to_list())
    return {
        s: round(sum(t in train_texts for t in _strip_labeler(by_split[s])) / max(len(ids), 1), 4)
        for s, ids in split_ids.items()
        if s != TRAIN
    }


def _source_versions(paths: Paths) -> dict:
    manifest = read_json(paths.manifest, {}) or {}
    ndc, rx = manifest.get("ndc", {}), manifest.get("rxnorm", {})
    return {
        "ndc_export_date": ndc.get("export_date"),
        "ndc_sha256": [f["sha256"] for f in ndc.get("files", [])],
        "rxnorm_release": rx.get("release_date"),
        "rxnorm_sha256": rx.get("sha256"),
    }


def _print_stats(s: dict, out: Path, log) -> None:
    n, c = s["ndc"], s["catalog"]
    log("")
    log("=== build summary ===")
    log(
        f"RxNorm SCD concepts: {c['scd_total']:,} ({c['in_catalog']:,} in catalog, "
        f"{c['held_out']:,} held out)"
    )
    log(f"NDC products:        {n['products_total']:,}")
    log(
        f"  included:          {n['included']:,} "
        f"({n['included_not_in_catalog']:,} whose SCD was held out -> NIL)"
    )
    log(f"  excluded:          {n['excluded']:,}")
    for reason, k in n["excluded_by_reason"].items():
        log(f"    {reason:<24}{k:,}")
    for name, sp in s["splits"].items():
        log(f"split {name:<5}: {sp['n']:,} queries ({sp['n_not_in_catalog']:,} NIL)")
    log(
        f"split method {s['split_method']}: {s['groups_total']:,} groups, "
        f"{s['groups_shared_between_splits']} shared between splits, "
        f"{s['reserved_eval_group_members']:,} products left out (same group as a dev/test item)"
    )
    for name, rate in s["near_duplicate_rate_vs_train"].items():
        log(f"{name} queries with an identical text in train (labeler removed): {rate:.2%}")
    log(
        f"leak indicator (gold RxNorm name verbatim in query): "
        f"{s['leak_rate_gold_name_in_query']:.2%}"
    )
    log(f"written to {out}")
