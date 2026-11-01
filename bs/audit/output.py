"""Serialisation and validation of output.csv."""
import csv
import json

HEADER = ["case_id", "deletion_status", "steps_json"]
FIELDS = ["step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"]
OPS = {
    "FINDING": {"REPORT_REMAINING_RECORD": "PRESENT", "REPORT_EXPOSED_PII": "PRESENT", "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
                "REPORT_RESTORE_RISK": "ACTIVE"},
    "REMEDIATION": {"DISABLE_DATA_FLOW": "DISABLED", "BLOCK_RESTORE": "BLOCKED", "DELETE_RECORD": "ABSENT",
                    "REDACT_RECORD": "REDACTED", "ANONYMIZE_RECORD": "ANONYMIZED"},
    "VERIFICATION": {"VERIFY_RECORD_ABSENT": "ABSENT", "VERIFY_RECORD_PRESENT": "PRESENT", "VERIFY_RECORD_REDACTED": "REDACTED",
                     "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED", "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
                     "VERIFY_RESTORE_BLOCKED": "BLOCKED"},
}
PHASE_ORDER = ["FINDING", "REMEDIATION", "VERIFICATION"]


def write_output(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(HEADER)
        for cid in sorted(rows):
            status, steps = rows[cid]
            w.writerow([cid, status, json.dumps(steps, separators=(",", ":"), ensure_ascii=False, sort_keys=False)])


FIND_ORDER = ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"]
PHASE_OPS = {ph: list(ops) for ph, ops in OPS.items()}   # dict order == operation precedence from the problem statement


def validate(path, requests, manifest, activity_time=None, audit_time=None, expected_rows=None):
    """Independent check of output.csv against the contract; returns a list of problems (empty == valid).

    requests: list of request dicts (case_id, audit_at, ...); manifest: file_id -> row with captured_at;
    activity_time / audit_time: optional id -> timestamp maps for activity_id / audit_id citations."""
    errs = []
    activity_time = activity_time or {}
    audit_time = audit_time or {}
    case_ids = [r["case_id"] for r in requests]
    cutoff = {r["case_id"]: r["audit_at"] for r in requests}

    def cited_time(ev):
        if ev in manifest:
            return manifest[ev]["captured_at"]
        return activity_time.get(ev) or audit_time.get(ev)

    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        head = next(rd, None)
        if head != HEADER:
            errs.append("bad header %r" % head)
        rows = list(rd)
    ids = [r[0] for r in rows if r]
    if any(len(r) != 3 for r in rows):
        errs.append("rows with wrong column count")
    if ids != sorted(ids):
        errs.append("rows not sorted by case_id")
    if len(set(ids)) != len(ids):
        errs.append("duplicate case ids")
    if expected_rows is not None and len(rows) != expected_rows:
        errs.append("expected exactly %d data rows, found %d" % (expected_rows, len(rows)))
    if len(rows) != len(case_ids) or set(ids) != set(case_ids):
        errs.append("case set mismatch: missing=%d extra=%d" % (len(set(case_ids) - set(ids)), len(set(ids) - set(case_ids))))
    for r in rows:
        if len(r) != 3:
            continue
        cid, status, sj = r
        e = lambda m: errs.append("%s: %s" % (cid, m))
        if status not in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"):
            e("bad status %r" % status)
        try:
            steps = json.loads(sj)
        except ValueError:
            e("invalid json")
            continue
        if not isinstance(steps, list):
            e("steps_json is not an array")
            continue
        if status == "NOT_APPLICABLE" and steps:
            e("NOT_APPLICABLE must have empty steps")
        if status in ("COMPLETE", "INCOMPLETE") and not steps:
            e("%s must have steps" % status)
        phases_seen = []
        keys = []
        seen = set()
        for n, s in enumerate(steps, 1):
            if not isinstance(s, dict) or set(s) != set(FIELDS):
                e("step %d fields are not exactly %s" % (n, FIELDS))
                continue
            if type(s["step_no"]) is not int or s["step_no"] != n:
                e("step_no not consecutive from 1 at position %d" % n)
            ph, op = s["phase"], s["operation"]
            if ph not in OPS or op not in OPS[ph] or OPS[ph][op] != s["state"]:
                e("illegal phase/operation/state at %d: %r %r %r" % (n, ph, op, s["state"]))
                continue
            if not all(isinstance(s[f], str) and (s[f] or f == "evidence_id") for f in FIELDS[1:]):
                e("empty or non-string field at %d" % n)
            if (ph, op, s["system_id"], s["resource_id"]) in seen:
                e("duplicate step at %d" % n)
            seen.add((ph, op, s["system_id"], s["resource_id"]))
            phases_seen.append(ph)
            keys.append((PHASE_ORDER.index(ph), PHASE_OPS[ph].index(op), s["system_id"], s["resource_id"]))
            ev = s["evidence_id"]
            needs_ev = ph == "FINDING" or (ph == "VERIFICATION" and status == "COMPLETE")
            if needs_ev and not ev:
                e("step %d (%s) requires an evidence_id" % (n, ph))
            if not needs_ev and ev != "":
                e("step %d (%s) is future work and must have empty evidence_id" % (n, ph))
            if ev:
                t = cited_time(ev)
                if t is None:
                    e("step %d cites unknown evidence %s" % (n, ev))
                elif t > cutoff.get(cid, "9999"):
                    e("step %d cites %s captured after audit_at" % (n, ev))
        if keys != sorted(keys):
            e("steps violate phase / operation precedence / system_id / resource_id ordering")
        if status == "COMPLETE" and any(p != "VERIFICATION" for p in phases_seen):
            e("COMPLETE may contain only VERIFICATION steps")
        if status == "INCOMPLETE":
            for ph in PHASE_ORDER:
                if ph not in phases_seen:
                    e("INCOMPLETE requires %s steps" % ph)
            # every finding on a record needs a remediation and a verification on the same record
            fnd = {(s["system_id"], s["resource_id"]) for s in steps if isinstance(s, dict) and s.get("phase") == "FINDING"}
            rem = {(s["system_id"], s["resource_id"]) for s in steps if isinstance(s, dict) and s.get("phase") == "REMEDIATION"}
            ver = {(s["system_id"], s["resource_id"]) for s in steps if isinstance(s, dict) and s.get("phase") == "VERIFICATION"}
            if fnd != rem:
                e("findings and remediation cover different resources")
            if not fnd <= ver:
                e("a remediated resource has no verification step")
    return errs
