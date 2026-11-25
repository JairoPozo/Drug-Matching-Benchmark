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
stage 5  Same candidates and filters as stage 4, but the score is the probability that the
         candidate is right, from a logistic regression trained on train (see _fit_model):
         - cross-fitted: the train rows are split in N_FOLDS folds by group (package sizes and
           repackagers of one medicine stay together); the features of each fold are computed
           with form and conversion tables learned on the other folds, so no row sees its own
           label in its features;
         - no resampling or class weights (they would distort the probabilities);
         - in SIMULATED_NIL of the rows the right concept is hidden, so the model also learns
           what "not in the catalog" looks like, without touching the held-out concepts.

Heuristic score, in [0, 1] (stages 1-4; also a feature of stage 5):
stage 1: text similarity.
stage 2: 0.5 if every strength matches + 0.25 x share of matching strengths + 0.25 x similarity.
stage 3-4: 0.5 if every strength matches + 0.1 x share of matching strengths (a converted match
         counts 0.8) + 0.3 x dose form likelihood relative to the best candidate + 0.1 x similarity.
"""

from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass

import numpy as np
import polars as pl
from rapidfuzz import fuzz, utils

from dmb.config import SEED, Paths
from dmb.forms import FormModel
from dmb.matchers.base import Candidates, Matcher
from dmb.parse import parse_catalog_name, parse_query
from dmb.rxvocab import Vocab, load_vocab, name_variants, norm_name
from dmb.strength import Strength, converted_match, learn_factors

STAGES = (1, 2, 3, 4, 5)
_CONVERTED = 0.8  # credit of a strength matched through a learned conversion
_MAX_SUFFIX_WORDS = 10
N_FOLDS = 5
SIMULATED_NIL = 0.10
FEATURES = (
    "full",  # every strength matches (directly or converted)
    "frac",  # share of matching strengths (converted = 0.8)
    "converted",  # at least one strength matched only through a conversion
    "form_rel",  # dose form likelihood relative to the best candidate
    "form_logp",  # log of the dose form likelihood
    "form_unseen",  # the NDC form was never seen in train (no form information)
    "sim",  # text similarity
    "log_candidates",  # how many candidates passed the filters
    "n_ingredients",
    "heuristic",  # stage 3-4 score
    "heuristic_gap",  # distance to the best other candidate (negative if not the best)
    "is_top",  # best candidate by the heuristic
)


@dataclass
class _Entry:
    rxcui: str
    text: str  # processed name, for text similarity
    components: list[tuple[str, Strength | None]]  # (ingredient key, strength)
    dose_form: str


def _fold(group: str) -> int:
    return zlib.crc32(group.encode("utf-8")) % N_FOLDS


class RulesMatcher(Matcher):
    name = "rules"

    def __init__(self, stage: int | str = STAGES[-1]):
        self.stage = int(stage)
        if self.stage not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")

    @property
    def params(self) -> dict:
        return {"stage": self.stage}

    # ----- index ---------------------------------------------------------------------------
    def fit(
        self,
        catalog: pl.DataFrame,
        vocab: Vocab | None = None,
        form_model: FormModel | None = None,
        factors: dict | None = None,
        train: pl.DataFrame | None = None,
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
        self.form_model: FormModel | None = None
        self.factors: dict = {}
        self.model = None
        self.training_summary: dict = {}
        needs_train = (
            (self.stage >= 3 and form_model is None)
            or (self.stage >= 4 and factors is None)
            or self.stage >= 5
        )
        if needs_train and train is None:
            train = self._train_rows(paths)
        if self.stage >= 3:
            self.form_model = form_model or self._learn_forms(train)
        if self.stage >= 4:
            self.factors = factors if factors is not None else self._learn_factors(train)
        if self.stage >= 5:
            self.model = self._fit_model(train)

    @staticmethod
    def _train_rows(paths: Paths) -> pl.DataFrame:
        """Train products whose concept is in the catalog (benchmark rules)."""
        train = pl.read_parquet(paths.processed / "train.parquet").filter(pl.col("in_catalog"))
        if "group_key" not in train.columns:
            train = train.with_columns(pl.col("product_ndc").alias("group_key"))
        return train.select("query_text", "gold_rxcui", "gold_name", "group_key")

    def _learn_forms(self, train: pl.DataFrame) -> FormModel:
        pairs = (
            (text, parse_catalog_name(gold, self.vocab.dose_forms).dose_form)
            for text, gold in train.select("query_text", "gold_name").iter_rows()
        )
        return FormModel().fit(pairs)

    def _learn_factors(self, train: pl.DataFrame) -> dict:
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

    def _fit_model(self, train: pl.DataFrame):
        """Cross-fitted logistic regression on candidate features (see module docstring)."""
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        rows = train.select("query_text", "gold_rxcui", "group_key").rows()
        folds = [_fold(g) for _, _, g in rows]
        rng = random.Random(SEED)
        hide = [rng.random() < SIMULATED_NIL for _ in rows]
        full_forms, full_factors = self.form_model, self.factors
        X, y = [], []
        try:
            for k in range(N_FOLDS):
                others = train.filter(pl.Series([f != k for f in folds]))
                self.form_model = self._learn_forms(others)
                self.factors = self._learn_factors(others)
                for (text, gold, _), f, hidden in zip(rows, folds, hide, strict=True):
                    if f != k:
                        continue
                    for rxcui, feats in self._candidate_features(
                        text, hidden=gold if hidden else None
                    ):
                        X.append([feats[n] for n in FEATURES])
                        y.append(int(rxcui == gold))
        finally:
            self.form_model, self.factors = full_forms, full_factors
        self.training_summary = {
            "queries": len(rows),
            "candidate_rows": len(y),
            "positives": int(sum(y)),
            "folds": N_FOLDS,
            "simulated_nil_share": SIMULATED_NIL,
        }
        if not y or min(y) == max(y):
            return None  # nothing to learn: fall back to the heuristic score
        X = np.asarray(X, dtype=float)
        scaler = StandardScaler().fit(X)
        model = LogisticRegression(max_iter=2000).fit(scaler.transform(X), np.asarray(y))
        self.training_summary["coefficients"] = dict(
            zip(FEATURES, (round(float(c), 3) for c in model.coef_[0]), strict=True)
        )
        return scaler, model

    # ----- ingredient keys -------------------------------------------------------------------
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

    def _dose_credit(self, key: str, ndc: Strength | None, rxn: Strength | None) -> float:
        if ndc is None or rxn is None:
            return 0.0
        if rxn.matches(ndc):
            return 1.0
        if self.stage >= 4 and converted_match(key, ndc, rxn, self.factors):
            return _CONVERTED
        return 0.0

    # ----- matching --------------------------------------------------------------------------
    def _candidate_features(self, query: str, hidden: str | None = None) -> list[tuple[str, dict]]:
        """Candidates that pass the filters, with their features. hidden: a concept to leave out
        (used in training to simulate a product that is not in the catalog)."""
        parsed = parse_query(query)
        if not parsed.ingredients:
            return []
        keys = [self._query_key(i.text) for i in parsed.ingredients]
        if any(key is None for key in keys):
            return []
        entries = [
            self.entries[i] for i in self.blocks.get(frozenset(keys), [])
            if self.entries[i].rxcui != hidden
        ]  # fmt: skip
        if not entries:
            return []
        strengths = dict(zip(keys, (i.strength for i in parsed.ingredients), strict=True))
        form_p: dict[str, float | None] = {}
        if self.form_model is not None:
            form_p = self.form_model.scores(query, {e.dose_form for e in entries if e.dose_form})
            entries = [e for e in entries if not e.dose_form or form_p.get(e.dose_form) is not None]
            if not entries:
                return []  # no compatible dose form: abstain
        known = [p for p in form_p.values() if p is not None]
        best_form = max(known, default=1.0)
        form_unseen = float(not form_p or all(p == 1.0 for p in known))
        processed = utils.default_process(query)
        out = []
        for e in entries:
            sim = fuzz.token_set_ratio(processed, e.text) / 100.0
            credits = [self._dose_credit(key, strengths.get(key), s) for key, s in e.components]
            frac = sum(credits) / len(credits)
            full = float(all(c > 0 for c in credits))
            p_form = form_p.get(e.dose_form) if self.form_model is not None else None
            form_rel = (p_form or 0.0) / best_form if self.form_model is not None else 1.0
            if self.stage == 1:
                heuristic = sim
            elif self.stage == 2:
                heuristic = 0.5 * full + 0.25 * frac + 0.25 * sim
            else:
                heuristic = 0.5 * full + 0.1 * frac + 0.3 * form_rel + 0.1 * sim
            out.append(
                (
                    e.rxcui,
                    {
                        "full": full,
                        "frac": frac,
                        "converted": float(any(0 < c < 1 for c in credits)),
                        "form_rel": form_rel,
                        "form_logp": math.log(p_form) if p_form else math.log(1e-6),
                        "form_unseen": form_unseen,
                        "sim": sim,
                        "log_candidates": math.log1p(len(entries)),
                        "n_ingredients": float(len(keys)),
                        "heuristic": heuristic,
                    },
                )
            )
        h = [f["heuristic"] for _, f in out]
        top = max(range(len(h)), key=lambda i: (h[i], -i))
        second = max((v for i, v in enumerate(h) if i != top), default=0.0)
        for i, (_, f) in enumerate(out):
            f["is_top"] = float(i == top)
            f["heuristic_gap"] = h[i] - (second if i == top else h[top])
        return out

    def match(self, query: str, k: int = 5) -> Candidates:
        feats = self._candidate_features(query)
        if not feats:
            return []
        if self.stage >= 5 and self.model is not None:
            scaler, model = self.model
            X = np.asarray([[f[n] for n in FEATURES] for _, f in feats], dtype=float)
            probs = model.predict_proba(scaler.transform(X))[:, 1]
            scored = [(r, float(p)) for (r, _), p in zip(feats, probs, strict=True)]
        else:
            scored = [(r, f["heuristic"]) for r, f in feats]
        scored.sort(key=lambda t: (-t[1], t[0]))
        return scored[:k]
