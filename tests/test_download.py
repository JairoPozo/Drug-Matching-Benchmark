import ssl
import zipfile

import pytest

from dmb.download import extract_rrf, latest_rxnorm_release, ndc_partitions, ssl_context

HTML = """
<a href="https://download.nlm.nih.gov/rxnorm/RxNorm_full_prescribe_10052026.zip">Oct</a>
<a href="https://download.nlm.nih.gov/rxnorm/RxNorm_full_prescribe_09082026.zip">Sep</a>
<a href="https://download.nlm.nih.gov/rxnorm/RxNorm_full_prescribe_12012025.zip">Dec 2025</a>
"""


def test_latest_rxnorm_release_compares_dates_not_strings():
    # "12012025" > "10052026" as strings, but October 2026 is newer
    assert latest_rxnorm_release(HTML) == "10052026"


def test_latest_rxnorm_release_without_links():
    with pytest.raises(RuntimeError):
        latest_rxnorm_release("<html></html>")


def test_ndc_partitions():
    index = {
        "results": {
            "drug": {
                "ndc": {
                    "export_date": "2026-11-05",
                    "total_records": 130000,
                    "partitions": [
                        {
                            "file": "https://download.open.fda.gov/drug/ndc/drug-ndc-0001-of-0001.json.zip"
                        }
                    ],
                }
            }
        }
    }
    entry = ndc_partitions(index)
    assert entry["partitions"][0]["file"].endswith(".json.zip")
    with pytest.raises(RuntimeError):
        ndc_partitions({"results": {"drug": {}}})


def test_extract_rrf_from_nested_folder(tmp_path):
    zp = tmp_path / "RxNorm_full_prescribe_10052026.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("rrf/RXNCONSO.RRF", "1|ENG|\n")
        zf.writestr("rrf/RXNREL.RRF", "")
        zf.writestr("rrf/RXNSTY.RRF", "")
        zf.writestr("Readme_full_prescribe.txt", "")
    out = tmp_path / "out"
    assert extract_rrf(zp, out) == ["RXNCONSO.RRF", "RXNREL.RRF"]
    assert (out / "RXNCONSO.RRF").read_text() == "1|ENG|\n"


def test_extract_rrf_requires_rxnconso(tmp_path):
    zp = tmp_path / "x.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("rrf/RXNREL.RRF", "")
    with pytest.raises(RuntimeError):
        extract_rrf(zp, tmp_path / "out")


def test_ssl_context_always_verifies(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    ctx = ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
