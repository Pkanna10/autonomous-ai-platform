"""Tests for the engine error hierarchy (Step 2, unit U1).

Every engine error class lives in ``common/errors.py`` so that ``clients/``,
``execution/`` and ``persistence/`` can raise them without importing
``orchestrator/nodes.py`` (which would be an import cycle). Errors that stop
a run are ``EngineError`` subclasses; the two transport outcomes the nodes
map (``LLMUnavailable``, ``LLMRequestError``) are plain exceptions, so a
node that forgets to map one cannot silently turn it into a failed run.
"""

from __future__ import annotations

import pytest

from autonomous_ai_agents.common import errors
from autonomous_ai_agents.common.errors import (
    BudgetExceeded,
    DeliveryError,
    EngineError,
    InvalidRecordIdError,
    LLMConfigError,
    LLMRequestError,
    LLMUnavailable,
    PreflightError,
    ProjectConflictError,
    RepoTamperedError,
)
from autonomous_ai_agents.orchestrator import nodes

ENGINE_ERRORS: tuple[type[EngineError], ...] = (
    DeliveryError,
    PreflightError,
    RepoTamperedError,
    BudgetExceeded,
    LLMConfigError,
    ProjectConflictError,
    InvalidRecordIdError,
)
TRANSPORT_OUTCOMES: tuple[type[Exception], ...] = (LLMUnavailable, LLMRequestError)


def test_engine_error_is_a_plain_exception() -> None:
    """
    GIVEN the base engine error
    WHEN its bases are inspected
    THEN it derives directly from Exception
    """
    assert EngineError.__bases__ == (Exception,)


@pytest.mark.parametrize("cls", ENGINE_ERRORS, ids=lambda c: c.__name__)
def test_run_stopping_errors_are_engine_errors(cls: type[EngineError]) -> None:
    """
    GIVEN an error that must stop a run
    WHEN it is raised
    THEN ``except EngineError`` catches it with its message intact
    """
    with pytest.raises(EngineError, match="boom") as caught:
        raise cls("boom")

    assert type(caught.value) is cls
    assert cls.__bases__ == (EngineError,)


@pytest.mark.parametrize("cls", TRANSPORT_OUTCOMES, ids=lambda c: c.__name__)
def test_transport_outcomes_are_not_engine_errors(cls: type[Exception]) -> None:
    """
    GIVEN a transport outcome the nodes must map themselves
    WHEN it is checked against the hierarchy
    THEN it is a plain Exception and never an EngineError
    """
    assert cls.__bases__ == (Exception,)
    assert not issubclass(cls, EngineError)
    assert isinstance(cls("x"), Exception)


def test_every_error_class_has_a_one_line_docstring() -> None:
    """
    GIVEN every exception class defined in common/errors.py
    WHEN their docstrings are read
    THEN each has a non-empty single-line docstring, and all are listed above
    """
    defined = {
        obj
        for obj in vars(errors).values()
        if isinstance(obj, type)
        and issubclass(obj, Exception)
        and obj.__module__ == errors.__name__
    }

    assert defined == {EngineError, *ENGINE_ERRORS, *TRANSPORT_OUTCOMES}
    for cls in defined:
        doc = cls.__doc__
        assert doc is not None, cls.__name__
        assert doc.strip(), cls.__name__
        assert "\n" not in doc.strip(), cls.__name__


def test_nodes_re_exports_the_moved_errors() -> None:
    """
    GIVEN code that still imports EngineError and DeliveryError from nodes
    WHEN those names are resolved
    THEN they are the very classes defined in common/errors.py
    """
    assert nodes.EngineError is EngineError
    assert nodes.DeliveryError is DeliveryError
