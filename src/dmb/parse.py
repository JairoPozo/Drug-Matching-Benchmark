"""Turn a query text and a catalog name into structured attributes.

Query (format v0.3): {brand} {INGREDIENT strength, INGREDIENT strength...} {FORM} {ROUTE} {package}
{labeler}. The ingredient list is read as a chain: a strength, then ", " and the next ingredient,
and so on. The text before the first strength still holds the brand; the matcher finds where the
ingredient name starts (see RulesMatcher).

Catalog name (RxNorm SCD): [NN HR ][quantity UNIT ]ingredient strength[ / ingredient strength...]
Dose Form, e.g. "1.8 ML bupivacaine hydrochloride 5 MG/ML / epinephrine 0.005 MG/ML Cartridge".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dmb.strength import (
    NDC_STRENGTH,
    RXN_STRENGTH,
    Strength,
    parse_ndc_strength,
    parse_rxnorm_strength,
)

# FDA route of administration names as they appear in NDC listings.
ROUTES = [
    "AURICULAR (OTIC)", "BUCCAL", "CUTANEOUS", "DENTAL", "ENDOTRACHEAL", "EPIDURAL",
    "EXTRACORPOREAL", "INFILTRATION", "INTRA-ARTERIAL", "INTRA-ARTICULAR", "INTRACAVERNOUS",
    "INTRADERMAL", "INTRALESIONAL", "INTRAMUSCULAR", "INTRAOCULAR", "INTRAPERITONEAL",
    "INTRAPLEURAL", "INTRATHECAL", "INTRAUTERINE", "INTRAVENOUS", "INTRAVESICAL", "INTRAVITREAL",
    "IRRIGATION", "NASAL", "OPHTHALMIC", "ORAL", "OROPHARYNGEAL", "PERCUTANEOUS", "PERINEURAL",
    "PERIODONTAL", "RECTAL", "RESPIRATORY (INHALATION)", "SUBCUTANEOUS", "SUBLINGUAL",
    "SUBMUCOSAL", "TOPICAL", "TRANSDERMAL", "TRANSMUCOSAL", "URETERAL", "URETHRAL", "VAGINAL",
]  # fmt: skip
_ROUTE_RE = re.compile(
    r"(?<![A-Z])("
    + "|".join(re.escape(r) for r in sorted(ROUTES, key=len, reverse=True))
    + r")(?![A-Z])"
)
_MAX_NAME_CHARS = 120


@dataclass
class QueryIngredient:
    text: str  # text before the strength; for the first ingredient it starts with the brand
    strength: Strength | None
    raw_strength: str


@dataclass
class ParsedQuery:
    ingredients: list[QueryIngredient]
    form: str
    route: str
    package: str = ""  # text after form and route: package description and labeler


def _form_and_route(rest: str) -> tuple[str, str, str]:
    routes, end = [], None
    for m in _ROUTE_RE.finditer(rest):
        if end is None or not rest[end : m.start()].strip(" ,"):
            if end is None:
                form = rest[: m.start()].strip(" ,")
            routes.append(m.group(1))
            end = m.end()
        else:
            break
    if end is None:
        form = re.match(r"[^\d]*", rest).group(0).strip(" ,")
        end = len(form)
    return form, ", ".join(routes), rest[end:].strip(" ,")


def parse_query(text: str) -> ParsedQuery:
    m = NDC_STRENGTH.search(text)
    if not m:
        return ParsedQuery([], "", "", text)
    ingredients, name = [], text[: m.start()]
    while True:
        ingredients.append(QueryIngredient(name.strip(" ,"), parse_ndc_strength(m), m.group(0)))
        pos = m.end()
        if text.startswith(", ", pos):
            nxt = NDC_STRENGTH.search(text, pos + 2)
            if nxt and nxt.start() - (pos + 2) <= _MAX_NAME_CHARS:
                name, m = text[pos + 2 : nxt.start()], nxt
                continue
        break
    form, route, package = _form_and_route(text[pos:].strip())
    return ParsedQuery(ingredients, form, route, package)


@dataclass
class ParsedName:
    hours: int | None
    quantity: str | None  # e.g. "1.8 ML": volume of the unit (injectables)
    components: list[tuple[str, Strength | None]]
    dose_form: str


_PREFIX = re.compile(r"^(?:(?P<hr>\d+) HR )?(?:(?P<qty>\d*\.?\d+ [A-Z]+) )?(?P<body>.*)$")
_HOURS = re.compile(r"(?<![\w.])(\d+) HR ")


def parse_catalog_name(name: str, dose_forms: list[str]) -> ParsedName:
    m = _PREFIX.match(name)
    body, form = m.group("body"), ""
    for df in dose_forms:  # longest first
        if body.endswith(" " + df):
            form, body = df, body[: -len(df) - 1]
            break
    components = []
    for part in body.split(" / "):
        s = RXN_STRENGTH.search(part)
        ingredient = part[: s.start()].strip() if s else part.strip()
        components.append((ingredient, parse_rxnorm_strength(part)))
    # "NN HR" can also follow a qualifier, e.g. "Sprinkle 24 HR topiramate 150 MG ..."
    hr = m.group("hr") or (h.group(1) if (h := _HOURS.search(components[0][0])) else None)
    return ParsedName(int(hr) if hr else None, m.group("qty"), components, form)
