"""Compatibilidade: deep_search migrou para `formiga.ext.deepsearch`."""

from formiga.ext.deepsearch.tool import (
    DEEP_SEARCH_CAP_CHARS,
    MAX_SOURCES_LISTED,
    DeepSearchTool,
    _slugify,
)

__all__ = ["DEEP_SEARCH_CAP_CHARS", "MAX_SOURCES_LISTED", "DeepSearchTool", "_slugify"]
