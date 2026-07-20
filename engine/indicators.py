"""Indikator — fungsi murni pandas/numpy. Tanpa dependency `ta`."""
from __future__ import annotations
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder smoothing
    avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()   # Wilder RMA


def demo():
    idx = pd.date_range("2026-01-01", periods=300, freq="30min")
    close = pd.Series(np.linspace(100, 130, 300) + np.sin(np.arange(300) / 5), index=idx)
    df = pd.DataFrame({"open": close.shift(1).fillna(close), "high": close + 0.5,
                       "low": close - 0.5, "close": close, "volume": 1000.0}, index=idx)
    e = ema(close, 20); r = rsi(close, 14); a = atr(df, 14)
    assert len(e) == 300 and e.iloc[-1] > e.iloc[0], "EMA harus naik di uptrend"
    assert 0 <= r.iloc[-1] <= 100, "RSI harus 0..100"
    assert a.iloc[-1] > 0, "ATR harus positif"
    assert r.iloc[-1] > 55, f"RSI uptrend harus bullish, dapat {r.iloc[-1]:.1f}"
    print(f"[OK] EMA20={e.iloc[-1]:.2f} RSI={r.iloc[-1]:.1f} ATR={a.iloc[-1]:.3f}")


if __name__ == "__main__":
    demo()
