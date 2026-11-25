"""Matcher interface: match(query) -> [(rxcui, score)], best first, score in [0, 1]."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

import polars as pl

Candidates = list[tuple[str, float]]


class Matcher(ABC):
    name: ClassVar[str]

    def fit(self, catalog: pl.DataFrame) -> None:
        """Receive the catalog (columns: rxcui, name). Held-out concepts are never passed."""
        self.catalog = catalog

    @abstractmethod
    def match(self, query: str, k: int = 5) -> Candidates:
        """Return up to k candidates sorted by score, descending."""

    def match_many(self, queries: Sequence[str], k: int = 5) -> list[Candidates]:
        return [self.match(q, k) for q in queries]
