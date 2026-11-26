"""Write the RxNav queries for v0.2.2: data/rxnav/queries_<name>.jsonl.

Covers a sample of 2,000 training products (they fix RxNav's score scale and calibration), dev and
test2. Only inputs are written, never labels. Run from the repository root:
    python scripts/rxnav_queries.py
Then, on a machine that reaches rxnav.nlm.nih.gov: python scripts/rxnav_fetch.py
"""

from dmb.config import Paths
from dmb.rxnav import TRAIN_SAMPLE, export_queries

if __name__ == "__main__":
    export_queries(Paths.default(), [TRAIN_SAMPLE, "dev", "test2"])
