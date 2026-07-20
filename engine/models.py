"""Tipe inti yang dilewatkan antar modul. Sengaja minim.
(Dinamai models.py, BUKAN types.py — 'types' menabrak modul stdlib.)"""
from __future__ import annotations
from dataclasses import dataclass, field
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

    @property
    def rr(self) -> float:
        # entry ref = harga saat ini: entry_high utk BUY, entry_low utk SELL
        entry = self.entry_high if self.direction == "BUY" else self.entry_low
        risk = abs(entry - self.sl)
        return round(abs(self.tp[0] - entry) / risk, 2) if risk else 0.0
