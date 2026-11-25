"""Benchmark constants and project paths."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SEED = 42
N_DEV = 2000
N_TEST = 2000
HOLDOUT_FRAC = 0.10
TOP_K = 5
TARGET_PRECISION = 0.95
# How dev/test are sampled. A change here makes `dmb build` refuse the old split files until
# they are re-sampled with `--resample-splits` (allowed only before the test split is frozen).
SPLIT_METHOD = "grouped-stratified-v1"
QUERY_FORMAT_VERSION = "v0.3"  # v0.2: package NDC codes dropped; v0.3: route added


@dataclass(frozen=True)
class Paths:
    """All locations are derived from the repo root (override with DMB_ROOT)."""

    root: Path

    @classmethod
    def default(cls) -> Paths:
        env = os.environ.get("DMB_ROOT")
        return cls(Path(env).resolve() if env else Path.cwd().resolve())

    @property
    def raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def processed(self) -> Path:
        return self.root / "data" / "processed"

    @property
    def splits(self) -> Path:
        return self.root / "splits"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def manifest(self) -> Path:
        return self.raw / "manifest.json"

    @property
    def ndc_dir(self) -> Path:
        return self.raw / "ndc"

    @property
    def rxnorm_dir(self) -> Path:
        return self.raw / "rxnorm"

    @property
    def rrf_dir(self) -> Path:
        return self.rxnorm_dir / "rrf"

    @property
    def sources_file(self) -> Path:
        return self.root / "sources.json"


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
