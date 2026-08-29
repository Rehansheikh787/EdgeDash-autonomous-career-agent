from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from edgedash.config import Config


@dataclass
class AgentResult:
    agent: str
    status: Literal["ok", "failed"]
    records_touched: int
    notes: str


class Agent(Protocol):
    @property
    def name(self) -> str: ...

    def run(
        self,
        config: Config,
        db_path: str,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult: ...

