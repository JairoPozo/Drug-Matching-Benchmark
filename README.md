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

> Status: **v0.1.0.** Test evaluated once per matcher on 2026-11-25, from commit `2a8ae99`
> (tag `v0.1.0-pretest`), with thresholds and coefficients frozen on dev beforehand.
>
> **v0.2.0 in progress.** A second, independent test split (`test2`, 2,000 products drawn from the
> former train pool, no group shared with any other split) was frozen before any v0.2.0
> experiment; the plan, hypotheses and success criteria are pre-registered in
> `results/v0.2.0/plan.md`. Because `test2` left train, train now has 30,375 products: the
> v0.1.0 numbers below reproduce from tag `v0.1.0`.

## Results (test split, v0.1.0)

2,000 test products (182 not in the catalog), never used for any decision. Every number uses the
thresholds fixed on dev. **Coverage** = share of products accepted automatically; the accept
threshold is the one that gave ≥ 95% precision on dev.

| | Dummy (fuzzy text) | Rules, stage 4 | Rules, stage 5 (+ logistic regression) |
|---|---:|---:|---:|
| Top-1 accuracy (products in the catalog) | 54.8% | 85.5% | 85.5% |
| Right answer in top 5 | 78.3% | 92.7% | 92.5% |
| **Automatic coverage** | never reaches 95% precision | 50.8% | **67.0%** |
| Precision of automatic accepts (Wilson 95% CI) | — | 95.2% (93.7–96.3) | 94.9% (93.5–95.9) |
| False accepts (of which: product not in the catalog) | — | 49 (12) | 69 (20) |
| Products not in the catalog that were not accepted | — | 93.4% | 89.0% |
| Sent to review / right answer in their top 5 | — | 41.0% / 96.6% | 24.6% / 94.1% |
| Abstained: not in the catalog + in the catalog (system failure) | — | 57 + 107 | 58 + 108 |
| Calibration: ECE / Brier (top-1 per product) | 0.424 / 0.403 | 0.076 / 0.105 | **0.031 / 0.093** |

**Paired comparisons** (same 2,000 products; McNemar exact test on top-1 correctness, paired
bootstrap 95% intervals):

- Stage 4 vs. dummy: +30.6 points of top-1 accuracy (28.3–33.0), p < 10⁻¹⁰⁰.
- Stage 5 vs. stage 4: the same top-1 answers (p = 1.0; stage 5 only changes the score) and
  **+16.3 points of automatic coverage (14.1–18.4)**, at the same precision.

**Dev vs. test** (generalization): stage 5 top-1 accuracy 86.2% → 85.5%, coverage 68.3% →
67.0%, precision 95.2% → 94.9%, ECE 0.029 → 0.031. The test precision lands just under the 95%
target as a point estimate; the 95% interval (93.5–95.9) includes it.

**Trade-off.** Stage 5 accepts 325 more products automatically than stage 4, at about the same
precision, but lets 8 more products that are not in the catalog through (20 vs. 12): 89.0% of
them are still kept out of automatic matching, against 93.4% for stage 4. Pick stage 4 when a
false link to an absent product is the costliest error; stage 5 when review time is.

**Where it still fails** (stage 5, test): dental products (65.7% top-1, 41.7% of their automatic
accepts are wrong: fluoride toothpastes declare the fluoride ion while RxNorm uses the salt, and
train has no stable factor for it), kits that declare no ingredient (0%: only outside knowledge
of the brand can solve them), inhalation products (38.2%). Ophthalmic products reach 100% top-1
and oral products 95.4%.

Full numbers: `results/v0.1.0/` (frozen dev references, `freeze.json` with data hashes, test
metrics and `test_comparison.json`). The rule stages are described below.

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

## Benchmark definition (query format v0.3)

| | |
|---|---|
| Query unit | One NDC product (`product_ndc`), not each package |
| Query text (format v0.3) | `{brand_name} {ingredients + strength} {dosage_form} {route} {first package description} {labeler_name}`, built only from these NDC fields (`dmb.ndc.QUERY_FIELDS`). The package NDC code is removed from the description (a real catalog would not carry it). Never any `openfda.*` field (they come from RxNorm and would leak the answer) |
| Label | The RxCUI in `openfda.rxcui` whose RxNorm term type is `SCD` |
| Exclusions | Products with zero or more than one SCD (kits, multi-packs, ...), counted by reason in `data/processed/build_stats.json` |
| Catalog | All active `SCD` concepts with `SAB=RXNORM`; **10% are held out** so "not in catalog" (NIL) is a measurable answer |
| Splits | Grouped by brand + ingredients + dosage form, so package sizes and repackagers of one medicine never cross splits. 2,000 dev / 2,000 test products, one per group, seed 42, stratified by product type; frozen once `splits/test.txt` is committed. `train` = products of every other group (36,059). See `splits/README.md` |

### Metrics

- **Ranking** (answerable queries): accuracy@1, recall@5.
- **Accept/abstain decision** at threshold *t* (accept top-1 if score ≥ *t*):
  precision = correct accepts / accepts, recall = correct accepts / answerable queries, F1.
- **Decision counts**: every query is exactly one of *correct accept*, *wrong accept* (a wrong
  concept although the right one is in the catalog), *accept on NIL* (accepted something that is
  not in the catalog), *missed* (abstained although answerable) or *correct abstain*. Reported with
  the **false accept rate** (wrong accepts / accepts) and **coverage** (accepts / queries). A wrong
  accept is worse than an abstention: in a pharmacy catalog it links the wrong medicine.
- **Abstention** (NIL detection): precision and recall of abstaining on held-out concepts.
- **Precision-recall curve** over all thresholds; the reported operating point is the highest
  recall with precision ≥ 95% (automatic matching), plus the best-F1 point.
- **Calibration**: precision of the top-1 answer per score bin, the expected calibration error
  (ECE) and the Brier score. They say whether a score of 0.8 really means "right 80% of the time".
- **Decision bands**: accept (score ≥ the 95%-precision threshold), review (a person picks from
  the top 5) and abstain (score below the highest threshold under which ≥ 90% of the queries have
  no right answer in their top 5). Reported with each band's size and what it delivers.
- **Subgroups**, reported separately at the operating threshold: number of ingredients
  (0 = kits that declare no ingredient, 1, 2+), route (oral, topical, ophthalmic, nasal, dental,
  injectable, ...), in catalog vs. not in catalog (NIL), prescription vs. OTC.

## How the rules were built (dev split)

Numbers on the 2,000 dev queries (185 not in the catalog), used to build every stage.
Coverage is the share of queries accepted automatically at ≥ 95% precision.

| Matcher | accuracy@1 | recall@5 | coverage at 95% precision | ECE | Brier |
|---|---|---|---|---|---|
| `dummy`: fuzzy text similarity | 0.557 | 0.776 | — (never reaches 95%) | 0.422 | |
| `rules --param stage=1`: same ingredients only | 0.619 | 0.811 | — | 0.335 | |
| `rules --param stage=2`: + strengths compared as numbers | 0.764 | 0.900 | — | 0.186 | |
| `rules --param stage=3`: + dose form compatibility learned from train | 0.850 | 0.934 | 0.510 | 0.088 | |
| `rules --param stage=4`: + strength conversions learned from train | 0.861 | 0.935 | 0.510 | 0.087 | 0.115 |
| `rules --param stage=5`: same candidates, logistic regression score | **0.862** | **0.939** | **0.683** | **0.029** | **0.090** |

- Stages 1–4 come from a manual review of 40 dev cases. Each stage is a filter or a feature a
  pharmacist would check: same ingredients, same strength, compatible dose form, strength basis.
- Stage 5 keeps stage 4's candidates and only changes the score: a logistic regression trained
  on train turns the features into a probability. At the same 95% precision it accepts 68% of
  the queries instead of 51%, and its probabilities are calibrated (ECE 0.029: a score of 0.86
  is right about 86% of the time). It is **cross-fitted** (5 folds by group, so no train row sees
  its own label in its features), trained on all candidates with no resampling (the class
  imbalance is the real one), and hides the right concept in 10% of the rows so it learns what
  "not in the catalog" looks like. Text similarity gets almost no weight once the rules are in
  place; the margin over the runner-up and the dose form likelihood get the most. Training takes
  about two minutes.
- **Decision bands** (stage 5 on dev): accept 68.3% (precision 95.2%), send 24.8% to review
  (the right answer is in the top 5 for 95.1% of them), abstain on 6.9% (none of them has a
  right answer to pick). Both thresholds are fixed on dev and reused on test.

## Rules of the benchmark

- Data is never committed: `make data` downloads it and records versions + checksums.
- The test split is frozen. `dmb eval --split test` refuses to run without `--final`, and a
  second test run needs `--force-rerun` and is logged in `reports/test_runs.log`.
- **Matchers are developed and tuned on dev only.** On test, the decision thresholds are not
  picked again: `dmb eval` applies the ones fixed on the matcher's latest full dev run, and
  records which run in `metrics.json` (`thresholds_from`).
- **The query format is frozen before test is evaluated.** It is never changed after looking at
  test results.
- **Allowed resources for a matcher**: the query text and the catalog; the **train split**, only
  its rows whose concept is in the catalog (never dev or test labels); plus RxNorm's own names,
  synonyms and attributes (`RXNCONSO`, `RXNREL`, `RXNSAT`, e.g. ingredient synonyms or the basis
  of strength). **Not allowed**: NDC codes and other product-level attributes stored in RxNorm
  (`RXNSAT` NDC, LABELER, SPL_SET_ID, ...), MTHSPL product names (`DP`, `MTH_RXN_DP` in
  `RXNCONSO`), any `openfda.*` field, RxNorm data about clinical drugs that are not in the catalog
  the matcher receives (the held-out concepts stand for products missing from the catalog), and
  any external source that maps a product to its RxCUI (e.g. DailyMed or RxNav lookups). Each of
  them gives the answer away. Tools given to an LLM agent follow the same rule.
  `dmb/rxvocab.py` is the one place that reads RxNorm for the rules, and documents what it reads.
- Kits that declare no active ingredient stay in the benchmark and are reported as their own
  subgroup: text rules cannot solve them, so they show where outside knowledge helps.
- Exploration happens in notebooks (`make notebook`); official numbers come from `dmb eval`.
- To pin the RxNorm release, set `rxnorm_release` in `sources.json` (e.g. `"10052026"`).
  openFDA only serves the latest NDC export, so NDC is tracked by export date + sha256, and the
  frozen split IDs keep the test set stable.

## Repository layout

```
├── sources.json          # pinned source versions
├── splits/               # frozen dev/test IDs + derived train IDs (committed)
├── results/v0.1.0/       # freeze (dev thresholds, coefficients, data hashes) + test results
├── data/                 # raw downloads and processed parquet files (git-ignored)
├── reports/              # one folder per evaluation run (git-ignored)
├── src/dmb/
│   ├── download.py       # fetch NDC + RxNorm, record version and checksum
│   ├── build.py          # catalog, queries, labels, exclusions, grouped splits
│   ├── ndc.py / rxnorm.py
│   ├── rxvocab.py        # the only RxNorm reader for matchers: allowed vocabulary
│   ├── parse.py          # query text and catalog names -> ingredients, strengths, form, route
│   ├── strength.py       # strength normalization and learned conversion factors
│   ├── forms.py          # dose form compatibility table learned from train
│   ├── matchers/         # base interface, dummy, rules (stages 1-5)
│   ├── metrics.py        # ranking, decisions, calibration, bands
│   ├── evaluate.py       # metrics.json, pr_curve, calibration.csv, predictions.parquet
│   └── compare.py        # dmb freeze / dmb compare (paired tests)
└── tests/                # synthetic fixtures, no network needed
```

Reproduce the test results: `make data build`, then for each matcher
`dmb eval --matcher <name> [--param stage=N] --split dev` (fixes its thresholds), and
`dmb eval ... --split test --final` once. `dmb compare --split test --version v0.1.0 --matcher
dummy --matcher rules-stage4 --matcher rules-stage5` checks the data hashes and thresholds
against `results/v0.1.0/freeze.json`.

Adding a matcher: subclass `dmb.matchers.base.Matcher`, implement
`match(query, k) -> [(rxcui, score)]` (scores in [0, 1], best first) and register it in
`dmb/matchers/__init__.py`.

## License

Code: MIT (see `LICENSE`). Data: the NDC Directory and RxNorm Prescribable Content are
public-domain works of the U.S. FDA and NLM; this repo does not redistribute them. RxNorm is
produced by the National Library of Medicine; this project is not endorsed by NLM or FDA.
