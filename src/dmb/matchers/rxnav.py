"""RxNav approximate matching (NLM) under the benchmark's rules (v0.2.2).

Reads responses downloaded beforehand by scripts/rxnav_fetch.py (see dmb.rxnav). Of each
response it keeps only atoms from RxNorm's own names (source RXNORM) of concepts in the benchmark
catalog, in RxNav's order:

- names from drug labels (source MTHSPL) are dropped, because the label of the product itself
  would match its query and give the answer away;
- held-out concepts and anything that is not an SCD are dropped, because they are not in the
  catalog the benchmark offers.

RxNav's score only ranks the results of one query ("higher is better, among a given set of
results"), so it needs a fixed scale to be thresholded across products:

- score="raw": its empirical distribution function over the top scores of a sample of training
  products, so 0.95 means "higher than 95% of them". No labels are used.
- score="cal": a logistic regression on that value, the gap to the second candidate and the
  number of candidates, fitted on the same training products with 10% of them shown without
  their concept, like the benchmark's own scorer.
"""

from __future__ import annotations

import bisect
import math
import random
from collections.abc import Sequence

import polars as pl

from dmb.matchers.base import Candidates, Matcher
from dmb.rxnav import TRAIN_SAMPLE, VARIANTS, load_responses

SCORES = ("raw", "cal")
SIMULATED_NIL = 0.10
CAL_SEED = 2027


class RxNavMatcher(Matcher):
    name = "rxnav"

    def __init__(self, input: str = "full", score: str = "raw") -> None:
        if input not in VARIANTS:
            raise ValueError(f"input must be one of {VARIANTS}")
        if score not in SCORES:
            raise ValueError(f"score must be one of {SCORES}")
        self.input = input
        self.score = score

    @property
    def params(self) -> dict:
        return {"input": self.input, "score": self.score}

    # -- RxNav output under the benchmark's rules ----------------------------------------------
    def _keep(self, raw: list) -> list[tuple[str, float]]:
        """(rxcui, RxNav score) of catalog concepts matched through RXNORM names, best first."""
        order = sorted(range(len(raw)), key=lambda i: (-float(raw[i][2]), int(raw[i][3]), i))
        out, seen = [], set()
        for i in order:
            rxcui, _rxaui, score, _rank, source, _name = raw[i]
            if source != "RXNORM" or rxcui not in self._catalog or rxcui in seen:
                continue
            seen.add(rxcui)
            out.append((rxcui, float(score)))
        return out

    def _scale(self, score: float) -> float:
        return bisect.bisect_right(self._reference, score) / len(self._reference)

    def _features(self, kept: list[tuple[str, float]]) -> list[float]:
        top = self._scale(kept[0][1])
        second = self._scale(kept[1][1]) if len(kept) > 1 else 0.0
        return [top, top - second, math.log1p(len(kept))]

    def _scored(self, kept: list[tuple[str, float]], k: int) -> Candidates:
        if not kept:
            return []
        scaled = [self._scale(s) for _, s in kept[:k]]
        if self.score == "raw":
            return [(r, v) for (r, _), v in zip(kept, scaled, strict=False)]
        p = float(self._model.predict_proba([self._features(kept)])[0, 1])
        # only the first candidate's score is used for decisions; the rest stay below it
        rest = [p] + [p * v / scaled[0] if scaled[0] > 0 else 0.0 for v in scaled[1:]]
        return [(r, v) for (r, _), v in zip(kept, rest, strict=False)]

    # -- matcher interface --------------------------------------------------------------------
    def fit(self, catalog: pl.DataFrame) -> None:
        super().fit(catalog)
        if self.paths is None or self.split is None:
            raise RuntimeError(
                "rxnav reads cached responses: the evaluator must set paths and split"
            )
        self._catalog = set(catalog["rxcui"].to_list())
        train = {
            n: self._keep(c)
            for n, c in load_responses(self.paths, TRAIN_SAMPLE, self.input).items()
        }
        self._reference = sorted(kept[0][1] for kept in train.values() if kept)
        if not self._reference:
            raise RuntimeError("No usable RxNav response in the training sample")
        summary = {"training_products": len(train), "with_candidates": len(self._reference)}
        if self.score == "cal":
            summary |= self._fit_calibration(train)
        self.training_summary = summary

        split = pl.read_parquet(self.paths.processed / f"{self.split}.parquet")
        responses = load_responses(self.paths, self.split, self.input)
        missing = [n for n in split["product_ndc"].to_list() if n not in responses]
        if missing:
            raise RuntimeError(
                f"{len(missing)} {self.split} products have no RxNav response; "
                f"run scripts/rxnav_fetch.py {self.split}"
            )
        self._by_text = {
            text: self._keep(responses[ndc])
            for ndc, text in split.select("product_ndc", "query_text").iter_rows()
        }

    def _fit_calibration(self, train: dict[str, list]) -> dict:
        from sklearn.linear_model import LogisticRegression

        gold = dict(
            pl.read_parquet(self.paths.processed / "train.parquet")
            .select("product_ndc", "expected_rxcui")
            .iter_rows()
        )
        rng = random.Random(CAL_SEED)
        x, y = [], []
        for ndc in sorted(train):
            kept = train[ndc]
            if rng.random() < SIMULATED_NIL:  # shown without its concept
                kept = [c for c in kept if c[0] != gold[ndc]]
            if kept:
                x.append(self._features(kept))
                y.append(int(kept[0][0] == gold[ndc]))
        self._model = LogisticRegression(max_iter=1000).fit(x, y)
        names = ("scaled_score", "gap_to_second", "log_candidates")
        coef = dict(zip(names, (round(float(c), 3) for c in self._model.coef_[0]), strict=True))
        return {"coefficients": coef | {"intercept": round(float(self._model.intercept_[0]), 3)}}

    def match(self, query: str, k: int = 5) -> Candidates:
        return self._scored(self._by_text.get(query, []), k)

    def match_many(self, queries: Sequence[str], k: int = 5) -> list[Candidates]:
        return [self.match(q, k) for q in queries]
