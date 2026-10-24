"""Typed JSON serde for ``EngineState``: what a JSONB column stores and reads.

``dump_state`` turns a state into plain JSON values (dicts, lists, strings,
numbers, booleans and ``None``) and ``load_state`` turns such values back
into the declared types: enums, frozen models, tuples, dates and tz-aware
datetimes, so ``load_state(dump_state(s)) == s`` on every key, the reducer
channels included. Both refuse a key set that differs from ``EngineState``
and name the key whose value does not fit, so nothing is stored that cannot
be loaded back. ``dump_state`` also refuses inf and NaN, which JSONB cannot
store.

Why one ``TypeAdapter`` per key: ``TypeAdapter(EngineState)`` raises
``PydanticUserError`` on Python 3.11 because ``state.py`` uses
``typing.TypedDict`` (pydantic wants ``typing_extensions.TypedDict`` before
3.12). Adapting each value's own type works on every supported version;
``get_type_hints`` drops the reducers' ``Annotated`` metadata, so the
channels are plain lists. The adapters are built on first use, not at import.

Both functions validate before they convert, so they also accept partly
typed values, such as a ``PostgresSaver`` snapshot whose ``phase`` comes back
as a plain ``str`` (Step 4 re-types those through ``load_state``). The
LangGraph checkpointer keeps its own ``JsonPlusSerializer``; this module is
for the repository and for re-typing.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Iterable, Mapping
from typing import Any, cast, get_type_hints

from pydantic import TypeAdapter, ValidationError

from autonomous_ai_agents.orchestrator.state import EngineState


@functools.cache
def _adapters() -> dict[str, TypeAdapter[Any]]:
    """One adapter per ``EngineState`` key, in declaration order."""
    return {key: TypeAdapter(hint) for key, hint in get_type_hints(EngineState).items()}


def _matching_adapters(keys: Iterable[str], what: str) -> dict[str, TypeAdapter[Any]]:
    """The adapters, or ``ValueError`` when ``keys`` is not exactly the state keys."""
    adapters = _adapters()
    given = set(keys)
    missing = sorted(adapters.keys() - given)
    unknown = sorted(given - adapters.keys())
    if missing or unknown:
        raise ValueError(
            f"{what} does not match EngineState: missing {missing}, unknown {unknown}"
        )
    return adapters


def _validated(adapter: TypeAdapter[Any], key: str, value: object) -> Any:
    try:
        return adapter.validate_python(value)
    except ValidationError as exc:
        raise ValueError(
            f"state[{key!r}] does not fit its declared type: {exc}"
        ) from exc


def dump_state(state: EngineState) -> dict[str, Any]:
    """Return ``state`` as JSON-safe values, one entry per ``EngineState`` key.

    Raises ``ValueError`` for a missing or unknown key, a value that does not
    fit its key's type, or a float that is inf or NaN.
    """
    raw = cast(Mapping[str, Any], state)
    adapters = _matching_adapters(raw, "state")
    dumped: dict[str, Any] = {}
    for key, adapter in adapters.items():
        value = adapter.dump_python(_validated(adapter, key, raw[key]), mode="json")
        try:
            json.dumps(value, allow_nan=False)
        except ValueError as exc:
            raise ValueError(f"state[{key!r}] is not JSON-safe: {exc}") from exc
        dumped[key] = value
    return dumped


def load_state(data: Mapping[str, Any]) -> EngineState:
    """Re-type stored values (``dump_state`` output or a snapshot) as ``EngineState``.

    Raises ``ValueError`` for a missing or unknown key, or a value that does
    not fit its key's type; the message names the key.
    """
    adapters = _matching_adapters(data, "stored state")
    loaded = {
        key: _validated(adapter, key, data[key]) for key, adapter in adapters.items()
    }
    return cast(EngineState, loaded)
