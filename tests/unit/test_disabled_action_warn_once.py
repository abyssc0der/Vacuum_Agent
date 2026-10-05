"""Warn-once throttle for a DISABLED action entity.

Reported 2026-10-05 with the log pasted: a Roborock owner whose four consumable reset
buttons were disabled in the registry got four identical WARNING lines every few
seconds, indefinitely. Both `maintenance/manager.py` and `dock/manager.py` resolve an
action entity on every upkeep/snapshot build and both logged unthrottled -- the same
defect written twice. Issue #57 closed on this symptom; this is the half left behind.

Coverage targets:
  [WOD-1] the same disabled entity warns ONCE however many times it is resolved
  [WOD-2] a DIFFERENT component on the same vacuum gets its own warning
  [WOD-3] the same component on a DIFFERENT vacuum gets its own warning
  [WOD-4] clearing on a clean resolution lets a LATER regression be reported again
  [WOD-5] the message names the entity and the remedy — it is advice, not a fault report
"""

from __future__ import annotations

import logging

import pytest

from custom_components.eufy_vacuum.adapters import entity_resolve


@pytest.fixture(autouse=True)
def _clean_warn_state():
    entity_resolve._DISABLED_ACTION_WARNED.clear()
    yield
    entity_resolve._DISABLED_ACTION_WARNED.clear()


def _warn(vac="vacuum.alfred", name="main_brush", eid="button.alfred_reset_main_brush"):
    entity_resolve.warn_disabled_action_once(
        vacuum_entity_id=vac, kind="reset button", name=name,
        entity_id=eid, advice="enable it to reset this consumable from here",
    )


def test_wod_1_repeated_resolution_warns_once(caplog):
    """[WOD-1] THE RED INPUT. The resolver runs every few seconds; the advice is worth
    saying and is not worth saying three hundred times an hour."""
    with caplog.at_level(logging.WARNING, logger=entity_resolve.__name__):
        for _ in range(25):
            _warn()
    hits = [r for r in caplog.records if "DISABLED in the entity registry" in r.getMessage()]
    assert len(hits) == 1, f"25 resolutions produced {len(hits)} warnings"


def test_wod_2_each_component_is_its_own_warning(caplog):
    """[WOD-2] The reporter had FOUR disabled buttons. Throttling per vacuum rather than
    per component would have told him about one of them and hidden the rest."""
    with caplog.at_level(logging.WARNING, logger=entity_resolve.__name__):
        for component in ("main_brush", "side_brush", "filter", "sensor"):
            for _ in range(5):
                _warn(name=component)
    hits = [r for r in caplog.records if "DISABLED in the entity registry" in r.getMessage()]
    assert len(hits) == 4, f"expected one per component, got {len(hits)}"


def test_wod_3_each_vacuum_is_its_own_warning(caplog):
    """[WOD-3] Two vacuums with the same component must not silence each other."""
    with caplog.at_level(logging.WARNING, logger=entity_resolve.__name__):
        _warn(vac="vacuum.alfred")
        _warn(vac="vacuum.ivy")
        _warn(vac="vacuum.alfred")
    hits = [r for r in caplog.records if "DISABLED in the entity registry" in r.getMessage()]
    assert len(hits) == 2


def test_wod_4_clearing_lets_a_later_regression_report_again(caplog):
    """[WOD-4] The throttle must not become a permanent silence. The user enables the
    entity, we forget; if it is disabled again they are told again. A warn-once that
    never forgets is indistinguishable from a warning that was removed."""
    with caplog.at_level(logging.WARNING, logger=entity_resolve.__name__):
        _warn()
        _warn()
        entity_resolve.clear_disabled_action_warning(
            vacuum_entity_id="vacuum.alfred", kind="reset button", name="main_brush"
        )
        _warn()
    hits = [r for r in caplog.records if "DISABLED in the entity registry" in r.getMessage()]
    assert len(hits) == 2, "a recurrence after a clean resolution must be reported"


def test_wod_5_the_message_is_actionable(caplog):
    """[WOD-5] A disabled entity is a toggle in the user's own UI, not our fault. The
    line has to name WHICH entity and WHAT to do, or it is noise with a severity."""
    with caplog.at_level(logging.WARNING, logger=entity_resolve.__name__):
        _warn()
    msg = next(r.getMessage() for r in caplog.records
               if "DISABLED in the entity registry" in r.getMessage())
    assert "button.alfred_reset_main_brush" in msg, "must name the entity"
    assert "enable it" in msg, "must say what to do"
    assert "logged once" in msg, "must say it will not repeat, so silence is not mistaken for fixed"
