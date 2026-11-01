"""Evidence extraction: turns every supported evidence format into uniform observations.

Observation: dict(file, cap, t, rid, state, ids, explicit, ctx)
  file  - manifest file_id           cap - manifest capture time (eligibility cutoff)
  t     - time the state was observed rid - resource id (prefix decides system/kind)
  state - PRESENT/ABSENT/IDENTIFIABLE/ANONYMIZED/REDACTED/ACTIVE/DISABLED/BLOCKED
  ids   - identifiers linking the record to a person (emails, user ids, hashes, phones)
Coverage: dict(file, cap, t, system, rids) - a snapshot that fully covers a system, so a
resource missing from it can be treated as absent when no explicit observation exists.
"""
import csv
import json
import os
import re
import sqlite3
from collections import defaultdict

from .common import ids_in, kind_of, phone_key, system_of
from .logparse import parse_file

RESULT_STATE = {"FOUND": "PRESENT", "NOT_FOUND": "ABSENT", "IDENTIFIABLE": "IDENTIFIABLE",
                "ANONYMIZED": "ANONYMIZED", "REDACTED": "REDACTED", "ACTIVE": "ACTIVE",
                "BLOCKED": "BLOCKED", "DISABLED": "DISABLED"}
SUBJECT_KEYS = ("lookup_key", "match_key", "scan_key", "subject_key", "subject_ref", "owner_key",
                "correlation_key", "customer_email", "customer_reference", "subject_reference", "email",
                "requester_email", "owner_email", "subject_selector", "matched_value", "user_id")
TRUE = ("true", "1", "yes")


class Evidence:
    def __init__(self, dataset_dir):
        self.dir = dataset_dir
        self.obs = defaultdict(list)       # rid -> [obs]
        self.cover = defaultdict(list)     # system -> [coverage]
        self.manifest = {}
        self.files_failed = []
        self.doc_hooks = []                # (file_id, text) for PDF/PNG documents
        self.links = defaultdict(set)      # rid -> identifiers asserted by data-catalog link events
        with open(os.path.join(dataset_dir, "system_activity.csv"), newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["event_type"] == "LINK_RESOURCE_IDENTITY":
                    self.links[r["resource_id"]] |= ids_in(r["details"])
        with open(os.path.join(dataset_dir, "evidence_files.csv"), newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                self.manifest[r["file_id"]] = r
        for fid, r in sorted(self.manifest.items()):
            path = os.path.join(dataset_dir, r["file_path"])
            try:
                self._load(fid, r["captured_at"], path)
            except Exception as exc:  # robust: one bad file must not stop the run
                self.files_failed.append((fid, repr(exc)))

    # ------------------------------------------------------------------ helpers
    def add(self, file, cap, t, rid, state, ids, ctx=None):
        if not rid or kind_of(rid) is None:
            return
        self.obs[rid].append(dict(file=file, cap=cap, t=t, rid=rid, state=state, ids=set(ids), ctx=ctx or {}))

    def add_cover(self, file, cap, t, system, rids):
        self.cover[system].append(dict(file=file, cap=cap, t=t, system=system, rids=set(rids)))

    # ------------------------------------------------------------------ dispatch
    def _load(self, fid, cap, path):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".sql":
            self._sql(fid, cap, path)
        elif ext == ".json":
            self._json(fid, cap, path)
        elif ext == ".log":
            self._log(fid, cap, path)
        elif ext == ".txt":
            self._txt(fid, cap, path)
        elif ext in (".pdf", ".png"):
            from .documents import read_document
            self._document(fid, cap, read_document(path))

    # ------------------------------------------------------------------ record semantics
    def _state_from_record(self, rid, rec, collection=""):
        k = kind_of(rid)
        g = lambda *ks: next((rec[x] for x in ks if rec.get(x) not in (None, "")), None)
        direct = [g("full_name", "name", "display_name", "requester_name"), g("email", "requester_email", "owner_email",
                  "customer_email"), g("phone", "requester_phone", "owner_phone"), g("email_hash")]
        if k == "ANALYTICS":
            return "IDENTIFIABLE" if any(rec.get(x) for x in ("user_id", "email", "phone", "email_hash", "customer_reference")) else "ANONYMIZED"
        if k == "SUPPORT":
            if collection == "ticket_attachments" or rec.get("file_name"):
                return "PRESENT"
            text = str(rec.get("message_text") or rec.get("message_excerpt") or "")
            ident = any(direct) or bool(ids_in(text))
            return "IDENTIFIABLE" if ident else "REDACTED"
        if k == "TOMBSTONE":
            return "IDENTIFIABLE" if any(direct) else "REDACTED"
        if k == "FLOW":
            return "ACTIVE" if str(rec.get("enabled")).lower() in TRUE else "DISABLED"
        if k == "BACKUP":
            return "ACTIVE" if str(rec.get("restore_allowed")).lower() in TRUE else "BLOCKED"
        if k == "EXPORT" and rec.get("download_available") is False:
            return "ABSENT"
        return "PRESENT"

    def _rec_ids(self, rec):
        vals = [v for k, v in rec.items() if v is not None and not isinstance(v, (dict, list))]
        out = ids_in(*vals)
        doc = rec.get("document")
        if isinstance(doc, dict):
            out |= ids_in(*[v for v in doc.values()])
        for pk in ("phone", "owner_phone", "requester_phone"):
            p = phone_key(rec.get(pk))
            if p:
                out.add(p)
        return out

    # ------------------------------------------------------------------ SQL snapshots
    def _sql(self, fid, cap, path):
        text = open(path, encoding="utf-8").read()
        m = re.search(r"Captured at:\s*(\S+)", text)
        snap_t = m.group(1) if m else cap
        db = sqlite3.connect(":memory:")
        db.executescript(text)
        tables = [r[0] for r in db.execute("select name from sqlite_master where type='table'")]
        scope = []
        if "snapshot_scope" in tables:
            scope = [r[0] for r in db.execute("select origin_system from snapshot_scope")]
        seen = defaultdict(set)
        for t in tables:
            if t == "snapshot_scope":
                continue
            cur = db.execute(f'select * from "{t}"')
            cols = [c[0] for c in cur.description]
            for row in cur.fetchall():
                rec = dict(zip(cols, row))
                collection = rec.get("collection_name", "")
                if "record_json" in rec:
                    inner = json.loads(rec["record_json"])
                    system = rec.get("origin_system")
                    rid = rec["resource_id"]
                    inner.setdefault("resource_id", rid)
                    rec = inner
                else:
                    rid = rec["resource_id"]
                    system = system_of(rid)
                    if "user_id" in rec and "customer_reference" not in rec:
                        rec["customer_reference"] = rec["user_id"]
                self.add(fid, cap, snap_t, rid, self._state_from_record(rid, rec, collection), self._rec_ids(rec),
                         dict(src="sql", table=t))
                if system:
                    seen[system].add(rid)
        covered = set(scope) | set(seen)
        for s in covered:
            self.add_cover(fid, cap, snap_t, s, seen.get(s, set()))
        db.close()

    # ------------------------------------------------------------------ JSON
    def _json(self, fid, cap, path):
        d = json.load(open(path, encoding="utf-8"))
        if "snapshots" in d:
            for s in d["snapshots"]:
                st = s.get("captured_at", cap)
                present = set()
                coll = s.get("collection", "")
                for r in s.get("records", []):
                    rid = r["resource_id"]
                    if coll == "operational_record_history":
                        self._tuple(fid, cap, r.get("recorded_at", st), r["system"], rid, r["result"],
                                    r.get("lookup_value"))
                        continue
                    present.add(rid)
                    self.add(fid, cap, st, rid, self._state_from_record(rid, r, coll), self._rec_ids(r),
                             dict(src="bundle", collection=coll))
                if coll != "operational_record_history":
                    self.add_cover(fid, cap, st, s["data_store"], present)
        elif "service_exports" in d:
            self._service_export(fid, cap, d)
        elif "records" in d and d["records"] and "record_type" in d["records"][0]:
            for r in d["records"]:
                self._tuple(fid, cap, r.get("recorded_at", cap), r["system"], r["resource_id"], r["result"],
                            r.get("subject_reference"))
        elif "records" in d:   # flat collections (analytics report, export jobs)
            t = d.get("captured_at", cap)
            for r in d["records"]:
                self.add(fid, cap, t, r["resource_id"], self._state_from_record(r["resource_id"], r), self._rec_ids(r),
                         dict(src="records"))

    def _tuple(self, fid, cap, t, system, rid, result, subject):
        state = RESULT_STATE.get(result, result)
        self.add(fid, cap, t, rid, state, ids_in(subject), dict(src="tuple", system=system))

    def _service_export(self, fid, cap, d):
        for svc, groups in d["service_exports"].items():
            for gname, recs in groups.items():
                for r in recs:
                    rid = r["resource_id"]
                    t = r.get("observed_at", cap)
                    k = kind_of(rid)
                    if gname == "profile_lookups":
                        prof = r.get("profile")
                        state = "ABSENT" if (prof is None or r.get("status_code") == 404) else "PRESENT"
                        ids = self._rec_ids(prof) if prof else set()
                    elif gname == "index_queries":
                        docs = r.get("hits", {}).get("documents", [])
                        state = "PRESENT" if r.get("hits", {}).get("total", 0) else "ABSENT"
                        ids = ids_in(r.get("query"))
                        for dd in docs:
                            ids |= self._rec_ids(dd)
                    else:
                        state = self._state_from_record(rid, r, gname)
                        ids = self._rec_ids(r)
                        if k == "EXPORT" and r.get("object_key") is None:
                            state = "ABSENT"
                    self.add(fid, cap, t, rid, state, ids, dict(src="export", group=gname))

    # ------------------------------------------------------------------ plain text handover
    def _txt(self, fid, cap, path):
        for ln in open(path, encoding="utf-8"):
            parts = [p.strip() for p in ln.lstrip("- ").split("|")]
            if len(parts) == 6 and parts[0][:2] == "20":
                self._tuple(fid, cap, parts[0], parts[1], parts[2], parts[4], parts[5])

    # ------------------------------------------------------------------ logs
    def _log(self, fid, cap, path):
        rows = parse_file(path)
        traces = defaultdict(list)
        for r in rows:
            if r["event"] == "record_lookup":
                kv = r["kv"]
                self._tuple(fid, cap, r["ts"], kv.get("system", ""), kv["resource_id"], kv["result"],
                            kv.get("subject_reference"))
            elif r["trace"]:
                traces[r["trace"]].append(r)
        for tr, evs in traces.items():
            subj = set()
            for e in evs:
                for k in SUBJECT_KEYS:
                    if e["kv"].get(k):
                        subj |= ids_in(e["kv"][k])
            for e in evs:
                self._log_event(fid, cap, e, subj)

    def _log_event(self, fid, cap, e, subj):
        kv = {k: (None if v in ("null", "None", "") else v) for k, v in e["kv"].items()}
        ev, t = e["event"], e["ts"]
        rid = kv.get("resource_id")
        if not rid:
            return
        ids = set(subj) | ids_in(*(kv.get(k) for k in SUBJECT_KEYS))
        if kv.get("phone"):
            p = phone_key(kv["phone"])
            if p:
                ids.add(p)
        k = kind_of(rid)
        state = None
        if ev in ("profile_lookup_completed", "contact_query_completed", "contact_lookup_completed"):
            ok = kv.get("http_status") == "200" or kv.get("rows") not in (None, "0")
            if kv.get("http_status") == "404" or kv.get("rows") == "0":
                ok = False
            state = "PRESENT" if ok else "ABSENT"
            if ev == "contact_lookup_completed":
                rid = rid  # marketing-style contact in analytics: treated as present record
        elif ev == "index_query_completed":
            state = "PRESENT" if kv.get("result") == "hit" and kv.get("total_hits", "1") != "0" else "ABSENT"
        elif ev in ("analytics_profile_read_completed",):
            state = self._state_from_record(rid, {x: kv.get(x) for x in ("email", "phone", "email_hash", "customer_reference")})
        elif ev == "analytics_profile_read":
            state = "IDENTIFIABLE" if kv.get("direct_identifiers", "0") != "0" or kv.get("email") or kv.get("phone") else "ANONYMIZED"
        elif ev == "analytics_identity_scan":
            state = "IDENTIFIABLE"
        elif ev in ("message_pii_scan",):
            state = "IDENTIFIABLE"
        elif ev == "attachment_pii_scan":
            state = "PRESENT"
        elif ev == "message_read":
            state = "IDENTIFIABLE" if ids_in(kv.get("message_text")) else "REDACTED"
        elif ev == "support_ticket_read_completed":
            state = self._state_from_record(rid, {x: kv.get(x) for x in ("requester_name", "requester_email", "requester_phone")})
        elif ev in ("connector_config_read_completed",):
            state = "ACTIVE" if kv.get("enabled") in TRUE else "DISABLED"
        elif ev in ("connector_config_loaded", "connector_heartbeat"):
            state = "ACTIVE" if kv.get("enabled") in TRUE else "DISABLED"
        elif ev == "restore_policy_read_completed":
            state = "ACTIVE" if kv.get("restore_allowed") in TRUE else "BLOCKED"
        elif ev == "restore_candidate_evaluated":
            state = "ACTIVE" if kv.get("eligible") in TRUE and kv.get("deletion_block") not in TRUE else "BLOCKED"
        elif ev == "restore_authorization_completed":
            state = "BLOCKED" if kv.get("decision") == "deny" else "ACTIVE"
        elif ev in ("export_metadata_read_completed", "export_download_check_completed"):
            state = "PRESENT" if kv.get("available") in TRUE else "ABSENT"
        elif ev == "audit_record_read_completed":
            state = "PRESENT"
        elif ev == "deletion_marker_check":
            state = "PRESENT"
        if state:
            self.add(fid, cap, t, rid, state, ids, dict(src="log", event=ev, contact=(ev == "contact_lookup_completed")))

    # ------------------------------------------------------------------ PDF / screenshot documents
    DOC_RID = re.compile(r"\b(account|search|analytics|support|export|marketing|object|tombstone|backup|audit_record|data_flow)[_ ](\d+)\b")

    def _document(self, fid, cap, text):
        """Business artifacts: a resource shown in a document exists at capture time. Identity comes from
        data-catalog link events, or from the document itself when it concerns exactly one resource."""
        rids = []
        for m in self.DOC_RID.finditer(text or ""):
            rid = "%s_%s" % (m.group(1), m.group(2))
            if rid not in rids:
                rids.append(rid)
        doc_ids = ids_in(text)
        for rid in rids:
            ids = set(self.links.get(rid, set()))
            if not ids and len(rids) == 1:
                ids = set(doc_ids)
            k = kind_of(rid)
            if k == "TOMBSTONE":
                state = "IDENTIFIABLE" if any("@" in i or len(i) == 64 for i in doc_ids if i not in ids) else "REDACTED"
            elif k == "ANALYTICS":
                state = "IDENTIFIABLE" if any("@" in i for i in ids | doc_ids) else "ANONYMIZED"
            elif k == "SUPPORT":
                state = "PRESENT"
            else:
                state = "PRESENT"
            self.add(fid, cap, cap, rid, state, ids, dict(src="document"))
