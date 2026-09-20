# QINAI Bad Outputs Quarantine Schema v0.1

Status: offline quarantine schema. Quarantine data must never directly enter SFT Gold.

## Required JSONL Fields

- `id`: stable bad-output id.
- `prompt`: original prompt if safe to retain.
- `raw_bad_output`: raw visible bad output, redacted if needed.
- `source_log_reference`: audit/report/log path and timestamp if available.
- `failure_type`: concise failure label.
- `classification`: `P0`, `P1`, or `P2`.
- `usable_as_dpo_rejected`: boolean.
- `redaction_applied`: boolean.
- `review_status`: `new`, `triaged`, `approved_for_dpo_rejected`, `discarded`.
- `notes`: reviewer notes.

## Rules

- Bad outputs must never directly enter SFT Gold.
- Any prompt/internal/token/path leakage must be redacted before data use.
- P0 samples require owner review before becoming DPO rejected examples.
- Quarantine is offline only and is not runtime memory.