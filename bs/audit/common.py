"""Shared constants and identifier helpers."""
import hashlib
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
UID_RE = re.compile(r"\buser_\d+\b")
HASH_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")

# resource-id prefix -> (system_id, record kind)
PREFIXES = [
    ("account_", "account_service", "ACCOUNT"),
    ("search_", "search_service", "SEARCH"),
    ("analytics_", "analytics_platform", "ANALYTICS"),
    ("support_", "support_platform", "SUPPORT"),
    ("export_", "export_service", "EXPORT"),
    ("data_flow_", "integration_service", "FLOW"),
    ("backup_", "backup_service", "BACKUP"),
    ("audit_record_", "security_service", "AUDIT"),
    ("tombstone_", "identity_service", "TOMBSTONE"),
    ("marketing_", "marketing_platform", "MARKETING"),
    ("object_", "object_storage", "OBJECT"),
    ("legal_", "legal_service", "LEGAL"),
]


def kind_of(rid):
    for p, sysid, kind in PREFIXES:
        if rid.startswith(p):
            return kind
    return None


def system_of(rid):
    for p, sysid, kind in PREFIXES:
        if rid.startswith(p):
            return sysid
    return None


def sha256_email(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def ids_in(*values):
    """Extract normalised identifiers (emails, user ids, sha256 hashes) from arbitrary values."""
    out = set()
    for v in values:
        if v is None:
            continue
        s = str(v)
        for m in EMAIL_RE.findall(s):
            out.add(m.lower())
        for m in UID_RE.findall(s):
            out.add(m)
        for m in HASH_RE.findall(s):
            out.add(m.lower())
    return out


def phone_key(p):
    if not p:
        return None
    d = re.sub(r"\D", "", str(p))
    return "tel:" + d if len(d) >= 7 else None
