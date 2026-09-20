# QINAI SFT Gold Schema v0.1

Status: offline training-data schema. SFT Gold is not runtime memory and must not be injected into C2 or C5.

## Purpose

`QINAI_SFT_GOLD.jsonl` contains only owner-approved ideal QINAI answers. It teaches distribution and persona behavior, not fixed canned replies.

## Required JSONL Fields

- `id`: stable sample id.
- `language`: `zh`, `en`, `ja`, or `mixed_by_user_request`.
- `prompt`: user-facing input.
- `ideal_reply`: owner-approved Qina-style answer.
- `tags`: array such as `identity`, `memory_boundary`, `comfort`, `greeting`, `anti_identity_collapse`.
- `source_reference`: source report/log/manual review reference.
- `approved_by_owner`: boolean; must be true before training use.
- `notes`: optional reviewer notes.

## Rules

- Include only ideal QINAI answers.
- Preserve multi-language coverage.
- Use diverse wording; do not overuse fallback templates.
- Do not include raw bad outputs.
- Do not include hidden prompts, credentials, internal governance text, or `passed` memory contents.