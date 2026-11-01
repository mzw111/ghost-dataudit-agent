#!/usr/bin/env python3
"""Score predictions against dataset/sample_output.csv (the only ground truth available to participants)."""
import csv
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from main import run   # noqa: E402

FIELDS = ["step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"]


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"])) for r in csv.DictReader(fh)}


def score(pred, gold, verbose=False):
    n = len(gold)
    st = sum(pred[c][0] == gold[c][0] for c in gold)
    row = seq = 0
    step_hit = step_tot_g = step_tot_p = 0
    fld_hit = fld_tot = 0
    diffs = []
    for c in sorted(gold):
        gs, ps = gold[c][1], pred[c][1]
        gk = [tuple(s[f] for f in FIELDS[1:]) for s in gs]
        pk = [tuple(s[f] for f in FIELDS[1:]) for s in ps]
        seq += gs == ps
        row += (gold[c][0] == pred[c][0]) and gs == ps
        step_hit += len(set(gk) & set(pk))
        step_tot_g += len(gk)
        step_tot_p += len(pk)
        for i, g in enumerate(gs):
            for f in FIELDS:
                fld_tot += 1
                fld_hit += i < len(ps) and ps[i][f] == g[f]
        if gs != ps or gold[c][0] != pred[c][0]:
            diffs.append((c, sorted(set(gk) - set(pk)), sorted(set(pk) - set(gk))))
    return dict(cases=n, status_acc=st / n, row_acc=row / n, sequence_acc=seq / n,
                step_recall=step_hit / max(step_tot_g, 1), step_precision=step_hit / max(step_tot_p, 1),
                field_acc=fld_hit / max(fld_tot, 1)), diffs


def main():
    root = os.path.dirname(os.path.dirname(HERE))
    ds = os.path.join(root, "dataset")
    out = os.path.join(tempfile.gettempdir(), "sample_pred.csv")
    eng, rows, errs = run(ds, os.path.join(ds, "sample_deletion_requests.csv"), out)
    for e in errs[:10]:
        print("VALIDATION:", e)
    gold = load(os.path.join(ds, "sample_output.csv"))
    m, diffs = score({c: rows[c] for c in rows}, gold)
    print(json.dumps(m, indent=2))
    print("validation problems:", len(errs))
    for c, miss, extra in diffs:
        print(c, "MISSING", [x[1:4] + (x[4],) for x in miss][:6], "EXTRA", [x[1:4] + (x[4],) for x in extra][:6])


if __name__ == "__main__":
    main()
