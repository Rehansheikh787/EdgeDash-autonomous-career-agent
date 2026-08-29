from __future__ import annotations

from edgedash.sources.base import SOURCES, Source, register
from edgedash.sources.http import SourceError, get_json
import edgedash.sources.arbeitnow  # Registers ArbeitnowSource in SOURCES registry
import edgedash.sources.apify      # Registers ApifySource in SOURCES registry

__all__ = ["SOURCES", "Source", "SourceError", "get_json", "register"]
