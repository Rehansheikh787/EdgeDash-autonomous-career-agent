from __future__ import annotations

from typing import Any, Protocol, TypeVar

from edgedash.config import Config

SourceT = TypeVar("SourceT", bound="Source")


class Source(Protocol):
    """Protocol for external job sources."""

    @property
    def name(self) -> str:
        ...

    def fetch(self, config: Config) -> list[dict[str, Any]]:
        ...


SOURCES: dict[str, type[Source]] = {}


def register(cls: type[SourceT]) -> type[SourceT]:
    """Decorator to register a Source class in the global SOURCES registry."""
    try:
        instance_name = cls().name
    except Exception:
        instance_name = getattr(cls, "name", cls.__name__.lower())
    SOURCES[str(instance_name)] = cls
    return cls
