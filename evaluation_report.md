# Evaluation report - Ghost Data Still Exists

Ground truth available to participants is limited to the 32 public samples (`dataset/sample_output.csv`).
Nothing below is a claim about hidden-label accuracy on the 518 target cases. The engine is deterministic and makes no
model calls. All numbers were measured by running the scripts named here on the final code.

Reproduce: `python3 code/main.py`, `python3 code/evaluation/evaluate.py`, `python3 code/evaluation/custom_cases.py`,
`python3 code/evaluation/context_impact.py`, `python3 code/evaluation/intake_crosscheck.py`.

## 1. Public-sample metrics (32 cases)

| Metric | Original submission | After 2nd review | Final (this run) |
|---|---|---|---|
| Case-level status accuracy | 32/32 = 100.0% | 100.0% | 32/32 = 100.0% |
| Row accuracy (status + full steps array exact) | 29/32 = 90.6% | 22/32 = 68.8% | 19/32 = 59.4% |
| Sequence accuracy (steps identical, incl. order) | 29/32 = 90.6% | 68.8% | 19/32 = 59.4% |
| Step-level recall | 98.4% | 94.3% | 91.7% |
| Step-level precision | 99.5% | 100.0% | 100.0% |
| Field-level accuracy (positional, 7 fields/step) | 97.7% | 88.5% | 85.3% |

The drop from the original numbers is deliberate: the original 90.6% relied on guessed pairings that happened to match
the public answers. The final code emits no step it cannot support from participant-visible evidence (precision 100%;
every loss is an omitted step, not a wrong one). The code was developed while looking at these 32 cases, so even the
final numbers are development-set numbers.

The last drop (22 -> 19 rows) comes from the final temporal fix (section 3, item 6): retained audit records whose only
observations were captured after `audit_at` are no longer verified. Statuses did not change.

## 2. Remaining sample differences (13 rows; the 10 below plus 3 from the temporal fix)

| Cases | Missing step | Cause | Verdict |
|---|---|---|---|
| 25, 26, 27, 28, 03 | `VERIFY_RECORD_ANONYMIZED` for an anonymized analytics record | The record carries no identifier; several same-day cases and records fit equally. Matching by case order/time would be a guess. | Genuine ambiguity, omitted |
| 23, 28, 29 | account `VERIFY_RECORD_ABSENT` | Linked only via `system_activity.csv`; same-status cases share the same candidate DELETE activities (e.g. 28 and 29 both fit `account_5482`/`account_7012`). | Genuine ambiguity, omitted |
| 04 | `account_004` | The id exists nowhere in participant data. | Would be an invented resource |
| 18, 20 | `audit_record_6645` / `audit_record_5569` | These ids appear in no participant-visible file. | Unrecoverable |
| 3 further sample cases | `VERIFY_RECORD_PRESENT` for a security audit record | The record is observed only in evidence captured after the case's `audit_at` (e.g. `audit_record_4902` for case_09, first seen in a file captured 2026-09-18 vs audit_at 2026-09-16). The gold answers include it; the temporal contract forbids using later evidence to establish a state at `audit_at`. | Deliberately omitted (not reverted to raise the score) |

## 3. Behaviour of the implemented code, per review item

1. **Deletion intent / `CLASSIFY_REQUEST`** (`engine.py`): authorisation is decided from `request_text` only
   (`Engine.na`, built from `intent.deletion_intent`). Intake `CLASSIFY_REQUEST` rows are system claims and influence
   neither `NOT_APPLICABLE` nor account assignment; the dead attribute that collected them was removed. Non-deletion cases
   are excluded from account and analytics assignment. Diagnostic only (`intake_crosscheck.py`): 10 text-based
   NOT_APPLICABLE cases, 10 intake rows, all 10 cases share a reported day with an intake row (17 deletion cases also share
   those days, so this is weak corroboration). Test C7 poisons the intake set and checks a deletion request stays a deletion.
2. **Identity resolution** (`_assign_accounts`, `_assign_anon_analytics`): no pairing by case order or time. Order of
   evidence now used: (a) accounts observed with the person's identifiers (current/historical emails, phones, sha256 hashes,
   user_id), preferring the one whose DELETE activity fits the case window; (b) DELETE activities with matching reported
   result inside the window and **not before `requested_at`** (new timestamp constraint), skipping accounts owned by other
   known users; (c) elimination; (d) **one account per person**: claims are keyed by user, so repeat requests by the same
   person reuse their account (fixes a bug where a second request by the same user was refused the account the first one
   held); (e) the `account_NNN`<->`user_NN` convention only when the id is visible in participant data and not owned by
   someone else. Anything still ambiguous gets no activity-derived account (recorded in `Engine.account_ambiguous`): 132 of 508
   deletion cases in the 518 run (131 ambiguous among 2+ candidates). Anonymized analytics are assigned only when exactly
   one candidate case and one record fit the day, and a record owned by any known user (by any identifier) is never a
   candidate (this second condition was a bug: records of other people could be offered).
3. **Output validation** (`audit/output.py`, `main.py`): the validator enforces exact header and 3 columns; unique, sorted case ids
   equal to the request set, and exactly 518 rows for the full request file; JSON array; exactly the 7 step fields with int
   `step_no`; consecutive numbering; valid status; legal phase/operation/state triples; phase order, operation precedence,
   then ascending `system_id` and `resource_id`; duplicate steps; empty `evidence_id` for remediation and INCOMPLETE
   verification; required evidence for findings and COMPLETE verification; evidence ids valid as manifest `file_id`,
   `activity_id` or `audit_id`; no citation captured after `audit_at`; NOT_APPLICABLE empty; COMPLETE verification-only and
   non-empty; INCOMPLETE has all three phases, findings equal remediated resources, each verified. `main.py` adds two
   evidence cross-checks: a cited file must mention or cover the cited resource, and completeness (every linked resource
   whose latest eligible state violates policy has a finding, active flows and restore risks included, and every linked
   retained audit/legal record with eligible evidence has a `VERIFY_RECORD_PRESENT`). The file is re-validated by a separate
   call outside `run()` in the final check: 0 problems.
4. **Sample contamination** (`main.py`, `Engine.prepare`): sample requests are context-only and off by default
   (`--sample-context`); `sample_output.csv` is read only by `evaluate.py`. Before the fixes, enabling them changed 2 of 518
   rows: `case_61` (same person as sample `case_07`, `user_07`) lost `account_007` because the claim was exclusive per case
   rather than per person, and `case_51` gained `analytics_2265` because a record owned by a sample user was previously
   counted as an anonymous candidate. Both are fixed; `context_impact.py` now reports 0 changed rows, and test C9 asserts it.
5. **Evidence and policy**: re-checked against the data. No email maps to two users and all 100 requests using a historical
   email resolve; no snapshot holds conflicting states for one resource at one time (replica drift appears as presence in a
   replica table only, treated as present); no retention date is expired at any audit time; tombstones are redacted, never
   deleted; flows and backups produce findings. `email_delivery_*` and `cache_*` resources appear only in
   `system_activity.csv` (never in evidence), so no state can be established for them and no step is emitted.
   Support-replica contact lookups (`deletion_marker_check marker_found=false`) are treated as a record still present.
   COMPLETE cases omit verification steps for records with no eligible evidence (never emitted with an empty `evidence_id`).

6. **Temporal contract for retained records** (`Engine._items`): a security-audit or legal-hold record is now verified
   only if an observation captured at or before `audit_at` shows it. Previously, when a record had no eligible observation
   the engine assumed it was still retained, using a link established by later evidence. That let future evidence determine
   a past state, so the assumption was removed. Effect on the 518 run: 121 `VERIFY_RECORD_PRESENT` steps for audit records
   and 1 for a legal hold were dropped, no status changed, nothing was added. Identity links from later evidence still
   decide *which* resources belong to a person; they never supply a state. Unresolved ambiguity: for those 122 records the
   engine cannot tell whether the record existed at `audit_at`, so it emits nothing. Test C10 checks both directions
   (case_09's record is not verified at its audit_at and is verified when audit_at is moved past the evidence capture).

## 4. Additional evaluation cases (manually authored, not organiser truth)

`code/evaluation/custom_cases.py`; expectations written by hand from the AGENTS.md contract. All 10 pass.

| # | Scenario | Result |
|---|---|---|
| C1 | Negative / multilingual / verification-phrased intent (6 texts) | PASS |
| C2 | Historical email resolves to the same user and status as the current email | PASS |
| C3 | `audit_at` before all evidence cites nothing | PASS |
| C4 | Cutoff between snapshots: no cited file captured after `audit_at` | PASS |
| C5 | Tombstone remediation is REDACT, never DELETE | PASS |
| C6 | Ambiguous accounts (case_28/case_29) are left unassigned | PASS |
| C7 | Poisoned intake CLASSIFY_REQUEST rows do not flip a deletion request | PASS |
| C8 | Validator rejects each of 10 contract-violating mutations, accepts the good row | PASS |
| C9 | Sample requests as pool context leave all 518 predictions unchanged | PASS |
| C10 | Retained record seen only after `audit_at` is not verified; it is once `audit_at` is later | PASS |

These are behavioural/structural checks, not accuracy measurements.

## 5. Full-dataset results (518 cases, no labels)

Validator problems: 0 (schema, evidence-support and completeness checks, plus an independent re-validation).
Distribution: 352 INCOMPLETE, 156 COMPLETE, 10 NOT_APPLICABLE. Compared with the original submission output: statuses
unchanged. Versus the original submission output the earlier review changed 194 rows (220 steps removed, 2 added); the
final temporal fix then changed 121 further rows (122 audit/legal-hold steps removed, 0 added). `context_impact.py`: 0 of 518
rows change when the sample requests join the pool.

## 6. Remaining limitations

- Where several same-window cases share candidates and no evidence separates them (131 cases for accounts, 43 days for
  anonymized analytics), the step is missing rather than guessed; expect lower recall on hidden cases, not wrong steps.
- Audit records whose ids appear in no participant file cannot be recovered.
- Retained audit/legal records seen only in evidence captured after `audit_at` are not verified (state at `audit_at` is not
  established); the public gold answers include such records, so recall on them is lower by design.
- Screenshot state comes from OCR and is coarse; shared-attachment ownership (rule_06) is modelled only via catalog links.
