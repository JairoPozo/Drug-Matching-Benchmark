"""Read RxNorm RRF files.

RXNCONSO.RRF is pipe-delimited with a trailing pipe and no header. Column reference:
https://www.nlm.nih.gov/research/umls/rxnorm/docs/techdoc.html
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

RXNCONSO_COLUMNS = [
    "RXCUI",
    "LAT",
    "TS",
    "LUI",
    "STT",
    "SUI",
    "ISPREF",
    "RXAUI",
    "SAUI",
    "SCUI",
    "SDUI",
    "SAB",
    "TTY",
    "CODE",
    "STR",
    "SRL",
    "SUPPRESS",
    "CVF",
]


def read_rxnconso(path: Path) -> pl.DataFrame:
    schema = {c: pl.String for c in RXNCONSO_COLUMNS} | {"_trailing": pl.String}
    df = pl.read_csv(
        path,
        separator="|",
        has_header=False,
        quote_char=None,
        schema=schema,
        truncate_ragged_lines=True,
        encoding="utf8",
    )
    return df.drop("_trailing")


def scd_catalog(conso: pl.DataFrame) -> pl.DataFrame:
    """All active Semantic Clinical Drug concepts: ingredient + strength + dose form.

    Returns one row per RXCUI with columns (rxcui, name).
    """
    return (
        conso.filter(
            (pl.col("SAB") == "RXNORM") & (pl.col("TTY") == "SCD") & (pl.col("SUPPRESS") == "N")
        )
        .select(pl.col("RXCUI").alias("rxcui"), pl.col("STR").alias("name"))
        .unique(subset="rxcui", keep="first", maintain_order=True)
        .sort("rxcui")
    )


def tty_counts(conso: pl.DataFrame) -> dict[str, int]:
    """Number of distinct RXNORM concepts per term type (for profiling)."""
    counts = (
        conso.filter(pl.col("SAB") == "RXNORM")
        .group_by("TTY")
        .agg(pl.col("RXCUI").n_unique().alias("n"))
        .sort("n", descending=True)
    )
    return dict(zip(counts["TTY"].to_list(), counts["n"].to_list(), strict=True))
