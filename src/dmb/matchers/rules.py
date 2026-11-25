"""Rule-based baseline, built in stages so each step is measured on dev.

stage 1  Read the query: the ingredient list with strengths, then form and route. Map every
         ingredient (and every catalog ingredient) to its RxNorm base ingredient, using names,
         salts (PIN -> IN) and labeler substance names (SU). Only catalog concepts with exactly
         the same set of ingredients are candidates; if there is none, abstain. Candidates are
         ranked by plain text similarity.
stage 2  Compare strengths as numbers after normalizing units (10 mg/5mL = 2 MG/ML, 47 mg/g =
         0.047 MG/MG). Candidates whose strengths all match rank first.
stage 3  Dose form compatibility, learned from the train split (see dmb/forms.py): candidates whose
         RxNorm dose form never goes with the product's NDC form are dropped (a toothpaste never
         competes with a mouthwash); among the rest, the more usual dose form for that NDC form,
         route and container (syringe, cartridge, pen...) ranks first. No candidate left: abstain.

stage 4  Strengths declared in another basis: the factor between NDC and RxNorm values is
         learned per ingredient and unit pair from train (salt vs. moiety, mg vs. mEq, mg/mL vs.
         mg per actuation, mass vs. volume) and used only when train agrees on it. A strength
         that matches directly still ranks above one that matches through a conversion.

Next (plan): 12/24 HR and unit volume, and a calibrated score.

The score is in [0, 1].
Stage 2: 0.5 if every strength matches + 0.25 x share of matching strengths + 0.25 x similarity.
Stage 3: 0.5 if every strength matches + 0.1 x share of matching strengths + 0.3 x dose form
         likelihood (relative to the best candidate) + 0.1 x text similarity.
Stage 4: as stage 3, but a strength matched through a conversion counts 0.8 instead of 1 in
         the share term.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
from rapidfuzz import fuzz, utils

from dmb.config import Paths
from dmb.forms import FormModel
from dmb.matchers.base import Candidates, Matcher
from dmb.parse import parse_catalog_name, parse_query
from dmb.rxvocab import Vocab, load_vocab, name_variants, norm_name
from dmb.strength import Strength, converted_match, learn_factors

STAGES = (1, 2, 3, 4)
_CONVERTED = 0.8  # credit of a strength matched through a learned conversion
_MAX_SUFFIX_WORDS = 10


@dataclass
class _Entry:
    rxcui: str
    text: str  # processed name, for text similarity
    components: list[tuple[str, Strength | None]]  # (ingredient key, strength)
    dose_form: str


class RulesMatcher(Matcher):
    name = "rules"

    def __init__(self, stage: int | str = STAGES[-1]):
        self.stage = int(stage)
        if self.stage not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")

    @property
    def params(self) -> dict:
        return {"stage": self.stage}

    # ----- index -------------------------------------------------------------------------
    def fit(
        self,
        catalog: pl.DataFrame,
        vocab: Vocab | None = None,
        form_model: FormModel | None = None,
        factors: dict | None = None,
    ) -> None:
        super().fit(catalog)
        paths = self.paths or Paths.default()
        self.vocab = vocab or load_vocab(paths.rrf_dir)
        self.entries: list[_Entry] = []
        self.blocks: dict[frozenset[str], list[int]] = {}
        self.catalog_names: set[str] = set()
        for rxcui, name in catalog.select("rxcui", "name").iter_rows():
            parsed = parse_catalog_name(name, self.vocab.dose_forms)
            comps = []
            for ingredient, strength in parsed.components:
                comps.append((self._catalog_key(ingredient), strength))
                self.catalog_names.update(name_variants(ingredient))
            self.blocks.setdefault(frozenset(k for k, _ in comps), []).append(len(self.entries))
            self.entries.append(_Entry(rxcui, utils.default_process(name), comps, parsed.dose_form))
        # Learned pieces come last: they read train queries with the index built above.
        self.form_model = None
        self.factors: dict = {}
        if self.stage >= 3:
            self.form_model = form_model or self._learn_forms(paths)
        if self.stage >= 4:
            self.factors = factors if factors is not None else self._learn_factors(paths)

    def _learn_forms(self, paths: Paths) -> FormModel:
        """Dose form table from train products whose concept is in the catalog."""
        train = pl.read_parquet(paths.processed / "train.parquet").filter(pl.col("in_catalog"))
        pairs = (
            (text, parse_catalog_name(gold, self.vocab.dose_forms).dose_form)
            for text, gold in train.select("query_text", "gold_name").iter_rows()
        )
        return FormModel().fit(pairs)

    def _learn_factors(self, paths: Paths) -> dict:
        """Conversion factors from train products whose concept is in the catalog."""
        train = pl.read_parquet(paths.processed / "train.parquet").filter(pl.col("in_catalog"))
        observations: dict = {}
        for text, gold in train.select("query_text", "gold_name").iter_rows():
            parsed = parse_query(text)
            keys = [self._query_key(i.text) for i in parsed.ingredients]
            if not keys or None in keys:
                continue
            declared = dict(zip(keys, (i.strength for i in parsed.ingredients), strict=True))
            for ingredient, rxn in parse_catalog_name(gold, self.vocab.dose_forms).components:
                key = self._catalog_key(ingredient)
                ndc = declared.get(key)
                if rxn is None or ndc is None or ndc.value <= 0 or rxn.matches(ndc):
                    continue
                kinds = (ndc.num_kind, ndc.den_kind, rxn.num_kind, rxn.den_kind)
                observations.setdefault((key, *kinds), []).append(rxn.value / ndc.value)
        return learn_factors(observations)

    def _dose_credit(self, key: str, ndc: Strength | None, rxn: Strength | None) -> float:
        if ndc is None or rxn is None:
            return 0.0
        if rxn.matches(ndc):
            return 1.0
        if self.stage >= 4 and converted_match(key, ndc, rxn, self.factors):
            return _CONVERTED
        return 0.0

    def _catalog_key(self, ingredient: str) -> str:
        # Names can carry qualifiers before the ingredient ("Sprinkle 24 HR topiramate").
        return self._vocab_suffix(ingredient) or "name:" + name_variants(ingredient)[-1]

    def _vocab_suffix(self, text: str) -> str | None:
        """Base ingredient named by the longest word suffix of the text, if any."""
        words = norm_name(text).split()
        for n in range(min(len(words), _MAX_SUFFIX_WORDS), 0, -1):
            found = self.vocab.lookup(" ".join(words[-n:]))
            if found:
                return min(found)
        return None

    def _query_key(self, text: str) -> str | None:
        """Ingredient named at the end of the text (the brand comes before it)."""
        key = self._vocab_suffix(text)
        if key:
            return key
        words = norm_name(text).split()
        for n in range(min(len(words), _MAX_SUFFIX_WORDS), 0, -1):
            for v in name_variants(" ".join(words[-n:])):
                if v in self.catalog_names:
                    return "name:" + v
        return None

    # ----- matching ------------------------------------------------------------------------
    def match(self, query: str, k: int = 5) -> Candidates:
        parsed = parse_query(query)
        if not parsed.ingredients:
            return []
        keys = [self._query_key(i.text) for i in parsed.ingredients]
        if any(key is None for key in keys):
            return []
        block = self.blocks.get(frozenset(keys), [])
        if not block:
            return []
        strengths = dict(zip(keys, (i.strength for i in parsed.ingredients), strict=True))
        processed = utils.default_process(query)
        entries = [self.entries[i] for i in block]
        form_p: dict[str, float | None] = {}
        if self.form_model is not None:
            form_p = self.form_model.scores(query, {e.dose_form for e in entries if e.dose_form})
            entries = [e for e in entries if not e.dose_form or form_p.get(e.dose_form) is not None]
            if not entries:
                return []  # no compatible dose form: abstain
        best_form = max((p for p in form_p.values() if p is not None), default=1.0)
        scored = []
        for e in entries:
            sim = fuzz.token_set_ratio(processed, e.text) / 100.0
            if self.stage == 1:
                scored.append((e.rxcui, sim))
                continue
            credits = [self._dose_credit(key, strengths.get(key), s) for key, s in e.components]
            frac = sum(credits) / len(credits)
            full = all(c > 0 for c in credits)
            if self.stage == 2:
                score = 0.5 * full + 0.25 * frac + 0.25 * sim
            else:
                form = (form_p.get(e.dose_form) or 0.0) / best_form
                score = 0.5 * full + 0.1 * frac + 0.3 * form + 0.1 * sim
            scored.append((e.rxcui, score))
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored[:k]
