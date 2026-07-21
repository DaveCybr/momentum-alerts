"""
SmcCanonical — stateful SMC engine per spesifikasi xauusd-smc-trading-system.md.
Dibangun bertahap: tiap fungsi punya demo() sendiri.
"""
from __future__ import annotations
import pandas as pd

from engine.models import Bundle, Setup, SmcState
from engine import indicators as ind


def in_session(ts: pd.Timestamp, sessions_utc: list[list[int]], server_utc_offset: int = 0) -> bool:
    """True jika ts (waktu candle broker) di dalam salah satu jendela [start,end) UTC.
    entries: [start_h, start_m, end_h, end_m]."""
    utc_min = ((ts.hour - server_utc_offset) % 24) * 60 + ts.minute
    for sh, sm, eh, em in sessions_utc:
        if sh * 60 + sm <= utc_min < eh * 60 + em:
            return True
    return False


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
    """Bias H1 + BOS + protected level. Return (bias, bos_confirmed, protected_price, bos_idx)."""
    win = df.iloc[-p["struct_lookback"]:] if len(df) > p["struct_lookback"] else df
    highs, lows = _last_swings(win, p["swing_k"])
    if len(highs) < 1 or len(lows) < 1:
        return "none", False, 0.0, -1
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
    return last_bias, last_bias != "none", protected, last_bos_i


def bias_alive(df, bias, protected, _bos_idx, p):
    """§4: bias invalid jika body close menembus protected level di df terbaru."""
    if bias == "none" or protected == 0.0:
        return False
    closes = df["close"].values
    if bias == "bullish":
        return not bool((closes < protected).any())
    return not bool((closes > protected).any())


def dealing_range(df, bias, protected):
    """§5: anchor = protected -> external extreme impuls BOS. Return (lo, hi)."""
    if bias == "bullish":
        return protected, float(df["high"].max())
    return float(df["low"].min()), protected


def pd_zone(price, lo, hi):
    """premium/discount/equilibrium dari posisi harga di dealing range."""
    if hi <= lo:
        return "none"
    frac = (price - lo) / (hi - lo)
    if frac < 0.45:
        return "discount"
    if frac > 0.55:
        return "premium"
    return "equilibrium"


def _mk(rows, freq="5min"):
    idx = pd.date_range("2026-01-05 08:00", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1000.0
    return df


def demo():
    p = SMC_DEFAULTS
    sess = [[7, 0, 10, 0], [12, 0, 15, 30]]
    T = lambda h, m: pd.Timestamp(f"2026-01-05 {h:02d}:{m:02d}", tz="UTC")

    assert in_session(T(7, 0), sess, 0)
    assert not in_session(T(10, 0), sess, 0)
    assert in_session(T(15, 29), sess, 0)
    assert not in_session(T(15, 30), sess, 0)
    assert not in_session(T(11, 0), sess, 0)
    assert in_session(T(9, 0), sess, 2)
    assert not in_session(T(8, 59), sess, 2)
    print("[OK] in_session: minute precision + offset")

    # detect_bias: bullish BOS jelas
    rows = [(100, 100.4, 99.6, 100)] * 38
    rows[10] = (100, 100.5, 97.0, 100)
    rows[20] = (100, 103.0, 100.0, 100)
    rows += [(100, 100.5, 99.6, 100), (100, 104.5, 100.0, 104.2)]
    dfb = _mk(rows, "1h")
    bias, bos, prot, bos_idx = detect_bias(dfb, p)
    assert bias == "bullish" and bos, (bias, bos)
    assert bias_alive(dfb, bias, prot, bos_idx, p)

    brok = dfb.copy()
    ts = brok.index[-1] + (brok.index[-1] - brok.index[-2])
    brok.loc[ts] = [100, 100.0, prot - 5, prot - 4, 1000.0]
    win = brok.iloc[-p["struct_lookback"]:] if len(brok) > p["struct_lookback"] else brok
    ba = bias_alive(brok, "bullish", prot, bos_idx, p)
    assert not ba, "should be dead after violation"
    print("[OK] detect_bias + protected veto")

    # dealing_range anchored + pd_zone
    lo, hi = dealing_range(dfb, "bullish", prot)
    assert lo == prot, (lo, prot)
    assert hi >= 104.2
    assert pd_zone(lo + 0.1 * (hi - lo), lo, hi) == "discount"
    assert pd_zone(lo + 0.9 * (hi - lo), lo, hi) == "premium"
    assert pd_zone(lo + 0.5 * (hi - lo), lo, hi) == "equilibrium"
    print("[OK] dealing_range anchored + pd_zone")


if __name__ == "__main__":
    demo()
