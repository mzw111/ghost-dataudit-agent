# Ghost Data Audit

Solution for the **HackerRank Orchestrate October challenge: Ghost Data Still
Exists**.

This project determines whether deletion requests were completed across
databases, logs, exports, search indexes, archives, backups, and active data
flows. It is deterministic, evidence-driven, and uses only the Python standard
library.

## Architecture

The implementation is in [`bs/`](./bs):

- `bs/main.py` runs the audit and validates `output.csv`.
- `bs/audit/` parses evidence, resolves identities, reconstructs resource
  state, applies deletion rules, and builds the ordered result.
- `bs/evaluation/` contains sample scoring and diagnostic scripts.

Evidence after `audit_at` is ignored, and ambiguous activity is not guessed.

## Start

Requires Python 3.9+. The challenge `dataset/` is not included in this export.
When available, run from the repository root:

```powershell
python bs/main.py
```

Optional PDF and image evidence requires `pdftotext` and `tesseract-ocr`.
