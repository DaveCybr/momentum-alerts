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


def swings(df: pd.DataFrame, k: int = 2) -> tuple[pd.Series, pd.Series]:
    """Fractal pivot sensitivitas k (default 2 candle kiri-kanan) — deterministik.
    Return (is_swing_high, is_swing_low) sebagai Series boolean sejajar index df.
    Swing High: high candle tengah > high k candle kiri DAN k candle kanan (strict).
    Candle di tepi (belum punya k kanan) selalu False (belum terkonfirmasi)."""
    h, l = df["high"], df["low"]
    n = len(df)
    sh = pd.Series(False, index=df.index)
    sl = pd.Series(False, index=df.index)
    hv, lv = h.values, l.values
    for i in range(k, n - k):
        c_h, c_l = hv[i], lv[i]
        is_h = all(c_h > hv[i - j] and c_h > hv[i + j] for j in range(1, k + 1))
        is_l = all(c_l < lv[i - j] and c_l < lv[i + j] for j in range(1, k + 1))
        if is_h:
            sh.iloc[i] = True
        if is_l:
            sl.iloc[i] = True
    return sh, sl


def fvg(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Fair Value Gap 3-candle (imbalance) — deterministik.
    Return (bull_gap, bear_gap): Series float berisi lebar gap di candle KETIGA (index i),
    0.0 kalau tak ada gap. Bullish: high[i-2] < low[i] (gap = low[i]-high[i-2]).
    Bearish: low[i-2] > high[i] (gap = low[i-2]-high[i])."""
    h, l = df["high"].values, df["low"].values
    n = len(df)
    bull = pd.Series(0.0, index=df.index)
    bear = pd.Series(0.0, index=df.index)
    for i in range(2, n):
        if h[i - 2] < l[i]:
            bull.iloc[i] = l[i] - h[i - 2]
        if l[i - 2] > h[i]:
            bear.iloc[i] = l[i - 2] - h[i]
    return bull, bear


def fvg_zones(df: pd.DataFrame, bull: bool) -> list[tuple[int, float, float, float]]:
    """Batas tiap FVG (bukan cuma lebar) — buat entry limit 50% FVG (spec §11).
    Return list (i, lo, hi, mid) urut lama→baru, i = index posisi candle ketiga.
    Bullish gap: lo=high[i-2], hi=low[i]. Bearish gap: lo=high[i], hi=low[i-2].
    mid = 50% zona (level entry limit)."""
    h, l = df["high"].values, df["low"].values
    out = []
    for i in range(2, len(df)):
        if bull and h[i - 2] < l[i]:
            lo, hi = float(h[i - 2]), float(l[i])
            out.append((i, lo, hi, (lo + hi) / 2))
        elif not bull and l[i - 2] > h[i]:
            lo, hi = float(h[i]), float(l[i - 2])
            out.append((i, lo, hi, (lo + hi) / 2))
    return out


def displacement(df: pd.DataFrame, atr_series: pd.Series | None = None,
                 body_ratio: float = 0.65, atr_mult: float = 1.5,
                 atr_period: int = 14) -> pd.Series:
    """Displacement (agresi order) — deterministik. Return Series int:
    +1 bullish displacement, -1 bearish, 0 bukan. Syarat (spek SMC §4):
      body/total_range >= body_ratio DAN range >= atr_mult × ATR(atr_period)."""
    o, c = df["open"].values, df["close"].values
    h, l = df["high"].values, df["low"].values
    a = (atr_series if atr_series is not None else atr(df, atr_period)).values
    out = pd.Series(0, index=df.index)
    for i in range(len(df)):
        rng = h[i] - l[i]
        if rng <= 0 or not (a[i] > 0):
            continue
        body = abs(c[i] - o[i])
        if body / rng >= body_ratio and rng >= atr_mult * a[i]:
            out.iloc[i] = 1 if c[i] > o[i] else -1
    return out


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

    # swings: pivot buatan yang jelas
    sw = pd.DataFrame({
        "open": [10, 11, 15, 12, 9, 8, 13, 14],
        "high": [10, 12, 16, 12, 9, 8, 13, 14],   # idx2 high=16 puncak, idx5 low=8 lembah
        "low":  [9, 10, 14, 11, 8, 6, 12, 13],
        "close": [10, 11, 15, 12, 9, 8, 13, 14],
    })
    sh, sl = swings(sw, k=2)
    assert sh.iloc[2] and not sh.iloc[3], "idx2 harus swing high"
    assert sl.iloc[5] and not sl.iloc[4], "idx5 harus swing low"
    assert not sh.iloc[0] and not sh.iloc[-1], "tepi tak boleh swing (belum konfirmasi)"
    print(f"[OK] swings: SH@{list(sh[sh].index)} SL@{list(sl[sl].index)}")

    # fvg: bikin gap bullish eksplisit (high[i-2] < low[i])
    fv = pd.DataFrame({
        "open": [10, 11, 14, 14], "close": [11, 13, 15, 15],
        "high": [11, 13, 16, 16], "low":  [10, 11, 14, 14],   # idx2: high[0]=11 < low[2]=14 → bull gap 3
    })
    bull, bear = fvg(fv)
    assert abs(bull.iloc[2] - 3.0) < 1e-9, f"bull gap harus 3.0, dapat {bull.iloc[2]}"
    assert bear.iloc[2] == 0.0, "tak ada bear gap di sini"
    print(f"[OK] fvg: bull@idx2={bull.iloc[2]}")

    # fvg_zones: batas + midpoint 50% (buat entry limit §11). idx2: lo=high[0]=11, hi=low[2]=14, mid=12.5
    zones = fvg_zones(fv, bull=True)
    z2 = next((z for z in zones if z[0] == 2), None)
    assert z2 is not None, f"harus ada zona bull @idx2, dapat {zones}"
    _, zlo, zhi, zmid = z2
    assert (zlo, zhi, zmid) == (11.0, 14.0, 12.5), f"zona bull salah: {z2}"
    assert fvg_zones(fv, bull=False) == [], "tak ada bear zone di sini"
    print(f"[OK] fvg_zones: bull lo={zlo} hi={zhi} mid50%={zmid}")

    # displacement: satu candle besar-body di tengah candle kecil
    base = [dict(open=100, high=100.5, low=99.5, close=100) for _ in range(20)]
    big = dict(open=100, high=106, low=99.8, close=105.5)   # body 5.5 / range 6.2 ≈ 0.89, range >> ATR
    dfd = pd.DataFrame(base + [big])
    disp = displacement(dfd, body_ratio=0.65, atr_mult=1.5, atr_period=14)
    assert disp.iloc[-1] == 1, f"candle terakhir harus bullish displacement, dapat {disp.iloc[-1]}"
    assert (disp.iloc[:-1] == 0).all(), "candle kecil tak boleh displacement"
    print(f"[OK] displacement: last={disp.iloc[-1]}")


if __name__ == "__main__":
    demo()
