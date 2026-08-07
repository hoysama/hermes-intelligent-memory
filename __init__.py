"""Hermes Intelligent Memory standalone plugin entrypoint."""

from plugin.intelligent_memory import IntelligentMemoryProvider, register

__all__ = ["IntelligentMemoryProvider", "register"]
