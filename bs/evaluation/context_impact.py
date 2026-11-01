#!/usr/bin/env python3
"""Measure how much the public sample requests influence the 518 target predictions when they are allowed to
join account elimination (main.py --sample-context). The default pipeline does not use them."""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from audit.engine import Engine  # noqa: E402

DS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "dataset")


def main():
    rd = lambda n: list(csv.DictReader(open(os.path.join(DS, n), encoding="utf-8")))
    tgt, smp = rd("deletion_requests.csv"), rd("sample_deletion_requests.csv")
    eng = Engine(DS)
    eng.prepare(tgt)
    a = {c["case_id"]: eng.decide(c["case_id"]) for c in tgt}
    eng.prepare(tgt, smp)
    b = {c["case_id"]: eng.decide(c["case_id"]) for c in tgt}
    diff = sorted(c for c in a if a[c] != b[c])
    print("target rows: %d; rows that change when sample requests join the pool: %d %s" % (len(a), len(diff), diff))
    print("status changes:", sum(a[c][0] != b[c][0] for c in a))


if __name__ == "__main__":
    main()
