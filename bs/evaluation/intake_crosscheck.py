#!/usr/bin/env python3
"""Corroboration only (not used for decisions): compare the text-based NOT_APPLICABLE set with the privacy-intake
CLASSIFY_REQUEST activity rows. Rows are matched by calendar day of the case's reported_at and one-to-one by order."""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from audit.intent import deletion_intent  # noqa: E402

DS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "dataset")


def main():
    cases = list(csv.DictReader(open(os.path.join(DS, "deletion_requests.csv"), encoding="utf-8")))
    cls = [a for a in csv.DictReader(open(os.path.join(DS, "system_activity.csv"), encoding="utf-8")) if a["event_type"] == "CLASSIFY_REQUEST"]
    na = [c for c in cases if not deletion_intent(c["request_text"])]
    days = sorted(a["event_time"][:10] for a in cls)
    hit = sum(1 for c in na if c["reported_at"][:10] in days)
    others = sum(1 for c in cases if deletion_intent(c["request_text"]) and c["reported_at"][:10] in days)
    print("text-based NOT_APPLICABLE cases:", len(na))
    print("CLASSIFY_REQUEST activity rows:", len(cls))
    print("NOT_APPLICABLE cases whose reported day has an intake non-deletion row:", hit)
    print("(deletion cases share those days too: %d, so day-matching alone is only weak corroboration)" % others)


if __name__ == "__main__":
    main()
