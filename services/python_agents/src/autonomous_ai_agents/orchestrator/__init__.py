"""Orchestrator (L2): the engine loop as a LangGraph graph.

``state`` holds the checkpointed ``EngineState``, ``nodes`` one closure per
loop phase over a frozen ``NodeContext``, ``main`` the compiled graph and the
``Orchestrator`` that runs, pauses for approval and resumes it, and
``events`` the live log. Import from the submodules; this package re-exports
nothing on purpose so importing it stays side-effect free.
"""

__all__: list[str] = []
