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
> **v0.2.0: evaluated on `test2`** (2,000 products, 175 not in the catalog), a second independent
> split frozen before any v0.2.0 experiment, once per matcher, from tag `v0.2.0-pretest`. The plan
> and hypotheses were pre-registered in `results/v0.2.0/plan.md`; all of them are reported in
> `results/v0.2.0/resultados.md` (Spanish), met or not:
>
> | test2 | Stage 5, Wilson threshold | v0.2.0 (gradient boosting + v2 features, Wilson) |
> |---|---:|---:|
> | Automatic coverage | 64.6% | **72.6%** (+7.95 pts, paired 95% CI 6.5–9.5) |
> | Precision of accepts (Wilson 95% CI) | 96.2% (95.0–97.1) | 95.0% (93.8–96.0) |
> | Not-in-catalog products accepted (of 175) | 19 | 28 (worse, McNemar p = 0.049) |
>
> - Choosing the accept threshold on dev with the Wilson lower bound kept precision at or above
>   95% on new data; the plain observed-precision threshold missed it on both test splits (94.9%
>   and 94.6%).
> - The v0.2.0 scorer adds coverage, but the extra accepts are riskier (incremental precision
>   85.5%), and it accepts more products that are not in the catalog, mostly sibling dose forms.
> - Secondary, descriptive only: on the v0.1.0 test, which is not independent of the v0.2.0 design,
>   the v0.2.0 reaches 71.6% coverage at 96.7% precision (95.7–97.5), against 67.0% at 94.9% for
>   the v0.1.0 stage 5. The same model gives 95.0% on `test2`: sample-to-sample variation is why
>   intervals are reported.
> - Because `test2` left train, train now has 30,375 products: the v0.1.0 numbers below reproduce
>   from tag `v0.1.0`.
>
> **v0.2.1: threshold rules with a formal guarantee.** Two rules with a finite-sample guarantee,
> Learn then Test (`ltt`) and selection with guaranteed risk (`sgr`), both at δ = 0.05, against the
> Wilson rule. Pre-registered in `results/v0.2.1/plan.md`, evaluated once from tag
> `v0.2.1-pretest`, all hypotheses in `results/v0.2.1/resultados.md` (Spanish). In 1,000
> calibration samples of 2,000 drawn from the 4,000 dev and test2 products:
>
> | Threshold rule | Misses the 95% target (LR / GB) | Mean coverage (LR / GB) |
> |---|---:|---:|
> | Observed precision (v0.1.0) | 50.3% / 48.7% | 67.8% / 74.0% |
> | Wilson lower bound (v0.2.0) | 1.5% / 1.5% | 64.3% / 70.2% |
> | Learn then Test, δ = 0.05 | 2.9% / 3.9% | 64.8% / 70.8% |
> | Selection with guaranteed risk, δ = 0.05 | 0.4% / 0.2% | 62.4% / 68.4% |
>
> - The Wilson rule has no formal guarantee but misses the target about as often as Learn then
>   Test at δ = 0.025. Learn then Test gives the guarantee with half a point more coverage.
> - On test2, with the thresholds fixed on dev, the guaranteed rules meet 95% in 3 of 4 cases.
>   Gradient boosting with `ltt` gets 94.85%: it accepts 5 more products than Wilson, 3 of them
>   wrong, as the plan anticipated. The guarantee is about the population, not each sample.
>
> **v0.2.2: comparison with RxNav**, NLM's public approximate matching for drug names, under the
> same rules: only RxNorm's own names (label names would give the answer away) and only catalog
> concepts. Pre-registered in `results/v0.2.2/plan.md`, evaluated once from tag `v0.2.2-pretest`,
> results in `results/v0.2.2/resultados.md` (Spanish). On test2, RxNav's first candidate is right
> for 71.0% of the products in the catalog, against 84.1% for the logistic regression (paired
> difference −13.1 pts, 95% CI −15.1 to −11.1), and no risk-controlled rule finds a threshold at 95%
> precision: even its most confident 5% of products are 93.0% precise.
>
> **v0.2.3: comparison with SapBERT**, a state-of-the-art biomedical entity linker, indexing the
> RxNorm names of the catalog concepts. Pre-registered in `results/v0.2.3/plan.md`, evaluated once
> from tag `v0.2.3-pretest`, results in `results/v0.2.3/resultados.md` (Spanish). On test2, SapBERT
> with short queries ranks better than the rules generator (top-1 87.9% vs 84.1%, paired difference
> +3.8 pts, 95% CI 2.4 to 5.3) and accepts fewer products that are not in the catalog (5 vs 19 of
> 175), but under the same 95% Wilson rule it covers 40.5% of products against 64.6%. With Wilson
> and Learn then Test, all four SapBERT configurations kept precision above 95%.

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
├── results/v0.2.0/       # pre-registration, dev experiments, freeze, test2 results and analysis
├── results/v0.2.1/       # threshold rules with a formal guarantee: plan, freeze, test2, resampling
├── results/v0.2.2/       # RxNav baseline: plan, dev runs, freeze, test2 results
├── results/v0.2.3/       # SapBERT baseline: plan, dev runs, freeze, test2 results
├── results/figures/      # article figures 1-3 (PNG and PDF, Spanish and English)
├── scripts/              # one-off analyses (test2_analysis.py, test_secondary.py,
│                         #   pharmacist_review.py, threshold_resampling.py,
│                         #   precision_at_coverage.py), the RxNav download
│                         #   (rxnav_queries.py, rxnav_fetch.py), the SapBERT candidates
│                         #   (sapbert_names.py, sapbert_embed.py) and the article figures
│                         #   (figures.py)
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
│   ├── matchers/         # base interface, dummy, rules (stages 1-5), rxnav and sapbert (cached candidates)
│   ├── metrics.py        # ranking, decisions, calibration, bands, threshold rules
│   ├── evaluate.py       # metrics.json, pr_curve, calibration.csv, predictions.parquet
│   ├── rxnav.py          # RxNav queries and cached responses (v0.2.2)
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
