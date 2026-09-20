# QINAI Log-to-Dataset Pipeline v0.1

Status: offline pipeline plan. This pipeline must not run automatically against runtime memory.

## Flow

1. Collect candidate failures from G3/L5 audit logs, evaluation reports, and owner-marked examples.
2. Redact secrets, private paths, tokens, prompt internals, and memory contents not approved for dataset use.
3. Tag each sample as P0, P1, or P2.
4. Store raw bad samples in `BAD_OUTPUTS_QUARANTINE`.
5. Owner reviews and approves whether a sample may become DPO rejected data.
6. Create diverse ideal answers for SFT Gold only after owner approval.
7. Create DPO pairs from chosen/rejected pairs only after owner approval.
8. Run offline eval against model profiles before any deployment decision.
9. Return trained artifacts only through GPU sidecar model profiles.

## Non-Runtime Rule

- Eval/data files do not enter C2 memory.
- Eval/data files are not injected into C5 prompt.
- No dataset file may write to `passed`.
- No training artifact changes production default profile without separate owner approval.