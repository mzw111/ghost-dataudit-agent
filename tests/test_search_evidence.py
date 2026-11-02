import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "bs"))

from agent import AgentState, search_evidence


class SearchEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        dataset = self.temp_dir.name
        self._write_csv("system_activity.csv", [
            "event_type", "resource_id", "details", "target_system",
            "reported_result", "event_time",
        ], [])
        self._write_csv("evidence_files.csv", [
            "file_id", "captured_at", "file_path", "origin",
        ], [["evidence_1", "2026-01-02T00:00:00Z", "evidence.json", "test"]])
        self._write_csv("deletion_rules.csv", ["rule_id"], [])
        self._write_csv("user_identities.csv", [
            "user_id", "email", "email_hash", "phone",
        ], [["user_1", "person@example.com", "hash", ""]])
        self._write_csv("user_audit_log.csv", [
            "user_id", "field_name", "old_value", "new_value",
        ], [])
        self._write_csv("deletion_requests.csv", [
            "case_id", "email", "request_text", "requested_at",
            "reported_status", "reported_at", "audit_at",
        ], [["case_1", "person@example.com", "delete my data",
               "2026-01-01T00:00:00Z", "COMPLETE",
               "2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z"]])
        with open(os.path.join(dataset, "evidence.json"), "w", encoding="utf-8") as fh:
            json.dump({"records": [{
                "resource_id": "account_001",
                "email": "person@example.com",
                "observed_at": "2026-01-02T12:00:00Z",
            }]}, fh)
        self.state = AgentState(dataset)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_csv(self, name, headers, rows):
        with open(os.path.join(self.temp_dir.name, name), "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            writer.writerows(rows)

    def test_valid_query_returns_evidence(self):
        result = search_evidence("case_1", "account_001", self.state)
        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"][0]["evidence_id"], "evidence_1")
        self.assertEqual(result["matches"][0]["timestamp"], "2026-01-02T00:00:00Z")

    def test_invalid_case_returns_controlled_error(self):
        result = search_evidence("missing", "account", self.state)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CASE_NOT_FOUND")
        self.assertEqual(result["matches"], [])

    def test_no_match_is_empty(self):
        result = search_evidence("case_1", "does-not-exist", self.state)
        self.assertEqual(result, {"ok": True, "matches": []})


if __name__ == "__main__":
    unittest.main()
