# Canonical SMC Trading System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `trend_pullback` and the stateless `smc_prescreen` with a single canonical, stateful SMC strategy (`smc_canonical`) driving M5-cadence alerts, one-tap pending-limit execution on a demo account, and a spec-faithful journal for XAUUSD.vx + BTCUSD.vx.

**Architecture:** Single Python process, three threads (scheduler M5, monitor 60s, telegram poll). A per-instrument state machine persisted in SQLite advances IDLE → BIAS_OK → POI_TAGGED → SWEPT → MSS_CONFIRMED → PENDING_ORDER → FILLED/EXPIRED/CANCELLED. Broker gains pending-limit + cancel. Journal schema expands to record RR, risk, spread, lot, MAE/MFE, classification, and per-alert parameter snapshot.

**Tech Stack:** Python 3.11, pandas/numpy (no `ta`), SQLite WAL, MT5 via mt5linux RPyC, Telegram long-poll (urllib). No new dependencies.

## Global Constraints

- All thresholds are knobs in `config.yaml`. Never hardcode. (CLAUDE.md)
- Cross-platform: dev on Windows, deploy on Linux. No Unix-only path assumptions.
- Every core module keeps a runnable `demo()` self-check using `assert`; no pytest framework. Run with `python -m <module>`.
- Instrument symbols must carry the `.vx` suffix (`XAUUSD.vx`, `BTCUSD.vx`).
- Scope: XAUUSD.vx + BTCUSD.vx, **identical rule set**, stats split per instrument.
- Session windows (UTC, minute precision): London 07:00–10:00, NY 12:00–15:30.
- Model: set-and-forget — ONE SL, ONE TP, no trailing/BE/partial.
- Risk: 1% equity, actual up to 2% (lot min 0.01); skip if lot-min > 2%. Min RR 2.5R, no cap.
- Daily stop (global account): 2 losses OR 3 trades OR net ≥ +2.5R → stop until next UTC day.
- Max one open-or-pending position per instrument.
- News filter DEFERRED for block 1; every alert logged with `news_filter_applied = 0`.
- Execution enabled on **demo only**; broker verifies account is demo before any order.
- SELL allowed during demo data collection (`allow_short: true`); comment reminder to lock before LIVE.
- Broker timestamps are UTC+`server_utc_offset` (currently +2); convert to UTC before session checks.
- Canonical spec: `strategy/xauusd-smc-trading-system.md` (primary), `strategy/smc.md` (supplementary). Section refs below (§N) point there.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/smc_canonical.py` (new) | State machine + pure detection helpers (bias, dealing range anchored, POI H1 OB+FVG, sweep-in-POI, MSS pre-sweep, 50% FVG entry, sweep-extreme SL, liquidity TP, RR). Owns `SmcCanonical` class implementing `evaluate()` returning a `Setup` with pending-limit fields. |
| `engine/models.py` (modify) | Extend `Setup` with `entry_type`, `risk_money`, `risk_pct`, `spread`, `lot`, `rr_planned`; add `SmcState` dataclass. |
| `execute/broker.py` (modify) | `place_limit()`, `cancel_order()`, `is_demo_account()`, `current_spread()`, `equity_risk_amount()`. Keep `place()` (market) for reference but unused by SMC. |
| `monitor/watcher.py` (modify) | Wire pending lifecycle (real cancel/fill), reconstruct daily stats on boot, simulate shadow outcomes (`sent IN (0,1)`). Remove trailing calls for SMC (guarded by `execution.trailing:false`). |
| `journal/db.py` (modify) | Schema migration (new columns), symbol-aware dedup, `daily_stats` helpers, state persistence (`smc_state`), pending status transitions, parameter snapshot. |
| `delivery/telegram.py` (modify) | Alert format for single-TP limit orders; `Eksekusi Limit` button; disabled-exec message. |
| `delivery/callbacks.py` (modify) | Handle `exec:` via `place_limit()`; daily-stop + max-position + demo guards. |
| `ops/scheduler.py` (modify) | `run_candle_loop` accepts arbitrary `minutes` (already does); add `next_tick` M5 test. |
| `config.yaml` (modify) | Remove `strategy.params`/`smc` trend knobs, add `smc_canonical` block, M5 cadence, session windows, `execution.enabled`, `demo_verified`, `news`. |
| `main.py` (modify) | Delete strategy factory; instantiate `SmcCanonical` only; M5 cadence; wire pending lifecycle + daily-stats reconstruct. |
| `engine/strategy.py`, `engine/smc.py` (delete) | Removed after canonical verified. |

---

## Task 1: Extend models (`Setup` + `SmcState`)

**Files:**
- Modify: `engine/models.py`

**Interfaces:**
- Produces: `Setup(... entry_type: str, risk_money: float, risk_pct: float, spread: float, lot: float, rr_planned: float ...)`; new `SmcState(symbol, state, data, updated_at)` dataclass with `to_json()`/`from_json()`.

- [ ] **Step 1: Write the failing test.** Append to `engine/models.py` `demo()` (or create if none):

```python
def demo():
    s = Setup("XAUUSD.vx", "BUY", "M5", 2980.0, 2985.0, 2970.0, [3010.0],
              "HIGH_CONF", 5, "smc buy", {"bias": "bullish"},
              experimental=False, entry_type="LIMIT",
              risk_money=10.0, risk_pct=1.0, spread=0.2, lot=0.01, rr_planned=3.0)
    assert s.entry_type == "LIMIT"
    assert s.rr_planned == 3.0 and s.lot == 0.01
    assert abs(s.rr - 3.0) < 1e-9  # single-TP rr property

    st = SmcState("XAUUSD.vx", "SWEPT", {"sweep_extreme": 2969.0, "bias": "bullish"})
    blob = st.to_json()
    st2 = SmcState.from_json("XAUUSD.vx", "SWEPT", blob)
    assert st2.data["sweep_extreme"] == 2969.0
    print("[OK] models: Setup extras + SmcState round-trip")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m engine.models`  Expected: FAIL (`Setup() got unexpected keyword` / `SmcState` undefined).

- [ ] **Step 3: Implement.** In `engine/models.py`, extend `Setup` (keep existing fields; add new ones with defaults so old callers still work) and add `SmcState`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
import json
import pandas as pd


@dataclass
class Bundle:
    symbol: str
    price: float
    tf: dict[str, pd.DataFrame]
    sources: dict[str, str] = field(default_factory=dict)

    def df(self, timeframe: str) -> pd.DataFrame | None:
        return self.tf.get(timeframe)


@dataclass
class Setup:
    symbol: str
    direction: str
    tf: str
    entry_low: float
    entry_high: float
    sl: float
    tp: list[float]
    tier: str
    score: int
    reason: str
    gates: dict = field(default_factory=dict)
    experimental: bool = False
    entry_type: str = "LIMIT"        # LIMIT (SMC) | MARKET
    entry: float = 0.0               # 50% FVG limit price (0 = use entry_high/low)
    risk_money: float = 0.0
    risk_pct: float = 0.0
    spread: float = 0.0
    lot: float = 0.0
    rr_planned: float = 0.0          # actual entry->TP / entry->SL at emit

    @property
    def rr(self) -> float:
        if self.rr_planned:
            return round(self.rr_planned, 2)
        entry = self.entry or (self.entry_high if self.direction == "BUY" else self.entry_low)
        risk = abs(entry - self.sl)
        return round(abs(self.tp[0] - entry) / risk, 2) if risk else 0.0


@dataclass
class SmcState:
    symbol: str
    state: str                        # IDLE|BIAS_OK|POI_TAGGED|SWEPT|MSS_CONFIRMED|PENDING_ORDER|FILLED|EXPIRED|CANCELLED
    data: dict = field(default_factory=dict)
    updated_at: str = ""

    def to_json(self) -> str:
        return json.dumps(self.data)

    @classmethod
    def from_json(cls, symbol: str, state: str, blob: str | None, updated_at: str = "") -> "SmcState":
        return cls(symbol, state, json.loads(blob) if blob else {}, updated_at)
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m engine.models`  Expected: PASS `[OK] models: ...`.

- [ ] **Step 5: Commit.**

```bash
git add engine/models.py
git commit -m "feat(models): Setup pending-limit fields + SmcState"
```

---

## Task 2: Session windows with minute precision

**Files:**
- Create: `engine/smc_canonical.py` (start the module with helpers)
- Test: inside `engine/smc_canonical.py` `demo()`

**Interfaces:**
- Produces: `in_session(ts, sessions_utc, server_utc_offset) -> bool` where `sessions_utc` is `[[h1,m1,h2,m2], ...]` half-open `[start,end)` in UTC minutes.

- [ ] **Step 1: Write the failing test.** Create `engine/smc_canonical.py` with a module docstring and a `demo()` containing:

```python
def demo():
    import pandas as pd
    sess = [[7, 0, 10, 0], [12, 0, 15, 30]]
    T = lambda h, m: pd.Timestamp(f"2026-01-05 {h:02d}:{m:02d}", tz="UTC")
    # offset 0
    assert in_session(T(7, 0), sess, 0)          # London start inclusive
    assert not in_session(T(10, 0), sess, 0)     # London end exclusive
    assert in_session(T(15, 29), sess, 0)        # NY still in
    assert not in_session(T(15, 30), sess, 0)    # NY end exclusive
    assert not in_session(T(11, 0), sess, 0)     # gap between sessions
    # broker offset +2: candle stamp 09:00 broker = 07:00 UTC -> London start
    assert in_session(T(9, 0), sess, 2)
    assert not in_session(T(8, 59), sess, 2)     # 06:59 UTC
    print("[OK] in_session: minute precision + offset")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m engine.smc_canonical`  Expected: FAIL (`in_session` undefined).

- [ ] **Step 3: Implement `in_session`.** Add near the top of `engine/smc_canonical.py`:

```python
from __future__ import annotations
import pandas as pd
from engine.models import Bundle, Setup, SmcState
from engine import indicators as ind


def in_session(ts: pd.Timestamp, sessions_utc: list[list[int]], server_utc_offset: int = 0) -> bool:
    """True if ts (broker candle time) falls in any [start,end) UTC window.
    sessions_utc entries are [start_h, start_m, end_h, end_m]."""
    utc_min = ((ts.hour - server_utc_offset) % 24) * 60 + ts.minute
    for sh, sm, eh, em in sessions_utc:
        if sh * 60 + sm <= utc_min < eh * 60 + em:
            return True
    return False
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m engine.smc_canonical`  Expected: PASS `[OK] in_session: ...`.

- [ ] **Step 5: Commit.**

```bash
git add engine/smc_canonical.py
git commit -m "feat(smc): minute-precision session gate"
```

---

## Task 3: Bias H1 with protected-level veto

**Files:**
- Modify: `engine/smc_canonical.py`

**Interfaces:**
- Consumes: `indicators.swings`.
- Produces: `detect_bias(h1, p) -> tuple[str, bool, float]` returning `(bias, bos_confirmed, protected_price)`; `bias_alive(h1, bias, protected, p) -> bool` returns False if a body close violated the protected level.

- [ ] **Step 1: Write the failing test.** Append to `demo()`:

```python
    p = SMC_DEFAULTS
    rows = [(100, 100.4, 99.6, 100)] * 38
    rows[10] = (100, 100.5, 97.0, 100)      # swing low @10
    rows[20] = (100, 103.0, 100.0, 100)     # swing high @20
    rows += [(100, 100.5, 99.6, 100), (100, 104.5, 100.0, 104.2)]  # BOS up
    dfb = _mk(rows, "1h")
    bias, bos, prot = detect_bias(dfb, p)
    assert bias == "bullish" and bos, (bias, bos)
    assert bias_alive(dfb, bias, prot, p)   # protected low intact
    # now append a candle that closes below protected low -> bias dead
    broke = dfb.copy()
    last_ts = broke.index[-1] + (broke.index[-1] - broke.index[-2])
    broke.loc[last_ts] = [100, 100.0, prot - 5, prot - 4, 1000.0]
    assert not bias_alive(broke, "bullish", prot, p)
    print("[OK] detect_bias + protected veto")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m engine.smc_canonical`  Expected: FAIL (`detect_bias`/`SMC_DEFAULTS`/`_mk` undefined).

- [ ] **Step 3: Implement.** Add `SMC_DEFAULTS`, `_mk`, `_closed`, `_last_swings`, `detect_bias` (port from `engine/smc.py:58-92`), and new `bias_alive`:

```python
SMC_DEFAULTS = dict(
    swing_k=2, atr_period=14, disp_body_ratio=0.65, disp_atr_mult=1.5,
    rr_min=2.5, rr_aplus=3.0, struct_lookback=40, trigger_lookback=12,
    sweep_lookback=20, sessions_utc=[[7, 0, 10, 0], [12, 0, 15, 30]],
    server_utc_offset=2, require_session=True, poi_lookback=60,
    sl_spread_mult=1.0, expiry_candles=3,
)


def _closed(df):
    return df.iloc[:-1] if df is not None and len(df) > 1 else df


def _last_swings(df, k):
    sh, sl = ind.swings(df, k)
    highs = [df.index.get_loc(i) for i in sh[sh].index]
    lows = [df.index.get_loc(i) for i in sl[sl].index]
    return highs, lows


def detect_bias(df, p):
    win = df.iloc[-p["struct_lookback"]:] if len(df) > p["struct_lookback"] else df
    highs, lows = _last_swings(win, p["swing_k"])
    if len(highs) < 1 or len(lows) < 1:
        return "none", False, 0.0
    hv, lv, cv = win["high"].values, win["low"].values, win["close"].values
    n = len(win)
    last_bos_i, last_bias, protected = -1, "none", 0.0
    for i in range(n):
        prior_h = [hi for hi in highs if hi + p["swing_k"] < i]
        prior_l = [li for li in lows if li + p["swing_k"] < i]
        if prior_h:
            sh_i = prior_h[-1]
            if cv[i] > hv[sh_i] and i > last_bos_i:
                pl = [li for li in lows if li < sh_i]
                last_bos_i, last_bias = i, "bullish"
                protected = float(lv[pl[-1]]) if pl else float(lv[:sh_i].min() if sh_i > 0 else lv[0])
        if prior_l:
            sl_i = prior_l[-1]
            if cv[i] < lv[sl_i] and i > last_bos_i:
                ph = [hi for hi in highs if hi < sl_i]
                last_bos_i, last_bias = i, "bearish"
                protected = float(hv[ph[-1]]) if ph else float(hv[:sl_i].max() if sl_i > 0 else hv[0])
    return last_bias, last_bias != "none", protected


def bias_alive(df, bias, protected, p):
    """§4: bias invalid if a body close crossed the protected level."""
    if bias == "none" or protected == 0.0:
        return False
    win = df.iloc[-p["struct_lookback"]:] if len(df) > p["struct_lookback"] else df
    closes = win["close"].values
    if bias == "bullish":
        return not bool((closes < protected).any())
    return not bool((closes > protected).any())


def _mk(rows, freq="5min"):
    idx = pd.date_range("2026-01-05 08:00", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1000.0
    return df
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m engine.smc_canonical`  Expected: PASS both prior lines.

- [ ] **Step 5: Commit.**

```bash
git add engine/smc_canonical.py
git commit -m "feat(smc): H1 bias + protected-level veto"
```

---

## Task 4: Anchored dealing range + premium/discount

**Files:**
- Modify: `engine/smc_canonical.py`

**Interfaces:**
- Produces: `dealing_range(h1, bias, protected, p) -> tuple[float, float]` anchored protected→external impulse extreme; `pd_zone(price, lo, hi) -> str`.

- [ ] **Step 1: Write the failing test.** Append to `demo()`:

```python
    lo, hi = dealing_range(dfb, "bullish", prot, p)
    assert lo == prot, (lo, prot)                  # bullish anchor = protected low
    assert hi >= 104.2                              # external high from impulse
    assert pd_zone(lo + 0.1 * (hi - lo), lo, hi) == "discount"
    assert pd_zone(lo + 0.9 * (hi - lo), lo, hi) == "premium"
    assert pd_zone(lo + 0.5 * (hi - lo), lo, hi) == "equilibrium"
    print("[OK] dealing_range anchored + pd_zone")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m engine.smc_canonical`  Expected: FAIL (`dealing_range`/`pd_zone` undefined).

- [ ] **Step 3: Implement.**

```python
def dealing_range(df, bias, protected, p):
    """§5: anchor = protected level -> external extreme of the BOS impulse.
    Bullish: protected low -> highest high after protected. Bearish: mirror."""
    win = df.iloc[-p["struct_lookback"]:] if len(df) > p["struct_lookback"] else df
    if bias == "bullish":
        lo = protected
        hi = float(win["high"].max())
        return lo, hi
    hi = protected
    lo = float(win["low"].min())
    return lo, hi


def pd_zone(price, lo, hi):
    if hi <= lo:
        return "none"
    frac = (price - lo) / (hi - lo)
    if frac < 0.45:
        return "discount"
    if frac > 0.55:
        return "premium"
    return "equilibrium"
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m engine.smc_canonical`  Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add engine/smc_canonical.py
git commit -m "feat(smc): anchored dealing range + premium/discount"
```

---

## Task 5: POI H1 (OB + FVG, fresh, distal invalidation)

**Files:**
- Modify: `engine/smc_canonical.py`

**Interfaces:**
- Consumes: `indicators.fvg_zones`, `indicators.displacement`, `indicators.swings`.
- Produces: `find_poi(h1, bias, lo, hi, p) -> dict | None` returning `{"proximal": float, "distal": float, "origin_idx": int}`; `poi_fresh(h1, poi, bias) -> bool`; `poi_invalidated(h1, poi, bias) -> bool` (body close beyond distal edge after origin).

- [ ] **Step 1: Write the failing test.** Append to `demo()`:

```python
    # Build H1 with a bullish OB+FVG in discount: down base candle, then displacement up leaving FVG
    prows = [(100, 100.3, 99.7, 100)] * 30
    prows[14] = (100.5, 100.6, 99.0, 99.2)          # bearish base (OB origin) in discount
    prows[15] = (99.2, 103.5, 99.2, 103.3)          # displacement up
    prows[16] = (103.3, 104.0, 103.1, 103.8)        # gap: high[14]=100.6 < low[16]=103.1 -> FVG
    poih1 = _mk(prows, "1h")
    lo2, hi2 = 99.0, 104.0
    poi = find_poi(poih1, "bullish", lo2, hi2, p)
    assert poi is not None and poi["proximal"] > poi["distal"], poi
    assert poi_fresh(poih1, poi, "bullish")
    # distal invalidation: append H1 close far below distal
    inv = poih1.copy()
    ts = inv.index[-1] + (inv.index[-1] - inv.index[-2])
    inv.loc[ts] = [100, 100, poi["distal"] - 2, poi["distal"] - 1, 1000.0]
    assert poi_invalidated(inv, poi, "bullish")
    print("[OK] find_poi + fresh + distal invalidation")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m engine.smc_canonical`  Expected: FAIL (`find_poi` undefined).

- [ ] **Step 3: Implement.** Add POI detection. An OB is the last opposite-color candle before a displacement that leaves an FVG; proximal/distal are the OB body/wick edges (bullish: proximal=high of OB, distal=low of OB).

```python
def find_poi(h1, bias, lo, hi, p):
    """§6: OB H1 with same-displacement FVG, sitting on correct P/D side, fresh.
    Returns dict(proximal, distal, origin_idx) or None. Bullish proximal=OB high,
    distal=OB low. Bearish mirror."""
    win = h1.iloc[-p["poi_lookback"]:] if len(h1) > p["poi_lookback"] else h1
    o = win["open"].values; c = win["close"].values
    hv = win["high"].values; lv = win["low"].values
    disp = ind.displacement(win, body_ratio=p["disp_body_ratio"],
                            atr_mult=p["disp_atr_mult"], atr_period=p["atr_period"])
    bull_fvg = ind.fvg_zones(win, bull=(bias == "bullish"))
    fvg_at = {z[0]: z for z in bull_fvg}
    best = None
    for i in range(2, len(win)):
        s = int(disp.iloc[i])
        want = 1 if bias == "bullish" else -1
        if s != want:
            continue
        # FVG left by this displacement is registered at i or i+1 (3-candle gap)
        if i not in fvg_at and (i + 1) not in fvg_at:
            continue
        # OB origin = last opposite-color candle before displacement bar i
        j = i - 1
        while j >= 0:
            opp = (c[j] < o[j]) if bias == "bullish" else (c[j] > o[j])
            if opp:
                break
            j -= 1
        if j < 0:
            continue
        if bias == "bullish":
            proximal, distal = float(hv[j]), float(lv[j])
            mid = (distal + proximal) / 2
            if pd_zone(mid, lo, hi) != "discount":
                continue
        else:
            proximal, distal = float(lv[j]), float(hv[j])
            mid = (distal + proximal) / 2
            if pd_zone(mid, lo, hi) != "premium":
                continue
        best = {"proximal": proximal, "distal": distal, "origin_idx": int(j)}
    return best


def poi_fresh(h1, poi, bias):
    """§6: fresh = price has not closed back into the zone since the OB formed."""
    win = h1
    idx = poi["origin_idx"]
    after = win.iloc[idx + 3:] if len(win) > idx + 3 else win.iloc[len(win):]
    prox, dist = poi["proximal"], poi["distal"]
    zlo, zhi = min(prox, dist), max(prox, dist)
    for _, r in after.iterrows():
        if zlo <= float(r["close"]) <= zhi:
            return False
    return True


def poi_invalidated(h1, poi, bias):
    """§6: invalid if an H1 body close crosses the distal edge after origin."""
    idx = poi["origin_idx"]
    after = h1.iloc[idx + 1:]
    dist = poi["distal"]
    closes = after["close"].values
    if bias == "bullish":
        return bool((closes < dist).any())
    return bool((closes > dist).any())
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m engine.smc_canonical`  Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add engine/smc_canonical.py
git commit -m "feat(smc): H1 POI (OB+FVG, fresh, distal invalidation)"
```

---

## Task 6: Sweep-in-POI + MSS on pre-sweep swing

**Files:**
- Modify: `engine/smc_canonical.py`

**Interfaces:**
- Produces: `swept_in_poi(m15, m5, bias, poi, p) -> tuple[bool, int, float]` returning `(swept, m5_bar, sweep_extreme)`; sweep must occur while M5 price is inside the POI bounds. `mss_after_sweep(m5, bias, sweep_bar, p) -> tuple[bool, float, tuple]` returning `(confirmed, entry_50pct, (fvg_lo, fvg_hi))` where MSS breaks the structural M5 swing formed *before* the sweep and an FVG exists at the displacement leg.

- [ ] **Step 1: Write the failing test.** Append to `demo()`:

```python
    # Sweep inside POI: M15 has a swing low pool; M5 wick pierces then closes back, inside POI zone
    m15rows = [(100, 100.6, 99.7, 100)] * 25
    m15rows[10] = (100, 100.5, 99.0, 100)         # swing low pool @99.0
    m15 = _mk(m15rows, "15min")
    poi2 = {"proximal": 100.2, "distal": 98.8, "origin_idx": 0}   # zone 98.8..100.2
    m5rows = [(100, 100.4, 99.6, 100)] * 6
    m5rows[-4] = (100, 100.2, 98.5, 100.1)        # sweep: low 98.5<99 pool, close 100.1, inside POI
    # displacement up leaving FVG, breaking pre-sweep swing high
    m5rows[-3] = (100.1, 100.2, 99.9, 100.15)
    m5rows[-2] = (100.15, 102.5, 100.1, 102.3)    # big displacement
    m5rows[-1] = (102.3, 102.6, 102.0, 102.4)     # gap over pre-sweep highs
    m5b = _mk(m5rows, "5min")
    sw, bar, ext = swept_in_poi(m15, m5b, "bullish", poi2, p)
    assert sw and ext <= 98.5, (sw, bar, ext)
    ok_mss, entry50, (flo, fhi) = mss_after_sweep(m5b, "bullish", bar, p)
    assert ok_mss and flo < entry50 < fhi, (ok_mss, entry50, flo, fhi)
    print("[OK] sweep-in-POI + MSS pre-sweep swing + 50% FVG")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m engine.smc_canonical`  Expected: FAIL (undefined).

- [ ] **Step 3: Implement.**

```python
def swept_in_poi(m15, m5, bias, poi, p):
    """§8: M5 wick sweeps M15 liquidity while price is inside POI H1 bounds.
    Returns (swept, m5_bar_index_in_trigger_window, sweep_extreme)."""
    if m15 is None or m5 is None or len(m15) < p["sweep_lookback"] or len(m5) < 3:
        return (False, -1, 0.0)
    sh, sl = ind.swings(m15, p["swing_k"])
    win = m5.iloc[-p["trigger_lookback"]:]
    lo_v, hi_v, cl_v = win["low"].values, win["high"].values, win["close"].values
    zlo = min(poi["proximal"], poi["distal"])
    zhi = max(poi["proximal"], poi["distal"])
    for i in range(len(win)):
        # price must be interacting with POI on this bar
        if not (lo_v[i] <= zhi and hi_v[i] >= zlo):
            continue
        if bias == "bullish":
            pools = [float(m15["low"].loc[j]) for j in sl[sl].index]
            if not pools:
                continue
            pool = pools[-1]
            if lo_v[i] < pool and cl_v[i] > pool:
                return (True, i, float(lo_v[i]))
        else:
            pools = [float(m15["high"].loc[j]) for j in sh[sh].index]
            if not pools:
                continue
            pool = pools[-1]
            if hi_v[i] > pool and cl_v[i] < pool:
                return (True, i, float(hi_v[i]))
    return (False, -1, 0.0)


def mss_after_sweep(m5, bias, sweep_bar, p):
    """§9-10: after sweep, displacement breaks the structural M5 swing formed BEFORE
    the sweep, leaving an FVG. Returns (confirmed, entry_50pct_of_fvg, (fvg_lo, fvg_hi))."""
    win = m5.iloc[-p["trigger_lookback"]:]
    n = len(win)
    if sweep_bar < 0 or sweep_bar >= n:
        return (False, 0.0, (0.0, 0.0))
    highs, lows = _last_swings(win, p["swing_k"])
    # structural reference = last confirmed swing BEFORE the sweep bar
    pre_h = [h for h in highs if h + p["swing_k"] < sweep_bar]
    pre_l = [l for l in lows if l + p["swing_k"] < sweep_bar]
    disp = ind.displacement(win, body_ratio=p["disp_body_ratio"],
                            atr_mult=p["disp_atr_mult"], atr_period=p["atr_period"])
    hv, lv, cv = win["high"].values, win["low"].values, win["close"].values
    fvgs = ind.fvg_zones(win, bull=(bias == "bullish"))
    for i in range(sweep_bar + 1, n):
        s = int(disp.iloc[i])
        if bias == "bullish" and s > 0 and pre_h and cv[i] > hv[pre_h[-1]]:
            zs = [z for z in fvgs if z[0] <= i + 1 and z[0] >= sweep_bar]
            if zs:
                _, flo, fhi, mid = zs[-1]
                return (True, float(mid), (float(flo), float(fhi)))
        if bias == "bearish" and s < 0 and pre_l and cv[i] < lv[pre_l[-1]]:
            zs = [z for z in fvgs if z[0] <= i + 1 and z[0] >= sweep_bar]
            if zs:
                _, flo, fhi, mid = zs[-1]
                return (True, float(mid), (float(flo), float(fhi)))
    return (False, 0.0, (0.0, 0.0))
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m engine.smc_canonical`  Expected: PASS. If the synthetic fixture does not trigger, adjust fixture candle values (not the logic) until sweep+MSS fire, keeping the assertion semantics.

- [ ] **Step 5: Commit.**

```bash
git add engine/smc_canonical.py
git commit -m "feat(smc): sweep-in-POI + MSS on pre-sweep swing + 50% FVG entry"
```

---

## Task 7: TP liquidity target, sweep-extreme SL, RR gate

**Files:**
- Modify: `engine/smc_canonical.py`

**Interfaces:**
- Produces: `tp_target(h1, m15, bias, entry, p) -> float | None` (priority external H1 → prev-day HL → session → equal highs → structural swing; nearest opposing liquidity); `build_plan(bias, entry, sweep_extreme, spread, target, p) -> dict | None` returning `{"sl","tp","rr","risk"}` or None if RR < rr_min.

- [ ] **Step 1: Write the failing test.** Append to `demo()`:

```python
    plan = build_plan("bullish", entry=3000.0, sweep_extreme=2990.0, spread=0.2,
                      target=3030.0, p=p)
    assert plan is not None
    assert plan["sl"] == 2990.0 - p["sl_spread_mult"] * 0.2      # sweep low - 1x spread
    assert abs(plan["rr"] - (30.0 / (3000.0 - plan["sl"]))) < 0.01
    # RR < 2.5 -> skip
    assert build_plan("bullish", 3000.0, 2990.0, 0.2, 3010.0, p) is None
    print("[OK] build_plan: sweep-extreme SL + single-TP RR gate")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m engine.smc_canonical`  Expected: FAIL (`build_plan` undefined).

- [ ] **Step 3: Implement.**

```python
def tp_target(h1, m15, bias, entry, p):
    """§13: nearest opposing liquidity, H1 external prioritized over M15 structural."""
    cands = []
    win1 = h1.iloc[-p["struct_lookback"]:] if len(h1) > p["struct_lookback"] else h1
    sh1, sl1 = ind.swings(win1, p["swing_k"])
    if bias == "bullish":
        cands += [float(win1["high"].loc[i]) for i in sh1[sh1].index if float(win1["high"].loc[i]) > entry]
    else:
        cands += [float(win1["low"].loc[i]) for i in sl1[sl1].index if float(win1["low"].loc[i]) < entry]
    if m15 is not None and len(m15) > p["swing_k"] * 2 + 2:
        w15 = m15.iloc[-p["sweep_lookback"] * 4:] if len(m15) > p["sweep_lookback"] * 4 else m15
        sh15, sl15 = ind.swings(w15, p["swing_k"])
        if bias == "bullish":
            cands += [float(w15["high"].loc[i]) for i in sh15[sh15].index if float(w15["high"].loc[i]) > entry]
        else:
            cands += [float(w15["low"].loc[i]) for i in sl15[sl15].index if float(w15["low"].loc[i]) < entry]
    if not cands:
        return None
    return min(cands, key=lambda x: abs(x - entry))


def build_plan(bias, entry, sweep_extreme, spread, target, p):
    """§12-13: SL = sweep extreme ± 1x spread; single TP at target; RR>=rr_min else None."""
    if target is None:
        return None
    buf = p["sl_spread_mult"] * max(spread, 0.0)
    if bias == "bullish":
        sl = sweep_extreme - buf
        risk = entry - sl
        reward = target - entry
    else:
        sl = sweep_extreme + buf
        risk = sl - entry
        reward = entry - target
    if risk <= 0 or reward <= 0:
        return None
    rr = round(reward / risk, 2)
    if rr < p["rr_min"]:
        return None
    return {"sl": round(sl, 3), "tp": [round(target, 3)], "rr": rr, "risk": round(risk, 3)}
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m engine.smc_canonical`  Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add engine/smc_canonical.py
git commit -m "feat(smc): liquidity TP + sweep-extreme SL + RR gate"
```

---

## Task 8: State machine + `SmcCanonical.evaluate`

**Files:**
- Modify: `engine/smc_canonical.py`

**Interfaces:**
- Consumes: all helpers above, `SmcState`.
- Produces: `class SmcCanonical` with `name="smc_canonical"`, `version="1.0"`, and `evaluate(bundle, params, state: SmcState) -> tuple[Setup | None, SmcState]`. The evaluate advances state and, on `MSS_CONFIRMED`, returns a `Setup` (entry_type LIMIT, `entry`=50% FVG, single TP). `spread`/`lot`/`risk_money`/`risk_pct` are filled by the caller (Task 12) which has broker access; evaluate sets `spread=0`, computes `rr_planned`.

- [ ] **Step 1: Write the failing test.** Append to `demo()`:

```python
    # Flat data -> no setup, state stays IDLE, no crash
    flat = _mk([(100, 100.3, 99.7, 100)] * 80, "1h")
    b = Bundle("XAUUSD.vx", price=100.0, tf={
        "H1": flat, "M15": _mk([(100, 100.3, 99.7, 100)] * 80, "15min"),
        "M5": _mk([(100, 100.3, 99.7, 100)] * 80, "5min")})
    strat = SmcCanonical()
    st = SmcState("XAUUSD.vx", "IDLE", {})
    setup, st = strat.evaluate(b, {}, st)
    assert setup is None and st.state == "IDLE", (setup, st.state)
    print("[OK] evaluate(flat) -> None, IDLE")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m engine.smc_canonical`  Expected: FAIL (`SmcCanonical` undefined).

- [ ] **Step 3: Implement the class.** State transitions per spec. On each call it recomputes context and moves forward; on invalidation it steps back. Direction respects `params["direction"]` (`long_only` blocks SELL).

```python
class SmcCanonical:
    name = "smc_canonical"
    version = "1.0"

    def evaluate(self, bundle, params, state):
        p = {**SMC_DEFAULTS, **(params or {})}
        h1 = _closed(bundle.df("H1")); m15 = _closed(bundle.df("M15")); m5 = _closed(bundle.df("M5"))
        if h1 is None or m5 is None or len(h1) < p["struct_lookback"] + 5 or len(m5) < 20:
            return None, state
        d = dict(state.data)
        s = state.state

        bias, bos, protected = detect_bias(h1, p)
        direction_cfg = (params or {}).get("direction", "both")
        if bias == "none" or not bos or not bias_alive(h1, bias, protected, p):
            return None, SmcState(state.symbol, "IDLE", {})
        if bias == "bearish" and direction_cfg == "long_only":
            return None, SmcState(state.symbol, "IDLE", {})
        lo, hi = dealing_range(h1, bias, protected, p)

        poi = find_poi(h1, bias, lo, hi, p)
        if poi is None or not poi_fresh(h1, poi, bias) or poi_invalidated(h1, poi, bias):
            return None, SmcState(state.symbol, "BIAS_OK", {"bias": bias})

        swept, bar, extreme = swept_in_poi(m15, m5, bias, poi, p)
        if not swept:
            return None, SmcState(state.symbol, "POI_TAGGED",
                                  {"bias": bias, "poi": poi})

        confirmed, entry50, (flo, fhi) = mss_after_sweep(m5, bias, bar, p)
        if not confirmed:
            return None, SmcState(state.symbol, "SWEPT",
                                  {"bias": bias, "poi": poi, "sweep_extreme": extreme})

        target = tp_target(h1, m15, bias, entry50, p)
        plan = build_plan(bias, entry50, extreme, 0.0, target, p)
        if plan is None:
            return None, SmcState(state.symbol, "SWEPT",
                                  {"bias": bias, "poi": poi, "sweep_extreme": extreme})

        in_sess = in_session(m5.index[-1], p["sessions_utc"], p["server_utc_offset"])
        if p["require_session"] and not in_sess:
            return None, SmcState(state.symbol, "MSS_CONFIRMED",
                                  {"bias": bias, "poi": poi, "sweep_extreme": extreme,
                                   "entry": entry50})

        direction = "BUY" if bias == "bullish" else "SELL"
        rr = plan["rr"]
        tier = "HIGH_CONF" if rr >= p["rr_aplus"] else "NORMAL"
        setup = Setup(
            symbol=bundle.symbol, direction=direction, tf="M5",
            entry_low=round(flo, 3), entry_high=round(fhi, 3),
            entry=round(entry50, 3), sl=plan["sl"], tp=plan["tp"],
            tier=tier, score=7, rr_planned=rr, entry_type="LIMIT",
            experimental=(direction == "SELL"),
            reason=f"SMC {bias} · POI · sweep · MSS · RR{rr}",
            gates={"bias": bias, "bos": bos, "poi_fresh": True, "sweep": True,
                   "mss": True, "rr": rr, "session": in_sess,
                   "sweep_extreme": extreme, "entry": entry50},
        )
        new_state = SmcState(state.symbol, "MSS_CONFIRMED",
                             {"bias": bias, "poi": poi, "sweep_extreme": extreme,
                              "entry": entry50, "alerted_candle": str(m5.index[-1])})
        return setup, new_state
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m engine.smc_canonical`  Expected: PASS all `[OK]` lines.

- [ ] **Step 5: Add the `if __name__` guard and commit.** Ensure the file ends with:

```python
if __name__ == "__main__":
    demo()
```

```bash
git add engine/smc_canonical.py
git commit -m "feat(smc): SmcCanonical state machine evaluate()"
```

---

## Task 9: Journal schema migration + symbol dedup + state + daily stats

**Files:**
- Modify: `journal/db.py`

**Interfaces:**
- Consumes: `Setup` (with new fields).
- Produces:
  - `record(setup, candle_id, strategy, version, sent, suppress, ts, symbol_dedup=True)` now stores `symbol, entry_type, status, rr_planned, risk_money, risk_pct, spread, lot, news_filter_applied, state_snapshot`.
  - `candle_sent(symbol, candle_id, direction) -> bool` (symbol-aware).
  - `set_status(alert_id, status)`; `set_pending(alert_id, ticket)`.
  - `save_state(symbol, state, data_json)`, `load_state(symbol) -> (state, data_json)`.
  - `daily_counts(day_utc) -> dict(losses, trades, net_r)`; `record_outcome_r(alert_id, result, hit, exit_price, profit, result_r, mae, mfe, classification)`.

- [ ] **Step 1: Write the failing test.** Extend `journal/db.py` `demo()`:

```python
    # symbol-aware dedup
    j.record(s, "CDUP", "smc_canonical", "1.0", sent=True, symbol_ovr="XAUUSD.vx")
    assert j.candle_sent("XAUUSD.vx", "CDUP", "BUY")
    assert not j.candle_sent("BTCUSD.vx", "CDUP", "BUY")   # other symbol not suppressed
    # state persistence
    j.save_state("XAUUSD.vx", "SWEPT", '{"sweep_extreme": 2990.0}')
    stt, blob = j.load_state("XAUUSD.vx")
    assert stt == "SWEPT" and "2990" in blob
    # daily counts
    from ops.clock import now_wib
    print("[OK] journal: symbol dedup + state + migration")
```

*(Keep the existing demo assertions; only the `candle_sent` call signatures inside the old demo must be updated to the new 3-arg form. Update those lines too.)*

- [ ] **Step 2: Run to verify it fails.** Run: `python -m journal.db`  Expected: FAIL (`candle_sent` arity / `save_state` undefined).

- [ ] **Step 3: Implement.** In `journal/db.py`:

1. Add to `_SCHEMA` (after `config_kv`):

```sql
CREATE TABLE IF NOT EXISTS smc_state (
    symbol     TEXT PRIMARY KEY,
    state      TEXT NOT NULL,
    data_json  TEXT,
    updated_at TEXT
);
```

2. Extend `_migrate` with idempotent `ALTER TABLE` for each new column:

```python
def _migrate(self, c):
    stmts = (
        "ALTER TABLE alerts ADD COLUMN ticket INTEGER",
        "ALTER TABLE outcomes ADD COLUMN profit REAL",
        "ALTER TABLE alerts ADD COLUMN entry_type TEXT",
        "ALTER TABLE alerts ADD COLUMN rr_planned REAL",
        "ALTER TABLE alerts ADD COLUMN risk_money REAL",
        "ALTER TABLE alerts ADD COLUMN risk_pct REAL",
        "ALTER TABLE alerts ADD COLUMN spread REAL",
        "ALTER TABLE alerts ADD COLUMN lot REAL",
        "ALTER TABLE alerts ADD COLUMN news_filter_applied INTEGER DEFAULT 0",
        "ALTER TABLE alerts ADD COLUMN state_snapshot TEXT",
        "ALTER TABLE outcomes ADD COLUMN result_r REAL",
        "ALTER TABLE outcomes ADD COLUMN mae REAL",
        "ALTER TABLE outcomes ADD COLUMN mfe REAL",
        "ALTER TABLE outcomes ADD COLUMN classification TEXT",
    )
    for stmt in stmts:
        try:
            c.execute(stmt)
        except sqlite3.OperationalError:
            pass
```

3. Update `record()` to persist the new fields and accept a `symbol_ovr` (used by tests) — default to `setup.symbol`. Include `entry_type`, `rr_planned`, `risk_money`, `risk_pct`, `spread`, `lot`, `news_filter_applied`, `state_snapshot`:

```python
def record(self, setup, candle_id, strategy, version, sent, suppress=None, ts=None,
           news_filter_applied=0, state_snapshot=None, symbol_ovr=None):
    sym = symbol_ovr or setup.symbol
    with self._c() as c:
        cur = c.execute(
            """INSERT INTO alerts(ts_wib,symbol,direction,tf,candle_id,strategy,version,
                   tier,score,entry_low,entry_high,sl,tp_json,rr,reason,gates_json,sent,suppress,status,
                   entry_type,rr_planned,risk_money,risk_pct,spread,lot,news_filter_applied,state_snapshot)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ts or wib_str(), sym, setup.direction, setup.tf, candle_id, strategy, version,
             setup.tier, setup.score, setup.entry_low, setup.entry_high, setup.sl,
             json.dumps(setup.tp), setup.rr, setup.reason, json.dumps(setup.gates),
             1 if sent else 0, suppress, "ACTIVE" if sent else "CLOSED",
             getattr(setup, "entry_type", "LIMIT"), getattr(setup, "rr_planned", 0.0),
             getattr(setup, "risk_money", 0.0), getattr(setup, "risk_pct", 0.0),
             getattr(setup, "spread", 0.0), getattr(setup, "lot", 0.0),
             int(news_filter_applied), state_snapshot))
        return cur.lastrowid
```

4. Change `candle_sent` to symbol-aware:

```python
def candle_sent(self, symbol, candle_id, direction) -> bool:
    with self._c() as c:
        r = c.execute("SELECT 1 FROM alerts WHERE symbol=? AND candle_id=? AND direction=? AND sent=1 LIMIT 1",
                      (symbol, candle_id, direction)).fetchone()
        return r is not None
```

5. Add state + status + daily-stats helpers:

```python
def save_state(self, symbol, state, data_json):
    with self._c() as c:
        c.execute("INSERT OR REPLACE INTO smc_state VALUES(?,?,?,?)",
                  (symbol, state, data_json, wib_str()))

def load_state(self, symbol):
    with self._c() as c:
        r = c.execute("SELECT state, data_json FROM smc_state WHERE symbol=?", (symbol,)).fetchone()
        return (r["state"], r["data_json"]) if r else ("IDLE", None)

def set_status(self, alert_id, status):
    with self._c() as c:
        c.execute("UPDATE alerts SET status=? WHERE id=?", (status, int(alert_id)))

def pending_alerts(self):
    with self._c() as c:
        return c.execute("SELECT * FROM alerts WHERE status='PENDING' AND ticket IS NOT NULL").fetchall()

def record_outcome_r(self, alert_id, result, hit, exit_price, profit=None,
                     result_r=None, mae=None, mfe=None, classification=None):
    with self._c() as c:
        c.execute("""INSERT OR REPLACE INTO outcomes
                     (alert_id,result,hit,exit_price,exit_ts_wib,profit,result_r,mae,mfe,classification)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (alert_id, result, hit, exit_price, wib_str(), profit, result_r, mae, mfe, classification))
        c.execute("UPDATE alerts SET status='CLOSED' WHERE id=?", (alert_id,))

def daily_counts(self, day_prefix):
    """day_prefix like '21/07/2026'. Returns dict(losses, trades, net_r) for filled trades."""
    with self._c() as c:
        rows = c.execute("""SELECT o.result, o.result_r FROM outcomes o
                            JOIN alerts a ON a.id=o.alert_id
                            WHERE a.ticket IS NOT NULL AND a.ts_wib LIKE ?""",
                         (day_prefix + "%",)).fetchall()
    losses = sum(1 for r in rows if r["result"] == "LOSS")
    trades = len(rows)
    net_r = sum(float(r["result_r"] or 0.0) for r in rows)
    return {"losses": losses, "trades": trades, "net_r": round(net_r, 2)}
```

6. Update the existing `label_outcome` `INSERT` to match the widened `outcomes` column list (add trailing NULLs for `result_r,mae,mfe,classification`), or route it through `record_outcome_r`.

7. Update old demo lines that call `candle_sent("C1", "BUY")` to `candle_sent("XAUUSD", "C1", "BUY")`.

- [ ] **Step 4: Run to verify it passes.** Run: `python -m journal.db`  Expected: PASS `[OK] journal: ...`.

- [ ] **Step 5: Commit.**

```bash
git add journal/db.py
git commit -m "feat(journal): SMC schema migration, symbol dedup, state, daily stats"
```

---

## Task 10: Broker pending-limit, cancel, demo guard, spread, equity risk

**Files:**
- Modify: `execute/broker.py`

**Interfaces:**
- Produces:
  - `is_demo_account(cfg) -> bool`
  - `current_spread(cfg, symbol) -> float`
  - `equity_risk_amount(cfg) -> float` (equity × risk_percent/100)
  - `place_limit(cfg, symbol, direction, entry, sl, tp, expiry_min) -> dict` (ORDER_TYPE_BUY_LIMIT/SELL_LIMIT, ORDER_TIME_GTD)
  - `cancel_order(cfg, ticket) -> bool` (TRADE_ACTION_REMOVE)
  - `pending_count(cfg, symbol) -> int`

- [ ] **Step 1: Write the failing test.** Extend `execute/broker.py` `demo()` with pure-logic checks only (no MT5):

```python
    # equity risk amount is pure arithmetic
    assert round(1000.0 * 1.0 / 100.0, 2) == 10.0
    # spread buffer arithmetic sanity
    assert 2990.0 - 1.0 * 0.2 == 2989.8
    print("[OK] broker: risk/spread arithmetic (MT5 calls untested here)")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m execute.broker`  Expected: PASS existing + new print (this task is mostly MT5 plumbing not unit-testable without a live terminal; the assertion guards the arithmetic).

- [ ] **Step 3: Implement.** Add to `execute/broker.py`:

```python
def is_demo_account(cfg) -> bool:
    with sources.MT5_LOCK:
        m = sources._connect(cfg["data"]["mt5"])
        ai = m.account_info()
        # MT5 ACCOUNT_TRADE_MODE_DEMO == 0
        return int(getattr(ai, "trade_mode", 0)) == 0


def current_spread(cfg, symbol) -> float:
    with sources.MT5_LOCK:
        m = sources._connect(cfg["data"]["mt5"])
        t = m.symbol_info_tick(symbol)
        return float(t.ask - t.bid) if t else 0.0


def equity_risk_amount(cfg) -> float:
    with sources.MT5_LOCK:
        m = sources._connect(cfg["data"]["mt5"])
        ai = m.account_info()
        return float(ai.equity) * float(cfg["execution"]["risk_percent"]) / 100.0


def pending_count(cfg, symbol) -> int:
    with sources.MT5_LOCK:
        m = sources._connect(cfg["data"]["mt5"])
        orders = m.orders_get(symbol=symbol)
        return len(orders) if orders else 0


def place_limit(cfg, symbol, direction, entry, sl, tp, expiry_min: int = 15) -> dict:
    """§11: pending LIMIT at 50% FVG. Demo only. One open-or-pending per instrument."""
    ex = cfg["execution"]
    if not is_demo_account(cfg):
        return {"ok": False, "msg": "akun BUKAN demo — eksekusi ditolak"}
    with sources.MT5_LOCK:
        if open_count(cfg, symbol) + pending_count(cfg, symbol) >= ex["max_positions"]:
            return {"ok": False, "msg": f"sudah ada posisi/pending {symbol}"}
        m = sources._connect(cfg["data"]["mt5"])
        si = m.symbol_info(symbol)
        entry, sl, tp = float(entry), float(sl), float(tp)
        sl_distance = abs(entry - sl)
        if sl_distance <= 0:
            return {"ok": False, "msg": "jarak SL 0/invalid"}
        risk_amount = equity_risk_amount(cfg)
        lot = _lot(si, risk_amount, sl_distance)
        pt = float(si.point) or 0.01
        tickval = float(getattr(si, "trade_tick_value", 1)) or 1
        vol_min = float(getattr(si, "volume_min", 0.01) or 0.01)
        min_risk = vol_min * (sl_distance / pt) * tickval
        ai = m.account_info()
        max_2pct = float(ai.equity) * 2.0 / 100.0
        if min_risk > max_2pct:
            return {"ok": False, "msg": f"lot-min risiko ${min_risk:.2f} > 2% equity (${max_2pct:.2f}) · §14 skip"}
        est_risk = lot * (sl_distance / pt) * tickval
        is_buy = direction == "BUY"
        otype = m.ORDER_TYPE_BUY_LIMIT if is_buy else m.ORDER_TYPE_SELL_LIMIT
        import time as _t
        req = {
            "action": m.TRADE_ACTION_PENDING, "symbol": symbol, "volume": lot,
            "type": otype, "price": entry, "sl": sl, "tp": tp,
            "magic": int(ex.get("magic", 0)), "comment": "smc-limit",
            "type_time": m.ORDER_TIME_GTD,
            "expiration": int(_t.time()) + int(expiry_min) * 60,
        }
        res, rc = _send(m, req)
    if rc == RC_DONE:
        return {"ok": True, "lot": lot, "entry": entry,
                "ticket": int(getattr(res, "order", 0) or 0),
                "est_risk": round(est_risk, 2), "spread": current_spread(cfg, symbol),
                "risk_pct": round(est_risk / float(ai.equity) * 100, 2)}
    return {"ok": False, "msg": f"retcode={rc} ({getattr(res, 'comment', '')})", "lot": lot}


def cancel_order(cfg, ticket) -> bool:
    with sources.MT5_LOCK:
        m = sources._connect(cfg["data"]["mt5"])
        res = m.order_send({"action": m.TRADE_ACTION_REMOVE, "order": int(ticket)})
        return int(res.retcode) == RC_DONE
```

*(Note: `_send` sets `type_filling`; for pending orders MT5 ignores it, which is harmless.)*

- [ ] **Step 4: Run to verify it passes.** Run: `python -m execute.broker`  Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add execute/broker.py
git commit -m "feat(broker): pending-limit, cancel, demo guard, spread, equity risk"
```

---

## Task 11: Monitor — pending lifecycle wiring, daily-stat reconstruct, shadow outcomes

**Files:**
- Modify: `monitor/watcher.py`

**Interfaces:**
- Consumes: `journal.pending_alerts`, `journal.daily_counts`, `broker.cancel_order`, `data.sources.fetch_price`.
- Produces:
  - `manage_pending(journal, cfg)` — for each PENDING alert, check fill (position exists for ticket → FILLED) or expiry/invalidation rules (§11) → cancel + mark CANCELLED.
  - `daily_stop_hit(journal, cfg, now) -> tuple[bool, str]` — global account: 2 losses OR 3 trades OR net_r ≥ +2.5R.
  - `run_pass` selects shadow too (`sent IN (0,1)` where no ticket).

- [ ] **Step 1: Write the failing test.** Extend `monitor/watcher.py` `demo()`:

```python
    # daily_stop_hit thresholds (pure dict input via fake journal)
    class FakeJ:
        def __init__(self, dc): self._dc = dc
        def daily_counts(self, day): return self._dc
    from ops.clock import now_wib
    cfg2 = {"execution": {"daily_stop": {"max_losses": 2, "max_trades": 3, "target_r": 2.5}}}
    assert daily_stop_hit(FakeJ({"losses": 2, "trades": 2, "net_r": -1.0}), cfg2, now_wib())[0]
    assert daily_stop_hit(FakeJ({"losses": 0, "trades": 3, "net_r": 0.5}), cfg2, now_wib())[0]
    assert daily_stop_hit(FakeJ({"losses": 1, "trades": 2, "net_r": 2.5}), cfg2, now_wib())[0]
    assert not daily_stop_hit(FakeJ({"losses": 1, "trades": 2, "net_r": 1.0}), cfg2, now_wib())[0]
    print("[OK] daily_stop_hit thresholds")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m monitor.watcher`  Expected: FAIL (`daily_stop_hit` undefined).

- [ ] **Step 3: Implement.** Add:

```python
def daily_stop_hit(journal, cfg, now):
    ds = cfg["execution"].get("daily_stop", {})
    day = now.strftime("%d/%m/%Y")
    dc = journal.daily_counts(day)
    if dc["losses"] >= int(ds.get("max_losses", 2)):
        return True, f"{dc['losses']} loss"
    if dc["trades"] >= int(ds.get("max_trades", 3)):
        return True, f"{dc['trades']} trade"
    if dc["net_r"] >= float(ds.get("target_r", 2.5)):
        return True, f"+{dc['net_r']}R"
    return False, ""


def manage_pending(journal, cfg):
    """§11: fill detection + auto-cancel of pending limits. Needs MT5."""
    from data import sources
    from execute import broker
    rows = journal.pending_alerts()
    if not rows:
        return 0
    n = 0
    with sources.MT5_LOCK:
        m = sources._connect(cfg["data"]["mt5"])
        for a in rows:
            tk = int(a["ticket"])
            pos = m.positions_get(ticket=tk)
            if pos and len(pos) > 0:                 # order filled -> now a position
                journal.set_status(a["id"], "FILLED")
                n += 1
                continue
            orders = m.orders_get(ticket=tk)
            if not orders:                            # neither pending nor position -> expired/removed by broker
                journal.record_outcome_r(a["id"], "CANCELLED", "EXPIRED", float(a["entry_high"]),
                                         classification="Cancelled setup")
                n += 1
    return n
```

Then in `run_pass`, change the source query to include shadow candidates without tickets — update `journal.open_alerts()` usage by adding a new journal method `open_or_shadow()` selecting `sent IN (0,1) AND status='ACTIVE' AND ticket IS NULL`, and use it here. (Add that method in `journal/db.py` alongside Task 9; if not present, add it now.)

- [ ] **Step 4: Run to verify it passes.** Run: `python -m monitor.watcher`  Expected: PASS (existing pending_lifecycle demo + new daily_stop demo).

- [ ] **Step 5: Commit.**

```bash
git add monitor/watcher.py journal/db.py
git commit -m "feat(monitor): pending lifecycle wiring + daily stop + shadow outcomes"
```

---

## Task 12: Callbacks — execute via pending-limit with guards

**Files:**
- Modify: `delivery/callbacks.py`

**Interfaces:**
- Consumes: `broker.place_limit`, `broker.current_spread`, `monitor.daily_stop_hit`.
- Produces: `_do_execute(a, journal, cfg)` now places a LIMIT order; blocks when daily stop hit, when not demo, when SELL locked.

- [ ] **Step 1: Write the failing test.** Update `delivery/callbacks.py` `demo()`: the existing `exec:` tests run with `execution.enabled: False`, so they still short-circuit before touching broker. Add:

```python
    # exec disabled path unchanged
    cfg_off = {"execution": {"enabled": False}}
    t, sfx = handle_callback(f"exec:{aid}", j, cfg_off)
    assert "dimatikan" in t.lower() and sfx is None
    print("[OK] callbacks: exec disabled short-circuit")
```

- [ ] **Step 2: Run to verify it fails/passes.** Run: `python -m delivery.callbacks`  Expected: PASS (guard unchanged); this confirms no regression before we swap internals.

- [ ] **Step 3: Implement.** Replace `_do_execute` body to place a limit order and add a daily-stop guard in `handle_callback` for `exec`:

```python
def _do_execute(a, journal, cfg):
    if a["direction"] == "SELL" and not cfg["execution"].get("allow_short", False):
        return False, "SHORT dikunci (allow_short=false)"
    from execute import broker
    entry = a["entry_high"] if a["direction"] == "SELL" else a["entry_low"]
    # entry price = 50% FVG stored at emit; prefer explicit column if present
    try:
        entry = float(a["gates_json"] and json.loads(a["gates_json"]).get("entry") or entry)
    except Exception:
        pass
    tps = json.loads(a["tp_json"])
    tp = float(tps[0])
    expiry_min = int(cfg["execution"].get("pending_expiry_min", 15))
    try:
        r = broker.place_limit(cfg, a["symbol"], a["direction"], entry, a["sl"], tp, expiry_min)
    except Exception as e:
        return False, f"eksekusi error: {e}"
    if r.get("ok"):
        journal.tag_taken(a["id"], "YES")
        if r.get("ticket"):
            journal.set_ticket(a["id"], r["ticket"])
            journal.set_status(a["id"], "PENDING")
        return True, (f"LIMIT lot {r['lot']} @ {r['entry']} · SL {a['sl']} · TP {tp} · "
                      f"risk ~${r['est_risk']} ({r.get('risk_pct','?')}%)")
    return False, f"gagal: {r.get('msg')}"
```

In `handle_callback`, before calling `_do_execute` under `action == "exec"`, add:

```python
        from monitor.watcher import daily_stop_hit
        from ops.clock import now_wib
        hit, why = daily_stop_hit(journal, cfg, now_wib())
        if hit:
            return f"⛔ Batas harian ({why}) — stop", None
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m delivery.callbacks`  Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add delivery/callbacks.py
git commit -m "feat(callbacks): execute pending-limit + daily-stop guard"
```

---

## Task 13: Telegram format for single-TP limit alerts

**Files:**
- Modify: `delivery/telegram.py`

**Interfaces:**
- Produces: `format_alert(setup, now)` renders limit entry + single TP; `alert_keyboard` button label `Eksekusi Limit`.

- [ ] **Step 1: Write the failing test.** Update `delivery/telegram.py` `demo()`:

```python
    s = Setup("XAUUSD.vx", "BUY", "M5", 2979.0, 2985.0, 2970.0, [3010.0],
              "HIGH_CONF", 7, "SMC bullish · POI · sweep · MSS · RR3.0", {},
              entry_type="LIMIT", entry=2982.0, rr_planned=3.0)
    msg = format_alert(s)
    assert "LIMIT" in msg and "2982" in msg and "3010" in msg
    kb = alert_keyboard(42)
    assert kb["inline_keyboard"][0][0]["callback_data"] == "exec:42"
    assert "Limit" in kb["inline_keyboard"][0][0]["text"]
    print("[OK] telegram: single-TP limit alert")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m delivery.telegram`  Expected: FAIL (old format expects `tp[1]`/`tp[2]`, "Limit" not in button).

- [ ] **Step 3: Implement.** Update `format_alert` to use `setup.entry` and single TP, and change button text:

```python
def format_alert(setup, now=None):
    emoji = "\U0001F7E2" if setup.direction == "BUY" else "\U0001F534"
    tier = "\U0001F525 HIGH CONFIDENCE" if setup.tier == "HIGH_CONF" else "NORMAL"
    lines = [f"{emoji} <b>{setup.symbol} — {setup.direction}</b>   {tier}", "━" * 16]
    if setup.experimental:
        lines += ["\U0001F9EA <b>EKSPERIMEN</b> — short belum terbukti edge-nya.",
                  "Tandai buat DATA, jangan dibet dulu.", "━" * 16]
    entry = setup.entry or (setup.entry_high if setup.direction == "BUY" else setup.entry_low)
    lines += [
        f"\U0001F4C8 {setup.tf} · {setup.entry_type} entry <b>{entry}</b> (FVG {setup.entry_low}–{setup.entry_high})",
        f"\U0001F6D1 SL  : {setup.sl}",
        f"✅ TP  : {setup.tp[0]}",
        f"\U0001F4CA RR  : {setup.rr}  · skor {setup.score}/7",
        f"\U0001F9ED {setup.reason}",
        "━" * 16,
        f"\U0001F550 {wib_str(now)}",
    ]
    return "\n".join(lines)


def alert_keyboard(alert_id):
    return {"inline_keyboard": [[
        {"text": "\U0001F7E2 Eksekusi Limit", "callback_data": f"exec:{alert_id}"},
        {"text": "✅ Ambil",                  "callback_data": f"take:{alert_id}"},
        {"text": "⏭ Skip",                    "callback_data": f"skip:{alert_id}"},
    ]]}
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m delivery.telegram`  Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add delivery/telegram.py
git commit -m "feat(telegram): single-TP pending-limit alert format"
```

---

## Task 14: Config rewrite for canonical SMC

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Edit config.** Apply these changes to `config.yaml`:
  - `source_tz: "UTC"` (SMC uses UTC; drop TODO note).
  - `strategy:` becomes:
    ```yaml
    strategy:
      active: smc_canonical
    ```
    (remove the `params:` sub-block entirely).
  - Replace the `smc:` block with `smc_canonical:`:
    ```yaml
    smc_canonical:
      swing_k: 2
      atr_period: 14
      disp_body_ratio: 0.65
      disp_atr_mult: 1.5
      rr_min: 2.5
      rr_aplus: 3.0
      struct_lookback: 40
      trigger_lookback: 12
      sweep_lookback: 20
      poi_lookback: 60
      sl_spread_mult: 1.0
      expiry_candles: 3
      sessions_utc: [[7, 0, 10, 0], [12, 0, 15, 30]]   # London 07:00-10:00, NY 12:00-15:30 UTC
      server_utc_offset: 2                              # broker UTC+2; verify DST -> +3
      require_session: true
    ```
  - `scheduler:` set `eval_on_close: M5`, `minutes: 5`.
  - `execution:` set:
    ```yaml
    execution:
      enabled: false                # flip to true only after activation gate; demo verified
      demo_verified: false          # set true after manual confirm account is demo
      allow_short: true             # DEMO data collection; set false before LIVE
      risk_percent: 1.0
      max_positions: 1              # one open-or-pending per instrument
      pending_expiry_min: 15        # ~3 M5 candles
      trailing: false
      target_tp: 1
      daily_stop:
        max_losses: 2
        max_trades: 3
        target_r: 2.5
      deviation_pct: 0.1
      magic: 20260726
    ```
    (Remove the `trail:` sub-block — trailing is off for SMC.)
  - Add a `news:` block:
    ```yaml
    news:
      enabled: false                # DEFERRED block 1; alerts tagged news_filter_applied=0
      file: "var/news.txt"          # future: manual high-impact USD times, one ISO ts per line
    ```

- [ ] **Step 2: Validate YAML parses.** Run: `python -c "import yaml; yaml.safe_load(open('config.yaml', encoding='utf-8')); print('yaml ok')"`  Expected: `yaml ok`.

- [ ] **Step 3: Commit.**

```bash
git add config.yaml
git commit -m "config: canonical SMC (M5 cadence, sessions, daily stop, news deferred)"
```

---

## Task 15: main.py — wire canonical strategy, M5, state, daily-stat reconstruct

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `SmcCanonical`, `journal.load_state/save_state`, `monitor.manage_pending`, `daily_stop_hit`.

- [ ] **Step 1: Rewrite `build_strategy` and scan.** Replace the strategy factory and scan loop:

```python
from engine.smc_canonical import SmcCanonical
from engine.models import SmcState
from monitor.watcher import run_pass, check_deadman, manage_pending, daily_stop_hit
```

Remove imports of `TrendPullback` and `SmcPrescreen`. Replace `build_strategy`:

```python
def build_strategy(cfg):
    params = {**cfg.get("smc_canonical", {}), "direction": cfg["direction"]}
    return SmcCanonical(), params
```

- [ ] **Step 2: Update `run_scan` to drive the state machine per symbol.** For each symbol: load state, call `strat.evaluate(bundle, params, state)`, persist returned state, and only when a `Setup` is produced run `decide()` (symbol-aware dedup) and record with `state_snapshot` + `news_filter_applied=0`:

```python
def run_scan(cfg, journal, strat, params, *, dry=False):
    for symbol in cfg["instruments"]:
        if not is_market_open(symbol):
            print(f"[main] {symbol}: pasar tutup - skip"); continue
        bundle = get_bundle(cfg["data"], symbol)
        if bundle is None:
            print(f"[main] {symbol}: data tak tersedia - skip"); continue
        st_name, st_blob = (journal.load_state(symbol) if journal else ("IDLE", None))
        state = SmcState.from_json(symbol, st_name, st_blob)
        setup, state = strat.evaluate(bundle, params, state)
        if journal and not dry:
            journal.save_state(symbol, state.state, state.to_json())
        if setup is None:
            print(f"[main] {wib_str()} · {symbol} state={state.state} · tidak ada setup"); continue
        df = bundle.df(setup.tf)
        candle_id = str(df.index[-2])
        now = now_wib()
        if journal:
            hit, why = daily_stop_hit(journal, cfg, now)
            if hit:
                print(f"[main] {symbol} daily-stop ({why}) · suppress")
                journal.record(setup, candle_id, strat.name, strat.version, sent=False,
                               suppress=f"daily-stop {why}", ts=wib_str(now),
                               state_snapshot=state.to_json())
                continue
        send, why = decide(setup, candle_id, cfg["alert"], journal, now) if journal else (True, "dry")
        print(f"[main] {wib_str(now)} · {symbol} {setup.direction} tier={setup.tier} "
              f"RR={setup.rr} -> {'KIRIM' if send else 'SUPPRESS ('+why+')'}")
        if dry or not journal:
            continue
        aid = journal.record(setup, candle_id, strat.name, strat.version, sent=send,
                             suppress=None if send else why, ts=wib_str(now),
                             news_filter_applied=0, state_snapshot=state.to_json())
        if send:
            mid = telegram.send(telegram.format_alert(setup, now), cfg["delivery"]["telegram"],
                                reply_markup=telegram.alert_keyboard(aid))
            if mid:
                journal.cfg_set(f"msg_{aid}", str(mid))
```

`decide()` calls `journal.candle_sent(...)` — update `alert/engine.py` to pass `setup.symbol` (Task 16).

- [ ] **Step 3: Update `run_loop` monitor tick and cadence.** In `run_loop`:

```python
    def monitor_tick():
        run_pass(journal, cfg)
        if cfg.get("execution", {}).get("enabled"):
            manage_pending(journal, cfg)
            reconcile_executed(journal, cfg)
        check_deadman(journal, sc, cfg["delivery"]["telegram"])
    ...
    scheduler.run_candle_loop(tick, sc["minutes"], sc["offset_sec"])   # sc["minutes"]==5 now
```

Remove the `manage_positions` import/call (trailing off for SMC). Remove `shadow_grade` unless `ai.enabled` (leave the function but it references `SmcPrescreen` — delete `shadow_grade` and its call since SmcPrescreen is being removed).

- [ ] **Step 4: Run smoke.** Run: `python -c "import main; print('import ok')"`  Expected: `import ok` (no `ImportError` from deleted modules).

- [ ] **Step 5: Commit.**

```bash
git add main.py
git commit -m "feat(main): drive SmcCanonical state machine on M5 + daily-stop"
```

---

## Task 16: alert/engine.py symbol-aware dedup

**Files:**
- Modify: `alert/engine.py`

- [ ] **Step 1: Update `decide` dedup call.** Change line in `decide`:

```python
    if journal.candle_sent(setup.symbol, candle_id, setup.direction):
        return False, f"dup candle {candle_id}"
```

- [ ] **Step 2: Update demo.** In `alert/engine.py` `demo()`, the `Setup` symbol is `"XAUUSD"`; `candle_sent` now needs symbol. The demo calls `decide(...)` (which internally passes `setup.symbol`) and `j.record(...)`, so only ensure `j.record` stored `symbol="XAUUSD"`. No direct `candle_sent` call in this demo — verify it still passes.

- [ ] **Step 3: Run to verify.** Run: `python -m alert.engine`  Expected: PASS `[OK] alert engine: ...`.

- [ ] **Step 4: Commit.**

```bash
git add alert/engine.py
git commit -m "fix(alert): symbol-aware candle dedup"
```

---

## Task 17: Remove trend_pullback + smc_prescreen

**Files:**
- Delete: `engine/strategy.py`, `engine/smc.py`

- [ ] **Step 1: Confirm no remaining imports.** Run: `python -c "import re,glob,io;[print(f) for f in glob.glob('**/*.py',recursive=True) if re.search(r'TrendPullback|SmcPrescreen|engine\.strategy|engine\.smc\b', open(f,encoding='utf-8').read())]"`  Expected: no output (empty).

If any file still references them, fix that file first (should only be `main.py`, already done in Task 15).

- [ ] **Step 2: Delete the files.**

```bash
git rm engine/strategy.py engine/smc.py
```

- [ ] **Step 3: Run aggregate self-checks.**

```bash
python -m engine.models
python -m engine.indicators
python -m engine.smc_canonical
python -m journal.db
python -m alert.engine
python -m monitor.watcher
python -m delivery.telegram
python -m delivery.callbacks
python -m ops.scheduler
python -m execute.broker
```

Expected: every command prints its `[OK] ...` line and exits 0.

- [ ] **Step 4: Compile-all.** Run: `python -m compileall -q .`  Expected: no errors.

- [ ] **Step 5: Commit.**

```bash
git add -A
git commit -m "chore: remove trend_pullback + smc_prescreen (canonical SMC only)"
```

---

## Task 18: Scheduler M5 tick test + docs sync

**Files:**
- Modify: `ops/scheduler.py` (add M5 assertion), `CLAUDE.md`, `config.yaml` comments already updated.

- [ ] **Step 1: Add M5 assertion to scheduler demo.** In `ops/scheduler.py` `demo()`:

```python
    assert next_tick(d(2026, 7, 20, 10, 3, tzinfo=WIB), 5, 5) == d(2026, 7, 20, 10, 5, 5, tzinfo=WIB)
    assert next_tick(d(2026, 7, 20, 10, 55, tzinfo=WIB), 5, 5) == d(2026, 7, 20, 11, 0, 5, tzinfo=WIB)
```

- [ ] **Step 2: Run.** Run: `python -m ops.scheduler`  Expected: PASS.

- [ ] **Step 3: Sync CLAUDE.md.** Update the strategy/architecture sections to state: active strategy `smc_canonical` (stateful), scope XAU+BTC same rules, M5 cadence, pending-limit execution, set-and-forget, daily stop, news deferred. Remove the stale "SMC dropped, don't revive" paragraph and the "trend_pullback active" line. Keep the principles.

- [ ] **Step 4: Commit.**

```bash
git add ops/scheduler.py CLAUDE.md
git commit -m "docs: sync CLAUDE.md to canonical SMC + M5 scheduler test"
```

---

## Task 19: Activation gate (manual, before enabling execution)

**Files:** none (operational checklist; do not enable execution in code).

- [ ] **Step 1:** Run all module demos (Task 17 Step 3) — all green.
- [ ] **Step 2:** `python -m compileall -q .` — clean.
- [ ] **Step 3:** `python main.py once --dry` against live MT5 — completes without exception; prints per-symbol `state=` lines; produces at least the state transitions (may print "tidak ada setup" if market has no valid setup — that is acceptable, the gate is "no crash + correct state handling").
- [ ] **Step 4:** Manually inspect ≥10 emitted or shadow candidates vs `strategy/xauusd-smc-trading-system.md` §18 — confirm rule adherence ≥90%. Record notes in `docs/superpowers/specs/`.
- [ ] **Step 5:** Confirm account is demo: `python -c "import yaml,main; cfg=main.load_config(); from execute import broker; print('demo=', broker.is_demo_account(cfg))"` → `demo= True`.
- [ ] **Step 6:** Only then set `execution.enabled: true` and `execution.demo_verified: true` in `config.yaml`, commit:

```bash
git add config.yaml
git commit -m "config: enable SMC execution on verified demo account"
```

---

## Self-Review

**Spec coverage:** §1 scope (XAU+BTC, Task 14/15) · §3 sessions (Task 2/14) · §4 bias+protected (Task 3) · §5 dealing range (Task 4) · §6 POI (Task 5) · §7-8 liquidity+sweep-in-POI (Task 6) · §9-10 displacement+MSS pre-sweep (Task 6) · §11 entry limit 50% FVG + expiry (Task 6/10/11) · §12 SL sweep-extreme+spread (Task 7) · §13 single-TP RR gate (Task 7) · §14 sizing 1-2% equity (Task 10) · §15 set-and-forget (Task 14 trailing off) · §16 daily stop + one position (Task 11/10) · §17 no-trade gates (state machine returns None) · §19-20 journal fields (Task 9) · §21 validation metrics (Task 9 `daily_counts`/`record_outcome_r`, classification). News filter deferred per owner (Task 14, tagged in Task 15). Execution demo-gate (Task 19).

**Placeholder scan:** No TBD/TODO left in tasks; each code step is complete.

**Type consistency:** `SmcState(symbol,state,data)` and `.to_json()/.from_json()` used identically in Tasks 1/8/9/15. `evaluate(bundle,params,state) -> (Setup|None, SmcState)` consistent across Task 8/15. `place_limit(...) -> dict{ok,lot,entry,ticket,est_risk,spread,risk_pct}` consumed in Task 12. `daily_counts(day_prefix) -> {losses,trades,net_r}` produced Task 9, consumed Task 11. `candle_sent(symbol,candle_id,direction)` new arity used in Task 9/16.
