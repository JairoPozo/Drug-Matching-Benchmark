"""Download the two public sources into data/raw and record version + sha256.

- openFDA NDC Directory: bulk JSON listed at https://api.fda.gov/download.json
  under results.drug.ndc.
- RxNorm Current Prescribable Content: RxNorm_full_prescribe_MMDDYYYY.zip from the
  NLM RxNorm Files page (no UMLS license required).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import ssl
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from dmb.config import Paths, read_json, write_json

NDC_INDEX_URL = "https://api.fda.gov/download.json"
RXNORM_FILES_PAGE = "https://www.nlm.nih.gov/research/umls/rxnorm/docs/rxnormfiles.html"
RXNORM_URL_TEMPLATE = "https://download.nlm.nih.gov/rxnorm/RxNorm_full_prescribe_{release}.zip"
RXNORM_RRF_FILES = ("RXNCONSO.RRF", "RXNREL.RRF", "RXNSAT.RRF")
USER_AGENT = "drug-matching-benchmark/0.1 (research; python-urllib)"
_RELEASE_RE = re.compile(r"RxNorm_full_prescribe_(\d{8})\.zip")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ssl_context() -> ssl.SSLContext:
    """TLS context that verifies certificates against the operating system's trust store.

    Python's bundled OpenSSL does not see everything Windows trusts (roots that Windows
    fetches on demand, or the root an antivirus / corporate proxy installs for HTTPS
    inspection). `truststore` delegates verification to the OS, like a browser does.
    Set SSL_CERT_FILE to a PEM bundle to use that file instead.
    """
    cafile = os.environ.get("SSL_CERT_FILE")
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _open(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            raise RuntimeError(
                f"TLS certificate verification failed for {url}: {e.reason.verify_message}. "
                "Something on this network is presenting a certificate the OS does not trust "
                "(often an antivirus HTTPS scan or a corporate proxy). Open the URL in a "
                "browser to see who issued it, or point SSL_CERT_FILE at that CA's PEM file."
            ) from e
        raise


def fetch_text(url: str) -> str:
    with _open(url) as resp:
        return resp.read().decode("utf-8", errors="replace")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path, log=print) -> dict:
    """Stream url to dest (via a .part file) and return {sha256, bytes}."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    n = 0
    next_report = 0
    with _open(url, timeout=300) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            out.write(chunk)
            h.update(chunk)
            n += len(chunk)
            if n >= next_report:
                pct = f" ({100 * n / total:.0f}%)" if total else ""
                log(f"    {n / 1e6:7.1f} MB{pct}")
                next_report += 10_000_000
    tmp.replace(dest)
    return {"sha256": h.hexdigest(), "bytes": n}


def latest_rxnorm_release(html: str) -> str:
    """Pick the most recent MMDDYYYY release linked from the RxNorm Files page."""
    releases = set(_RELEASE_RE.findall(html))
    if not releases:
        raise RuntimeError("No RxNorm_full_prescribe_*.zip link found on the RxNorm Files page")
    return max(releases, key=lambda s: datetime.strptime(s, "%m%d%Y"))


def ndc_partitions(index: dict) -> dict:
    """Return the results.drug.ndc entry of openFDA's download.json."""
    try:
        entry = index["results"]["drug"]["ndc"]
    except KeyError as e:
        raise RuntimeError("download.json has no results.drug.ndc entry") from e
    if not entry.get("partitions"):
        raise RuntimeError("results.drug.ndc has no partitions")
    return entry


def _file_entry(url: str, path: Path, info: dict) -> dict:
    return {"url": url, "file": path.name, "sha256": info["sha256"], "bytes": info["bytes"]}


def download_ndc(paths: Paths, force: bool = False, log=print) -> dict:
    log(f"[ndc] reading {NDC_INDEX_URL}")
    entry = ndc_partitions(json.loads(fetch_text(NDC_INDEX_URL)))
    files = []
    for part in entry["partitions"]:
        url = part["file"]
        dest = paths.ndc_dir / url.rsplit("/", 1)[-1]
        if dest.exists() and not force:
            log(f"[ndc] {dest.name} already present, skipping (use --force to re-download)")
            info = {"sha256": sha256_file(dest), "bytes": dest.stat().st_size}
        else:
            log(f"[ndc] downloading {url}")
            info = download_file(url, dest, log=log)
        files.append(_file_entry(url, dest, info))
    return {
        "source": "openFDA NDC Directory",
        "index_url": NDC_INDEX_URL,
        "export_date": entry.get("export_date"),
        "total_records": entry.get("total_records"),
        "files": files,
        "downloaded_at": _now(),
    }


def extract_rrf(zip_path: Path, out_dir: Path, names=RXNORM_RRF_FILES) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = {n.upper() for n in names}
    extracted = []
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            base = member.rsplit("/", 1)[-1]
            if base.upper() in wanted:
                with zf.open(member) as src, (out_dir / base).open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(base)
    missing = wanted - {e.upper() for e in extracted}
    if "RXNCONSO.RRF" in missing:
        raise RuntimeError(f"RXNCONSO.RRF not found inside {zip_path.name}")
    return sorted(extracted)


def download_rxnorm(
    paths: Paths, release: str | None = None, force: bool = False, log=print
) -> dict:
    if release is None:
        log(f"[rxnorm] looking up latest release on {RXNORM_FILES_PAGE}")
        release = latest_rxnorm_release(fetch_text(RXNORM_FILES_PAGE))
    url = RXNORM_URL_TEMPLATE.format(release=release)
    dest = paths.rxnorm_dir / url.rsplit("/", 1)[-1]
    if dest.exists() and not force:
        log(f"[rxnorm] {dest.name} already present, skipping (use --force to re-download)")
        info = {"sha256": sha256_file(dest), "bytes": dest.stat().st_size}
    else:
        log(f"[rxnorm] downloading {url}")
        info = download_file(url, dest, log=log)
    extracted = extract_rrf(dest, paths.rrf_dir)
    log(f"[rxnorm] extracted {', '.join(extracted)} -> {paths.rrf_dir}")
    return {
        "source": "RxNorm Current Prescribable Content",
        "release": release,
        "release_date": datetime.strptime(release, "%m%d%Y").date().isoformat(),
        **_file_entry(url, dest, info),
        "extracted": extracted,
        "downloaded_at": _now(),
    }


def run(paths: Paths, rxnorm_release: str | None = None, force: bool = False, log=print) -> dict:
    if rxnorm_release is None:
        rxnorm_release = (read_json(paths.sources_file, {}) or {}).get("rxnorm_release")
    manifest = read_json(paths.manifest, {}) or {}
    previous = dict(manifest)
    manifest["ndc"] = download_ndc(paths, force=force, log=log)
    manifest["rxnorm"] = download_rxnorm(paths, release=rxnorm_release, force=force, log=log)
    write_json(paths.manifest, manifest)
    _warn_on_changes(previous, manifest, log)
    log(f"[done] manifest -> {paths.manifest}")
    log(f"       NDC export_date={manifest['ndc']['export_date']}")
    log(f"       RxNorm release={manifest['rxnorm']['release_date']}")
    return manifest


def _warn_on_changes(previous: dict, current: dict, log) -> None:
    old = {f["file"]: f["sha256"] for f in previous.get("ndc", {}).get("files", [])}
    if "rxnorm" in previous:
        old[previous["rxnorm"]["file"]] = previous["rxnorm"]["sha256"]
    new = {f["file"]: f["sha256"] for f in current["ndc"]["files"]}
    new[current["rxnorm"]["file"]] = current["rxnorm"]["sha256"]
    for name, digest in new.items():
        if name in old and old[name] != digest:
            log(f"[warn] {name} changed since the last download (sha256 differs)")
