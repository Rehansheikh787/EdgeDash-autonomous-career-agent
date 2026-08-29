"""EdgeDash — run one fetch/score/analyze cycle."""

import sys

# Ensure UTF-8 output on all platforms
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from edgedash.config import load_config
from edgedash.orchestrator import run_cycle

config = load_config()
run_cycle(config)
