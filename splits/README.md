# Splits

`dev.txt`, `test.txt` and `train.txt` list the `product_ndc` values of each split, one per line.
`meta.json` records how dev and test were sampled.

## How the split is made (method `grouped-stratified-v1`)

- **Groups.** Products are grouped by brand + ingredients with strength + dosage form, ignoring
  package and labeler (`dmb.ndc.group_key`). The same medicine sold by several repackagers, or in
  several package sizes, is one group. There are about 21,000 groups among 47,496 products.
- **Dev and test** take one product from each of 2,000 distinct groups, drawn with seed 42 and
  stratified by product type, so the prescription/OTC mix matches the data (about 47% OTC).
- **Train** is every product whose group is not used by dev or test. The other members of
  dev/test groups are left out of every split (about 7,400 products), so **no group crosses from
  one split to another**. A trained model therefore cannot memorize a test answer from train.
- In `train`, rows with `in_catalog = False` are NIL examples (their concept is held out of the
  catalog). Do not use their `gold_rxcui` as a training target, or the held-out concepts leak.
- What train still shares with dev/test is the generic medicine under another brand (for example
  "ibuprofen 200 mg tablet" from two store brands). That is legitimate: it is the task itself.

`build_stats.json` checks this on every build: `groups_shared_between_splits` must be 0 and
`near_duplicate_rate_vs_train` (identical description, labeler removed) must be 0%.

## Frozen dev/test rules

- `dmb build` reuses `dev.txt` and `test.txt` whenever they exist, whatever seed or size you pass,
  so the test set never changes silently. `train.txt` is derived and rewritten on every build.
- If the split method in `meta.json` differs from the code's, `dmb build` stops and asks for
  `dmb build --resample-splits` (`make build BUILD_ARGS=--resample-splits`).
- **Freezing** = committing `test.txt` to git (week 4 of the plan). After that,
  `--resample-splits` is refused.
- If a newer NDC export no longer contains some of these products, `dmb build` warns and skips
  them instead of re-sampling.
