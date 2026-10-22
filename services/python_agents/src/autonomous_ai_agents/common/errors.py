"""Every engine error class, in one module with no engine imports.

``clients/``, ``execution/`` and ``persistence/`` raise these without
importing ``orchestrator/nodes.py``, which would be an import cycle;
``nodes.py`` re-exports ``EngineError`` and ``DeliveryError`` so existing
imports keep working.

An ``EngineError`` stops the run: ``Orchestrator.run`` turns one raised by a
node into a ``failed`` result. ``LLMUnavailable`` and ``LLMRequestError`` are
plain exceptions on purpose: they are transport outcomes each node maps
itself (a failed trial, ``understanding=None``), never a run failure by
accident.
"""

from __future__ import annotations


class EngineError(Exception):
    """A run cannot continue: the state or the measurements are not trustworthy."""


class DeliveryError(EngineError):
    """A branch would be unsafe (the default branch, outside the prefix, bad refname)."""


class PreflightError(EngineError):
    """The project failed a connect-time check, so it cannot be measured safely."""


class RepoTamperedError(EngineError):
    """The user's repository or a worktree's ``.git`` link changed during a run."""


class BudgetExceeded(EngineError):  # noqa: N818 - name fixed by the spec
    """A request or a recorded spend would take the run past its cost cap."""


class LLMConfigError(EngineError):
    """The Claude API refused the credentials, billing or account (HTTP 401-403)."""


class ProjectConflictError(EngineError):
    """Another project id is already registered for this repository root."""


class InvalidRecordIdError(EngineError):
    """An id bound for a UUID database column is not a UUID."""


class LLMUnavailable(Exception):  # noqa: N818 - name fixed by the spec
    """A transient Claude API failure: 429, 5xx, 529, a timeout or a lost connection."""


class LLMRequestError(Exception):
    """The Claude API refused the request itself (HTTP 400, 404 or 413)."""
