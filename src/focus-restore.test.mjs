// Run: node --test src/focus-restore.test.mjs
//
// [FOCUS-UNIQUE-1] ISSUE #60 — focus restoration restored the WRONG element.
//
// After every render the card re-focuses whatever had focus, via a selector built in
// main.js::_buildFocusRestoreSelector. That builder returns the FIRST valued data-*
// attribute, justified in its own comment with "these are single-instance editors, so
// a valued data-* attr or a class selector is unique in the active view".
//
// Setup -> System is not single-instance. It renders one
//   <select class="evcc-system-picker" data-action="set-entity-override" data-role="...">
// PER ROLE — seventeen on the reporter's install. Source order puts data-action first
// and data-action is identical on every row, so all seventeen captured the SAME
// selector and _restoreShadowFocusState's querySelector returned the first match.
// Every dropdown "reset like tabbing to the first" and only the top one was usable.
//
// The fix records WHICH match was focused and restores that one. Same shape as
// header-battery.test.mjs: the decision logic mirrored here (it is pure), plus source
// pins on the constructs — the pins are what go red if someone reverts to a bare
// querySelector or drops matchIndex.
//
// Coverage (FR = Focus Restore):
//   [FR-1] the captured index selects its own element, not the first match
//   [FR-2] a changed match count DECLINES rather than guessing
//   [FR-3] exactly one match still restores — the whole issue-#37 family
//   [FR-4] source pins: matchIndex is captured, and restore reads querySelectorAll
//   [FR-5] the condition that caused it still exists in the markup

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const MAIN = readFileSync(new URL("./main.js", import.meta.url), "utf8");
const SETUP = readFileSync(new URL("./renderers/setup.js", import.meta.url), "utf8");

// Mirror of main.js::_restoreShadowFocusState's target choice.
function pickTarget(matches, matchIndex) {
  const index = Number.isInteger(matchIndex) ? matchIndex : 0;
  return matches[index] ?? (matches.length === 1 ? matches[0] : null);
}

test("[FR-1] the captured index wins, not the first match", () => {
  const rows = ["active_map", "battery", "dock_status", "task_status"];
  // Every row shares data-action, so all four captured the same selector.
  for (let i = 0; i < rows.length; i++) {
    assert.equal(
      pickTarget(rows, i), rows[i],
      `row ${i} (${rows[i]}) restored to the wrong element`,
    );
  }
  // THE BUG, stated as the old behaviour: index ignored => always the first.
  assert.notEqual(pickTarget(rows, 3), rows[0], "regressed to first-match");
});

test("[FR-2] a changed match count declines rather than guessing", () => {
  // A re-render dropped rows; the captured index no longer means anything. Focusing
  // some other row is worse than focusing nothing — that IS the reported bug.
  assert.equal(pickTarget(["a", "b"], 5), null);
  assert.equal(pickTarget([], 0), null);
});

test("[FR-3] a single match still restores — the issue-#37 family", () => {
  // Run-profile name, chip-search, setup rename: one instance, so the old code was
  // right about them and must stay right. Index 0 of 1, and even a stale index.
  assert.equal(pickTarget(["only"], 0), "only");
  assert.equal(pickTarget(["only"], 9), "only", "single match must survive a stale index");
});

test("[FR-4] source pins: the index is captured and used", () => {
  assert.match(
    MAIN, /matchIndex,/,
    "the focus snapshot no longer carries matchIndex — restoration is guessing again",
  );
  assert.match(
    MAIN, /querySelectorAll\(snapshot\.selector\)/,
    "restore reverted to a single-match lookup; a repeated control will restore to the first",
  );
  assert.doesNotMatch(
    MAIN, /querySelector\(snapshot\.selector\)/,
    "restore uses the bare querySelector again — this is exactly ISSUE #60",
  );
});

test("[FR-5] the condition that caused it still exists", () => {
  // Not a pin on attribute ORDER (reordering is not the fix and must not look like
  // one). The durable fact is that this control is REPEATED while carrying a shared
  // data-action — which is what makes a selector non-unique in the first place.
  assert.match(SETUP, /data-action="set-entity-override"/);
  assert.match(SETUP, /data-role="\$\{this\.escapeHtml\(String\(row\?\.role/,
    "the picker no longer varies by role — re-check whether it is still repeated",
  );
});
