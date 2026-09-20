# QINAI Phase 3 Eval Runner Hygiene Plan v0.1

Status: documentation-only hygiene plan. This is not an eval runner implementation and must not be executed as model evaluation.

## 1. Purpose

This plan defines the minimum hygiene requirements that must be satisfied before any Phase 3 model evaluation is implemented or run. It exists because prior live-eval attempts showed UTF-8 prompt corruption, L2 heartbeat contention, auth/channel handling risk, and invalid evaluator evidence.

## 2. UTF-8 Safety

- Probe text must be read from UTF-8 files, not passed as Chinese/Japanese literals through PowerShell command-line arguments.
- Input files, output logs, result JSON/JSONL, and markdown reports must be written with explicit UTF-8.
- The runner must preserve Chinese and Japanese prompts end-to-end.
- If any prompt, runtime log, or result contains corruption such as `????`, mojibake, or replacement-character damage, the run must stop immediately.
- Any corrupted run is rejected as evidence and must not be used for model comparison.

## 3. Heartbeat Safety

- Do not tight-loop poll the L2 heartbeat file.
- Perform one readiness check before a run starts.
- During probe execution, heartbeat checks must be low-frequency and must not contend with worker atomic heartbeat writes.
- If heartbeat `stage=failed`, `ready=false`, or `chat_ready=false`, the runner must stop immediately.
- Do not continue sending probes after heartbeat failure.
- Do not classify model quality from a run blocked by L2 heartbeat/channel failure.

## 4. Route Integrity

- Future eval may use full L2 path only after owner approval.
- Direct C5 calls are prohibited.
- Direct GPU `/generate` scoring is prohibited.
- C6 or `passed` write paths must not be invoked by the evaluator.
- Sidecar direct memory access is prohibited.
- The route used by each probe must be logged and must be verifiable as approved L2 interactive route.

## 5. Channel Handling

- The runner must correctly read, decode, and use the approved L2 chat channel.
- `authkey_b64` must be decoded exactly once using the expected base64 format.
- Wrong authkey decoding, missing channel, malformed channel, or unverified channel means the result is invalid.
- Each probe must be sent through the approved interactive/L2 route only.
- Channel verification failure must stop the run rather than falling back to mock echo, direct C5, or direct GPU calls.

## 6. Logging Requirements

For each probe, the future runner must record:

- raw input prompt;
- visible reply after C4;
- expected language;
- P0/P1/P2 classification;
- latency;
- C4 fallback/rewrite status when available;
- route used;
- error state;
- whether the result is accepted or rejected as evidence.

Logs must clearly distinguish model failure, C4 repair/fallback, transport failure, heartbeat failure, and evaluator hygiene failure.

## 7. Stop Conditions

The runner must stop immediately if any of the following occurs:

- UTF-8 corruption is detected;
- L2 heartbeat fails;
- route cannot be verified as full L2;
- any probe would bypass C5/C4/C6;
- any write to `passed` is attempted;
- channel/authkey handling is invalid;
- evaluator output cannot be trusted as evidence.

## 8. Phase Boundary

- This document is not an eval runner implementation.
- Core 16 eval must not be run in this phase.
- No model eval is approved by this document.
- Owner approval is required before implementing any runner.
- Owner approval is required before running any eval.
- This document must not be injected into C2 memory or C5 prompt.
- This document must not change runtime behavior.

## 9. Minimum Acceptance For A Future Runner

A future Phase 3 runner plan or implementation must demonstrate:

- UTF-8 clean probe ingestion;
- no PowerShell command-line mojibake path for non-ASCII prompt text;
- no heartbeat tight-loop polling;
- verified L2 chat channel handling;
- full L2 route only;
- no direct C5/GPU scoring;
- no `passed` writes;
- structured per-probe evidence acceptance/rejection fields.

