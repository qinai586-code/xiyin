# Archived predecessor

This directory preserves the XIYIN repository's inherited QINAI-style modules,
rules, evaluation assets, baselines and deployment backups for reference. It is
not the separate QINAI project and is not part of XIYIN's active runtime.

Previously active Python modules refuse import and execution before doing work.
Use the current repository's `xiyin.py` entry and Supervisor for runtime and
recovery. Historical `DEPLOY_BACKUP` contents remain byte-for-byte reference
material; they are not supported entry points and must not be executed.

The active compatibility surface remains `L2_CENTRAL/C1_Auth` and
`L2_CENTRAL/L2_MAIN/l2_central.py`. It delegates to the same XIYIN runtime and
does not revive C2–C7, old persona rewriting, `wait_check` or old file-memory
administration. Existing `L1_MEMORY` and external data roots were not moved or
rewritten by this source reorganization.
