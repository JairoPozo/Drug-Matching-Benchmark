"""Ingredient vocabulary from RxNorm, restricted to what a matcher is allowed to use.

Allowed (concept-level knowledge about substances and dose forms):
- RXNORM ingredient names (IN), precise ingredients (PIN, e.g. a salt) and their synonyms
  (SY, TMSY), mapped to the base ingredient through the PIN "form_of" IN relation.
- MTHSPL substance names (SU), the names labelers use for active ingredients (e.g. ALCOHOL for
  ethanol, DEXTROSE MONOHYDRATE for glucose).
- RXNORM dose form names (DF).

Never read here, because each one gives the answer away: MTHSPL product names (DP, MTH_RXN_DP),
product-level attributes in RXNSAT (NDC, LABELER, SPL_SET_ID, ...), and anything about clinical
drug concepts (SCD) that are not in the catalog the matcher receives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from dmb.rxnorm import read_rxnconso

_NAME_TTYS = ("IN", "PIN", "SY", "TMSY", "SU")
_RXNREL_COLUMNS = [
    "RXCUI1", "RXAUI1", "STYPE1", "REL", "RXCUI2", "RXAUI2", "STYPE2", "RELA",
    "RUI", "SRUI", "SAB", "SL", "DIR", "RG", "SUPPRESS", "CVF",
]  # fmt: skip

# Qualifiers that do not change which substance is meant.
_DROP = [
    re.compile(r"\s*\([^)]*\)"),
    re.compile(r",\s*unspecified form$"),
    re.compile(r",\s*usp$"),
    re.compile(r"\s+anhydrous$"),
]


def norm_name(text: str) -> str:
    return " ".join(text.lower().replace(" ", " ").split()).strip(" ,;")


def name_variants(text: str) -> list[str]:
    """The normalized name, then the name without qualifiers such as '(NATURAL)' or ', USP'."""
    out = [norm_name(text)]
    stripped = out[0]
    for pat in _DROP:
        stripped = pat.sub("", stripped).strip(" ,")
    if stripped and stripped not in out:
        out.append(stripped)
    return out


@dataclass
class Vocab:
    name_to_in: dict[str, frozenset[str]]
    dose_forms: list[
        str
    ]  # longest first, so "Extended Release Oral Tablet" wins over "Oral Tablet"

    def lookup(self, text: str) -> frozenset[str] | None:
        for v in name_variants(text):
            if v in self.name_to_in:
                return self.name_to_in[v]
        return None


def _pin_to_in(rrf_dir: Path) -> dict[str, set[str]]:
    path = rrf_dir / "RXNREL.RRF"
    if not path.exists():
        return {}
    rel = (
        pl.scan_csv(
            path,
            separator="|",
            has_header=False,
            quote_char=None,
            new_columns=[*_RXNREL_COLUMNS, "_trailing"],
            schema_overrides={c: pl.String for c in [*_RXNREL_COLUMNS, "_trailing"]},
        )
        .filter(
            (pl.col("SAB") == "RXNORM")
            & (pl.col("STYPE1") == "CUI")
            & (pl.col("RELA") == "form_of")
        )
        .select("RXCUI1", "RXCUI2")  # RXCUI2 (PIN) form_of RXCUI1 (IN)
        .collect()
    )
    out: dict[str, set[str]] = {}
    for ing, pin in rel.iter_rows():
        out.setdefault(pin, set()).add(ing)
    return out


def load_vocab(rrf_dir: Path) -> Vocab:
    conso = read_rxnconso(rrf_dir / "RXNCONSO.RRF").filter(pl.col("SUPPRESS") == "N")
    rx = conso.filter(pl.col("SAB") == "RXNORM")
    ins = set(rx.filter(pl.col("TTY") == "IN")["RXCUI"].to_list())
    pins = set(rx.filter(pl.col("TTY") == "PIN")["RXCUI"].to_list())
    pin_to_in = _pin_to_in(rrf_dir)

    def base(rxcui: str) -> set[str]:
        if rxcui in ins:
            return {rxcui}
        if rxcui in pins:
            return pin_to_in.get(rxcui, set())
        return set()

    names = conso.filter(
        ((pl.col("SAB") == "RXNORM") & pl.col("TTY").is_in(["IN", "PIN", "SY", "TMSY"]))
        | ((pl.col("SAB") == "MTHSPL") & (pl.col("TTY") == "SU"))
    )
    acc: dict[str, set[str]] = {}
    for rxcui, text in names.select("RXCUI", "STR").iter_rows():
        b = base(rxcui)
        if b:
            acc.setdefault(norm_name(text), set()).update(b)
    forms = rx.filter(pl.col("TTY") == "DF")["STR"].unique().to_list()
    return Vocab(
        name_to_in={k: frozenset(v) for k, v in acc.items()},
        dose_forms=sorted(forms, key=lambda s: (-len(s), s)),
    )
