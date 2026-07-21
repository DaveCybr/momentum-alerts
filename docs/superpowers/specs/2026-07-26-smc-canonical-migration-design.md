# Spec: Canonical SMC Trading System (2026-07-20 Migration)

## Overview

This spec governs the migration to `smc_canonical` as the **sole** active strategy.  It replaces the previous `trend_pullback` and the stateless `smc_prescreen` draft.  The strategy is a true **cross-candle state machine** per instrument, because SMC entry rules require sequential context (bias → POI → sweep → MSS → limit entry → expiry) that cannot be evaluated in a single snapshot.  State is persisted to SQLite so a restart does not lose the sequence.

**Canonical source:** `strategy/xauusd-smc-trading-system.md` (primary) supplemented by `strategy/smc.md`.  Every clause in this design derives from that spec, with trade-offs documented below.

## Authority

When this spec or the primary SMC spec conflict with `PRD.md` / `ARCHITECTURE.html` / `CLAUDE.md`, this spec wins.  References below are to the canonical strategy files.

## Key Decisions (owner confirmed)

| Topic | Decision |
|---|---|
| Canonical strategy | `smc_canonical` — deterministic, stateful, rule-driven. |
| Scope | XAUUSD.vx + BTCUSD.vx.  Same rule set for both.  Stats split per instrument. |
| Execution mode | Pending LIMIT at 50 % FVG M5, auto-cancel via monitor.  Demo only, enabled after gate. |
| Model | Set-and-forget: ONE SL, ONE TP, no trailing, no BE, no partial. |
| Session | London 07:00–10:00 UTC; NY 12:00–15:30 UTC. Minute precision. |
| Risk / TP | 1 % equity, actual up to 2 % (lot min 0.01).  Single TP at next liquidity (external H1 > previous day HL > session range > equal highs > structural swing), min RR 2.5R, no cap. |
| Daily stop | Global account: 2 losses OR 3 trades OR +2.5R net → stop until next day. |
| Max positions | One (open OR pending) per instrument. |
| Short trades | SELL allowed during demo data collection (same rules mirrored). |
| News filter | **Deferred** for first 25-trade block.  Every trade logged with `news_filter_applied = false` so the block is explicitly tagged “not yet validated under news filter”.  Filter will be a manual `var/news.txt` when introduced later. |
| Trend pullback lama | Delete total (`engine/strategy.py`, related config knobs, strategy factory switch). |

## Architecture

Single process Python 3.11.  Three threads remain:

1. `scheduler` — ticks **every M5 close** (`:00/:05/…/:55`).  Higher-TF analysis (H1/H4/D1) is re-evaluated only when the relevant H1 candle closes; M5 scanning uses cached bias/state in between.  `smc_canonical` runs once per M5.
2. `monitor` — every 60 s: auto-cancel pending orders, fill detection, simulate non-executed outcomes, reconcile broker-closed positions, dead-man switch.
3. `telegram-poll` — owner-only long-poll.  New button `Eksekusi Limit` places a pending LIMIT order for the alert; manager cancels if rules are violated.

No leader lock (single process).  No auto-execute; every trade remains one-tap.

## State machine (per instrument)

State is persisted in a new SQLite table `smc_state(symbol, state, data_json, updated_at)`.

States:

- `IDLE` — waiting for new H1 candle opening context.  Monitors if previous H1 bias and protected level are still valid (body close has not violated protected).  Once valid bias exists, transitions to `BIAS_OK`.  If violated, stays `IDLE` until next valid bias.
- `BIAS_OK` — bias established, but not yet identified a fresh H1 POI (OB with FVG/imbalance).  When POI found and marked fresh, transition to `POI_TAGGED`.  If bias invalidated, back to `IDLE`.
- `POI_TAGGED` — waiting for price to return inside/ near POI (usually discount for BUY, premium for SELL).  When a liquidity sweep occurs *inside the POI bounds*, records sweep extreme and transitions to `SWEPT`.  If H1 POI distal edge is closed through, back to `BIAS_OK` (old POI invalidated; scan for new one).
- `SWEPT` — waiting for M5 displacement + MSS that breaks the **structural swing M5 formed *before* the sweep** (not any random prior high/low).  On confirmation, computes FVG M5 at the displacement leg, records 50 % limit price and bar index, transitions to `MSS_CONFIRMED`.  If sweep extreme is exceeded by a body close in wrong direction, back to `POI_TAGGED`.
- `MSS_CONFIRMED` — setup verified.  On the next scheduler tick (M5 close), if all conditions still hold and no guard blocks it, publishes an alert.  If owner taps `Eksekusi Limit`, broker places a LIMIT order at the recorded 50 % FVG price; state transitions to `PENDING_ORDER`.  Alert still carries expiry conditions (3 M5 candles, target hit first, POI broken, session end).
- `PENDING_ORDER` — monitor tracks the pending order.  On fill → `FILLED`; on expiry or cancellation rule → `CANCELLED/EXPIRED`.  Both store outcome and return to `IDLE` after a small cooldown.
- `FILLED` — monitor watches the open position.  When broker closes (TP hit, SL hit, manual close), outcome is measured and stored.  Then returns to `IDLE`.
- `EXPIRED` / `CANCELLED` — outcome stored, return to `IDLE`.

Because state is stored per instrument, XAU and BTC evolve independently.

## Data & time

- **Source:** MT5 Valetax via `mt5linux` RPyC localhost:8001.  Instrument symbols must include `.vx` suffix.
- **TFs:** M30 native for historical continuity, but state machine logic uses M5 as the trigger.  H1 and H4 candles used for bias / POI / liquidity.  D1 is not used by SMC.
- **Cadence:** `ops/scheduler.py` gains a `minutes_smc` knob; `main.py` loop runs `scheduler.run_candle_loop(..., minutes_smc=5, ...)` when strategy is SMC.
- **Timezone:** assumed UTC from broker in config; will stamp all state transitions in UTC.  `source_tz` goes from placeholder to explicit `UTC` for SMC.

## Core rule summary

### Bias & Protected Level (from spec §4)
Bias is determined from H1 structure (BOS).  Protected level = extreme of the swing before the BOS; if body close crosses the protected extreme, the bias is invalidated and state returns to `IDLE`.  Dealing range is anchored from the protected level out to the external extreme of the impulse BOS; it **does not move** when new bars arrive.

### POI H1 (from spec §5)
Only demand/supply zones created as **Order Block on H1** that contain an FVG/imbalance from the displacement leg.  Freshness means the zone has not been retested (no candle close inside then back out after the OB formed).  Invalid if body close beyond distal edge.  Freshness is tracked per state (`poi_fresh_until` or flag inside `data_json`).

### Liquidity (from spec §8)
Target liquidity is the nearest external H1 level, falling back in order: previous day high/low, session range, equal highs/lows, structural swing.

### Sweep (from spec §8)
A sweep must happen while price is inside the POI H1 bounds.  Wick on M5 extends beyond the M15 liquidity level, close returns.  The sweep extreme (low for BUY, high for SELL) is recorded for SL.

### Displacement & MSS (from spec §9–§10)
Displacement M5 after sweep = close beyond prior structural level leaving FVG.  MSS must break the structural swing that existed **immediately before the sweep**, establishing a new higher high (bullish) or lower low (bearish).  Sequence is enforced by state order (`SWEPT` → `MSS_CONFIRMED`).

### Entry (from spec §11)
- LIMIT at 50 % of the FVG created by the displacement M5 leg.
- **No FVG at MSS bar → no setup.**  No market fallback.
- Expiry conditions (monitor auto-cancels):
  1. 3 closed M5 candles since MSS without fill.
  2. TP liquidity target is hit before limit is filled.
  3. Sweep extreme exceeded by body close.
  4. POI invalidated (distal edge broken).
  5. Session window ends.
  6. News filter deferral (tagged but no block for first 25 trades).

### Stop Loss & Take Profit (from spec §12–§13)
- SL = sweep extreme + 1 × spread (actual current broker spread, not ATR estimate).
- TP = single target at the selected liquidity level.  If distance from entry gives RR < 2.5R → **skip setup**; do not tighten SL to fake RR.  No cap.

### Risk sizing (from spec §14)
- Target 1 % of equity (not balance).
- Min lot increment on Valetax; actual risk may land 1 %–2 %.
- If lot minimum would exceed 2 % risk → **skip setup**.
- Broker contract params pip size / contract size must come from `mt5.symbol_info` at runtime so BTC pip/size do not break sizing.

### Session timing (from spec §3)
- London: 07:00–10:00 UTC.
- NY: 12:00–15:30 UTC.
- Outside these windows, evaluate still runs but no alerts/entries allowed (state can advance but entry gate blocks).

### Daily stop (from spec §16)
Global account counters stored in `daily_stats` table (or simple in-memory today-key with DB backup):
- 2 losses → stop.
- 3 trades entered (filled) → stop.
- Net R ≥ +2.5R across closed trades today → stop.
- Reset at 00:00 UTC (or first tick after).

### Max positions (from spec §16)
One open or pending position per instrument.  Checked before any alert emission or order placement.

## Entry model / order lifecycle

```
Alert Telegram contains:
- Setup detail (bias, POI range, sweep extreme, limit price, SL, TP, RR, session)
- Buttons: [Eksekusi Limit] [Lewati] [Detail]

Owner taps [Eksekusi Limit]:
→ broker.place_limit(symbol, side, volume, limit_price, sl, tp)
→ journal row created with status = PENDING, entry_type = LIMIT
→ monitor watches by ticket

If filled by broker:
→ journal status = FILLED, start tracking MAE/MFE

If any expiry condition met:
→ broker.cancel(ticket) if still pending
→ journal status = CANCELLED/EXPIRED, simulate outcome as “missed”
→ state returns to IDLE
```

The broker module must gain `place_limit(..., type=ORDER_TYPE_BUY_LIMIT or SELL_LIMIT)`.  If MT5 returns an error (invalid price, off quotes), journal the error and notify Telegram with a short message.

## Journal & database changes

### Schema additions
All additions inside WAL SQLite, one connection per thread.

**Table `alerts`** add columns:
- `symbol` TEXT — for dedup and stats split.
- `risk_money` REAL
- `risk_pct` REAL
- `spread` REAL (recorded at alert time)
- `lot` REAL
- `entry_type` TEXT (`LIMIT` or `MARKET`)
- `status` TEXT (`PENDING`, `FILLED`, `CANCELLED`, `EXPIRED`)
- `state_snapshot` TEXT (JSON of strategy parameters used at generation)
- `rr_planned` REAL (actual entry→TP / entry→SL at alert time)
- `rr_journal` REAL (redundancy for exact RR stored at emission)
- `news_filter_applied` BOOLEAN default false for block 1.

**Table `outcomes`** add columns:
- `result_r` REAL
- `mae` REAL (max adverse excursion in price terms)
- `mfe` REAL (max favorable excursion)
- `classification` TEXT (`VALID_WIN`, `VALID_LOSS`, `INVALID_SETUP`)
- `rr_actual` REAL

**Backwards compatibility:** existing rows keep NULLs; new rows populate.  Migration is a one-time `ALTER TABLE`.  If column already exists no-op.

### Dedup fix
`candle_sent(candle_id, direction)` must become `candle_sent(symbol, candle_id, direction)` so XAU and BTC same candle do not suppress each other.

### Shadow outcome fix
Alerts inserted with `sent = 0` (shadow/AI grading) must still have simulated outcomes inside monitor.  Change `run_pass` to select `sent IN (0, 1)` where no ticket exists, simulate vs reference TP/SL, and store outcome so AI grading correlation can proceed.

### Parameter freeze enforcement
When config changes mid-block, engine must detect the mismatch between `state_snapshot` version and current config version, log a warning, and refuse to generate new alerts until the state snapshot matches the running config.  In practice this means strategy `version` is frozen per 25-trade block.

## Execution / broker changes

1. **Delete** `trend_pullback` references in `main.py`, config, and `engine/strategy.py`.
2. **Rename** stateless `engine/smc.py` to `engine/smc_prescreen_old.py` for reference, then delete once canonical module is verified.
3. **New** `engine/smc_canonical.py` implementing the state machine.
4. **Broker** gains `place_limit()`; `place()` renamed to `place_market()` if still needed (not used by SMC, but keep for future).
5. **Monitor** `manage_positions` / `pending_lifecycle` wired into the 60 s loop for real cancel/fill detection.
6. **Telegram** buttons update: `Eksekusi Limit` instead of old generic label; `Lewati` tag row as skipped.

## Guardrails & safety

- `execution.enabled` becomes `true` only after the activation gate (below).  Before that it stays `false`; Telegram buttons show disabled state.
- Bot verifies account is **demo** before accepting any broker order.  If account type != demo, refuse execution and log alarm.
- `allow_short: true` during demo data collection.  Clear comment in config: “SELL = experiment; set `false` before LIVE.”
- News filter deferred, but config still carries `news.enabled: false` with description.  When `news.enabled` flips to `true`, `ops/news.py` is expected to exist.

## Activation gate before demo execution

Before `execution.enabled` may be set to `true`, the following must pass:

1. `python engine/smc_canonical.py` → all internal `demo()` assertions pass.
2. `python -m compileall .` → zero syntax errors.
3. `python main.py once --dry` → runs through full path with live MT5 data, produces alert objects without sending Telegram or placing orders.  No exceptions, no state machine crash.
4. Manual inspection of ≥ 10 emitted alerts against `strategy/xauusd-smc-trading-system.md` §18 criteria; owner confirms rule adherence ≥ 90 %.
5. Snapshot schema migration applied cleanly to existing db (or new db created for demo block).
6. `config.yaml` reviewed: `execution.enabled: true`, `allow_short: true`, `demo_verified: true`.

After gate passed, first 25-trade block runs.  Stats must be reviewed before the next 25-trade block begins.

## Testing convention

- Every new module has a runnable `demo()` at the bottom (assert-based, no pytest).
- State machine tested with synthetic candle fixtures that play back sequences:
  - sweep → MSS → fill
  - sweep → MSS → expiry (3 candle timeout)
  - sweep → MSS → POI broken → cancel
  - protected violation during BIAS_OK → return IDLE
- Fixture generated from arrays of OHLC; not fetched from MT5 during test.
- Aggregate: run all module demos, then `python -m compileall`.

## File changes summary

| File | Action |
|---|---|
| `config.yaml` | Remove `trend_pullback` knobs; set `strategy: smc_canonical`; add `minutes_smc: 5`; session windows `[[7,0,10,0],[12,0,15,30]]`; add `execution.enabled: false`, `demo_verified: false`, freeze version. |
| `main.py` | Delete strategy factory switch; always instantiate `smc_canonical`.  Pass `direction` from config enforced.  Use `minutes_smc` cadence.  Wire `pending_lifecycle` from monitor. |
| `engine/strategy.py` | Delete `TrendPullback` class and `Strategy` protocol if no other user.  Keep only if needed by old code during transition. |
| `engine/smc.py` | Rename to `engine/smc_prescreen_old.py` then delete after canonical is verified. |
| `engine/smc_canonical.py` | New state machine implementation per this spec. |
| `engine/models.py` | Add `entry_type`, `status`, `rr_planned`, `risk_money`, `risk_pct`, `spread`, `lot`, `symbol`.  Remove trend-specific fields if safe. |
| `execute/broker.py` | Add `place_limit()`, `cancel()`.  Verify demo guard. |
| `monitor/watcher.py` | Wire `pending_lifecycle` into 60 s loop.  Track fills via broker history.  Monitor daily stop counters.  Simulate shadow outcomes (`sent IN (0,1)`). |
| `journal/db.py` | Schema migration + new columns.  Fix dedup with symbol.  Add `daily_stats` helper. |
| `delivery/telegram.py` | Update button labels/states for limit orders.  Send disabled message if execution off. |
| `delivery/callbacks.py` | Handle `Eksekusi Limit`; call `broker.place_limit()`.  Validate owner + daily stop + max positions. |
| `ops/scheduler.py` | Accept `minutes` param override for SMC cadence. |

## Risks & deferrals

- **News filter (deferred):** first 25-trade results explicitly tagged as incomplete validation.
- **State machine complexity:** more code than pre-screen.  Mitigated by `demo()` fixtures and gate checklist.
- **Broker limit order reliability:** MT5 via RPyC may have latency; monitor must robustly handle `ORDER_TIME_GTD` / expiry duplicate.
- **Daily stop edge cases:** if monitor restarts mid-day, it must reconstruct today’s counters from `journal/outcomes` before allowing new entries.  Implement reconstruct-on-boot.

## Acceptance criteria (spec §21 adapted)

- 100-trade demo block (XAU + BTC combined or split).
- Journals must contain `result_r`, `classification`, `rr_planned` on every closed trade.
- Expectancy > 0R, PF > 1, rule adherence ≥ 90 %.
- No config change mid-25-trade block (enforced by version mismatch guard).
- Drawdown tracked from journal; max acceptable set by owner before block starts.

---
Spec self-review: no TBD/TODO placeholders, no contradictions with owner decisions above, scope is single implementation plan (state machine + plumbing).