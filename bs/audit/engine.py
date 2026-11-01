"""Decision engine: resolves resources per case, reconstructs state at audit_at, applies policy."""
import csv
import os
import re
from collections import defaultdict

from .common import kind_of, system_of, ids_in
from .identity import Identities
from .evidence import Evidence

REPORT_TO_STATUS = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}
NEGATIVE = re.compile(r"\b(do not|don't|dont|not want|no longer want|never)\b.{0,40}\b(delete|deletion|erase|remove|close)\b", re.I)


class Engine:
    def __init__(self, dataset_dir):
        self.dir = dataset_dir
        self.idn = Identities(dataset_dir)
        self.ev = Evidence(dataset_dir)
        self.rules = list(csv.DictReader(open(os.path.join(dataset_dir, "deletion_rules.csv"), newline="")))
        self.acts = list(csv.DictReader(open(os.path.join(dataset_dir, "system_activity.csv"), newline="", encoding="utf-8")))
        self.link_rows = [a for a in self.acts if a["event_type"] == "LINK_RESOURCE_IDENTITY"]
        self.account_acts = [a for a in self.acts if a["event_type"] == "DELETE_RECORD" and a["target_system"] == "account_service"]
        # resource -> set of identifiers ever seen with it (any eligible time handled per case)
        self.assign = {}

    # ----------------------------------------------------------------- eligibility
    def eligible_obs(self, rid, audit_at):
        out = []
        for o in self.ev.obs.get(rid, []):
            if o["cap"] <= audit_at and o["t"] <= audit_at:
                out.append(o)
        return sorted(out, key=lambda o: (o["t"], o["cap"], o["file"]))

    def latest(self, rid, audit_at):
        obs = self.eligible_obs(rid, audit_at)
        return obs[-1] if obs else None

    def coverage_absence(self, system, rid, audit_at, after=None):
        """Latest eligible snapshot proving absence by omission. Inventory captures are point lookups of named
        resources, not full-table dumps, so they only count when nothing else covers the system."""
        elig = [c for c in self.ev.cover.get(system, []) if c["cap"] <= audit_at and c["t"] <= audit_at and rid not in c["rids"]]
        if not elig:
            return None
        elig = [c for c in elig if self.ev.manifest[c["file"]]["origin"] != "customer_data_inventory_capture"] or elig
        return max(elig, key=lambda c: (c["t"], c["cap"]))

    # ----------------------------------------------------------------- membership (static, any time)
    def build_membership(self):
        """resource -> identifiers ever observed with it (membership is identity, not state)."""
        mem = defaultdict(set)
        for rid, obs in self.ev.obs.items():
            for o in obs:
                mem[rid] |= o["ids"]
        for a in self.link_rows:
            mem[a["resource_id"]] |= ids_in(a["details"])
        self.member = mem
        self.by_id = defaultdict(set)
        for rid, ids in mem.items():
            for i in ids:
                self.by_id[i].add(rid)

    def linked(self, ids):
        out = set()
        for i in ids:
            out |= self.by_id.get(i, set())
        return out

    # ----------------------------------------------------------------- case preparation
    def prepare(self, cases, context_cases=()):
        """cases: requests to decide. context_cases: optional extra requests (e.g. the public samples) that
        only take part in account elimination; they are never decided and default to none."""
        self.build_membership()
        self.targets = [c["case_id"] for c in cases]
        self.cases = {c["case_id"]: c for c in list(cases) + [x for x in context_cases if x["case_id"] not in {y["case_id"] for y in cases}]}
        # authorisation comes from the request text only; intake CLASSIFY_REQUEST rows are a claim and are not used
        self.na = {cid: not _is_deletion(c["request_text"]) for cid, c in self.cases.items()}
        self.uid = {}
        self.ids = {}
        for cid, c in self.cases.items():
            u = self.idn.resolve(c["email"])
            self.uid[cid] = u
            self.ids[cid] = self.idn.identifiers(u) if u else ids_in(c["email"])
        self._assign_accounts()
        self._assign_anon_analytics()

    def _owners(self, rid):
        """Known users (from the identity tables) whose identifiers were ever observed with this resource."""
        if not hasattr(self, "_hash_owner"):
            self._hash_owner = {}
            for uid in self.idn.users:
                for i in self.idn.identifiers(uid):
                    self._hash_owner.setdefault(i, set()).add(uid)
        out = set()
        for i in self.member.get(rid, set()):
            out |= self._hash_owner.get(i, set())
        return out

    def _other_owner(self, rid, cid):
        """True when the resource carries identifiers of known users that do not include the case's user."""
        owners = self._owners(rid)
        return bool(owners) and self.uid.get(cid) not in owners

    def _assign_accounts(self):
        claimed = {}
        # 1. evidence-linked accounts
        self.account = {}
        for cid in self.cases:
            if self.na[cid]:
                continue
            accs = {r for r in self.linked(self.ids[cid]) if kind_of(r) == "ACCOUNT"}
            if len(accs) > 1:
                req = self.cases[cid]["requested_at"]
                c0 = self.cases[cid]
                want0, lo0, hi0 = REPORT_TO_STATUS.get(c0["reported_status"]), _shift(c0["reported_at"], -3 * 3600), _shift(c0["reported_at"], 1800)
                inwin = {a for a in accs if any(x["resource_id"] == a and x["reported_result"] == want0 and lo0 <= x["event_time"] <= hi0
                                                for x in self.account_acts)}
                recent =  inwin or {a for a in accs if any(o["t"] >= req for o in self.ev.obs.get(a, []))
                          or any(x["resource_id"] == a and x["event_time"] >= req for x in self.account_acts)}
                accs = recent or accs
            if accs:
                self.account[cid] = sorted(accs)
                for a in accs:
                    claimed[a] = self.uid.get(cid) or cid
        # accounts that belong to a user who is not a case subject are decoys
        cand = {}
        for cid, c in self.cases.items():
            if cid in self.account or self.na[cid]:
                continue
            want = REPORT_TO_STATUS.get(c["reported_status"])
            me = self.uid.get(cid) or cid
            rep = c["reported_at"]
            lo = _shift(rep, -3 * 3600)
            hi = _shift(rep, 1800)
            cs = []
            for a in self.account_acts:
                rid = a["resource_id"]
                if a["reported_result"] != want or not (lo <= a["event_time"] <= hi) or a["event_time"] < c["requested_at"]:
                    continue
                if claimed.get(rid, me) != me:        # already tied to a different person
                    continue
                if self._other_owner(rid, cid):
                    continue
                cs.append(a)
            cand[cid] = cs
        # 2. constraint propagation
        changed = True
        while changed:
            changed = False
            for cid, cs in sorted(cand.items(), key=lambda kv: len(kv[1])):
                if cid in self.account:
                    continue
                me = self.uid.get(cid) or cid
                cs = [a for a in cs if claimed.get(a["resource_id"], me) == me]
                cand[cid] = cs
                if len({a["resource_id"] for a in cs}) == 1:
                    self.account[cid] = [cs[0]["resource_id"]]
                    claimed[cs[0]["resource_id"]] = me
                    changed = True
        # 2b. several requests by the same person refer to the same account resource
        by_user = defaultdict(set)
        for cid, accs in self.account.items():
            by_user[self.uid.get(cid)].update(accs)
        for cid, cs in cand.items():
            if cid in self.account or self.na[cid]:
                continue
            known = by_user.get(self.uid.get(cid))
            if known and len(known) == 1:
                self.account[cid] = sorted(known)
        # 3. residual ambiguity is NOT resolved by case order or timing: such cases get no activity-derived account.
        self.account_ambiguous = {cid: [a["resource_id"] for a in cs] for cid, cs in cand.items()
                                  if cid not in self.account and len(cs) > 1}
        # 4. account_NNN <-> user_NN convention (shown by the failover-replica rows), only if that id is visible
        #    somewhere in participant data (evidence or activity); otherwise the resource would be invented.
        visible = {a["resource_id"] for a in self.acts} | set(self.ev.obs)
        for cid in self.cases:
            if cid in self.account or self.na[cid]:
                continue
            m = re.fullmatch(r"user_(\d{1,2})", self.uid.get(cid) or "")
            rid = "account_%03d" % int(m.group(1)) if m else None
            me = self.uid.get(cid) or cid
            if rid and rid in visible and claimed.get(rid, me) == me and not self._other_owner(rid, cid):
                self.account[cid] = [rid]
                claimed[rid] = me
        self.account_claimed = claimed

    def _assign_anon_analytics(self):
        self.anon = defaultdict(list)
        self.anon_ambiguous = {}
        anon_acts = [a for a in self.acts if a["event_type"] == "ANONYMIZE_RECORD" and a["target_system"] == "analytics_platform"]
        used = set()
        for cid, ids in self.ids.items():   # analytics already tied by identifier
            for r in self.linked(ids):
                if kind_of(r) == "ANALYTICS":
                    used.add(r)
        by_day = defaultdict(list)
        for cid, c in self.cases.items():
            by_day[self._anchor(cid)[:10]].append(cid)
        for day, cids in by_day.items():
            # an anonymised record by definition carries no identifier of any known person; a record already tied to
            # someone (by any identifier of any user in the identity tables) is that person's, not a candidate here
            cands = [a for a in anon_acts if a["event_time"][:10] == day and a["resource_id"] not in used
                     and not self._owners(a["resource_id"])]
            cands.sort(key=lambda a: a["event_time"])
            need = [c for c in sorted(cids, key=_case_no) if self._wants_analytics(c)]
            if len(need) == 1 and len(cands) == 1:      # pairing several by order/time would be a guess
                self.anon[need[0]].append(cands[0]["resource_id"])
            elif need and cands:
                self.anon_ambiguous[day] = (need, [a["resource_id"] for a in cands])

    def _anchor(self, cid):
        accs = self.account.get(cid) or []
        for a in self.account_acts:
            if a["resource_id"] in accs:
                return a["event_time"]
        return self.cases[cid]["reported_at"]

    def _wants_analytics(self, cid):
        """An anonymised analytics record can only be tied to a case through the worker batch, so it is offered
        to cases that are otherwise fully compliant account deletions (no tombstone-only reference cases)."""
        if self.na[cid]:
            return False
        items = self._items(cid)
        if any(i["find"] for i in items):
            return False
        if any(i["kind"] in ("TOMBSTONE", "ANALYTICS") for i in items):
            return False
        return True


def _case_no(cid):
    m = re.search(r"(\d+)$", cid)
    return int(m.group(1)) if m else 0


def _shift(ts, seconds):
    import datetime as dt
    d = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") + dt.timedelta(seconds=seconds)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


# ====================================================================== decisions
FIND_OP = {"REMAINING": ("REPORT_REMAINING_RECORD", "PRESENT"), "PII": ("REPORT_EXPOSED_PII", "PRESENT"),
           "FLOW": ("REPORT_ACTIVE_DATA_FLOW", "ACTIVE"), "RESTORE": ("REPORT_RESTORE_RISK", "ACTIVE")}
FIND_ORDER = ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"]
REME_ORDER = ["DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"]
VERI_ORDER = ["VERIFY_RECORD_ABSENT", "VERIFY_RECORD_PRESENT", "VERIFY_RECORD_REDACTED", "VERIFY_RECORD_ANONYMIZED",
              "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED"]
STATE_OF = {"DISABLE_DATA_FLOW": "DISABLED", "BLOCK_RESTORE": "BLOCKED", "DELETE_RECORD": "ABSENT", "REDACT_RECORD": "REDACTED",
            "ANONYMIZE_RECORD": "ANONYMIZED", "VERIFY_RECORD_ABSENT": "ABSENT", "VERIFY_RECORD_PRESENT": "PRESENT",
            "VERIFY_RECORD_REDACTED": "REDACTED", "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
            "VERIFY_DATA_FLOW_DISABLED": "DISABLED", "VERIFY_RESTORE_BLOCKED": "BLOCKED"}


def _is_deletion(text):
    from .intent import deletion_intent
    return deletion_intent(text)


def treat(kind, state, contact=False):
    """Policy: (finding, remediation, verification) for a record kind in its observed state."""
    if kind == "ANALYTICS" and contact:
        kind = "MARKETING"
    if kind in ("ACCOUNT", "SEARCH", "EXPORT", "MARKETING", "OBJECT"):
        if state == "ABSENT":
            return None, None, "VERIFY_RECORD_ABSENT"
        return ("REMAINING", "DELETE_RECORD", "VERIFY_RECORD_ABSENT")
    if kind == "SUPPORT":
        if state == "PRESENT":                                   # attachment owned by the subject
            return ("REMAINING", "DELETE_RECORD", "VERIFY_RECORD_ABSENT")
        if state == "ABSENT":
            return None, None, "VERIFY_RECORD_ABSENT"
        if state == "IDENTIFIABLE":
            return ("PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED")
        return None, None, "VERIFY_RECORD_REDACTED"
    if kind == "ANALYTICS":
        if state == "IDENTIFIABLE":
            return ("PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED")
        return None, None, "VERIFY_RECORD_ANONYMIZED"
    if kind == "TOMBSTONE":
        if state == "IDENTIFIABLE":
            return ("PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED")
        return None, None, "VERIFY_RECORD_REDACTED"
    if kind == "FLOW":
        if state == "ACTIVE":
            return ("FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED")
        return None, None, "VERIFY_DATA_FLOW_DISABLED"
    if kind == "BACKUP":
        if state == "ACTIVE":
            return ("RESTORE", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED")
        return None, None, "VERIFY_RESTORE_BLOCKED"
    if kind in ("AUDIT", "LEGAL"):
        return None, None, "VERIFY_RECORD_PRESENT"
    return None, None, None


def _items(self, cid):
    c = self.cases[cid]
    audit_at = c["audit_at"]
    rids = set(self.linked(self.ids[cid])) | set(self.account.get(cid, [])) | set(self.anon.get(cid, []))
    items = []
    for rid in sorted(rids):
        kind = kind_of(rid)
        if kind is None or kind == "CACHE":
            continue
        if kind != "ACCOUNT" and self._other_owner(rid, cid):
            continue
        if kind == "ACCOUNT" and rid not in self.account.get(cid, []):
            continue
        obs = self.eligible_obs(rid, audit_at)
        contact = any(o["ctx"].get("contact") for o in self.ev.obs.get(rid, []))
        if obs:
            lat = obs[-1]
            state, ev = lat["state"], lat["file"]
        elif kind == "ACCOUNT":
            cov = self.coverage_absence("account_service", rid, audit_at, c["reported_at"])
            state, ev = "ABSENT", (cov["file"] if cov else "")
        # A retained record (audit / legal hold) whose only observations were captured after audit_at is NOT assumed
        # present: later evidence cannot prove the state at audit_at, so no step is emitted for it.
        elif kind == "ANALYTICS" and rid in self.anon.get(cid, []):
            state, ev = "ANONYMIZED", ""
        else:
            continue
        f, r, v = treat(kind, state, contact)
        if v is None:
            continue
        items.append(dict(rid=rid, system=system_of(rid), kind=kind, find=f, reme=r, veri=v, ev=ev))
    return items


def not_applicable(self, cid):
    c = self.cases[cid]
    return self.na[cid]


def decide(self, cid):
    if self.not_applicable(cid):
        return "NOT_APPLICABLE", []
    return build_steps(self._items(cid))


def build_steps(items):
    """Assemble the ordered steps. A COMPLETE case may only contain verification steps that cite evidence of the
    compliant state, so a record with no eligible evidence cannot be verified and is left out (never invented)."""
    if not any(i["find"] for i in items):
        items = [i for i in items if i["ev"]]
    violations = [i for i in items if i["find"]]
    status = "INCOMPLETE" if violations else "COMPLETE"
    steps = []
    key = lambda i: (i["system"], i["rid"])
    if status == "INCOMPLETE":
        for op in FIND_ORDER:
            for i in sorted((x for x in violations if FIND_OP[x["find"]][0] == op), key=key):
                steps.append(("FINDING", i["system"], i["rid"], op, FIND_OP[i["find"]][1], i["ev"]))
        for op in REME_ORDER:
            for i in sorted((x for x in violations if x["reme"] == op), key=key):
                steps.append(("REMEDIATION", i["system"], i["rid"], op, STATE_OF[op], ""))
    for op in VERI_ORDER:
        for i in sorted((x for x in items if x["veri"] == op), key=key):
            steps.append(("VERIFICATION", i["system"], i["rid"], op, STATE_OF[op], "" if status == "INCOMPLETE" else i["ev"]))
    out = [dict(step_no=n + 1, phase=p, system_id=s, resource_id=r, operation=o, state=st, evidence_id=e)
           for n, (p, s, r, o, st, e) in enumerate(steps)]
    return status, out


Engine._items = _items
Engine.not_applicable = not_applicable
Engine.decide = decide
