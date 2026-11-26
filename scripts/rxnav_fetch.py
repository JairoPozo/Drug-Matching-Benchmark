"""Download RxNav approximate matches for the benchmark queries (v0.2.2).

Standalone on purpose: it needs only Python 3.9 or newer and internet access, so it can run on any
machine that reaches rxnav.nlm.nih.gov. It reads data/rxnav/queries_<name>.jsonl (written by
scripts/rxnav_queries.py) and appends one line per product and query form to
data/rxnav/responses_<name>.jsonl. Running it again resumes where it stopped and retries failures.

NLM asks for at most 20 requests per second per IP address; this script sends about 10.

Run from the repository root:
    python scripts/rxnav_fetch.py                  # train_sample, dev and test2
    python scripts/rxnav_fetch.py dev              # one of them
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

API = "https://rxnav.nlm.nih.gov/REST/Prescribe/approximateTerm.json"
VERSION_URLS = (
    "https://rxnav.nlm.nih.gov/REST/version.json",
    "https://rxnav.nlm.nih.gov/REST/Prescribe/version.json",
)
MAX_ENTRIES = 100
OPTION = 1
VARIANTS = ("full", "short")
NAMES = ("train_sample", "dev", "test2")
RATE = 10.0
WORKERS = 4
FOLDER = Path("data") / "rxnav"
USER_AGENT = "drug-matching-benchmark/0.2 (research; github.com/JairoPozo/Drug-Matching-Benchmark)"


class RateLimiter:
    def __init__(self, per_second: float) -> None:
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next = time.monotonic()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            self.next = max(self.next, now)
            delay = self.next - now
            self.next += self.interval
        if delay > 0:
            time.sleep(delay)


def get_json(url: str, limiter: RateLimiter, tries: int = 6):
    for attempt in range(tries):
        limiter.wait()
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:  # too many requests, or a server problem
                time.sleep(min(60, (5 if exc.code == 429 else 1) * 2**attempt))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(min(60, 2**attempt))
    raise RuntimeError(f"gave up after {tries} tries")


def approximate(term: str, limiter: RateLimiter, tries: int = 6) -> list:
    if not term.strip():
        return []
    query = urllib.parse.urlencode({"term": term, "maxEntries": MAX_ENTRIES, "option": OPTION})
    group = (get_json(f"{API}?{query}", limiter, tries) or {}).get("approximateGroup") or {}
    return [
        [
            c.get("rxcui"),
            c.get("rxaui"),
            float(c.get("score") or 0),
            int(c.get("rank") or 0),
            c.get("source"),
            c.get("name"),
        ]
        for c in group.get("candidate") or []
    ]


def versions(limiter: RateLimiter) -> dict:
    out = {}
    for url in VERSION_URLS:
        try:
            out[url] = get_json(url, limiter, tries=2)
        except Exception as exc:  # recorded, not fatal
            out[url] = f"error: {exc}"
    return out


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(name: str, limiter: RateLimiter) -> None:
    queries_path = FOLDER / f"queries_{name}.jsonl"
    out_path = FOLDER / f"responses_{name}.jsonl"
    meta_path = FOLDER / f"meta_{name}.json"
    queries = [
        json.loads(line)
        for line in queries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line) if line.strip() else {}
            if row.get("status") == "ok":
                done.add((row["product_ndc"], row["variant"]))
    todo = [
        (q["product_ndc"], v, q[v])
        for q in queries
        for v in VARIANTS
        if (q["product_ndc"], v) not in done
    ]
    minutes = len(todo) / RATE / 60
    print(f"[{name}] {len(queries)} products, {len(todo)} requests to send (~{minutes:.0f} min)")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta.setdefault("runs", []).append(
        {
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 (Python 3.9)
            "versions": versions(limiter),
        }
    )
    meta |= {"api": API, "maxEntries": MAX_ENTRIES, "option": OPTION, "variants": list(VARIANTS)}
    errors = 0
    start = time.monotonic()
    with out_path.open("a", encoding="utf-8") as out, ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(approximate, term, limiter): (ndc, v) for ndc, v, term in todo}
        for i, future in enumerate(as_completed(futures), 1):
            ndc, variant = futures[future]
            try:
                row = {
                    "product_ndc": ndc,
                    "variant": variant,
                    "status": "ok",
                    "candidates": future.result(),
                }
            except Exception as exc:
                errors += 1
                row = {
                    "product_ndc": ndc,
                    "variant": variant,
                    "status": "error",
                    "error": str(exc)[:200],
                }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            if i % 250 == 0 or i == len(todo):
                left = (time.monotonic() - start) / i * (len(todo) - i) / 60
                print(f"[{name}] {i}/{len(todo)} done, {errors} errors, about {left:.0f} min left")
    meta["runs"][-1] |= {
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 (Python 3.9)
        "sent": len(todo),
        "errors": errors,
    }
    meta["responses_sha256"] = sha256(out_path)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    status = "complete" if errors == 0 else f"{errors} errors: run the script again to retry them"
    print(f"[{name}] {status}. SHA-256 of {out_path}: {meta['responses_sha256']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help=f"any of {', '.join(NAMES)} (default: all)")
    names = parser.parse_args().names or list(NAMES)
    unknown = [n for n in names if n not in NAMES]
    if unknown:
        parser.error(f"unknown names {unknown}; choose from {', '.join(NAMES)}")
    limiter = RateLimiter(RATE)
    try:
        probe = approximate("amoxicillin 500 mg oral capsule", limiter, tries=2)
    except Exception as exc:
        raise SystemExit(
            f"RxNav is not reachable from this machine ({exc}). Nothing was sent."
        ) from None
    if not probe:
        raise SystemExit(f"The test query returned nothing. Check that {API} answers.")
    print(f"RxNav reachable: the test query returned {len(probe)} candidates.")
    for name in names:
        run(name, limiter)


if __name__ == "__main__":
    main()
