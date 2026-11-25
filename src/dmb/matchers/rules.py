"""Rule-based baseline (weeks 5 and 6 of the plan).

Planned steps:
1. Normalize text and units (mg/MG, mL, tablet/tab, ...).
2. Extract attributes: active ingredient(s), strength, dose form, quantity.
3. Blocking: only compare against catalog concepts that share an ingredient.
4. Score attribute agreement and pick a threshold on dev (precision >= 95%).
"""

from __future__ import annotations

from dmb.matchers.base import Candidates, Matcher


class RulesMatcher(Matcher):
    name = "rules"

    def match(self, query: str, k: int = 5) -> Candidates:
        raise NotImplementedError("The rules baseline is scheduled for weeks 5-6 of the plan.")
