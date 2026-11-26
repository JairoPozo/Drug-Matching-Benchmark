"""Matcher interface: match(query) -> [(rxcui, score)], best first, score in [0, 1]."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, ClassVar

import polars as pl

if TYPE_CHECKING:
    from dmb.config import Paths

Candidates = list[tuple[str, float]]


class Matcher(ABC):
    name: ClassVar[str]
    # Set by the evaluator before fit(): where the allowed resources (RxNorm files) live.
    paths: Paths | None = None
    # Set by the evaluator before fit(): the split being evaluated (read only by matchers that use
    # cached external output, such as rxnav).
    split: str | None = None

    @property
    def params(self) -> dict:
        """Settings that change the matcher's behavior (part of its label in reports)."""
        return {}

    @property
    def label(self) -> str:
        return self.name + "".join(f"-{k}{v}" for k, v in sorted(self.params.items()))

    def fit(self, catalog: pl.DataFrame) -> None:
        """Receive the catalog (columns: rxcui, name). Held-out concepts are never passed."""
        self.catalog = catalog

    @abstractmethod
    def match(self, query: str, k: int = 5) -> Candidates:
        """Return up to k candidates sorted by score, descending."""

    def match_many(self, queries: Sequence[str], k: int = 5) -> list[Candidates]:
        return [self.match(q, k) for q in queries]
