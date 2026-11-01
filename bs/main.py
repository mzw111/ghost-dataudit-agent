#!/usr/bin/env python3
"""Ghost Data Still Exists - deterministic deletion-audit engine.

Usage: python3 code/main.py [--dataset DIR] [--output FILE] [--cases CSV]
Reads participant-facing files from dataset/, writes output.csv at the repo root.
No model calls are made: the whole pipeline is deterministic.
"""
import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from audit.engine import Engine          # noqa: E402
from audit.output import validate, write_output   # noqa: E402


def read_cases(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def evidence_support_problems(eng, rows):
    """A cited evidence file must actually contain (or, for absence, cover) the resource it is cited for."""
    probs = []
    covers = {(c["file"], sysid) for sysid, cs in eng.ev.cover.items() for c in cs}
    for cid, (status, steps) in rows.items():
        for st in steps:
            ev = st["evidence_id"]
            if not ev:
                continue
            seen = any(o["file"] == ev for o in eng.ev.obs.get(st["resource_id"], []))
            if not seen and (ev, st["system_id"]) not in covers:
                probs.append("%s: %s cites %s which does not mention %s" % (cid, st["operation"], ev, st["resource_id"]))
    return probs


VIOLATING = {"ACCOUNT": ("PRESENT",), "SEARCH": ("PRESENT",), "EXPORT": ("PRESENT",), "MARKETING": ("PRESENT",),
             "OBJECT": ("PRESENT",), "SUPPORT": ("PRESENT", "IDENTIFIABLE"), "ANALYTICS": ("IDENTIFIABLE",),
             "TOMBSTONE": ("IDENTIFIABLE",), "FLOW": ("ACTIVE",), "BACKUP": ("ACTIVE",)}
FINDING_FOR = {"FLOW": "REPORT_ACTIVE_DATA_FLOW", "BACKUP": "REPORT_RESTORE_RISK"}


def completeness_problems(eng, rows):
    """Cross-check the decisions against the evidence: every resource that is linked to the person and whose latest
    eligible observation violates policy must carry a finding (active flows and restore risks included), and every
    linked retained record (security audit / legal hold) with eligible evidence must have a PRESENT verification."""
    from audit.common import kind_of
    probs = []
    for cid, (status, steps) in rows.items():
        if status == "NOT_APPLICABLE":
            continue
        have = {(s["resource_id"], s["phase"], s["operation"]) for s in steps}
        accs = set(eng.account.get(cid, []))
        for rid in sorted(eng.linked(eng.ids[cid])):
            kind = kind_of(rid)
            if kind is None or (kind == "ACCOUNT" and rid not in accs) or (kind != "ACCOUNT" and eng._other_owner(rid, cid)):
                continue
            obs = eng.eligible_obs(rid, eng.cases[cid]["audit_at"])
            if not obs:
                continue
            st = obs[-1]["state"]
            if kind in ("AUDIT", "LEGAL") and (rid, "VERIFICATION", "VERIFY_RECORD_PRESENT") not in have:
                probs.append("%s: retained record %s has no VERIFY_RECORD_PRESENT" % (cid, rid))
            if st in VIOLATING.get(kind, ()) and not any(r == rid and p == "FINDING" for r, p, o in have):
                probs.append("%s: %s is %s at audit_at but has no finding" % (cid, rid, st))
            if kind in FINDING_FOR and st == "ACTIVE" and (rid, "FINDING", FINDING_FOR[kind]) not in have:
                probs.append("%s: %s missing %s" % (cid, rid, FINDING_FOR[kind]))
    return probs


def run(dataset, cases_csv, output, sample_context=False, expected_rows=None):
    eng = Engine(dataset)
    cases = read_cases(cases_csv)
    # Optional: public sample requests may join account elimination (inputs only, never sample_output.csv).
    context = read_cases(os.path.join(dataset, "sample_deletion_requests.csv")) if sample_context else []
    eng.prepare(cases, context)
    rows = {c["case_id"]: eng.decide(c["case_id"]) for c in cases}
    write_output(output, rows)
    act_time = {a["activity_id"]: a["event_time"] for a in eng.acts}
    aud_time = {}
    with open(os.path.join(dataset, "user_audit_log.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            aud_time[r["audit_id"]] = r["event_time"]
    errs = (validate(output, cases, eng.ev.manifest, act_time, aud_time, expected_rows=expected_rows)
            + evidence_support_problems(eng, rows) + completeness_problems(eng, rows))
    return eng, rows, errs


def main():
    root = os.path.dirname(HERE)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=os.path.join(root, "dataset"))
    ap.add_argument("--cases", default=None)
    ap.add_argument("--output", default=os.path.join(root, "output.csv"))
    ap.add_argument("--sample-context", action="store_true",
                    help="let the public sample requests take part in account elimination (default: off)")
    a = ap.parse_args()
    cases_csv = a.cases or os.path.join(a.dataset, "deletion_requests.csv")
    # the full request file must yield exactly the 518 rows required by the contract
    full = os.path.basename(cases_csv) == "deletion_requests.csv" and os.path.abspath(a.dataset) == os.path.join(root, "dataset")
    eng, rows, errs = run(a.dataset, cases_csv, a.output, a.sample_context, 518 if full else None)
    counts = {}
    for st, _ in rows.values():
        counts[st] = counts.get(st, 0) + 1
    print("wrote %s: %d rows %s" % (a.output, len(rows), counts))
    print("validation problems: %d" % len(errs))
    for e in errs[:20]:
        print("  ", e)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
