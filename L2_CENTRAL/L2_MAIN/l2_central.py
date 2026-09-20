"""Compatibility entry for the XIYIN runtime.

The original baseline is retained in Git history. This entry and xiyin.py share
one Runtime; legacy QINAI prompts, keyword persona locks and wait_check writes
are not active on this path. The configured Windows token/path policy still applies.
"""
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from xiyin_runtime.bridge import submit_to_chain, submit_to_chain_result

__all__ = ["submit_to_chain", "submit_to_chain_result"]

if __name__ == "__main__":
    from xiyin_runtime.cli import main
    raise SystemExit(main(["chat"]))
