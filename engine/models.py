"""Tipe inti yang dilewatkan antar modul. Sengaja minim.
(Dinamai models.py, BUKAN types.py — 'types' menabrak modul stdlib.)"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import pandas as pd


@dataclass
class Bundle:
    """Snapshot data multi-timeframe untuk satu instrumen di satu evaluasi."""
    symbol: str
    price: float                       # harga live terakhir
    tf: dict[str, pd.DataFrame]        # "M30"/"H1"/"H4"/"D1" -> DataFrame OHLCV (index datetime)
    sources: dict[str, str] = field(default_factory=dict)   # tf -> "bridge"/"twelvedata"/...

    def df(self, timeframe: str) -> pd.DataFrame | None:
        return self.tf.get(timeframe)


@dataclass
class Setup:
    """Hasil strategi.evaluate(). None kalau tidak ada setup."""
    symbol: str
    direction: str                     # "BUY" | "SELL"
    tf: str                            # timeframe entry (mis. "M30")
    entry_low: float
    entry_high: float                  # zona entry (pullback) — bukan cuma market
    sl: float
    tp: list[float]                    # [tp1, tp2, tp3]
    tier: str                          # "HIGH_CONF" | "NORMAL"
    score: int
    reason: str                        # ringkas, per-gate
    gates: dict = field(default_factory=dict)   # {"regime":..., "setup":..., "volume":...}
    experimental: bool = False         # True utk SELL v1 (edge short belum terbukti)
    entry_type: str = "LIMIT"          # LIMIT (SMC) | MARKET
    entry: float = 0.0                 # 50% FVG limit price (0 = use entry_high/low)
    risk_money: float = 0.0
    risk_pct: float = 0.0
    spread: float = 0.0
    lot: float = 0.0
    rr_planned: float = 0.0            # actual entry->TP / entry->SL at emit

    @property
    def rr(self) -> float:
        if self.rr_planned:
            return round(self.rr_planned, 2)
        entry = self.entry or (self.entry_high if self.direction == "BUY" else self.entry_low)
        risk = abs(entry - self.sl)
        return round(abs(self.tp[0] - entry) / risk, 2) if risk else 0.0


@dataclass
class SmcState:
    """State SMC per instrumen — dilacak engine/strategy."""
    symbol: str
    state: str
    data: dict = field(default_factory=dict)
    updated_at: str = ""

    def to_json(self) -> str:
        return json.dumps(self.data)

    @classmethod
    def from_json(
        cls, symbol: str, state: str, blob: str | None, updated_at: str = ""
    ) -> "SmcState":
        return cls(symbol, state, json.loads(blob) if blob else {}, updated_at)


def demo():
    s = Setup("XAUUSD.vx", "BUY", "M5", 2980.0, 2985.0, 2970.0, [3010.0],
              "HIGH_CONF", 5, "smc buy", {"bias": "bullish"},
              experimental=False, entry_type="LIMIT",
              risk_money=10.0, risk_pct=1.0, spread=0.2, lot=0.01, rr_planned=3.0)
    assert s.entry_type == "LIMIT"
    assert s.rr_planned == 3.0 and s.lot == 0.01
    assert abs(s.rr - 3.0) < 1e-9

    st = SmcState("XAUUSD.vx", "SWEPT", {"sweep_extreme": 2969.0, "bias": "bullish"})
    blob = st.to_json()
    st2 = SmcState.from_json("XAUUSD.vx", "SWEPT", blob)
    assert st2.data["sweep_extreme"] == 2969.0
    print("[OK] models: Setup extras + SmcState round-trip")


if __name__ == "__main__":
    demo()
