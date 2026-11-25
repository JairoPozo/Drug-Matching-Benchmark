# Drug Matching Benchmark

**How well can you identify a normalized drug (active ingredient + strength + dose form) from
the commercial description of a product?**

This repo is an open, reproducible benchmark for that entity-resolution problem, built only
from public-domain data:

- **Queries**: products from the FDA [NDC Directory](https://open.fda.gov/apis/drug/ndc/)
  (via openFDA): brand, ingredients with strength, dose form, packaging and labeler.
- **Target catalog**: [RxNorm Current Prescribable Content](https://www.nlm.nih.gov/research/umls/rxnorm/docs/prescribe.html),
  Semantic Clinical Drug concepts (`TTY=SCD`).
- **Free labels**: each NDC record carries `openfda.rxcui`, which links it to RxNorm. That code
  is used as ground truth and hidden from the matcher, so we measure what can be recovered from
  the text alone.

The task: given a product, return its SCD concept in RxNorm **or answer "not in the catalog"**.
Output: `(product, concept, confidence)`.

> Status: **v0.1 in progress.** The pipeline (download → build → evaluate) works end to end with
> a dummy matcher. The rule-based baseline and the final test results are coming.

## Results

| Matcher | Split | accuracy@1 | recall@5 | Accept precision | Accept recall | Threshold |
|---------|-------|-----------:|---------:|-----------------:|--------------:|----------:|
| rules   | test  | _tbd_      | _tbd_    | _tbd_ (target ≥ 0.95) | _tbd_   | _tbd_     |

Error analysis: _tbd_.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you) and, optionally, `make`.

```bash
make setup data build              # install, download sources, build the dataset
make eval MATCHER=dummy SPLIT=dev  # run a matcher, metrics go to reports/
make test                          # pytest + ruff
```

Without `make` (e.g. Windows PowerShell), run the same steps directly:

```powershell
uv sync
uv run dmb download
uv run dmb build
uv run dmb eval --matcher dummy --split dev
uv run pytest; uv run ruff check .
```

`make data` downloads roughly 60 MB of zips (plus the extracted RRF files) into `data/raw/`
and writes `data/raw/manifest.json` with each source's version, URL and sha256.

## Benchmark definition (v0.1)

| | |
|---|---|
| Query unit | One NDC product (`product_ndc`), not each package |
| Query text (format v0.2) | `{brand_name} {ingredients + strength} {dosage_form} {first package description} {labeler_name}`, with the package NDC code removed from the description (a real catalog would not carry it). Never any `openfda.*` field (they come from RxNorm and would leak the answer) |
| Label | The RxCUI in `openfda.rxcui` whose RxNorm term type is `SCD` |
| Exclusions | Products with zero or more than one SCD (kits, multi-packs, ...), counted by reason in `data/processed/build_stats.json` |
| Catalog | All active `SCD` concepts with `SAB=RXNORM`; **10% are held out** so "not in catalog" (NIL) is a measurable answer |
| Splits | Grouped by brand + ingredients + dosage form, so package sizes and repackagers of one medicine never cross splits. 2,000 dev / 2,000 test products, one per group, seed 42, stratified by product type; frozen once `splits/test.txt` is committed. `train` = products of every other group (36,059). See `splits/README.md` |

### Metrics

- **Ranking** (answerable queries): accuracy@1, recall@5.
- **Accept/abstain decision** at threshold *t* (accept top-1 if score ≥ *t*):
  precision = correct accepts / accepts, recall = correct accepts / answerable queries, F1.
- **Abstention** (NIL detection): precision and recall of abstaining on held-out concepts.
- **Precision-recall curve** over all thresholds; the reported operating point is the highest
  recall with precision ≥ 95% (automatic matching).

## Rules of the benchmark

- Data is never committed: `make data` downloads it and records versions + checksums.
- The test split is frozen. `dmb eval --split test` refuses to run without `--final`, and a
  second test run needs `--force-rerun` and is logged in `reports/test_runs.log`.
- Exploration happens in notebooks (`make notebook`); official numbers come from `dmb eval`.
- To pin the RxNorm release, set `rxnorm_release` in `sources.json` (e.g. `"10052026"`).
  openFDA only serves the latest NDC export, so NDC is tracked by export date + sha256, and the
  frozen split IDs keep the test set stable.

## Repository layout

```
├── sources.json          # pinned source versions
├── splits/               # frozen dev/test IDs + derived train IDs (committed)
├── data/                 # raw downloads and processed parquet files (git-ignored)
├── reports/              # one folder per evaluation run (git-ignored)
├── src/dmb/
│   ├── download.py       # fetch NDC + RxNorm, record version and checksum
│   ├── build.py          # catalog, queries, labels, exclusions, splits
│   ├── ndc.py / rxnorm.py
│   ├── matchers/         # base interface, dummy, rules (baseline)
│   ├── metrics.py
│   └── evaluate.py       # metrics.json, pr_curve.csv/.png, predictions.parquet
└── tests/                # synthetic fixtures, no network needed
```

Adding a matcher: subclass `dmb.matchers.base.Matcher`, implement
`match(query, k) -> [(rxcui, score)]` (scores in [0, 1], best first) and register it in
`dmb/matchers/__init__.py`.

## License

Code: MIT (see `LICENSE`). Data: the NDC Directory and RxNorm Prescribable Content are
public-domain works of the U.S. FDA and NLM; this repo does not redistribute them. RxNorm is
produced by the National Library of Medicine; this project is not endorsed by NLM or FDA.
