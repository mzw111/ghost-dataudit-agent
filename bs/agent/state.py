"""Shared state used by agent tools."""
import csv
import os

from ..audit.engine import Engine


class AgentState:
    """Load the audit engine and request cases once for tool calls."""

    def __init__(self, dataset_dir):
        self.dataset_dir = dataset_dir
        self.engine = Engine(dataset_dir)
        cases_path = os.path.join(dataset_dir, "deletion_requests.csv")
        with open(cases_path, newline="", encoding="utf-8") as fh:
            self.cases = {row["case_id"]: row for row in csv.DictReader(fh)}
        self.engine.prepare(list(self.cases.values()))
