import polars as pl
import pytest

from dmb.matchers import get_matcher
from dmb.matchers.rules import RulesMatcher
from dmb.parse import parse_catalog_name, parse_query
from dmb.rxvocab import Vocab, name_variants
from dmb.strength import NDC_STRENGTH, parse_ndc_strength, parse_rxnorm_strength


def ndc(text):
    return parse_ndc_strength(NDC_STRENGTH.search(text))


@pytest.mark.parametrize(
    ("ndc_text", "rxnorm_text"),
    [
        ("10 mg/5mL", "2 MG/ML"),  # per 5 mL -> per 1 mL
        ("47 mg/g", "0.047 MG/MG"),  # mg/g and MG/MG
        ("50 mg/g", "50 MG/ML"),  # RxNorm treats g and mL alike
        ("325 mg/1", "325 MG"),  # per tablet
        ("100 [iU]/mL", "100 UNT/ML"),
        ("50 g/100mL", "500 MG/ML"),
        ("70 mL/100mL", "0.7 ML/ML"),
        ("24 mg/1.2mL", "20 MG/ML"),
        (".005 mg/mL", "0.005 MG/ML"),
        ("250 ug/mL", "0.25 MG/ML"),
        ("2.43 mg/g", "0.0024 MG/MG"),  # RxNorm rounding stays within tolerance
    ],
)
def test_equivalent_strengths(ndc_text, rxnorm_text):
    assert ndc(ndc_text).matches(parse_rxnorm_strength(rxnorm_text))


@pytest.mark.parametrize(
    ("ndc_text", "rxnorm_text"),
    [
        ("3 mg/1", "1 MG"),
        ("2 mg/mL", "2.5 MG/ML"),
        ("19.5 mg/1", "0.000729 MG/HR"),  # total amount vs release rate
        ("1.5 mg/g", "0.0024 MG/MG"),  # fluoride ion vs sodium fluoride: needs basis of strength
    ],
)
def test_different_strengths(ndc_text, rxnorm_text):
    assert not ndc(ndc_text).matches(parse_rxnorm_strength(rxnorm_text))


def test_package_text_is_not_a_strength():
    assert NDC_STRENGTH.search("1 BOTTLE in 1 CARTON / 118 mL in 1 BOTTLE Walgreen") is None


def test_parse_query_ingredients_form_and_route():
    q = (
        "Vivacaine BUPIVACAINE HYDROCHLORIDE ANHYDROUS 5 mg/mL, EPINEPHRINE BITARTRATE .005 mg/mL "
        "INJECTION, SOLUTION SUBCUTANEOUS 50 CARTRIDGE in 1 CARTON / 1.8 mL in 1 CARTRIDGE Sept"
    )
    p = parse_query(q)
    assert [i.text for i in p.ingredients] == [
        "Vivacaine BUPIVACAINE HYDROCHLORIDE ANHYDROUS",
        "EPINEPHRINE BITARTRATE",
    ]
    assert p.form == "INJECTION, SOLUTION" and p.route == "SUBCUTANEOUS"


def test_parse_query_names_with_commas_and_several_routes():
    q = (
        "Visine A.C. TETRAHYDROZOLINE HYDROCHLORIDE .5 mg/mL, ZINC SULFATE, UNSPECIFIED FORM "
        "2.5 mg/mL SOLUTION/ DROPS OPHTHALMIC 15 mL in 1 BOTTLE Kenvue"
    )
    p = parse_query(q)
    assert p.ingredients[1].text == "ZINC SULFATE, UNSPECIFIED FORM"
    assert (p.form, p.route) == ("SOLUTION/ DROPS", "OPHTHALMIC")
    q2 = "Lido LIDOCAINE HYDROCHLORIDE 20 mg/mL INJECTION, SOLUTION INFILTRATION, PERINEURAL 1 VIAL"
    assert parse_query(q2).route == "INFILTRATION, PERINEURAL"
    assert parse_query("RESPIRATORY X SALT 1 mg/1 TABLET ORAL 1 TABLET").route == "ORAL"


def test_kit_without_strength_has_no_ingredients():
    assert (
        parse_query("Cablivi KIT 1 KIT in 1 CARTON * 1 mL in 1 VIAL, GLASS Genzyme").ingredients
        == []
    )


FORMS = sorted(
    ["Extended Release Oral Tablet", "Oral Tablet", "Cartridge", "Extended Release Oral Capsule"],
    key=lambda s: (-len(s), s),
)


def test_parse_catalog_names():
    p = parse_catalog_name(
        "1.8 ML bupivacaine hydrochloride 5 MG/ML / epinephrine 0.005 MG/ML Cartridge", FORMS
    )
    assert p.quantity == "1.8 ML" and p.dose_form == "Cartridge"
    assert [c[0] for c in p.components] == ["bupivacaine hydrochloride", "epinephrine"]
    p = parse_catalog_name(
        "24 HR loratadine 10 MG / pseudoephedrine sulfate 240 MG Extended Release Oral Tablet",
        FORMS,
    )
    assert p.hours == 24 and p.dose_form == "Extended Release Oral Tablet"
    p = parse_catalog_name("Sprinkle 24 HR topiramate 150 MG Extended Release Oral Capsule", FORMS)
    assert p.hours == 24
    assert parse_catalog_name("sennosides, USP 25 MG Oral Tablet", FORMS).components[0][0] == (
        "sennosides, USP"
    )


def test_name_variants_drop_qualifiers():
    assert name_variants("CAMPHOR (NATURAL)") == ["camphor (natural)", "camphor"]
    assert name_variants("ZINC SULFATE, UNSPECIFIED FORM")[-1] == "zinc sulfate"
    assert name_variants("BUPIVACAINE HYDROCHLORIDE ANHYDROUS")[-1] == "bupivacaine hydrochloride"
    assert name_variants("sennosides, USP")[-1] == "sennosides"


def _matcher(stage=2):
    vocab = Vocab(
        name_to_in={
            "citalopram": frozenset({"IN1"}),
            "citalopram hydrobromide": frozenset({"IN1"}),  # salt -> base
            "ethanol": frozenset({"IN2"}),
            "alcohol": frozenset({"IN2"}),  # labeler substance name
            "benzyl alcohol": frozenset({"IN3"}),
        },
        dose_forms=["Topical Solution", "Oral Solution", "Oral Tablet", "Oral Gel"],
    )
    catalog = pl.DataFrame(
        {
            "rxcui": ["1", "2", "3", "4"],
            "name": [
                "citalopram 2 MG/ML Oral Solution",
                "citalopram 20 MG Oral Tablet",
                "ethanol 0.7 ML/ML Topical Solution",
                "benzyl alcohol 0.1 ML/ML Oral Gel",
            ],
        }
    )
    m = RulesMatcher(stage=stage)
    m.fit(catalog, vocab=vocab)
    return m


def test_rules_block_by_ingredient_and_compare_strengths():
    m = _matcher()
    c = m.match("Citalopram CITALOPRAM HYDROBROMIDE 10 mg/5mL SOLUTION ORAL 240 mL in 1 BOTTLE X")
    assert c[0][0] == "1" and {r for r, _ in c} == {"1", "2"}  # only citalopram concepts
    assert all(0.0 <= s <= 1.0 for _, s in c)
    sanitizer = m.match("Hand Sanitizer ALCOHOL 70 mL/100mL LIQUID TOPICAL 30 mL in 1 BOTTLE X")
    assert sanitizer[0][0] == "3"  # ALCOHOL is ethanol, not benzyl alcohol
    assert m.match("Mystery MYSTERYOL 5 mg/1 TABLET ORAL 10 TABLET in 1 BOTTLE X") == []
    assert m.match("Cablivi KIT 1 KIT in 1 CARTON Genzyme") == []


def test_rules_stages_and_labels():
    assert RulesMatcher(stage="1").label == "rules-stage1"
    assert get_matcher("rules").label == "rules-stage5"  # default: latest stage
    with pytest.raises(ValueError):
        RulesMatcher(stage=7)


def _form_model():
    from dmb.forms import FormModel

    rows = (
        [("A DRUGA 5 mg/1 TABLET ORAL 10 TABLET in 1 BOTTLE Lab", "Oral Tablet")] * 6
        + [("B NAF 1.5 mg/g PASTE, DENTIFRICE DENTAL 100 g in 1 TUBE Lab", "Toothpaste")] * 6
        + [("C NAF 1 mg/mL MOUTHWASH DENTAL 500 mL in 1 BOTTLE Lab", "Mouthwash")] * 6
        + [
            (
                "D Y 1 mg/mL INJECTION, SOLUTION SUBCUTANEOUS 1 mL in 1 SYRINGE Lab",
                "Prefilled Syringe",
            )
        ]
        * 6
        + [("E Y 1 mg/mL INJECTION, SOLUTION SUBCUTANEOUS 10 mL in 1 VIAL Lab", "Injection")] * 6
    )
    return FormModel().fit(rows)


def test_form_model_rules_out_and_ranks_dose_forms():
    fm = _form_model()
    paste = fm.scores(
        "Z NAF 1.1 mg/g PASTE, DENTIFRICE DENTAL 50 g in 1 TUBE Lab", ["Toothpaste", "Mouthwash"]
    )
    assert paste["Mouthwash"] is None and paste["Toothpaste"] > 0  # never seen together: ruled out
    syringe = fm.scores(
        "Z Y 2 mg/mL INJECTION, SOLUTION SUBCUTANEOUS 1 mL in 1 SYRINGE Lab",
        ["Injection", "Prefilled Syringe"],
    )
    assert syringe["Prefilled Syringe"] > syringe["Injection"]  # the container decides
    vial = fm.scores(
        "Z Y 2 mg/mL INJECTION, SOLUTION SUBCUTANEOUS 2 mL in 1 VIAL Lab",
        ["Injection", "Prefilled Syringe"],
    )
    assert vial["Injection"] > vial["Prefilled Syringe"]
    unseen = fm.scores("Z Q 1 mg/1 WAFER ORAL 1 WAFER in 1 BOX Lab", ["Oral Wafer", "Oral Tablet"])
    assert unseen == {"Oral Wafer": 1.0, "Oral Tablet": 1.0}  # no information: nothing ruled out


def test_container_priority():
    from dmb.forms import container

    assert container("1 AUTO-INJECTOR in 1 CARTON / 1 mL in 1 AUTO-INJECTOR") == "auto-injector"
    assert container("5 SYRINGE in 1 CARTON / 1 mL in 1 SYRINGE, GLASS") == "syringe"
    assert container("100 TABLET in 1 BOTTLE") == "other"


def test_rules_stage3_drops_incompatible_forms():
    vocab = Vocab(
        name_to_in={"sodium fluoride": frozenset({"IN9"})},
        dose_forms=["Toothpaste", "Mouthwash"],
    )
    catalog = pl.DataFrame(
        {
            "rxcui": ["10", "11"],
            "name": [
                "sodium fluoride 1 MG/ML Mouthwash",
                "sodium fluoride 0.0024 MG/MG Toothpaste",
            ],
        }
    )
    m = RulesMatcher(stage=3)
    m.fit(catalog, vocab=vocab, form_model=_form_model())
    c = m.match("Kids Paste SODIUM FLUORIDE 1.5 mg/g PASTE, DENTIFRICE DENTAL 119 g in 1 TUBE Lab")
    assert [r for r, _ in c] == ["11"]  # the mouthwash is not even a candidate
    m2 = RulesMatcher(stage=2)
    m2.fit(catalog, vocab=vocab)
    assert {
        r
        for r, _ in m2.match("Kids Paste SODIUM FLUORIDE 1.5 mg/g PASTE, DENTIFRICE DENTAL 1 TUBE")
    } == {
        "10",
        "11",
    }


def test_learn_factors_keeps_only_stable_ones():
    from dmb.strength import learn_factors

    kcl = ("IN_K", "mass", "each", "meq", "each")  # potassium chloride: 1500 mg = 20 mEq
    noisy = ("IN_F", "mass", "mlq", "mass", "mlq")
    factors = learn_factors(
        {
            kcl: [20 / 1500, 10 / 750, 8 / 600, 20 / 1500],
            noisy: [1.6, 2.2, 1.8, 2.5],  # train disagrees: no factor
            ("IN_X", "mass", "each", "meq", "each"): [0.5, 0.5],  # too few observations
        }
    )
    assert set(factors) == {kcl}
    assert abs(factors[kcl] - 20 / 1500) < 1e-9


def test_converted_match():
    from dmb.strength import Strength, converted_match

    factors = {("IN_K", "mass", "each", "meq", "each"): 20 / 1500}
    ndc = Strength(1500.0, "mass", "each")
    assert converted_match("IN_K", ndc, Strength(20.0, "meq", "each"), factors)
    assert not converted_match("IN_K", ndc, Strength(10.0, "meq", "each"), factors)
    assert not converted_match("IN_OTHER", ndc, Strength(20.0, "meq", "each"), factors)
    # per actuation: NDC declares sprays "per 1"
    spray = Strength(0.2055, "mass", "each")
    assert converted_match("IN_A", spray, Strength(0.206, "mass", "actuat"), {})


def test_rules_stage4_prefers_direct_over_converted():
    vocab = Vocab(
        name_to_in={"potassium chloride": frozenset({"IN_K"})},
        dose_forms=["Extended Release Oral Tablet"],
    )
    catalog = pl.DataFrame(
        {
            "rxcui": ["20", "21"],
            "name": [
                "potassium chloride 20 MEQ Extended Release Oral Tablet",
                "potassium chloride 10 MEQ Extended Release Oral Tablet",
            ],
        }
    )
    factors = {("IN_K", "mass", "each", "meq", "each"): 20 / 1500}
    q = "K-Tab POTASSIUM CHLORIDE 1500 mg/1 TABLET, EXTENDED RELEASE ORAL 100 TABLET in 1 BOTTLE"
    m3, m4 = RulesMatcher(stage=3), RulesMatcher(stage=4)
    m3.fit(catalog, vocab=vocab, form_model=_form_model())
    m4.fit(catalog, vocab=vocab, form_model=_form_model(), factors=factors)
    c3, c4 = m3.match(q), m4.match(q)
    assert c4[0][0] == "20" and c4[0][1] > c3[0][1]  # mg -> mEq conversion found the 20 mEq tablet
    assert c4[0][1] > c4[1][1]


def test_hidden_concept_simulates_not_in_catalog():
    m = _matcher(stage=2)
    q = "Citalopram CITALOPRAM HYDROBROMIDE 10 mg/5mL SOLUTION ORAL 240 mL in 1 BOTTLE X"
    assert "1" in [r for r, _ in m._candidate_features(q)]
    assert "1" not in [r for r, _ in m._candidate_features(q, hidden="1")]
    feats = dict(m._candidate_features(q))
    assert feats["1"]["is_top"] == 1.0 and feats["1"]["heuristic_gap"] > 0
    assert feats["2"]["is_top"] == 0.0 and feats["2"]["heuristic_gap"] < 0


def test_ablation_params_keep_base_labels():
    assert RulesMatcher(stage=5).label == "rules-stage5"
    assert RulesMatcher(stage=5, drop="sim,is_top").label == "rules-dropis_top+sim-stage5"
    assert RulesMatcher(stage=5, conversions=0).label == "rules-conversions0-stage5"
    assert RulesMatcher(stage=5, filter_forms="0").label == "rules-filter_forms0-stage5"
    with pytest.raises(ValueError):
        RulesMatcher(stage=5, drop="not_a_feature")


def test_filter_forms_off_keeps_incompatible_candidates():
    vocab = Vocab(
        name_to_in={"sodium fluoride": frozenset({"IN9"})}, dose_forms=["Toothpaste", "Mouthwash"]
    )
    catalog = pl.DataFrame(
        {
            "rxcui": ["10", "11"],
            "name": [
                "sodium fluoride 1 MG/ML Mouthwash",
                "sodium fluoride 0.0024 MG/MG Toothpaste",
            ],
        }
    )
    q = "Kids Paste SODIUM FLUORIDE 1.5 mg/g PASTE, DENTIFRICE DENTAL 119 g in 1 TUBE Lab"
    m = RulesMatcher(stage=3, filter_forms=0)
    m.fit(catalog, vocab=vocab, form_model=_form_model())
    feats = dict(m._candidate_features(q))
    assert set(feats) == {"10", "11"} and feats["10"]["form_rel"] == 0.0
