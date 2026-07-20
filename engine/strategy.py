"""
Strategi = resep rule deterministik (BUKAN prompt AI).
v1: trend_pullback — follow trend (H4+D1) → tunggu pullback ke EMA di M30/H1 → konfirmasi momentum.
  BULL regime → BUY. BEAR regime → SELL (mode EKSPERIMEN — edge short belum terbukti di data owner).
Target lebar (data owner: runner yang cuan).
"""
from __future__ import annotations
from typing import Protocol
import pandas as pd

from engine.models import Bundle, Setup
from engine import indicators as ind

DEFAULTS = dict(
    ema_fast=20, ema_slow=50, ema_trend=200, atr_period=14, rsi_period=14,
    sl_atr_mult=1.5, tp_r=[1.5, 3.0, 5.0], high_conf_score=4,
    pullback_atr=0.4, pullback_lookback=3, swing_lookback=10, vol_mult=1.2,
    entry_tfs=["M30", "H1"], direction="long_only",
)


class Strategy(Protocol):
    name: str
    version: str
    def evaluate(self, bundle: Bundle, params: dict) -> Setup | None: ...


def _closed(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Buang candle terakhir (masih terbentuk) — analisa hanya closed candle."""
    return df.iloc[:-1] if df is not None and len(df) > 1 else df


class TrendPullback:
    name = "trend_pullback"
    version = "0.2"     # 0.2 = tambah sisi SELL (eksperimen)

    def evaluate(self, bundle: Bundle, params: dict) -> Setup | None:
        p = {**DEFAULTS, **(params or {})}
        regime = self._regime(bundle, p)
        if regime == "BULL":
            direction = "BUY"
        elif regime == "BEAR" and p["direction"] == "both":
            direction = "SELL"
        else:
            return None   # ranging, atau bearish saat long_only → diam
        best: Setup | None = None
        for tf in p["entry_tfs"]:
            s = self._eval_tf(bundle, tf, p, regime, direction)
            if s and (best is None or s.score > best.score):
                best = s
        return best

    def _regime(self, bundle: Bundle, p: dict) -> str:
        h4, d1 = _closed(bundle.df("H4")), _closed(bundle.df("D1"))
        if h4 is None or d1 is None or len(h4) < p["ema_trend"] or len(d1) < p["ema_slow"]:
            return "NONE"
        c4 = h4["close"]
        et = ind.ema(c4, p["ema_trend"]).iloc[-1]
        ef = ind.ema(c4, p["ema_fast"]).iloc[-1]
        es = ind.ema(c4, p["ema_slow"]).iloc[-1]
        price4 = c4.iloc[-1]
        d1c = d1["close"].iloc[-1]
        d1es = ind.ema(d1["close"], p["ema_slow"]).iloc[-1]
        if price4 > et and ef > es and d1c > d1es:
            return "BULL"
        if price4 < et and ef < es and d1c < d1es:
            return "BEAR"
        return "NONE"

    def _eval_tf(self, bundle: Bundle, tf: str, p: dict, regime: str, direction: str) -> Setup | None:
        df = _closed(bundle.df(tf))
        if df is None or len(df) < p["ema_slow"] + p["swing_lookback"] + 5:
            return None
        c = df["close"]
        ema_f = ind.ema(c, p["ema_fast"])
        ema_s = ind.ema(c, p["ema_slow"])
        atr = float(ind.atr(df, p["atr_period"]).iloc[-1])
        rsi = ind.rsi(c, p["rsi_period"])
        price = float(c.iloc[-1])
        last = df.iloc[-1]
        if atr <= 0:
            return None
        ef, es = float(ema_f.iloc[-1]), float(ema_s.iloc[-1])
        rng = float(last["high"] - last["low"])

        if direction == "BUY":
            if not (ef > es and price > es):                                   # uptrend TF
                return None
            recent_low = float(df["low"].iloc[-p["pullback_lookback"]:].min())
            if recent_low > ef + p["pullback_atr"] * atr:                      # pullback turun ke EMA
                return None
            if not (last["close"] > last["open"] and last["close"] > ef):      # bounce naik konfirmasi
                return None
            strong = (last["close"] - last["low"]) / rng if rng > 0 else 0
            rsi_ok = rsi.iloc[-1] > rsi.iloc[-2] and 40 <= rsi.iloc[-1] <= 65
            swing = float(df["low"].iloc[-p["swing_lookback"]:].min())
            sl = min(swing, price - p["sl_atr_mult"] * atr) - 0.1 * atr
            risk = price - sl
            tp = [round(price + r * risk, 2) for r in p["tp_r"]]
            entry_low, entry_high = round(min(price, ef), 2), round(price, 2)
        else:  # SELL — cermin (eksperimen)
            if not (ef < es and price < es):                                   # downtrend TF
                return None
            recent_high = float(df["high"].iloc[-p["pullback_lookback"]:].max())
            if recent_high < ef - p["pullback_atr"] * atr:                     # pullback naik ke EMA
                return None
            if not (last["close"] < last["open"] and last["close"] < ef):      # rejection turun konfirmasi
                return None
            strong = (last["high"] - last["close"]) / rng if rng > 0 else 0
            rsi_ok = rsi.iloc[-1] < rsi.iloc[-2] and 35 <= rsi.iloc[-1] <= 60
            swing = float(df["high"].iloc[-p["swing_lookback"]:].max())
            sl = max(swing, price + p["sl_atr_mult"] * atr) + 0.1 * atr
            risk = sl - price
            tp = [round(price - r * risk, 2) for r in p["tp_r"]]
            entry_low, entry_high = round(price, 2), round(max(price, ef), 2)

        if risk <= 0:
            return None

        score = 2
        reasons = [f"regime {regime} H4/D1", f"pullback EMA{p['ema_fast']} {tf}", "konfirmasi"]
        if strong >= 0.66:
            score += 1; reasons.append("close kuat")
        if rsi_ok:
            score += 1; reasons.append(f"RSI {rsi.iloc[-1]:.0f}")
        vol_avg = df["volume"].rolling(20).mean().iloc[-1]
        vol_ok = bool(vol_avg and last["volume"] > p["vol_mult"] * vol_avg)
        if vol_ok:
            score += 1; reasons.append("volume↑")
        exp = direction == "SELL"
        if exp:
            reasons.insert(0, "SHORT eksperimen")

        return Setup(
            symbol=bundle.symbol, direction=direction, tf=tf,
            entry_low=entry_low, entry_high=entry_high, sl=round(sl, 2), tp=tp,
            tier=("HIGH_CONF" if score >= p["high_conf_score"] else "NORMAL"),
            score=score, reason=" · ".join(reasons),
            gates={"regime": regime, "pullback": True, "trigger": True, "volume": vol_ok},
            experimental=exp,
        )


# ────────────────────────── self-check ──────────────────────────
def _ohlcv(close, freq, vol=1000.0):
    import numpy as np
    close = pd.Series(close, index=pd.date_range("2026-01-01", periods=len(close), freq=freq))
    op = close.shift(1).fillna(close)
    hi = pd.concat([op, close], axis=1).max(axis=1) + 0.3
    lo = pd.concat([op, close], axis=1).min(axis=1) - 0.3
    return pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close,
                         "volume": pd.Series(vol, index=close.index)})


def _bull_bundle():
    import numpy as np
    up = lambda n, a, b, f: _ohlcv(np.linspace(a, b, n), f)
    h4 = up(300, 2000, 3000, "4h"); d1 = up(300, 2000, 3000, "1D")
    seq = list(np.linspace(2500, 3000, 256)) + [2965, 2962, 2995, 2996]   # dip → BOUNCE → forming
    m30 = _ohlcv(seq, "30min"); m30.iloc[-2, m30.columns.get_loc("volume")] = 2500.0
    return Bundle("XAUUSD", price=float(m30["close"].iloc[-1]),
                  tf={"M30": m30, "H1": up(260, 2500, 3000, "1h"), "H4": h4, "D1": d1})


def _bear_pullback_bundle():
    import numpy as np
    dn = lambda n, a, b, f: _ohlcv(np.linspace(a, b, n), f)
    h4 = dn(300, 3000, 2000, "4h"); d1 = dn(300, 3000, 2000, "1D")
    seq = list(np.linspace(2500, 2000, 256)) + [2035, 2038, 2005, 2004]   # rally → REJECT → forming
    m30 = _ohlcv(seq, "30min"); m30.iloc[-2, m30.columns.get_loc("volume")] = 2500.0
    return Bundle("XAUUSD", price=float(m30["close"].iloc[-1]),
                  tf={"M30": m30, "H1": dn(260, 2500, 2000, "1h"), "H4": h4, "D1": d1})


def demo():
    s = TrendPullback()
    # 1) bull-pullback → BUY (bukan eksperimen)
    buy = s.evaluate(_bull_bundle(), {})
    assert buy and buy.direction == "BUY" and not buy.experimental
    assert buy.sl < buy.entry_high < buy.tp[0] < buy.tp[1] < buy.tp[2] and buy.rr > 0
    print(f"[OK] BUY {buy.tf} entry {buy.entry_low}-{buy.entry_high} sl={buy.sl} tp={buy.tp} RR={buy.rr} score={buy.score}")
    # 2) bear regime + long_only → diam
    assert s.evaluate(_bear_pullback_bundle(), {"direction": "long_only"}) is None
    print("[OK] BEAR + long_only -> None")
    # 3) bear-pullback + both → SELL (eksperimen), invariant kebalik
    sell = s.evaluate(_bear_pullback_bundle(), {"direction": "both"})
    assert sell and sell.direction == "SELL" and sell.experimental
    assert sell.tp[2] < sell.tp[1] < sell.tp[0] < sell.entry_low < sell.sl and sell.rr > 0
    print(f"[OK] SELL {sell.tf} entry {sell.entry_low}-{sell.entry_high} sl={sell.sl} tp={sell.tp} RR={sell.rr} score={sell.score} exp={sell.experimental}")


if __name__ == "__main__":
    demo()
