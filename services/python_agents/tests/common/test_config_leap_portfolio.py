"""The portfolio leap's settings (U-portfolio): ``IDEAS_LEAP_PORTFOLIO`` off by
default, and the deal's library and run, each validated when given. That
the portfolio on needs both is the pipeline's check (``check_deal``), since
the X2 live test sets the library per case after the settings load."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autonomous_ai_agents.common.config import Settings


def test_the_portfolio_is_off_and_its_deal_unset_by_default() -> None:
    cfg = Settings(_env_file=None)
    assert cfg.IDEAS_LEAP_PORTFOLIO is False
    assert cfg.IDEAS_LEAP_DEAL_LIBRARY is None
    assert cfg.IDEAS_LEAP_DEAL_RUN is None


def test_the_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IDEAS_LEAP_PORTFOLIO", "true")
    monkeypatch.setenv("IDEAS_LEAP_DEAL_LIBRARY", "tomli")
    monkeypatch.setenv("IDEAS_LEAP_DEAL_RUN", "2")
    cfg = Settings(_env_file=None)
    assert (cfg.IDEAS_LEAP_PORTFOLIO, cfg.IDEAS_LEAP_DEAL_LIBRARY,
            cfg.IDEAS_LEAP_DEAL_RUN) == (True, "tomli", 2)  # fmt: skip


@pytest.mark.parametrize(
    "library", ["", "Tomli", "../tomli", "tomli lib", "requests", "idna"]
)
def test_a_deal_library_off_the_design_is_refused(library: str) -> None:
    with pytest.raises(ValidationError, match="IDEAS_LEAP_DEAL_LIBRARY"):
        Settings(_env_file=None, IDEAS_LEAP_DEAL_LIBRARY=library)


@pytest.mark.parametrize("run", [0, 4, 9, 10, -1])
def test_a_deal_run_outside_one_to_three_is_refused(run: int) -> None:
    with pytest.raises(ValidationError, match="IDEAS_LEAP_DEAL_RUN"):
        Settings(_env_file=None, IDEAS_LEAP_DEAL_RUN=run)


def test_the_portfolio_on_without_a_deal_still_loads() -> None:
    """The pipeline refuses it before any spend; the settings must load in a
    process whose library each case sets."""
    cfg = Settings(_env_file=None, IDEAS_LEAP_PORTFOLIO=True)
    assert cfg.IDEAS_LEAP_DEAL_LIBRARY is None
