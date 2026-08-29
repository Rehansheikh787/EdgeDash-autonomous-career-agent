"""EdgeDash \u2014 run one fetch/score/analyze cycle."""

from edgedash.config import load_config
from edgedash.orchestrator import run_cycle

run_cycle(load_config())
