from conftest import LEAK_SENTINEL, ndc_record, write_raw

from dmb.config import Paths
from dmb.ndc import build_query_text, load_products
from dmb.rxnorm import read_rxnconso, scd_catalog


def test_query_text_uses_ndc_fields_only():
    rec = ndc_record(7, {"ing": "ibuprofen", "strength": 200}, ["123456", "654321"])
    rec["openfda"]["generic_name"] = [LEAK_SENTINEL]
    text = build_query_text(rec)
    assert "Brand7" in text
    assert "IBUPROFEN 200 mg/1" in text
    assert "TABLET" in text
    assert "100 TABLET in 1 BOTTLE" in text
    assert "Lab 0" in text
    assert LEAK_SENTINEL not in text
    assert "123456" not in text and "654321" not in text
    assert "-01)" not in text and "(" not in text  # package NDC code dropped (v0.2)


def test_strip_package_ndc_keeps_the_description():
    from dmb.ndc import strip_package_ndc

    desc = "1 BOTTLE in 1 CARTON (0363-7470-04) / 118 mL in 1 BOTTLE"
    assert strip_package_ndc(desc) == "1 BOTTLE in 1 CARTON / 118 mL in 1 BOTTLE"
    assert strip_package_ndc("30 TABLET in 1 BOTTLE (71335-1752-1)") == "30 TABLET in 1 BOTTLE"
    # Codes that are not a parenthesized package NDC stay (e.g. part of a company name)
    assert strip_package_ndc("9055-7588 Quebec Inc.") == "9055-7588 Quebec Inc."


def test_query_text_tolerates_missing_fields():
    assert build_query_text({"brand_name": "Solo"}) == "Solo"
    assert build_query_text({}) == ""


def test_multiple_ingredients_are_joined():
    rec = {
        "active_ingredients": [
            {"name": "AMLODIPINE", "strength": "5 mg/1"},
            {"name": "BENAZEPRIL", "strength": "10 mg/1"},
        ]
    }
    assert build_query_text(rec) == "AMLODIPINE 5 mg/1, BENAZEPRIL 10 mg/1"


def test_rxnconso_and_scd_catalog(tmp_path):
    write_raw(tmp_path)
    conso = read_rxnconso(Paths(tmp_path).rrf_dir / "RXNCONSO.RRF")
    assert conso.columns[:3] == ["RXCUI", "LAT", "TS"]
    cat = scd_catalog(conso)
    # 40 active RXNORM SCDs; suppressed and non-RXNORM rows are dropped
    assert cat.height == 40
    assert set(cat.columns) == {"rxcui", "name"}
    assert "8888" not in cat["rxcui"].to_list()
    assert "7777" not in cat["rxcui"].to_list()


def test_load_products_keeps_rxcuis_out_of_query(tmp_path):
    write_raw(tmp_path)
    df = load_products(sorted(Paths(tmp_path).ndc_dir.glob("*.json.zip")))
    assert df.height == 124
    assert not df["query_text"].str.contains(LEAK_SENTINEL).any()


def test_group_key_ignores_package_and_labeler():
    import copy

    from dmb.ndc import group_key

    a = ndc_record(1, {"ing": "ibuprofen", "strength": 200}, [])
    b = copy.deepcopy(a)
    b["labeler_name"] = "Another Repackager"
    b["packaging"] = [{"description": "30 TABLET in 1 BOTTLE"}]
    assert group_key(a) == group_key(b)
    c = copy.deepcopy(a)
    c["active_ingredients"][0]["strength"] = "400 mg/1"
    assert group_key(a) != group_key(c)
