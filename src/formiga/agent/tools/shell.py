"""Compatibilidade: bash migrou para `formiga.ext.core`."""

from formiga.ext.core.shell import DANGEROUS_PATTERNS, PACKAGE_MUTATION, BashTool, _is_dangerous

__all__ = ["BashTool", "DANGEROUS_PATTERNS", "PACKAGE_MUTATION", "_is_dangerous"]
