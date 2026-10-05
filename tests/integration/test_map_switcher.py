"""Backend map_switcher resolution + post-switch frame gate for the dashboard snapshot.

Resolution has TWO rungs. The DECLARED `entities.active_map` role wins when it is a
`select` (Roborock, Dreame) — it needs no camera, and it is already resolved, including
through the localized-id rescue. Otherwise the eufy-clean fork's "Switch Map" select
(`select.<device>_switch_map`, unique_id `<device>_map_select`, novel-only) is resolved
as a device-sibling of the configured live-map camera; Eufy's own active_map is a
read-only SENSOR, so that rung is Eufy's, not a legacy path. Either way the control is
GATED on an entity existing and degrades to no switcher.

The block also carries ``frame_ungrounded`` — after a map switch the robot's coordinate
frame stays on the old map until it MOVES and re-localizes, so the card pauses zone
drawing in that window (see manager._compute_map_frame_gate / acknowledge_map_frame).

Coverage
--------
[MSW-1] camera's device-sibling *_map_select is surfaced with state/options/available.
[MSW-2] no camera configured -> None.
[MSW-3] camera exists but no *_map_select on the device (older fork) -> None.
[MSW-4] the select present but unavailable -> available False, current None.
[MSW-5] active-map change arms the gate; stays gated while the robot is docked.
[MSW-6] a pose move past the threshold clears the gate.
[MSW-7] acknowledge_map_frame overrides until the NEXT switch re-arms it.
[MSW-8] a cleaning/returning vacuum state clears the gate.
[MSW-9] no usable active-map signal -> never gated.
[MSW-10] the resolved block carries frame_ungrounded/reason after a switch.
[MSW-11] issue #61: a DECLARED active_map select resolves the switcher with no fork
         sibling and no camera at all (Roborock/Dreame).
[MSW-12] a declared active_map SENSOR (Eufy) is never bound as the switcher.
[MSW-13] the declared select loses to nothing: when it has no state, rung 2 still runs.
[MSW-14] the post-switch frame gate watches the DECLARED active_map role, so it arms on
         a brand whose role is a select (Roborock/Dreame), not only on Eufy's sensor.
[MSW-15] Eufy is unaffected: its declared role IS the id the gate used to hardcode.
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.eufy_vacuum.adapters.registry import register_adapter_config


def _wire_fork_entities(
    hass, mock_config_entry, *, ident="device123", select_state="My home (ID: 6)", select_options=None
):
    """Create a robovac_mqtt-style device with a live-map camera + a Switch Map select."""
    if mock_config_entry.entry_id not in hass.config_entries.async_entry_ids():
        mock_config_entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={("robovac_mqtt", ident)},
    )
    cam = ent_reg.async_get_or_create("camera", "robovac_mqtt", f"{ident}_map", device_id=device.id)
    sel = ent_reg.async_get_or_create(
        "select", "robovac_mqtt", f"{ident}_map_select", device_id=device.id
    )
    hass.states.async_set(
        sel.entity_id,
        select_state,
        {"options": select_options or ["My home (ID: 6)", "Testing map (ID: 7)"]},
    )
    return cam.entity_id, sel.entity_id


def _set_active_map(hass, obj, value):
    hass.states.async_set(f"sensor.{obj}_active_map", value)


def _set_pose(hass, obj, x, y):
    hass.states.async_set(f"sensor.{obj}_robot_position_x_raw", str(x))
    hass.states.async_set(f"sensor.{obj}_robot_position_y_raw", str(y))


async def test_map_switcher_resolves_sibling_select(hass, manager, mock_config_entry):
    """[MSW-1]"""
    cam_id, sel_id = _wire_fork_entities(hass, mock_config_entry)
    out = manager._resolve_map_switcher(
        vacuum_entity_id="vacuum.device123", live_map_image_entity=cam_id
    )
    assert out == {
        "entity_id": sel_id,
        "current": "My home (ID: 6)",
        "options": ["My home (ID: 6)", "Testing map (ID: 7)"],
        "available": True,
        "frame_ungrounded": False,
        "frame_ungrounded_reason": None,
    }


async def test_map_switcher_none_when_no_camera(manager):
    """[MSW-2]"""
    assert (
        manager._resolve_map_switcher(
            vacuum_entity_id="vacuum.nope", live_map_image_entity=None
        )
        is None
    )


async def test_map_switcher_none_when_no_sibling(hass, manager, mock_config_entry):
    """[MSW-3]"""
    if mock_config_entry.entry_id not in hass.config_entries.async_entry_ids():
        mock_config_entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={("robovac_mqtt", "dev_nosel")},
    )
    cam = ent_reg.async_get_or_create("camera", "robovac_mqtt", "dev_nosel_map", device_id=device.id)
    assert (
        manager._resolve_map_switcher(
            vacuum_entity_id="vacuum.dev_nosel", live_map_image_entity=cam.entity_id
        )
        is None
    )


async def test_map_switcher_unavailable_select(hass, manager, mock_config_entry):
    """[MSW-4]"""
    cam_id, sel_id = _wire_fork_entities(hass, mock_config_entry, ident="dev_unavail", select_state="unavailable")
    out = manager._resolve_map_switcher(
        vacuum_entity_id="vacuum.dev_unavail", live_map_image_entity=cam_id
    )
    assert out["entity_id"] == sel_id
    assert out["available"] is False
    assert out["current"] is None


async def test_frame_gate_arms_on_switch(hass, manager):
    """[MSW-5]"""
    obj, vac = "gate5", "vacuum.gate5"
    _set_active_map(hass, obj, "6")
    _set_pose(hass, obj, 100, 100)
    # First observation: no prior map to compare -> grounded.
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (False, None)
    # Switch to map 7 with the robot still docked -> armed, stays armed.
    _set_active_map(hass, obj, "7")
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (True, "map_switched")
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (True, "map_switched")


async def test_frame_gate_clears_on_move(hass, manager):
    """[MSW-6]"""
    obj, vac = "gate6", "vacuum.gate6"
    _set_active_map(hass, obj, "6")
    _set_pose(hass, obj, 100, 100)
    manager._compute_map_frame_gate(vacuum_entity_id=vac)  # seed
    _set_active_map(hass, obj, "7")
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac)[0] is True
    _set_pose(hass, obj, 200, 100)  # moved well past the threshold
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (False, None)


async def test_frame_gate_user_override(hass, manager):
    """[MSW-7]"""
    obj, vac = "gate7", "vacuum.gate7"
    _set_active_map(hass, obj, "6")
    _set_pose(hass, obj, 100, 100)
    manager._compute_map_frame_gate(vacuum_entity_id=vac)  # seed
    _set_active_map(hass, obj, "7")
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac)[0] is True
    # Override clears it even though the robot never moved.
    assert manager.acknowledge_map_frame(vacuum_entity_id=vac)["acknowledged"] is True
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (False, None)
    # The NEXT switch re-arms the gate.
    _set_active_map(hass, obj, "6")
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac)[0] is True


async def test_frame_gate_clears_when_cleaning(hass, manager):
    """[MSW-8]"""
    obj, vac = "gate8", "vacuum.gate8"
    _set_active_map(hass, obj, "6")
    _set_pose(hass, obj, 100, 100)
    manager._compute_map_frame_gate(vacuum_entity_id=vac)  # seed
    _set_active_map(hass, obj, "7")
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac)[0] is True
    hass.states.async_set(vac, "cleaning")  # moving -> re-localizing
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (False, None)


async def test_frame_gate_no_active_map_signal(manager):
    """[MSW-9]"""
    assert manager._compute_map_frame_gate(vacuum_entity_id="vacuum.nosignal") == (False, None)


async def test_map_switcher_block_reports_frame_ungrounded(hass, manager, mock_config_entry):
    """[MSW-10]"""
    obj, vac = "gate10", "vacuum.gate10"
    cam_id, _sel_id = _wire_fork_entities(hass, mock_config_entry, ident=obj)
    _set_active_map(hass, obj, "6")
    _set_pose(hass, obj, 100, 100)
    manager._resolve_map_switcher(vacuum_entity_id=vac, live_map_image_entity=cam_id)  # seed
    _set_active_map(hass, obj, "7")
    out = manager._resolve_map_switcher(vacuum_entity_id=vac, live_map_image_entity=cam_id)
    assert out["frame_ungrounded"] is True
    assert out["frame_ungrounded_reason"] == "map_switched"


# ---------------------------------------------------------------------------
# issue #61 — the declared role (rung 1)
# ---------------------------------------------------------------------------

_ROBOROCK_CFG = {
    "adapter_id": "roborock",
    "source": "code",
    "entities": {"active_map": "select.s7_mapa_seleccionado"},
}


async def test_msw11_declared_active_map_select_resolves_without_a_fork_sibling(hass, manager):
    """[MSW-11] issue #61.

    A Roborock user configured `active_map` correctly -- VA read it, compared it against
    the imported map and warned him they did not match -- and was then shown no control
    to change it, because resolution looked ONLY for a unique_id ending `_map_select`,
    which is the eufy-clean fork's convention. He had no such entity and never could.
    He was stuck on his first imported map permanently.

    No camera is wired here on purpose: switching the VA view does not need a backdrop,
    and requiring one was part of what hid the control.
    """
    register_adapter_config("vacuum.s7", dict(_ROBOROCK_CFG))
    hass.states.async_set(
        "select.s7_mapa_seleccionado",
        "Habitaciones",
        {"options": ["Comedor", "Habitaciones"]},
    )

    out = manager._resolve_map_switcher(
        vacuum_entity_id="vacuum.s7", live_map_image_entity=None
    )

    assert out is not None, "a declared active_map select must resolve the switcher"
    assert out["entity_id"] == "select.s7_mapa_seleccionado"
    assert out["current"] == "Habitaciones"
    assert out["options"] == ["Comedor", "Habitaciones"]
    assert out["available"] is True


async def test_msw12_a_declared_active_map_sensor_is_never_the_switcher(hass, manager):
    """[MSW-12] Eufy declares active_map as a read-only SENSOR. The card fires
    `select.select_option` on whatever this returns, so binding a sensor would render a
    control that throws on every pick. Rung 1 must decline and leave rung 2 to answer."""
    register_adapter_config(
        "vacuum.eufysensor",
        {"adapter_id": "eufy", "source": "code",
         "entities": {"active_map": "sensor.eufysensor_active_map"}},
    )
    hass.states.async_set("sensor.eufysensor_active_map", "6", {"options": ["6", "7"]})

    out = manager._resolve_map_switcher(
        vacuum_entity_id="vacuum.eufysensor", live_map_image_entity=None
    )

    assert out is None, "a sensor must not be bound as the map switcher"


async def test_msw13_declared_select_without_state_falls_through_to_the_fork(
    hass, manager, mock_config_entry
):
    """[MSW-13] A declared id is a naming claim, not proof the entity exists. When it has
    no state, rung 2 must still run -- otherwise adding rung 1 would REMOVE the switcher
    from the fork installs that have one today."""
    cam_id, sel_id = _wire_fork_entities(hass, mock_config_entry)
    register_adapter_config(
        "vacuum.device123",
        {"adapter_id": "eufy", "source": "code",
         "entities": {"active_map": "select.device123_never_created"}},
    )

    out = manager._resolve_map_switcher(
        vacuum_entity_id="vacuum.device123", live_map_image_entity=cam_id
    )

    assert out is not None and out["entity_id"] == sel_id


async def test_msw14_frame_gate_arms_on_a_select_based_active_map(hass, manager):
    """[MSW-14] issue #61, found by the pre-release audit.

    The gate hardcoded `sensor.{object_id}_active_map` -- Eufy's shape and only Eufy's.
    Roborock and Dreame declare a `select`, so the gate NEVER armed for them. The same
    issue handed both of those brands the map switcher, which would have given them the
    control without the pause that makes it safe: after a switch the robot's coordinate
    frame is still on the old map, so a zone drawn before it next moves lands wrong.

    Reading the declared role also picks up the localized-id rescue and any user entity
    override, neither of which a derived id can see.
    """
    vac = "vacuum.gate14"
    register_adapter_config(
        vac,
        {"adapter_id": "roborock", "source": "code",
         "entities": {"active_map": "select.gate14_selected_map"}},
    )
    _set_pose(hass, "gate14", 100, 100)
    hass.states.async_set("select.gate14_selected_map", "Comedor",
                          {"options": ["Comedor", "Habitaciones"]})
    # First observation: no prior token to compare against -> grounded.
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (False, None)

    hass.states.async_set("select.gate14_selected_map", "Habitaciones",
                          {"options": ["Comedor", "Habitaciones"]})
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (True, "map_switched"), (
        "a select-based active_map must arm the gate"
    )
    # Still docked, still un-grounded.
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (True, "map_switched")


async def test_msw15_eufy_frame_gate_is_unchanged_by_the_role_read(hass, manager):
    """[MSW-15] The safety property for MSW-14's change. Eufy declares
    `sensor.{object_id}_active_map` -- byte-identical to the id the gate hardcoded -- so
    routing through the role must leave Eufy's behaviour exactly as it was."""
    vac = "vacuum.gate15"
    register_adapter_config(
        vac,
        {"adapter_id": "eufy", "source": "code",
         "entities": {"active_map": "sensor.gate15_active_map"}},
    )
    _set_active_map(hass, "gate15", "6")
    _set_pose(hass, "gate15", 100, 100)
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (False, None)
    _set_active_map(hass, "gate15", "7")
    assert manager._compute_map_frame_gate(vacuum_entity_id=vac) == (True, "map_switched")
