"""Identity resolution: current + historical emails, phones and hashes per stable user_id."""
import csv
import os
from collections import defaultdict

from .common import phone_key, sha256_email


class Identities:
    def __init__(self, dataset_dir):
        self.users = {}
        self.emails = defaultdict(set)    # email -> {user_id}
        rd = lambda n: list(csv.DictReader(open(os.path.join(dataset_dir, n), newline="", encoding="utf-8")))
        for r in rd("user_identities.csv"):
            self.users[r["user_id"]] = dict(r, hist=[], old_emails=set(), old_phones=set())
        for a in rd("user_audit_log.csv"):
            u = self.users.get(a["user_id"])
            if not u:
                continue
            u["hist"].append(a)
            if a["field_name"] == "email":
                u["old_emails"].add(a["old_value"].lower())
                u["old_emails"].add(a["new_value"].lower())
            elif a["field_name"] == "phone":
                u["old_phones"].update([a["old_value"], a["new_value"]])
        for uid, u in self.users.items():
            for e in {u["email"].lower()} | u["old_emails"]:
                self.emails[e].add(uid)

    def resolve(self, email):
        """Return user_id for a request email (current first, then historical)."""
        e = email.strip().lower()
        cands = self.emails.get(e, set())
        cur = [u for u in cands if self.users[u]["email"].lower() == e]
        pick = cur or sorted(cands)
        return pick[0] if pick else None

    def identifiers(self, uid):
        u = self.users[uid]
        ems = {u["email"].lower()} | u["old_emails"]
        ids = {uid} | ems | {sha256_email(e) for e in ems} | {u["email_hash"].lower()}
        for p in {u["phone"]} | u["old_phones"]:
            k = phone_key(p)
            if k:
                ids.add(k)
        return ids
