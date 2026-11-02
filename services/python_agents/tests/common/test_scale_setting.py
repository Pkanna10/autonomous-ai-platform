"""The scaling judge's size setting (G6b, spec section 2): on the ``Workload``.

``ScaleSetting`` says how the scaling judge runs one workload at 2-3 input
sizes: the environment variable the benchmark reads its size from, the
sizes, and the timed runs per size and side. It lives on the caller's
``Workload`` (state the editor cannot reach, never a repository file), so
only the caller or the lab's setter defines it, never a trial. Hand-built
models, no I/O.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autonomous_ai_agents.common.models import (
    ENGINE_MODEL_CLASSES,
    SCALE_MIN_SPAN,
    SCALE_SIZE_MAX,
    ScaleSetting,
    Workload,
)
from autonomous_ai_agents.orchestrator.serde import dump_state, load_state
from autonomous_ai_agents.orchestrator.state import initial_state


def test_a_setting_holds_the_variable_the_sizes_and_three_runs_by_default() -> None:
    setting = ScaleSetting(env_var="BENCH_N", sizes=(1000, 2000, 4000))

    assert (setting.env_var, setting.sizes, setting.runs) == ("BENCH_N", (1000, 2000, 4000), 3)  # fmt: skip
    assert ScaleSetting(env_var="N", sizes=(10, 40), runs=1).runs == 1
    assert ScaleSetting in ENGINE_MODEL_CLASSES
    with pytest.raises(ValidationError):
        setting.runs = 5  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs"):
        ScaleSetting.model_validate({"env_var": "N", "sizes": (10, 40), "argv": "x"})


def test_a_workload_has_no_size_setting_unless_the_caller_gives_one() -> None:
    plain = Workload(project_id="p", name="w", command=("python", "b.py"))
    setting = ScaleSetting(env_var="N", sizes=(100, 400))
    scaled = Workload(project_id="p", name="w", command=("python", "b.py"), scale=setting)  # fmt: skip

    assert plain.scale is None
    assert scaled.scale == setting


@pytest.mark.parametrize(
    "sizes",
    [
        (100,),  # one size fits nothing
        (100, 200, 400, 800),  # at most three
        (100, 100, 400),  # strictly increasing
        (400, 100),
        (0, 400),  # positive
        (-4, 400),
        (100, SCALE_SIZE_MAX + 1),
        (100, 200),  # spans less than SCALE_MIN_SPAN
        (100, 399),
        (True, 400),  # an int, never a bool or a float
        (1.5, 400),
        ("100", "400"),
    ],
)
def test_sizes_are_two_or_three_increasing_integers_spanning_the_minimum(
    sizes: tuple[object, ...],
) -> None:
    with pytest.raises(ValidationError):
        ScaleSetting.model_validate({"env_var": "N", "sizes": sizes})


def test_the_span_bound_is_inclusive_and_the_size_bound_too() -> None:
    assert SCALE_MIN_SPAN == 4
    assert ScaleSetting(env_var="N", sizes=(100, 400)).sizes == (100, 400)
    assert ScaleSetting(env_var="N", sizes=(1, 2, SCALE_SIZE_MAX)).sizes[-1] == SCALE_SIZE_MAX  # fmt: skip


@pytest.mark.parametrize("runs", [0, 10, -1])
def test_runs_per_size_are_one_to_nine(runs: int) -> None:
    with pytest.raises(ValidationError):
        ScaleSetting(env_var="N", sizes=(10, 40), runs=runs)


@pytest.mark.parametrize(
    "name",
    [
        "", "n", "bench_n", "1N", "_N", "N-1", "N 1", "N\0", "N" * 65,  # the pattern
        "PATH", "HOME", "TMPDIR",  # what the engine sets for every run
        "PYTHONHASHSEED", "PYTHONPATH", "PYTHON_N", "LD_PRELOAD", "DYLD_N",  # interpreter and loader
    ],
)  # fmt: skip
def test_the_variable_is_an_upper_case_name_the_engine_and_loaders_leave_alone(
    name: str,
) -> None:
    with pytest.raises(ValidationError):
        ScaleSetting(env_var=name, sizes=(10, 40))


def test_a_scaled_workload_round_trips_through_the_checkpointed_state() -> None:
    """The setting survives the state's JSON round trip (the repository and
    the checkpointer store the state's workloads this way)."""
    from autonomous_ai_agents.common.models import Project

    project = Project(name="p", root_path="/srv/p")
    setting = ScaleSetting(env_var="BENCH_N", sizes=(1000, 4000, 16000), runs=2)
    workload = Workload(project_id=project.id, name="w", command=("python", "b.py"), scale=setting)  # fmt: skip
    state = initial_state(project, [workload], [], [], run_id="run-1")

    loaded = load_state(dump_state(state))

    assert loaded["workloads"] == [workload]
    assert loaded["workloads"][0].scale == setting
