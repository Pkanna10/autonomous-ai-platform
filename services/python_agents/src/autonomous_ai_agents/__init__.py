"""Autonomous AI Agents - LangGraph orchestrator and research agents.

This package provides AI agent capabilities for the autonomous AI platform,
including:
- LangGraph-based orchestrator for task coordination
- Research paper discovery and algorithm extraction
- Shared utilities and API clients
"""

from importlib.metadata import version

# Public API exports (will be populated as components are implemented)
__all__: list[str] = []

try:
    __version__ = version("autonomous-ai-agents")
except Exception:
    __version__ = "0.1.0"
