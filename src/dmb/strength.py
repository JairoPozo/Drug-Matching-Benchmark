"""Read and compare drug strengths, from NDC text ("10 mg/5mL") and RxNorm names ("2 MG/ML").

Every strength is turned into one canonical value with two kinds:
- numerator kind: mass (mg), volume (mL), unit (UNT, [iU], [USP'U]), meq or cfu
- denominator kind: "each" (per tablet, capsule...), "mlq" (per mL; g and mL are treated as equal,
  as RxNorm itself does: 50 mg/g is filed as 50 MG/ML) or a raw unit such as "hr" or "actuat"

So "10 mg/5mL" and "2 MG/ML" are both (2.0, mass, mlq), and "47 mg/g" and "0.047 MG/MG" are both
(47.0, mass, mlq). Two strengths match when kinds agree and values differ by at most 3% (RxNorm
rounds, e.g. 0.00243 vs 0.0024).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REL_TOL = 0.03

_MASS = {"mg": 1.0, "g": 1000.0, "ug": 0.001, "mcg": 0.001, "kg": 1e6}
_VOL = {"ml": 1.0, "l": 1000.0}
_UNIT = {"u", "unt", "iu", "[iu]", "[usp'u]", "[arb'u]"}
_DEN_MLQ = {"ml": 1.0, "l": 1000.0, "g": 1.0, "mg": 0.001, "kg": 1000.0}

# NDC strength: number, unit, "/", optional number, optional unit, with no spaces around "/".
# The numerator unit is restricted to strength units so package text ("CARTON / 118 mL")
# never matches.
NDC_STRENGTH = re.compile(
    r"(?<![\w.])(?P<num>\d*\.?\d+)\s*"
    r"(?P<unit>mg|g|ug|mcg|kg|mL|L|meq|mEq|U|\[iU\]|\[USP'U\]|\[CFU\]|\[arb'U\])"
    r"/(?P<den>\d*\.?\d+)?(?P<dunit>\[[^\]\s]+\]|[A-Za-z]+)?(?=[\s,;]|$)"
)

# RxNorm strength inside a normalized name: "2 MG/ML", "500 MG", "0.000729 MG/HR".
RXN_STRENGTH = re.compile(
    r"(?P<num>\d*\.?\d+) (?P<unit>[A-Z]+|\[[^\]]+\])(?:/(?P<dunit>[A-Z0-9]+))?$"
)


@dataclass(frozen=True)
class Strength:
    value: float
    num_kind: str
    den_kind: str

    def matches(self, other: Strength | None) -> bool:
        if other is None:
            return False
        if (self.num_kind, self.den_kind) != (other.num_kind, other.den_kind):
            return False
        a, b = self.value, other.value
        return abs(a - b) <= REL_TOL * max(abs(a), abs(b), 1e-12)


def _numerator(unit: str) -> tuple[str, float] | None:
    u = unit.lower()
    if u in _MASS:
        return "mass", _MASS[u]
    if u in _VOL:
        return "vol", _VOL[u]
    if u in _UNIT:
        return "unit", 1.0
    if u == "meq":
        return "meq", 1.0
    if u == "[cfu]":
        return "cfu", 1.0
    return None


def canonical(num: float, unit: str, den: float | None, dunit: str | None) -> Strength | None:
    n = _numerator(unit)
    if n is None:
        return None
    kind, factor = n
    den = den if den else 1.0
    if not dunit:
        return Strength(num * factor / den, kind, "each")
    d = dunit.lower()
    if d in _DEN_MLQ:
        return Strength(num * factor / (den * _DEN_MLQ[d]), kind, "mlq")
    return Strength(num * factor / den, kind, d)


def parse_ndc_strength(m: re.Match) -> Strength | None:
    den = m.group("den")
    return canonical(
        float(m.group("num")), m.group("unit"), float(den) if den else None, m.group("dunit")
    )


def parse_rxnorm_strength(text: str) -> Strength | None:
    m = RXN_STRENGTH.search(text)
    if not m:
        return None
    return canonical(float(m.group("num")), m.group("unit"), None, m.group("dunit"))


# ---- conversion factors (stage 4) ------------------------------------------------------------
# A product can declare a strength in a different basis than RxNorm: a salt vs. its moiety
# (copper vs. cupric chloride), mg vs. mEq (potassium chloride), mg/mL vs. mg per actuation
# (nasal sprays), mass vs. volume (density). For a given ingredient the factor between the two is
# fixed chemistry, so it can be learned from train pairs and used only when it is stable.

ConversionKey = tuple[
    str, str, str, str, str
]  # (ingredient, NDC num, NDC den, RxNorm num, RxNorm den)
MIN_OBSERVATIONS = 3
MIN_AGREEMENT = 0.7  # share of observations within REL_TOL of the median factor


def learn_factors(observations: dict[ConversionKey, list[float]]) -> dict[ConversionKey, float]:
    """Median factor RxNorm value / NDC value per key, kept only when the observations agree."""
    out = {}
    for key, ratios in observations.items():
        if len(ratios) < MIN_OBSERVATIONS:
            continue
        ratios = sorted(ratios)
        median = ratios[len(ratios) // 2]
        agree = sum(abs(r / median - 1) <= REL_TOL for r in ratios) / len(ratios)
        if agree >= MIN_AGREEMENT:
            out[key] = median
    return out


def converted_match(
    ingredient: str, ndc: Strength, rxn: Strength, factors: dict[ConversionKey, float]
) -> bool:
    """True when the NDC strength equals the RxNorm one after a known conversion."""
    if ndc.num_kind == rxn.num_kind and {ndc.den_kind, rxn.den_kind} == {"each", "actuat"}:
        # Sprays and inhalers: NDC declares the amount "per 1" actuation.
        return Strength(ndc.value, rxn.num_kind, rxn.den_kind).matches(rxn)
    f = factors.get((ingredient, ndc.num_kind, ndc.den_kind, rxn.num_kind, rxn.den_kind))
    return f is not None and Strength(ndc.value * f, rxn.num_kind, rxn.den_kind).matches(rxn)
