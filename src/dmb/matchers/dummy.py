"""Dummy matcher: plain fuzzy string similarity against catalog names.

Only meant to exercise the pipeline end to end. If it scores suspiciously high, the answer
is probably leaking into the query text.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import polars as pl
from rapidfuzz import fuzz, process, utils

from dmb.matchers.base import Candidates, Matcher


class DummyMatcher(Matcher):
    name = "dummy"
    batch_size = 256

    def fit(self, catalog: pl.DataFrame) -> None:
        super().fit(catalog)
        self._ids = catalog["rxcui"].to_list()
        self._names = [utils.default_process(n) for n in catalog["name"].to_list()]

    def match(self, query: str, k: int = 5) -> Candidates:
        return self.match_many([query], k)[0]

    def match_many(self, queries: Sequence[str], k: int = 5) -> list[Candidates]:
        k = min(k, len(self._ids))
        out: list[Candidates] = []
        for start in range(0, len(queries), self.batch_size):
            batch = [utils.default_process(q) for q in queries[start : start + self.batch_size]]
            scores = process.cdist(batch, self._names, scorer=fuzz.token_set_ratio, workers=-1)
            top = np.argsort(-scores, axis=1, kind="stable")[:, :k]
            for row, idx in zip(scores, top, strict=True):
                out.append([(self._ids[j], float(row[j]) / 100.0) for j in idx])
        return out
