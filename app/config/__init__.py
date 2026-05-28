"""Configuration package.

Split into ``schema`` (dataclasses) and ``loader`` (TOML parsing). Everything is
re-exported here so existing ``from app.config import ...`` imports keep working.
"""

from __future__ import annotations

from app.config.loader import (
    CONFIG_PATH,
    load_config,
    load_full_config,
)
from app.config.schema import (
    AdvancedSection,
    AppConfig,
    AppSection,
    AutoPRConfig,
    Config,
    MinutesConfig,
    OllamaSummaryConfig,
    SummarySection,
    TranscriptionSection,
)

__all__ = [
    "CONFIG_PATH",
    "load_config",
    "load_full_config",
    # legacy schema
    "AppConfig",
    "MinutesConfig",
    "AutoPRConfig",
    # v2 schema
    "Config",
    "AppSection",
    "AdvancedSection",
    "TranscriptionSection",
    "SummarySection",
    "OllamaSummaryConfig",
]
