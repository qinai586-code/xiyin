# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Repository scope

This workspace is a flat snapshot of the Qinai L2 central runtime rather than the full deployed filesystem. Many scripts hardcode production paths under `C:\L0_RUNTIME\...` and `D:\...`; treat those as deployment targets, not paths that exist inside this checkout.

The workspace also contains an embedded Python environment under `QINAI_SIDECAR_GPU/PY_ENV/`. Ignore files inside that virtual environment when analyzing project structure or searching for entrypoints.

## Important project rules

Derived from [qina_agent_rules.md](qina_agent_rules.md):

- Preserve the L0/L1/L2/L3/L5 zero-trust layering. The core request path is `C1 -> C3 -> C2 -> C5 -> C4 -> C6 -> L5`; changes should keep that order intact.
- L2 changes are expected to be minimal, localized hardening rather than architectural rewrites.
- Do not introduce code that directly writes to L1 `passed` memory or bypasses the main chain by calling C5 directly from sidecars.
- Be careful with scripts that reference protected runtime areas such as `C:\L0_RUNTIME\L0_MOTHER`, `C:\L0_RUNTIME\L1_MEMORY\passed`, or model files on `D:\...`; those references describe production boundaries.
- The rules file asks for preview/impact analysis before modifications. Follow that when making non-trivial code changes in this repo.

## Common commands

This repository does not include a packaging file, test runner config, or lint config. Development is script-oriented.

- Run the central interactive loop: `python L0_RUNTIME/L2_CENTRAL/L2_MAIN/l2_central.py`
- Run the local GPU sidecar HTTP service: `python QINAI_SIDECAR_GPU/gpu_server.py`
- Run individual module smoke checks:
  - `python L0_RUNTIME/L2_CENTRAL/C1_Auth/c1_gatekeeper.py`
  - `python L0_RUNTIME/L2_CENTRAL/C2_MEMORY/c2_retrieve.py`
  - `python L0_RUNTIME/L2_CENTRAL/C4_OUTPUT_CHECK/c4_verify.py`
  - `python L0_RUNTIME/L2_CENTRAL/C6_WRITEBACK/c6_submit.py`
  - `python L0_RUNTIME/L2_CENTRAL/L2_MAIN/qinai_security_check.py`
  - `python L0_RUNTIME/L2_CENTRAL/C5_LLM_CALL/script/p1_hash_generator.py`
- Run Phase 1 governance tools:
  - `python L0_RUNTIME/L5_SAFE/ADMIN_TOOLS/memory_review_tool.py`
  - `python L0_RUNTIME/L5_SAFE/ADMIN_TOOLS/snapshot_tool.py`
  - `python L0_RUNTIME/L5_SAFE/ADMIN_TOOLS/rollback_tool.py`
- Syntax-check the whole snapshot without executing runtime side effects: `python -m compileall L0_RUNTIME QINAI_SIDECAR_GPU *.py`
- Syntax-check a single file:
  - `python -m py_compile L0_RUNTIME/L2_CENTRAL/L2_MAIN/l2_central.py`
  - `python -m py_compile QINAI_SIDECAR_GPU/gpu_server.py`

There is no in-repo command for linting, pytest, or running a single formal unit test because no such tooling/config is present in this snapshot.

## High-level architecture

### Runtime orchestration

`L0_RUNTIME/L2_CENTRAL/L2_MAIN/l2_central.py` is the system entrypoint and coordinator. On startup it:

- mounts hardcoded module search paths for the deployed L2 runtime
- imports C1-C6 modules plus audit helpers
- probes the GPU sidecar at `http://127.0.0.1:11434/generate`
- optionally loads sidecar modules from an external `C7_PLUGINS/manifest.json`
- exposes `submit_to_chain()` as the only approved programmatic entrypoint for sidecars
- runs an interactive terminal loop that sends user input through the full chain

The core execution flow in `_run_chain()` is:

1. sanitize input through `utils_guard`
2. re-check runtime permissions with C1
3. block unsafe input with C3
4. recall long-term memory with C2, gated by an extra relevance threshold in L2
5. merge short-term memory and recalled memory into a prompt via C5 persona prompt generation
6. send the prompt to the local GPU sidecar through C5
7. validate/style-correct the model output through C4
8. append short-term memory and, for interactive traffic only, persist to L1 wait-check through C6
9. write audit output through L5 or the G3 fallback logger

### Module responsibilities

- `L0_RUNTIME/L2_CENTRAL/C1_Auth/c1_gatekeeper.py`: zero-trust runtime gate. Validates the current OS user, working directory, and free disk space; failure exits immediately.
- `L0_RUNTIME/L2_CENTRAL/C2_MEMORY/c2_retrieve.py`: file-backed memory retrieval over the L1 memory store. It uses keyword scoring plus file mtime weighting instead of a vector database.
- `L0_RUNTIME/L2_CENTRAL/C3_INPUT_GUARD/c3_filter.py`: input blocklist filter.
- `L0_RUNTIME/L2_CENTRAL/C4_OUTPUT_CHECK/c4_verify.py`: output/persona enforcement layer.
- `L0_RUNTIME/L2_CENTRAL/C5_LLM_CALL/script/c5_persona_prompt.py`: builds the final prompt, sanitizes user/memory text, and verifies the signed external P1 persona constitution file before loading it.
- `L0_RUNTIME/L2_CENTRAL/C5_LLM_CALL/script/c5_llm_gatekeeper.py`: thin HTTP client for the local inference sidecar.
- `L0_RUNTIME/L2_CENTRAL/C6_WRITEBACK/c6_submit.py`: writeback gate that only persists approved dialogue into L1 `wait_check`, with red-line and fact-injection rejection.
- `QINAI_SIDECAR_GPU/gpu_server.py`: local Flask sidecar that loads a GGUF model through `llama_cpp` and exposes `/generate`.
- `L0_RUNTIME/L2_CENTRAL/L2_MAIN/utils_guard.py`: shared hardening helpers used by L2 before/after the main chain, including sanitization and audit-bridge helpers.
- `L0_RUNTIME/L5_SAFE/l5_audit_logger.py`: primary structured audit logger; L2 falls back to G3 append-only logging when L5 is unavailable.

### Memory model

The system uses two context layers:

- short-term memory kept in-process in `SHORT_TERM_MEMORY` inside `l2_central.py`
- long-term memory retrieved from filesystem text files by C2 from L1 `passed`

L2 deliberately adds a second relevance gate before injecting recalled memory into prompts, so C2 returning text does not guarantee it reaches C5.

Writeback is intentionally asymmetric:

- C6 can only write candidate memories into L1 `wait_check`
- governance tooling is responsible for approving or rejecting those files before anything reaches L1 `passed`
- `L0_RUNTIME/L5_SAFE/ADMIN_TOOLS/memory_review_tool.py`, `L0_RUNTIME/L5_SAFE/ADMIN_TOOLS/snapshot_tool.py`, and `L0_RUNTIME/L5_SAFE/ADMIN_TOOLS/rollback_tool.py` implement the manual review/snapshot/restore loop used for Phase 1 governance

### Persona and safety model

Persona integrity is enforced at multiple points instead of in one place:

- C3 blocks disallowed user inputs before they touch memory/prompting
- C5 sanitizes prompt inputs and verifies the external signed persona file
- the GPU sidecar is expected to receive a fully structured prompt and only generate the completion
- C4 rejects or soft-rewrites outputs that violate persona/style rules
- `utils_guard.check_c4_rules_for_c6()` is the bridge check before C6 writeback
- C6 prevents unsafe or fabricated responses from being written back into memory

That layered enforcement is the key design idea of this codebase.

### Sidecars and deployment boundaries

There are two different extension mechanisms in this snapshot:

- the GPU sidecar (`QINAI_SIDECAR_GPU/gpu_server.py`), which is the local inference service called by C5
- optional C7 sidecars declared in `C:\L0_RUNTIME\L2_CENTRAL\C7_PLUGINS\manifest.json`, which are started by `l2_central.py` after a manifest-level permission check

Sidecars are expected to integrate through `submit_to_chain()` rather than touching C5 or L1 directly.

### Configuration files that matter

- `L0_RUNTIME/module_config.json`: canonical list of required vs optional L2 modules and the module search path layout expected by the runtime.
- `hardware_profile.json`: local-only hardware/runtime policy for context window, generation limits, memory write policy, and the zero-trust constraints expected by the governance tooling.

## External/runtime dependencies to keep in mind

The snapshot relies on environment-specific resources that are not included here:

- Windows accounts such as `SJ_Run` / `SJ_Admin`
- deployed runtime directories under `C:\L0_RUNTIME` and `D:\L0_RUNTIME`
- a local GGUF model file for `QINAI_SIDECAR_GPU/gpu_server.py`
- optional `l5_audit_logger` and external C7 plugin manifest/runtime files

When editing code in this repo, distinguish between logic that is present here and deployment assets that only exist on the target machine.

## Runtime-aligned hardening notes (2026-04-22)

The current runtime-aligned remediation adds several enforcement details that should be preserved in future changes:

- P1 loader filtering in `L0_RUNTIME/L2_CENTRAL/C5_LLM_CALL/script/c5_persona_prompt.py` must drop governance header lines that begin with box-drawing characters and must strip structural lock header tags before any P1 text is injected into the prompt. The current runtime filters `╔╗╚╝║═╠╣╦╩╬`-style header artifacts and strips inline markers such as `[LOCK-L0]`, `[NEW-PE]`, and `🔒`.
- Prompt-language steering must remain plain instruction text. Leakable structural tags such as `[LANG]` are not valid prompt content and must not be introduced as visible prompt sections or output-facing control markers.
- GPU sidecar stop-token rules must include both half-width and full-width caller delimiters, plus delimiter/tag-related tokens that prevent template bleed-through. The current runtime stops on `主理人:`, `主理人：`, `====================`, `[LANG]`, `<|USER|>`, `</|USER|>`, `<|PERSONA_START|>`, and `<|PERSONA_END|>`.
- Output sanitization is intentionally layered and must stay layered rather than being collapsed into one place: (1) P1 source filtering in C5, (2) pre-check sanitization in C4, and (3) fallback output sanitization inside the GPU sidecar before the final reply is returned.


