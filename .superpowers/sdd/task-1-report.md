# Task 1 Report: Extend models (Setup + SmcState)

## What I implemented

- Extended `Setup` with 6 new fields after `experimental`: `entry_type`, `entry`, `risk_money`, `risk_pct`, `spread`, `lot`, `rr_planned` — all with defaults so existing callers unchanged.
- Updated `Setup.rr` property to return `rr_planned` when set (non-zero), otherwise falls back to computed entry-based RR.
- Added `SmcState` dataclass with `to_json()`/`from_json()`. `from_json` accepts `None` blob (returns empty dict), compatible with optional serialized state.
- Added `demo()` test + `if __name__` block per project convention.

## TDD Evidence

**RED** — `python -m engine.models`:
```
TypeError: Setup.__init__() got an unexpected keyword argument 'entry_type'
```
Confirmed: new keyword args not accepted; `SmcState.to_json`/`from_json` nonexistent.

**GREEN** — `python -m engine.models`:
```
[OK] models: Setup extras + SmcState round-trip
```

## Files Changed

- `engine/models.py` — 49 insertions, 2 deletions (+import json, +7 Setup fields, +rr_planned check in rr, +SmcState dataclass with to_json/from_json, +demo/ifmain block)

## Smoke Tests

- `python -m compileall -q engine` — no errors
- `python -m delivery.telegram` — `[OK] telegram: ...` (Setup constructed positionally, unaffected)
- `python -m journal.db` — `[OK] journal: ...` (Setup constructed positionally, unaffected)

## Commits

```
aab4cdb feat(models): Setup pending-limit fields + SmcState
```

## Self-Review

- Field order matches brief exactly: existing fields up to `experimental` preserved, new fields appended after.
- No reordering of existing fields, no changes to existing `Bundle`.
- `rr_planned` defaults to 0.0 (falsy) so old code path unchanged.
- `entry` defaults to 0.0, `entry or (...)` correctly falls back to existing zone logic.
- `SmcState.from_json` handles `blob=None` gracefully.
- No overbuilding: no methods on `SmcState` beyond what the test asserts.
- Test asserts real behavior (`rr_planned → rr`, `data round-trip`). No tautological asserts.
- Comment lang: Indonesian-style comments matching existing file.

## Concerns

None.
