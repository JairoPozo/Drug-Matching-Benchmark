"""SapBERT candidates for the benchmark queries (v0.2.3).

Runs on any machine with PyTorch, transformers and access to huggingface.co (the model is
downloaded the first time). It embeds every catalog name in data/sapbert/catalog_names.jsonl
(written by scripts/sapbert_names.py) and every query in data/rxnav/queries_<name>.jsonl, in its
full and short forms, with the [CLS] vector of SapBERT. For each query it writes the 100 catalog
concepts with the highest cosine similarity (a concept's similarity is that of its best name) to
data/sapbert/responses_<name>.jsonl, in the same format as the RxNav responses.

Install once, in the project's environment:
    uv pip install torch transformers
Run from the repository root (CPU is fine; about 15 to 30 minutes):
    python scripts/sapbert_embed.py
"""

from __future__ import annotations

import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import transformers
from transformers import AutoModel, AutoTokenizer

MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
MAX_LENGTH = 128
BATCH = 64
TOP = 100
VARIANTS = ("full", "short")
NAMES = ("train_sample", "dev", "test2")
OUT = Path("data") / "sapbert"
QUERIES = Path("data") / "rxnav"


def embed(texts: list[str], tokenizer, model, label: str) -> np.ndarray:
    """L2-normalized [CLS] vectors, in the order of texts (batches sorted by length)."""
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    out = np.zeros((len(texts), model.config.hidden_size), dtype=np.float32)
    start = time.monotonic()
    with torch.inference_mode():
        for b in range(0, len(order), BATCH):
            idx = order[b : b + BATCH]
            batch = tokenizer(
                [texts[i] for i in idx],
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            )
            cls = model(**batch).last_hidden_state[:, 0, :]
            cls = torch.nn.functional.normalize(cls, dim=1)
            out[idx] = cls.numpy()
            done = b + len(idx)
            if done % (BATCH * 50) < BATCH or done == len(order):
                left = (time.monotonic() - start) / done * (len(order) - done) / 60
                print(f"[{label}] {done}/{len(order)} embedded, about {left:.0f} min left")
    return out


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    torch.manual_seed(0)
    tokenizer = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModel.from_pretrained(MODEL).eval()
    meta = {
        "model": MODEL,
        "model_commit": getattr(model.config, "_commit_hash", None),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "python": platform.python_version(),
        "max_length": MAX_LENGTH,
        "top": TOP,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
        "files": {},
    }
    print(f"SapBERT loaded (revision {meta['model_commit']}), torch {torch.__version__}")

    names = [
        json.loads(line)
        for line in (OUT / "catalog_names.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cache = OUT / "name_embeddings.npy"
    if cache.exists() and np.load(cache).shape[0] == len(names):
        name_vecs = np.load(cache)
    else:
        name_vecs = embed([n["name"] for n in names], tokenizer, model, "catalog names")
        np.save(cache, name_vecs)
    # names are sorted by concept: one block of columns per concept
    concepts, starts = [], []
    for i, n in enumerate(names):
        if not concepts or concepts[-1] != n["rxcui"]:
            concepts.append(n["rxcui"])
            starts.append(i)
    starts = np.array(starts)

    for name in NAMES:
        queries = [
            json.loads(line)
            for line in (QUERIES / f"queries_{name}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        out_path = OUT / f"responses_{name}.jsonl"
        with out_path.open("w", encoding="utf-8") as out:
            for variant in VARIANTS:
                vecs = embed([q[variant] for q in queries], tokenizer, model, f"{name} {variant}")
                for b in range(0, len(queries), 256):
                    sims = vecs[b : b + 256] @ name_vecs.T  # cosine: vectors are normalized
                    best = np.maximum.reduceat(sims, starts, axis=1)  # best name per concept
                    which = np.argmax(sims, axis=1)
                    for row, q in enumerate(queries[b : b + 256]):
                        top = np.argpartition(-best[row], TOP)[:TOP]
                        top = top[np.argsort(-best[row][top], kind="stable")]
                        cands = [
                            [
                                concepts[c],
                                None,
                                round(float(best[row][c]), 6),
                                rank,
                                "SAPBERT",
                                None,
                            ]
                            for rank, c in enumerate(top, 1)
                        ]
                        cands[0][5] = names[int(which[row])]["name"]  # best matching name
                        line = {
                            "product_ndc": q["product_ndc"],
                            "variant": variant,
                            "status": "ok",
                            "candidates": cands,
                        }
                        out.write(json.dumps(line, ensure_ascii=False) + "\n")
        meta["files"][out_path.name] = sha256(out_path)
        print(f"[{name}] written. SHA-256 of {out_path}: {meta['files'][out_path.name]}")
    meta["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: UP017
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("Done.")


if __name__ == "__main__":
    main()
