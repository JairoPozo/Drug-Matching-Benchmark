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
