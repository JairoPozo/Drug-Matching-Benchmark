"""Which RxNorm dose forms fit an NDC product: a table learned from the train split.

An NDC listing declares a dosage form ("TABLET, FILM COATED", "SOLUTION/ DROPS", "INJECTION,
SOLUTION"), a route ("OPHTHALMIC") and a package ("1 mL in 1 SYRINGE"). RxNorm uses its own dose
forms ("Oral Tablet", "Ophthalmic Solution", "Prefilled Syringe"). Instead of writing the ~200 x 120
correspondences by hand, the table is counted on train products whose concept is in the catalog:
for each context, how often each RxNorm dose form was the right one.

Contexts go from specific to general: (form, route, container), (form, route), (form). The most
specific context seen at least MIN_COUNT times gives the probabilities. A dose form never seen
with the product's form (at the two general levels) is incompatible: a toothpaste never competes
with a mouthwash. If the NDC form was never seen in train, nothing is ruled out.

Only train rows with in_catalog = True are used: held-out concepts stay unseen (benchmark rules).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from dmb.parse import parse_query

MIN_COUNT = 5

# Containers that decide between RxNorm forms such as Injection / Prefilled Syringe / Cartridge.
# Order = priority when several appear in the package text.
_CONTAINERS = [
    ("AUTO-INJECTOR", "auto-injector"),
    ("INJECTOR", "pen"),
    ("PEN", "pen"),
    ("CARTRIDGE", "cartridge"),
    ("SYRINGE", "syringe"),
    ("AMPULE", "vial"),
    ("VIAL", "vial"),
    ("INHALER", "inhaler"),
    ("CANISTER", "canister"),
    ("APPLICATOR", "applicator"),
    ("BAG", "bag"),
    ("PATCH", "patch"),
]
_CONTAINER_RE = [(re.compile(rf"(?<![A-Z]){re.escape(w)}(?![A-Z])"), k) for w, k in _CONTAINERS]


def container(package: str) -> str:
    up = package.upper()
    for pattern, key in _CONTAINER_RE:
        if pattern.search(up):
            return key
    return "other"


def contexts(query_text: str) -> tuple[tuple, tuple, tuple]:
    p = parse_query(query_text)
    form = " ".join(p.form.upper().split())
    return (form, p.route, container(p.package)), (form, p.route), (form,)


class FormModel:
    def __init__(self) -> None:
        self.counts: dict[tuple, Counter] = {}

    def fit(self, pairs: Iterable[tuple[str, str]]) -> FormModel:
        """pairs: (query text, RxNorm dose form of the right answer)."""
        for text, dose_form in pairs:
            if not dose_form:
                continue
            for ctx in contexts(text):
                self.counts.setdefault(ctx, Counter())[dose_form] += 1
        return self

    def _table(self, query_text: str) -> tuple[Counter | None, set]:
        """Counts of the most specific context seen MIN_COUNT times, and the forms seen with the
        two general contexts. (None, empty) if the NDC form was never seen in train."""
        specific, middle, general = contexts(query_text)
        known = self.counts.get(general)
        if not known:
            return None, set()
        seen = set(known) | set(self.counts.get(middle, {}))
        table = next(
            (self.counts[c] for c in (specific, middle, general)
             if sum(self.counts.get(c, Counter()).values()) >= MIN_COUNT),
            known,
        )  # fmt: skip
        return table, seen

    def expected(self, query_text: str) -> str | None:
        """The most usual RxNorm dose form for this product's form, route and container."""
        table, _ = self._table(query_text)
        return table.most_common(1)[0][0] if table else None

    def relative_to_expected(self, query_text: str, dose_form: str) -> float:
        """Likelihood of a dose form relative to the most usual one over ALL dose forms (1 = it is
        the expected form). Unlike scores(), it does not depend on which forms the catalog has."""
        table, _ = self._table(query_text)
        if not table:
            return 1.0
        return (table.get(dose_form, 0) + 1) / (max(table.values()) + 1)

    def scores(self, query_text: str, dose_forms: Iterable[str]) -> dict[str, float | None]:
        """Probability of each dose form for this query; None = incompatible.

        Probabilities come from the most specific context seen MIN_COUNT times (add-one
        smoothing); incompatibility is judged on the two general contexts.
        """
        dose_forms = list(dose_forms)
        table, seen = self._table(query_text)
        if table is None:
            return dict.fromkeys(dose_forms, 1.0)  # unseen NDC form: no information
        n = sum(table.values())
        out: dict[str, float | None] = {}
        for df in dose_forms:
            out[df] = None if df not in seen else (table.get(df, 0) + 1) / (n + len(dose_forms))
        return out
