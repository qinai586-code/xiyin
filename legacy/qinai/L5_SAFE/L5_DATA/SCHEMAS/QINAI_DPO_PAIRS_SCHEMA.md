# QINAI DPO Pairs Schema v0.1

Status: offline preference-data schema. DPO pairs are not runtime memory and must not be injected into C2 or C5.

## Required JSONL Fields

- `id`: stable pair id.
- `prompt`: evaluation or real user prompt.
- `chosen`: preferred Qina-style reply.
- `rejected`: rejected reply.
- `reason`: concise reason for preference.
- `tags`: array such as `language_lock`, `memory_boundary`, `identity`, `persona_density`, `brevity`.
- `source_reference`: source report/log/manual review reference.
- `p0_p1_p2`: highest relevant classification.
- `approved_by_owner`: boolean; must be true before training use.

## Rules

- `chosen` must be safe and persona-aligned.
- `rejected` may come from bad model output, but must be redacted if it contains secrets or internal data.
- P0 failures may be used as rejected examples only after quarantine review.
- DPO data must never directly approve memory or write `passed`.