"""Figures 1 to 3 of the article, drawn from the committed results files.

Figure 1: decision flow, with the band shares of test2 (logistic regression, Wilson rule).
Figure 2: precision of the accepted products on new data, with 95% Wilson intervals, for each
method, threshold rule and test.
Figure 3: how often each threshold rule missed the 95% target in the 1,000 calibration
resamples of v0.2.1 (H7), against its mean coverage.

Run from the repository root:
    python scripts/figures.py              # Spanish and English versions
    python scripts/figures.py --lang en
Writes results/figures/figure{1,2,3}_{lang}.png (300 dpi) and .pdf.
"""

import argparse
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402
from matplotlib.transforms import blended_transform_factory  # noqa: E402

from dmb.metrics import wilson  # noqa: E402

RESULTS = Path("results")
OUT = RESULTS / "figures"
LANGS = ("es", "en")

INK = "#191919"
INK_2 = "#666666"
GRID = "#e6e6e6"
LINE = "#bdbdbd"
FILL = "#f6f6f6"
BLUE = "#257de0"
BLUE_FILL = "#e8f1fc"
ORANGE = "#f47230"
FONTS = ("Arial", "Liberation Sans", "Nimbus Sans", "DejaVu Sans")

GB = "rules-dropexpected_form_missing-featuresv2-scorergb-stage5"
SAPBERT_A = "sapbert-inputfull-scorecal"
SAPBERT_B = "sapbert-inputshort-scorecal"
RULES = ("point", "wilson", "ltt", "sgr")

TEXT = {
    "es": {
        "rules": {"point": "Puntual", "wilson": "Wilson", "ltt": "Learn then Test", "sgr": "SGR"},
        # Figure 1
        "input_title": "Descripción\ndel producto",
        "input_body": "NDC Directory (FDA)\n\nej.: Amoxicillin\n500 mg/1\nCAPSULE · ORAL",
        "cand_title": "Generación\nde candidatos",
        "cand_body": "1. Ingredientes\n2. Dosis\n3. Forma farmacéutica\n4. Conversión de unidades"
        "\n\nConceptos SCD del\ncatálogo (RxNorm)",
        "score_title": "Puntaje\ncalibrado",
        "score_body": "Probabilidad de que el\nmejor candidato sea\ncorrecto (regresión\n"
        "logística o gradient\nboosting)",
        "accept": ("Aceptar automáticamente", r"puntaje ≥ $t_{\mathrm{aceptar}}$"),
        "review": ("Revisar", "una persona elige entre\nlos 5 mejores candidatos"),
        "nil": ("No está en el catálogo", r"puntaje < $t_{\mathrm{abstener}}$"),
        "share": "{p} de test2",
        "footer": r"Umbrales fijados en dev: $t_{\mathrm{aceptar}}$ con una regla de umbral"
        " (puntual, Wilson, Learn then Test o SGR) y meta de 95 % de precisión;"
        "\n"
        r"$t_{\mathrm{abstener}}$ donde al menos 90 % de los productos de dev no tiene la"
        " respuesta entre sus 5 candidatos. Porcentajes: regresión logística con Wilson.",
        # Figure 2
        "groups": {
            "rules4": "Reglas, etapa 4 (sin modelo)",
            "lr": "Regresión logística",
            "gb": "Gradient boosting (v0.2.0)",
            "rxnav": "RxNav (coincidencia aproximada)",
            "sapbert_a": "SapBERT, consulta completa (A)",
            "sapbert_b": "SapBERT, consulta corta (B)",
        },
        "rxnav_none": "Wilson, LTT y SGR",
        "rxnav_none_note": "sin umbral en dev: no aceptó productos",
        "fig2_x": "Precisión de lo aceptado (IC de Wilson 95 %)",
        "target": "Meta: 95 %",
        "coverage": "Cobertura",
        "test": "test (v0.1.0)",
        "test2": "test2",
        # Figure 3
        "models": ("Regresión logística", "Gradient boosting (v0.2.0)"),
        "fig3_x": "Cobertura media en las 1.000 muestras",
        "fig3_y": "Muestras en que la precisión quedó\nbajo 95 % (escala logarítmica)",
        "delta": "δ = 5 %",
        "best": "Cobertura del mejor umbral de la población",
    },
    "en": {
        "rules": {"point": "Point", "wilson": "Wilson", "ltt": "Learn then Test", "sgr": "SGR"},
        "input_title": "Product\ndescription",
        "input_body": "FDA NDC Directory\n\ne.g., Amoxicillin\n500 mg/1\nCAPSULE · ORAL",
        "cand_title": "Candidate\ngeneration",
        "cand_body": "1. Ingredients\n2. Strength\n3. Dose form\n4. Unit conversion"
        "\n\nSCD concepts in the\ncatalog (RxNorm)",
        "score_title": "Calibrated\nscore",
        "score_body": "Probability that the\ntop candidate is\ncorrect (logistic\n"
        "regression or gradient\nboosting)",
        "accept": ("Accept automatically", r"score ≥ $t_{\mathrm{accept}}$"),
        "review": ("Review", "a person picks among\nthe top 5 candidates"),
        "nil": ("Not in the catalog", r"score < $t_{\mathrm{abstain}}$"),
        "share": "{p} of test2",
        "footer": r"Thresholds set on dev: $t_{\mathrm{accept}}$ by a threshold rule"
        " (point, Wilson, Learn then Test or SGR) with a 95% precision target;"
        "\n"
        r"$t_{\mathrm{abstain}}$ where at least 90% of dev products lack the answer among"
        " their top 5 candidates. Shares: logistic regression with Wilson.",
        "groups": {
            "rules4": "Rules, stage 4 (no model)",
            "lr": "Logistic regression",
            "gb": "Gradient boosting (v0.2.0)",
            "rxnav": "RxNav (approximate match)",
            "sapbert_a": "SapBERT, full query (A)",
            "sapbert_b": "SapBERT, short query (B)",
        },
        "rxnav_none": "Wilson, LTT and SGR",
        "rxnav_none_note": "no threshold on dev: accepted nothing",
        "fig2_x": "Precision of accepted products (95% Wilson CI)",
        "target": "Target: 95%",
        "coverage": "Coverage",
        "test": "test (v0.1.0)",
        "test2": "test2",
        "models": ("Logistic regression", "Gradient boosting (v0.2.0)"),
        "fig3_x": "Mean coverage across the 1,000 resamples",
        "fig3_y": "Resamples whose precision fell\nbelow 95% (log scale)",
        "delta": "δ = 5%",
        "best": "Coverage of the best population threshold",
    },
}


def pct(x: float, lang: str, digits: int = 1) -> str:
    # Half-up rounding of the decimal value, as in the results tables (0.2845 -> 28.5%).
    step = Decimal(1).scaleb(-digits)
    s = str((Decimal(str(x)) * 100).quantize(step, rounding=ROUND_HALF_UP))
    return s.replace(".", ",") + " %" if lang == "es" else s + "%"


def _load(path: str) -> dict:
    return json.loads((RESULTS / path).read_text(encoding="utf-8"))


def _setup() -> None:
    available = {f.name for f in font_manager.fontManager.ttflist}
    family = next(f for f in FONTS if f in available or f == "DejaVu Sans")
    plt.rcParams.update(
        {
            "font.family": family,
            "font.size": 8,
            "text.color": INK,
            "axes.edgecolor": INK_2,
            "axes.labelcolor": INK,
            "axes.linewidth": 0.8,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "xtick.labelcolor": INK,
            "ytick.labelcolor": INK,
            "mathtext.default": "regular",
            "pdf.fonttype": 42,
            "savefig.facecolor": "white",
        }
    )


def _save(fig, name: str, lang: str) -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [OUT / f"{name}_{lang}.{ext}" for ext in ("png", "pdf")]
    for p in paths:
        fig.savefig(p, dpi=300)
    plt.close(fig)
    return paths


# Figure 1 ----------------------------------------------------------------------------------


def _box(ax, x, y, w, h, title, body, *, edge=LINE, fill=FILL, lw=0.9):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0,rounding_size=1.2", ec=edge, fc=fill, lw=lw
        )
    )
    ax.text(
        x + w / 2,
        y + h - 1.8,
        title,
        ha="center",
        va="top",
        fontsize=8.5,
        fontweight="bold",
        linespacing=1.2,
    )
    body_top = y + h - 1.8 - 2.6 * (title.count("\n") + 1) - 1.8
    ax.text(x + w / 2, body_top, body, ha="center", va="top", fontsize=7.5, linespacing=1.35)


def _arrow(ax, start, end):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=9,
            color=INK_2,
            lw=0.9,
            shrinkA=0,
            shrinkB=0,
        )
    )


def figure1(lang: str) -> list[Path]:
    t = TEXT[lang]
    bands = _load("v0.2.0/test2/rules-stage5@wilson.json")["bands"]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 49.5)
    ax.axis("off")

    mid = 28.5  # vertical centre of the flow
    for x0, w0, h0, key in ((0.5, 19, 21, "input"), (24.5, 20, 27, "cand"), (49, 19, 24, "score")):
        _box(ax, x0, mid - h0 / 2, w0, h0, t[f"{key}_title"], t[f"{key}_body"])
    _arrow(ax, (19.5, mid), (24.5, mid))
    _arrow(ax, (44.5, mid), (49, mid))

    x, w, h, gap = 73.5, 26, 12.5, 1.5
    for key, y, edge, fill, lw in (
        ("accept", mid + h / 2 + gap, BLUE, BLUE_FILL, 1.3),
        ("review", mid - h / 2, LINE, FILL, 0.9),
        ("nil", mid - 1.5 * h - gap, LINE, FILL, 0.9),
    ):
        title, rule = t[key]
        share = bands["abstain" if key == "nil" else key]["share"]
        body = rule + "\n" + t["share"].format(p=pct(share, lang))
        ax.add_patch(
            FancyBboxPatch(
                (x, y), w, h, boxstyle="round,pad=0,rounding_size=1.2", ec=edge, fc=fill, lw=lw
            )
        )
        ax.text(
            x + w / 2, y + h - 1.8, title, ha="center", va="top", fontsize=8.5, fontweight="bold"
        )
        ax.text(x + w / 2, y + h - 4.8, body, ha="center", va="top", fontsize=7.5, linespacing=1.35)
        _arrow(ax, (68, mid), (x, y + h / 2))

    ax.text(0.5, 6.5, t["footer"], ha="left", va="top", fontsize=7, color=INK_2, linespacing=1.5)
    return _save(fig, "figure1", lang)


# Figure 2 ----------------------------------------------------------------------------------


def _metrics(path: str) -> tuple[float, float, float, float] | None:
    a = _load(path)["at_target_precision"]
    if a is None:
        return None
    lo, hi = wilson(a["counts"]["correct_accept"], a["n_accepted"])
    return a["accept_precision"], lo, hi, a["coverage"]


def _secondary(key: str) -> tuple[float, float, float, float]:
    r = _load("v0.2.0/test_secondary.json")["matchers"][key]
    lo, hi = r["accept_precision_ci95"]
    return r["accept_precision"], lo, hi, r["coverage"]


def _fig2_rows() -> list[tuple]:
    for rule in ("wilson", "ltt", "sgr"):  # the note row states this
        assert _metrics(f"v0.2.2/test2/rxnav-inputshort-scorecal@{rule}.json") is None
    rows = [
        ("h", "rules4"),
        (
            "r",
            "point",
            {
                "test": _secondary("rules-stage4"),
                "test2": _metrics("v0.2.0/test2/rules-stage4.json"),
            },
        ),
        ("h", "lr"),
        (
            "r",
            "point",
            {
                "test": _secondary("rules-stage5"),
                "test2": _metrics("v0.2.0/test2/rules-stage5.json"),
            },
        ),
        ("r", "wilson", {"test2": _metrics("v0.2.0/test2/rules-stage5@wilson.json")}),
        ("r", "ltt", {"test2": _metrics("v0.2.1/test2/rules-stage5@ltt.json")}),
        ("r", "sgr", {"test2": _metrics("v0.2.1/test2/rules-stage5@sgr.json")}),
        ("h", "gb"),
        (
            "r",
            "wilson",
            {
                "test": _secondary(f"{GB}@wilson"),
                "test2": _metrics(f"v0.2.0/test2/{GB}@wilson.json"),
            },
        ),
        ("r", "ltt", {"test2": _metrics(f"v0.2.1/test2/{GB}@ltt.json")}),
        ("r", "sgr", {"test2": _metrics(f"v0.2.1/test2/{GB}@sgr.json")}),
        ("h", "rxnav"),
        ("r", "point", {"test2": _metrics("v0.2.2/test2/rxnav-inputshort-scorecal.json")}),
        ("n", "rxnav_none"),
    ]
    for group, label in (("sapbert_a", SAPBERT_A), ("sapbert_b", SAPBERT_B)):
        rows.append(("h", group))
        for rule in ("wilson", "ltt"):
            rows.append(("r", rule, {"test2": _metrics(f"v0.2.3/test2/{label}@{rule}.json")}))
    return rows


def figure2(lang: str) -> list[Path]:
    t = TEXT[lang]
    rows = _fig2_rows()
    ys, y = [], 0.0
    for row in rows:
        y -= 0.9 if row[0] == "h" else 1.0
        ys.append(y)

    fig, ax = plt.subplots(figsize=(7.2, 0.26 * len(rows) + 1.2))
    fig.subplots_adjust(left=0.32, right=0.87, top=0.92, bottom=0.09)
    labels = blended_transform_factory(ax.transAxes, ax.transData)
    style = {"test": ("s", ORANGE), "test2": ("o", BLUE)}

    for row, y in zip(rows, ys, strict=True):
        kind, key = row[0], row[1]
        if kind == "h":
            ax.text(
                -0.555,
                y,
                t["groups"][key],
                transform=labels,
                ha="left",
                va="center",
                fontweight="bold",
            )
            if y != ys[0]:
                ax.axhline(y + 0.55, color=GRID, lw=0.8, zorder=0)
            continue
        if kind == "n":
            ax.text(-0.53, y, t["rxnav_none"], transform=labels, ha="left", va="center")
            ax.text(
                0.8725,
                y,
                t["rxnav_none_note"],
                ha="left",
                va="center",
                color=INK_2,
                fontstyle="italic",
                fontsize=7.5,
            )
            continue
        ax.text(-0.53, y, t["rules"][key], transform=labels, ha="left", va="center")
        values = row[2]
        both = len(values) == 2
        for test, (p, lo, hi, cov) in values.items():
            yy = y + ((0.2 if test == "test" else -0.2) if both else 0.0)
            marker, color = style[test]
            ax.errorbar(
                p,
                yy,
                xerr=[[p - lo], [hi - p]],
                fmt=marker,
                color=color,
                ms=5,
                mec="white",
                mew=0.6,
                elinewidth=1.3,
                capsize=0,
                zorder=3,
            )
            ax.text(
                1.04,
                yy,
                pct(cov, lang),
                transform=labels,
                ha="left",
                va="center",
                fontsize=7.5,
                color=INK_2,
            )

    ax.axvline(0.95, color=INK, lw=0.9, ls=(0, (4, 3)), zorder=1)
    top = blended_transform_factory(ax.transData, ax.transAxes)
    ax.text(0.95, 1.01, t["target"], transform=top, ha="center", va="bottom", fontsize=7.5)
    ax.text(
        1.04,
        1.01,
        t["coverage"],
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=7.5,
        fontweight="bold",
    )
    handles = [
        Line2D([], [], marker=m, color=c, ls="none", ms=5, mec="white", mew=0.6, label=t[k])
        for k, (m, c) in style.items()
    ]
    ax.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(-0.01, 1.0),
        ncol=2,
        frameon=False,
        handletextpad=0.3,
        columnspacing=1.2,
        borderaxespad=0.2,
    )

    ax.set_xlim(0.87, 0.99)
    ax.set_ylim(ys[-1] - 0.7, 0.1)
    ax.xaxis.set_major_locator(FixedLocator([0.88, 0.90, 0.92, 0.94, 0.96, 0.98]))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v, lang, 0)))
    ax.set_xlabel(t["fig2_x"])
    ax.set_yticks([])
    ax.grid(axis="x", color=GRID, lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    return _save(fig, "figure2", lang)


# Figure 3 ----------------------------------------------------------------------------------


def figure3(lang: str) -> list[Path]:
    t = TEXT[lang]
    res = _load("v0.2.1/resampling_dev_test2.json")
    reps = res["repetitions"]
    models = list(res["models"].values())
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    fig.subplots_adjust(left=0.13, right=0.97, top=0.9, bottom=0.12)

    style = ((BLUE, "o", "right"), (ORANGE, "s", "left"))
    for model, (color, marker, side) in zip(models, style, strict=True):
        best = model["population_best"]["coverage"]
        ax.axvline(best, color=color, lw=0.9, ls=(0, (1, 2)), zorder=1)
        for rule in RULES:
            r = model["rules"][rule]
            x, rate = r["coverage_mean"], r["violation_rate"]
            lo, hi = wilson(round(rate * reps), reps)
            ax.errorbar(
                x,
                rate,
                yerr=[[rate - lo], [hi - rate]],
                fmt=marker,
                color=color,
                ms=6,
                mec="white",
                mew=0.7,
                elinewidth=1.2,
                capsize=0,
                zorder=3,
            )
            dx = -7 if side == "right" else 7
            ax.annotate(
                t["rules"][rule],
                (x, rate),
                xytext=(dx, 0),
                textcoords="offset points",
                ha=side,
                va="center",
                fontsize=7.5,
            )

    ax.axhline(0.05, color=INK, lw=0.9, ls=(0, (4, 3)), zorder=1)
    ax.annotate(
        t["delta"],
        (1, 0.05),
        xycoords=("axes fraction", "data"),
        xytext=(-2, 3),
        textcoords="offset points",
        ha="right",
        va="bottom",
        fontsize=7.5,
    )
    handles = [
        Line2D([], [], marker=m, color=c, ls="none", ms=6, mec="white", mew=0.7, label=name)
        for (c, m, _), name in zip(style, t["models"], strict=True)
    ]
    handles.append(Line2D([], [], color=INK_2, lw=0.9, ls=(0, (1, 2)), label=t["best"]))
    ax.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0, 1.0),
        ncol=3,
        frameon=False,
        handletextpad=0.4,
        columnspacing=1.4,
        borderaxespad=0.2,
    )

    ax.set_yscale("log")
    ax.set_ylim(0.0004, 1)
    ticks = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1]
    ax.yaxis.set_major_locator(FixedLocator(ticks))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v, lang, 1 if v < 0.01 else 0)))
    ax.set_xlim(0.60, 0.76)
    ax.xaxis.set_major_locator(FixedLocator([0.60, 0.62, 0.64, 0.66, 0.68, 0.70, 0.72, 0.74, 0.76]))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v, lang, 0)))
    ax.set_xlabel(t["fig3_x"])
    ax.set_ylabel(t["fig3_y"])
    ax.grid(color=GRID, lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    return _save(fig, "figure3", lang)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lang", nargs="*", default=list(LANGS))
    args = parser.parse_args()
    unknown = sorted(set(args.lang) - set(LANGS))
    if unknown:
        parser.error(f"unknown language(s): {', '.join(unknown)}; choose from {', '.join(LANGS)}")
    _setup()
    for lang in args.lang:
        for draw in (figure1, figure2, figure3):
            for path in draw(lang):
                print(path)


if __name__ == "__main__":
    main()
