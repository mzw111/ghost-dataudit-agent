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

<<<<<<< HEAD
Optional PDF and image evidence requires `pdftotext` and `tesseract-ocr`.

## Agent evidence tool

The deterministic `search_evidence` tool is available from `bs.agent`:

```python
from agent import AgentState, search_evidence

state = AgentState("dataset")
result = search_evidence("case_001", "account", state)
```

An agent-facing adapter should expose only `case_id` and `query`; the backend
injects `AgentState`. Results contain parsed evidence IDs, timestamps, resource
IDs, and excerpts derived from the existing `Evidence` parser. Unknown cases
return a controlled error, while valid searches with no matches return an
empty `matches` list.
=======
Going to add LLM API soon to make it completely agentic.
>>>>>>> origin/main
