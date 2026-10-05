// Unit tests for activeMapId() — which map the card believes it is showing.
//
// Issue #64. The card re-derived the active map instead of reading the backend's
// answer, and both of its own rungs are wrong off Eufy: `sensor.<obj>_active_map` is
// Eufy's entity shape, and the room-switch fallback returns the FIRST switch in hash
// order. On a live Roborock the backend said 'Junk map' and the card said 'Main floor',
// so the main room list rendered the wrong map's rooms while the modal — opened with an
// explicit map id — rendered the right ones.
//
// Coverage targets:
//   [AMI-1] the snapshot's map_switcher.current_map_id wins (the rung added for #64)
//   [AMI-2] a Roborock-shaped install with NO Eufy sensor and switches from two maps
//           resolves from the snapshot, not from switches[0]
//   [AMI-3] switches[0] really is arbitrary — the pre-fix path answers by enumeration
//           order, which is what made #64 look intermittent
//   [AMI-4] Eufy is unaffected: no snapshot -> the sensor rung still answers
//   [AMI-5] a blank/invalid snapshot value falls through rather than winning
//   [AMI-6] nothing at all -> "1", the original floor
//   [AMI-7] the CANONICAL field is used, not the raw `current` the dropdown needs — a
//           whitespace-named map must still match the stripped keys the card compares
//           against, or the whitespace fix and this one cancel out
// Run: node --test src/state/active-map-id.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { applyRoomsState } from "./rooms.js";

function makeCard({ snapshot, states = {}, switches = [] } = {}) {
  const proto = {};
  applyRoomsState(proto);
  const card = Object.create(proto);
  card.vacuumEntityId = () => "vacuum.ivy";
  card.stateOf = (eid) => states[eid];
  card.dashboardSnapshot = () => snapshot;
  card._findRoomSwitchEntities = () => switches;
  return card;
}

const sw = (mapId) => ({ entityId: `switch.x_${mapId}`, state: "on", attributes: { map_id: mapId } });

test("[AMI-1] the backend's map_switcher.current_map_id wins", () => {
  const card = makeCard({
    snapshot: { map_switcher: { current_map_id: "Junk map" } },
    states: { "sensor.ivy_active_map": "Main floor" },
  });
  assert.equal(card.activeMapId(), "Junk map");
});

test("[AMI-2] Roborock shape: no Eufy sensor, switches from two maps, snapshot decides", () => {
  const card = makeCard({
    snapshot: { map_switcher: { current_map_id: "Junk map" } },
    states: {},                                   // sensor.ivy_active_map does not exist
    switches: [sw("Main floor"), sw("Main floor"), sw("Junk map")],
  });
  assert.equal(card.activeMapId(), "Junk map",
    "the backend resolved the declared select; the card must not out-vote it");
});

test("[AMI-3] without a snapshot the answer is whatever enumerated first", () => {
  // This is the pre-fix behaviour, kept as the fallback and pinned here so the
  // arbitrariness is visible rather than folklore.
  const a = makeCard({ switches: [sw("Main floor"), sw("Junk map")] });
  const b = makeCard({ switches: [sw("Junk map"), sw("Main floor")] });
  assert.equal(a.activeMapId(), "Main floor");
  assert.equal(b.activeMapId(), "Junk map");
  assert.notEqual(a.activeMapId(), b.activeMapId(),
    "same two maps, different enumeration order, different answer");
});

test("[AMI-4] Eufy still resolves through its sensor when no snapshot is present", () => {
  const card = makeCard({
    snapshot: undefined,
    states: { "sensor.ivy_active_map": "6" },
    switches: [sw("9")],
  });
  assert.equal(card.activeMapId(), "6", "the sensor rung must still beat the switch rung");
});

test("[AMI-5] a blank snapshot value falls through instead of winning", () => {
  for (const blank of [null, undefined, "", "unknown", "unavailable"]) {
    const card = makeCard({
      snapshot: { map_switcher: { current_map_id: blank } },
      states: { "sensor.ivy_active_map": "6" },
    });
    assert.equal(card.activeMapId(), "6", `snapshot ${JSON.stringify(blank)} must not win`);
  }
});

test("[AMI-6] nothing resolves -> '1'", () => {
  assert.equal(makeCard().activeMapId(), "1");
});


test("[AMI-7] the canonical field is used, not the raw selector text", () => {
  // `map_switcher.current` stays RAW on purpose: the dropdown pairs it with `options`,
  // and those strings go straight back to select.select_option. But every map KEY the
  // card compares against is whitespace-stripped, so reading `current` here produced an
  // empty room list on exactly the install the whitespace fix exists for — the two
  // fixes cancelling each other out. Caught in pre-release review, not by this suite,
  // because no case passed a value with surrounding whitespace.
  const card = makeCard({
    snapshot: { map_switcher: { current: "Obergeschoss ", current_map_id: "Obergeschoss" } },
    switches: [sw("Obergeschoss")],
  });
  assert.equal(card.activeMapId(), "Obergeschoss",
    "the raw selector text must not become the map identity");
});

test("[AMI-8] a snapshot carrying only the raw field falls through, it does not guess", () => {
  // An older integration paired with a newer card: no current_map_id. Rung 1 must
  // decline rather than reach for `current`, which is what reintroduced the bug.
  const card = makeCard({
    snapshot: { map_switcher: { current: "Obergeschoss " } },
    states: { "sensor.ivy_active_map": "6" },
  });
  assert.equal(card.activeMapId(), "6");
});
