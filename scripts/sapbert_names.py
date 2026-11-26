"""Write the names SapBERT indexes (v0.2.3): data/sapbert/catalog_names.jsonl.

The queries are the ones already written for RxNav (data/rxnav/queries_<name>.jsonl). Run from the
repository root:
    python scripts/sapbert_names.py
Then, on a machine with PyTorch and access to huggingface.co: python scripts/sapbert_embed.py
"""

from dmb.config import Paths
from dmb.rxnav import export_catalog_names

if __name__ == "__main__":
    export_catalog_names(Paths.default())
