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

