# Ghost Data Audit

Deterministic, evidence-driven deletion-audit engine for checking whether data
remains across databases, logs, exports, search indexes, archives, backups,
and active data flows.

The implementation currently lives under [`bs/`](./bs). The name `ghost-data-audit`
is used for the project and its GitHub repository.

## Setup
- Python 3.9+ (standard library only; no pip packages).
- Optional system tools for PDF/screenshot evidence: `pdftotext` (poppler-utils) and `tesseract-ocr`. Without them the
  documents are skipped and accuracy drops for the few document-backed cases.
- No environment variables or credentials are needed.

## Run
The complete challenge dataset is not included in this repository export. When
`dataset/` is available, run from the repository root:

    python bs/main.py

This writes `output.csv` at the repository root and validates it (exit code 1
on any problem). Options: `--dataset DIR --cases CSV --output FILE` and
`--sample-context` (off by default).

## Evaluate
    python bs/evaluation/evaluate.py
    python bs/evaluation/custom_cases.py
    python bs/evaluation/context_impact.py
    python bs/evaluation/intake_crosscheck.py

The evaluation scripts require the challenge dataset and sample files.

## Architecture (`bs/audit/`)
- `logparse.py` - parser for 7 log layouts. `evidence.py` - SQL/JSON/log/txt/PDF/PNG -> uniform observations.
- `identity.py` - current + historical emails, phones, sha256 hashes per user_id.
- `engine.py` - resource linking, account resolution from activity, state at `audit_at`, policy treatment, step ordering.
- `intent.py` - multilingual deletion-intent rules. `output.py` - serializer and schema/ordering/evidence validator.

## Key rules
- Evidence captured after `audit_at` is ignored.
- Reported statuses and activity results are never treated as proof of state.
- The latest eligible observation of each resource decides its state.
- When activity evidence is ambiguous, the engine does not guess by case order or timing.

Accounts are tied per person, so a repeat request by the same user reuses the
same account. Sample requests do not influence the full prediction set.

## Repository hygiene

Generated outputs, local logs, datasets, caches, and virtual environments are
ignored by Git. Keep challenge-only data local and do not commit credentials
or private evidence files.
