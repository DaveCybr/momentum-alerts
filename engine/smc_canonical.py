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


def find_poi(h1, bias, lo, hi, p):
    """§6: OB H1 dengan FVG dari displacement sama, di sisi P/D yang benar, fresh.
    Returns dict(proximal, distal, origin_idx) atau None.
    Bullish: proximal=OB high (tutup terbentuk sebelum displacement), distal=OB low.
    Bearish: kebalik."""
    win = h1.iloc[-p["poi_lookback"]:] if len(h1) > p["poi_lookback"] else h1
    o, c = win["open"].values, win["close"].values
    hv, lv = win["high"].values, win["low"].values
    disp = ind.displacement(win, body_ratio=p["disp_body_ratio"],
                            atr_mult=p["disp_atr_mult"], atr_period=p["atr_period"])
    fvg = ind.fvg_zones(win, bull=(bias == "bullish"))
    fvg_by_idx = {z[0]: z for z in fvg}
    best = None
    for i in range(2, len(win)):
        s = int(disp.iloc[i])
        want = 1 if bias == "bullish" else -1
        if s != want:
            continue
        if i not in fvg_by_idx and (i + 1) not in fvg_by_idx:
            continue
        j = i - 1
        while j >= 0:
            opp = (c[j] < o[j]) if bias == "bullish" else (c[j] > o[j])
            if opp:
                break
            j -= 1
        if j < 0:
            continue
        if bias == "bullish":
            prox, dist = float(hv[j]), float(lv[j])
            mid = (dist + prox) / 2
            if pd_zone(mid, lo, hi) != "discount":
                continue
        else:
            prox, dist = float(lv[j]), float(hv[j])
            mid = (dist + prox) / 2
            if pd_zone(mid, lo, hi) != "premium":
                continue
        best = {"proximal": prox, "distal": dist, "origin_idx": int(j)}
    return best


def poi_fresh(h1, poi):
    """§6: fresh = belum ada close masuk kembali ke zona POI sejak pembentukan."""
    idx = poi["origin_idx"]
    after = h1.iloc[idx + 3:] if len(h1) > idx + 3 else h1.iloc[len(h1):]
    zlo, zhi = sorted([poi["proximal"], poi["distal"]])
    for _, r in after.iterrows():
        if zlo <= float(r["close"]) <= zhi:
            return False
    return True


def poi_invalidated(h1, poi, bias):
    """§6: invalid jika H1 close menembus distal edge."""
    idx = poi["origin_idx"]
    after = h1.iloc[idx + 1:]
    dist = poi["distal"]
    if bias == "bullish":
        return bool((after["close"].values < dist).any())
    return bool((after["close"].values > dist).any())


def swept_in_poi(m15, m5, bias, poi, p):
    """§8: wick M5 melewati liquidity M15 saat harga di dalam POI H1.
    Returns (swept, m5_bar_index_in_trigger_window, sweep_extreme)."""
    if m15 is None or m5 is None or len(m15) < p["sweep_lookback"] or len(m5) < 3:
        return (False, -1, 0.0)
    sh, sl = ind.swings(m15, p["swing_k"])
    win = m5.iloc[-p["trigger_lookback"]:]
    lo_v, hi_v, cl_v = win["low"].values, win["high"].values, win["close"].values
    zlo = min(poi["proximal"], poi["distal"])
    zhi = max(poi["proximal"], poi["distal"])
    for i in range(len(win)):
        if not (lo_v[i] <= zhi and hi_v[i] >= zlo):
            continue
        if bias == "bullish":
            pools = [float(m15["low"].loc[j]) for j in sl[sl].index]
            if not pools: continue
            pool = pools[-1]
            if lo_v[i] < pool and cl_v[i] > pool:
                return (True, i, float(lo_v[i]))
        else:
            pools = [float(m15["high"].loc[j]) for j in sh[sh].index]
            if not pools: continue
            pool = pools[-1]
            if hi_v[i] > pool and cl_v[i] < pool:
                return (True, i, float(hi_v[i]))
    return (False, -1, 0.0)


def mss_after_sweep(m5, bias, sweep_bar, p):
    """§9-10: displacement setelah sweep memecah structural swing M5 pra-sweep + FVG.
    Returns (confirmed, entry_50pct, (fvg_lo, fvg_hi))."""
    win = m5.iloc[-p["trigger_lookback"]:]
    n = len(win)
    if sweep_bar < 0 or sweep_bar >= n:
        return (False, 0.0, (0.0, 0.0))
    highs, lows = _last_swings(win, p["swing_k"])
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

    # POI H1 dengan OB+FVG bullish
    poi_src = [(100.5, 100.6, 99.0, 99.2),           # bearish base (OB origin), di discount
               (99.2, 103.5, 99.2, 103.3),            # displacement up
               (103.3, 104.0, 103.1, 103.8)]          # gap: high[0]=100.6 < low[2]=103.1 → FVG
    fill = [(100, 100.3, 99.7, 100)] * 10
    rows_poi = fill + poi_src
    df_poi = _mk(rows_poi, "1h")
    lo2, hi2 = 97.0, 104.0
    poi = find_poi(df_poi, "bullish", lo2, hi2, p)
    assert poi is not None and poi["proximal"] > poi["distal"], poi
    assert poi_fresh(df_poi, poi)
    inv = df_poi.copy()
    ts_inv = inv.index[-1] + (inv.index[-1] - inv.index[-2])
    inv.loc[ts_inv] = [100, 100, poi["distal"] - 2, poi["distal"] - 1, 1000.0]
    assert poi_invalidated(inv, poi, "bullish")
    print("[OK] find_poi + fresh + distal invalidation")

    # Sweep di dalam POI + MSS memecah swing pra-sweep
    m15s = [(100, 100.6, 99.7, 100)] * 25
    m15s[10] = (100, 100.5, 99.0, 100)
    m15b = _mk(m15s, "15min")
    poi2 = {"proximal": 100.2, "distal": 98.8, "origin_idx": 0}
    m5s = [(100, 100.4, 99.6, 99.9)] * 19
    m5s += [(100, 100.4, 99.6, 99.9)]                 # win[0]
    m5s += [(100, 100.4, 99.6, 99.9)]                 # win[1]
    m5s += [(100, 101.5, 100, 101.5)]                 # win[2]: swing high
    m5s += [(101.5, 101.3, 101.0, 101.2)]            # win[3]
    m5s += [(101.2, 101.0, 100.5, 100.6)]            # win[4]
    m5s += [(100.5, 100.8, 100.2, 100.3)]            # win[5]
    m5s += [(99.9, 100.2, 98.5, 100.1)]              # win[6]: sweep
    m5s += [(100.1, 100.2, 99.9, 100.15)]            # win[7]
    m5s += [(100.15, 102.5, 100.1, 102.3)]           # win[8]: displacement, close > swing high
    m5s += [(102.3, 102.6, 102.0, 102.4)]            # win[9]: FVG + follow-through
    m5s += [(102.4, 102.5, 102.1, 102.3)]
    m5s += [(102.3, 102.7, 102.2, 102.6)]
    m5b = _mk(m5s, "5min")
    sw, bar, ext = swept_in_poi(m15b, m5b, "bullish", poi2, p)
    assert sw and ext <= 98.5, (sw, bar, ext)
    ok_ms, entry50, (flo, fhi) = mss_after_sweep(m5b, "bullish", bar, p)
    assert ok_ms and flo < entry50 < fhi, (ok_ms, entry50, flo, fhi)
    print("[OK] sweep-in-POI + MSS pre-sweep swing + 50% FVG")


if __name__ == "__main__":
    demo()
