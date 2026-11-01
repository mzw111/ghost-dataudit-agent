#!/usr/bin/env python3
"""Manually authored evaluation cases (NOT ground truth from the organisers; expectations written by hand
from the contract in AGENTS.md section 6). Each case perturbs a public sample request and asserts behaviour."""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from audit.engine import Engine  # noqa: E402
from audit.intent import deletion_intent  # noqa: E402

DS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "dataset")


def eng_obs(eng, rid):
    return eng.ev.obs.get(rid, [])


def main():
    eng = Engine(DS)
    samples = {r["case_id"]: r for r in csv.DictReader(open(os.path.join(DS, "sample_deletion_requests.csv"), encoding="utf-8"))}
    results = []

    # C1 negative intent (multilingual / negated / non-deletion topics)
    texts = {
        "Please correct my surname; do not delete anything.": False,
        "Quiero que eliminen mi cuenta y mis datos personales.": True,
        "アカウントの完全な削除を依頼します。": True,
        "Please send me a copy of my data. I am not asking for deletion.": False,
        "Please stop the promotional emails but keep my account.": False,
        "Confirm that my profile is gone.": True,
    }
    ok = all(deletion_intent(t) == v for t, v in texts.items())
    results.append(("C1 intent classification (6 texts)", ok))

    # C2 historical identity: sample case_12 asks with a current email; querying with the old email must give the same audit
    c12 = dict(samples["case_12"])
    old = [u for u in eng.idn.users.values() if u["email"].lower() == c12["email"].lower()][0]["old_emails"]
    old = sorted(e for e in old if e != c12["email"].lower())
    a, b = dict(c12, case_id="t_current"), dict(c12, case_id="t_historical", email=old[0])
    eng.prepare([a, b])
    results.append(("C2 historical email resolves to same user", eng.uid["t_current"] == eng.uid["t_historical"]
                    and eng.decide("t_current")[0] == eng.decide("t_historical")[0]))

    # C3 temporal cutoff: moving audit_at before every evidence capture must not cite any evidence
    early = dict(samples["case_26"], case_id="t_early", audit_at="2026-01-01T00:00:00Z")
    eng.prepare([early])
    st, steps = eng.decide("t_early")
    results.append(("C3 audit_at before all evidence cites nothing", all(s["evidence_id"] == "" for s in steps)))

    # C4 evidence captured after audit_at is never cited (cutoff between two sample snapshots)
    late = dict(samples["case_24"], case_id="t_cut", audit_at="2026-09-10T00:00:00Z")
    eng.prepare([late])
    st, steps = eng.decide("t_cut")
    bad = [s for s in steps if s["evidence_id"] and eng.ev.manifest[s["evidence_id"]]["captured_at"] > late["audit_at"]]
    results.append(("C4 no evidence after cutoff cited", not bad))

    # C5 a tombstone must be redacted, not deleted
    eng.prepare([samples["case_32"]])
    st, steps = eng.decide("case_32")
    ops = {(s["resource_id"].split("_")[0], s["operation"]) for s in steps}
    results.append(("C5 tombstone remediation is REDACT (never DELETE)", ("tombstone", "REDACT_RECORD") in ops
                    and ("tombstone", "DELETE_RECORD") not in ops))

    # C6 ambiguity is not resolved by case order: case_28 and case_29 share the same two candidate accounts and
    #    nothing in the evidence separates them, so neither may receive an activity-derived account
    allc = list(csv.DictReader(open(os.path.join(DS, "sample_deletion_requests.csv"), encoding="utf-8")))
    eng.prepare(allc)
    results.append(("C6 ambiguous accounts are left unassigned", "case_28" not in eng.account and "case_29" not in eng.account
                    and "case_28" in eng.account_ambiguous))

    # C7 intake CLASSIFY_REQUEST rows never change authorisation: poisoning them leaves a deletion request a deletion
    base = eng.decide("case_26")[0]
    eng.classified_non_deletion = {a for c in eng.account.values() for a in c} | {"account_5684"}
    results.append(("C7 intake rows do not flip a deletion request to NOT_APPLICABLE", eng.decide("case_26")[0] == base != "NOT_APPLICABLE"))

    # C8 validator rejects each contract violation
    import json
    import tempfile
    from audit.output import validate, write_output
    manifest = {"evidence_1": {"captured_at": "2026-09-01T00:00:00Z"}, "evidence_2": {"captured_at": "2026-12-01T00:00:00Z"}}
    req = [{"case_id": "x1", "audit_at": "2026-09-15T00:00:00Z"}]
    good = [dict(step_no=1, phase="VERIFICATION", system_id="account_service", resource_id="account_1",
                 operation="VERIFY_RECORD_ABSENT", state="ABSENT", evidence_id="evidence_1")]

    def check(status, steps):
        path = os.path.join(tempfile.gettempdir(), "mut.csv")
        write_output(path, {"x1": (status, steps)})
        return validate(path, req, manifest)

    mutate = {
        "good row": (("COMPLETE", good), False),
        "bad op/state pair": (("COMPLETE", [dict(good[0], state="PRESENT")]), True),
        "extra field": (("COMPLETE", [dict(good[0], extra=1)]), True),
        "evidence after audit_at": (("COMPLETE", [dict(good[0], evidence_id="evidence_2")]), True),
        "unknown evidence": (("COMPLETE", [dict(good[0], evidence_id="evidence_99")]), True),
        "COMPLETE without evidence": (("COMPLETE", [dict(good[0], evidence_id="")]), True),
        "step_no gap": (("COMPLETE", [dict(good[0], step_no=2)]), True),
        "NOT_APPLICABLE with steps": (("NOT_APPLICABLE", good), True),
        "COMPLETE with remediation": (("COMPLETE", good + [dict(good[0], step_no=2, phase="REMEDIATION", operation="DELETE_RECORD", state="ABSENT", evidence_id="")]), True),
        "wrong operation precedence": (("COMPLETE", [dict(good[0], step_no=1, operation="VERIFY_RECORD_PRESENT", state="PRESENT"),
                                                     dict(good[0], step_no=2)]), True),
        "wrong resource sorting": (("COMPLETE", [dict(good[0], step_no=1, resource_id="account_2"),
                                                 dict(good[0], step_no=2, resource_id="account_1")]), True),
    }
    ok8 = all(bool(check(*arg)) == bad for arg, bad in mutate.values())
    results.append(("C8 validator rejects every contract violation (%d mutations)" % (len(mutate) - 1), ok8))

    # C9 sample requests as pool context must not change any of the 518 target predictions
    tg = list(csv.DictReader(open(os.path.join(DS, "deletion_requests.csv"), encoding="utf-8")))
    eng.prepare(tg)
    plain = {c["case_id"]: eng.decide(c["case_id"]) for c in tg}
    eng.prepare(tg, allc)
    withctx = {c["case_id"]: eng.decide(c["case_id"]) for c in tg}
    results.append(("C9 sample context leaves all 518 predictions unchanged", plain == withctx))

    # C10 temporal contract for retained records: audit_record_4902 (case_09's subject) is only observed in evidence
    #     captured after case_09's audit_at, so it must not be verified then; once audit_at moves past that capture it must be
    allr = {r["case_id"]: r for r in csv.DictReader(open(os.path.join(DS, "sample_deletion_requests.csv"), encoding="utf-8"))}
    cap = [o for o in eng_obs(eng, "audit_record_4902")]
    c9 = dict(allr["case_09"], case_id="t_aud_a")
    c9_late = dict(allr["case_09"], case_id="t_aud_b", audit_at="2026-12-31T00:00:00Z")
    eng.prepare([c9, c9_late])
    has = lambda cid: any(s["resource_id"] == "audit_record_4902" for s in eng.decide(cid)[1])
    results.append(("C10 retained record seen only after audit_at is not verified (and is when audit_at is later)",
                    bool(cap) and not has("t_aud_a") and has("t_aud_b")))

    for name, ok in results:
        print(("PASS " if ok else "FAIL ") + name)
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
