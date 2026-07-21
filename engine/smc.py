"""
SMC pre-screen (deterministik) — CHALLENGER, bukan pengganti trend_pullback.

Tugas: "apakah ADA kandidat setup SMC di snapshot ini?" — mempersempit 24 jam
candle jadi segelintir momen kandidat SEBELUM AI dipanggil (task #3). Semua
trigger 100% deterministik (Prinsip #1 CLAUDE.md): AI tak pernah menghitung di sini.

Desain: DETEKSI STATELESS di snapshot candle terakhir (pola sama trend_pullback),
BUKAN mesin-status lintas-candle. Cukup untuk pre-screen; full state-machine =
pekerjaan lain kalau terbukti perlu (lihat memory smc-ai-pivot-decision).

7 kondisi (spek xauusd-smc-trading-system.md), semua diturunkan dari primitif
murni di indicators.py: bias H1, BOS, POI fresh, premium/discount, sweep M15,
displacement M5, MSS M5 — plus gerbang sesi London/NY dan RR>=rr_min.

Output = Setup biasa; checklist 7-boolean ditaruh di Setup.gates supaya
alert/journal/AI hilir jalan tanpa perlu ubah dataclass.
"""
from __future__ import annotations
import pandas as pd

from engine.models import Bundle, Setup
from engine import indicators as ind

SMC_DEFAULTS = dict(
    swing_k=2,
    atr_period=14,
    disp_body_ratio=0.65,
    disp_atr_mult=1.5,
    rr_min=2.5,
    rr_aplus=3.0,
    rr_cap=5.0,               # clamp RR ekstrem (SL M5 ketat + target H1 lebar → RR absurd,
                              # mis. 11.73, bikin TP tak realistis). Cap = batas TP masuk akal.
    struct_lookback=40,       # window candle utk cari swing struktural
    trigger_lookback=12,      # window candle M5 terakhir utk sweep/displacement/MSS
                              # (event berurutan, jarang pas di candle paling akhir)
    sweep_lookback=20,        # window M15 utk pool likuiditas + sweep M5
    sessions_utc=[[7, 16], [12, 21]],   # London 07-16, NY 12-21 UTC
    server_utc_offset=2,     # timestamp candle broker = UTC+2 (VERIFIED 20/07: H1 stamp 23:00
                             # saat UTC 21:00; daily stamp 00:00). Jam candle dikonversi ke UTC
                             # dulu sebelum cek sesi. CATATAN: broker bisa DST → cek ulang kalau +3.
    require_session=True,
)

def _closed(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Buang candle terakhir (masih terbentuk) — analisa hanya closed candle."""
    return df.iloc[:-1] if df is not None and len(df) > 1 else df


def _last_swings(df: pd.DataFrame, k: int) -> tuple[list[int], list[int]]:
    """Index posisi swing high & swing low terkonfirmasi (urut lama→baru)."""
    sh, sl = ind.swings(df, k)
    highs = [df.index.get_loc(i) for i in sh[sh].index]
    lows = [df.index.get_loc(i) for i in sl[sl].index]
    return highs, lows


def detect_bias(df: pd.DataFrame, p: dict) -> tuple[str, bool, float]:
    """Bias H1 + BOS + protected level. Return (bias, bos_confirmed, protected_price).
    bias: 'bullish'|'bearish'|'none'. Deterministik dari swing struktural + body close.
      Bullish: swing high struktural terakhir ditembus body close terbaru (BOS up),
               protected low = swing low terakhir sebelum impuls itu.
      Bearish: cermin."""
    win = df.iloc[-p["struct_lookback"]:] if len(df) > p["struct_lookback"] else df
    highs, lows = _last_swings(win, p["swing_k"])
    if len(highs) < 1 or len(lows) < 1:
        return "none", False, 0.0
    hv, lv, cv = win["high"].values, win["low"].values, win["close"].values
    n = len(win)

    # Scan KRONOLOGIS: BOS = close menembus swing high/low yang terkonfirmasi SEBELUMNYA.
    # Bias = arah BOS TERAKHIR di window (close sekarang tak perlu masih di atas/bawah —
    # setup dinilai saat retrace ke POI). Ini memperbaiki bug "harus di atas SH sekarang".
    last_bos_i, last_bias, protected = -1, "none", 0.0
    for i in range(n):
        # swing high/low yg sudah TERKONFIRMASI sebelum bar i (index + swing_k < i)
        prior_h = [hi for hi in highs if hi + p["swing_k"] < i]
        prior_l = [li for li in lows if li + p["swing_k"] < i]
        if prior_h:
            sh_i = prior_h[-1]
            if cv[i] > hv[sh_i] and i > last_bos_i:
                # protected low = swing low terakhir sebelum swing high yg ditembus
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


def find_tp_target(h1: pd.DataFrame, m15: pd.DataFrame | None, price: float,
                   bias: str, p: dict) -> float | None:
    """TP1 = opposing liquidity M15/H1 terdekat dari harga saat ini (§13).
    Bullish: swing HIGH terdekat di atas price (buy-side liquidity).
    Bearish: swing LOW terdekat di bawah price (sell-side liquidity).
    Prioritas: M15 swing dulu (lebih dekat), fallback ke H1 dealing range extreme."""
    candidates = []
    # M15 swing highs/lows
    if m15 is not None and len(m15) > p["swing_k"] * 2 + 2:
        win15 = m15.iloc[-p["sweep_lookback"] * 4:] if len(m15) > p["sweep_lookback"] * 4 else m15
        sh15, sl15 = ind.swings(win15, p["swing_k"])
        if bias == "bullish":
            cands15 = [float(win15["high"].loc[i]) for i in sh15[sh15].index
                       if float(win15["high"].loc[i]) > price]
        else:
            cands15 = [float(win15["low"].loc[i]) for i in sl15[sl15].index
                       if float(win15["low"].loc[i]) < price]
        candidates.extend(cands15)
    # H1 swing highs/lows
    win1 = h1.iloc[-p["struct_lookback"]:] if len(h1) > p["struct_lookback"] else h1
    sh1, sl1 = ind.swings(win1, p["swing_k"])
    if bias == "bullish":
        cands1 = [float(win1["high"].loc[i]) for i in sh1[sh1].index
                  if float(win1["high"].loc[i]) > price]
    else:
        cands1 = [float(win1["low"].loc[i]) for i in sl1[sl1].index
                  if float(win1["low"].loc[i]) < price]
    candidates.extend(cands1)
    if not candidates:
        return None
    # ambil yang TERDEKAT dari harga (nearest opposing liquidity)
    return min(candidates, key=lambda x: abs(x - price))


def dealing_range(df: pd.DataFrame, p: dict, bias: str) -> tuple[float, float]:
    """Dealing range dari dua swing eksternal (anchor = swing yg cipta BOS).
    Return (lo, hi). Bullish: protected low → external high. Bearish: kebalik."""
    win = df.iloc[-p["struct_lookback"]:] if len(df) > p["struct_lookback"] else df
    return float(win["low"].min()), float(win["high"].max())


def pd_zone(price: float, lo: float, hi: float) -> str:
    """premium/discount/equilibrium dari posisi harga di dealing range."""
    if hi <= lo:
        return "none"
    frac = (price - lo) / (hi - lo)
    if frac < 0.45:
        return "discount"
    if frac > 0.55:
        return "premium"
    return "equilibrium"


def swept_liquidity(m15: pd.DataFrame, m5: pd.DataFrame, p: dict, bias: str,
                    dealing_lo: float = 0.0, dealing_hi: float = 0.0) -> tuple[bool, int]:
    """Sweep: dalam trigger_lookback candle M5 TERAKHIR, ada wick melampaui swing low/high M15
    lalu close balik ke dalam range (§8). Return (swept, bar_in_trigger_window), bar=-1 jika tidak.

    #10: cek juga sweep terjadi DI DALAM zona POI (discount utk BUY, premium utk SELL).
    dealing_lo/hi = batas dealing range H1 (buat cek zona). Kalau 0 maka skip cek zona."""
    if m15 is None or m5 is None or len(m15) < p["sweep_lookback"] or len(m5) < 3:
        return (False, -1)
    sh_ser, sl_ser = ind.swings(m15, p["swing_k"])
    win = m5.iloc[-p["trigger_lookback"]:]
    lo_v, hi_v, cl_v = win["low"].values, win["high"].values, win["close"].values
    mid_range = (dealing_lo + dealing_hi) / 2 if (dealing_hi > dealing_lo) else 0.0
    for i in range(len(win)):
        cl = cl_v[i]
        # cek zona: sweep harus di discount (BUY) atau premium (SELL)
        if mid_range > 0:
            in_zone = (cl <= mid_range) if bias == "bullish" else (cl >= mid_range)
            if not in_zone:
                continue
        if bias == "bullish":
            swing_lows = [float(m15["low"].loc[j]) for j in sl_ser[sl_ser].index]
            if not swing_lows: continue
            pool_lo = swing_lows[-1]
            if lo_v[i] < pool_lo and cl_v[i] > pool_lo:
                return (True, i)
        if bias == "bearish":
            swing_highs = [float(m15["high"].loc[j]) for j in sh_ser[sh_ser].index]
            if not swing_highs: continue
            pool_hi = swing_highs[-1]
            if hi_v[i] > pool_hi and cl_v[i] < pool_hi:
                return (True, i)
    return (False, -1)
# PLACEHOLDER_HELPERS
def _in_session(ts: pd.Timestamp, sessions_utc: list[list[int]], server_utc_offset: int = 0) -> bool:
    """True kalau ts (jam CANDLE broker) di dalam salah satu jendela sesi UTC [start,end).
    ts.hour = jam broker (UTC+server_utc_offset) → konversi ke UTC dulu sebelum banding."""
    hr = (ts.hour - server_utc_offset) % 24
    return any(a <= hr < b for a, b in sessions_utc)


def _mss(m5: pd.DataFrame, p: dict, bias: str, after_bar: int = -1) -> tuple[bool, bool]:
    """MSS M5 dalam trigger_lookback candle TERAKHIR: displacement searah bias yang
    close-nya menembus swing internal terkonfirmasi sebelumnya. Windowed karena MSS
    terjadi di tengah urutan. Return (mss_confirmed, displaced_in_window).
    after_bar (#10): kalau >= 0, hanya scan SETELAH bar itu (jamin urutan sweep→disp→MSS)."""
    win_s = m5.iloc[-p["struct_lookback"]:] if len(m5) > p["struct_lookback"] else m5
    disp = ind.displacement(win_s, atr_mult=p["disp_atr_mult"],
                            body_ratio=p["disp_body_ratio"], atr_period=p["atr_period"])
    highs, lows = _last_swings(win_s, p["swing_k"])
    hv, lv, cv = win_s["high"].values, win_s["low"].values, win_s["close"].values
    n = len(win_s)
    trigger_start = max(0, n - p["trigger_lookback"])
    # jamin urutan: jangan scan sebelum sweep (after_bar dalam koordinat trigger window)
    scan_start = trigger_start if after_bar < 0 else trigger_start + after_bar + 1
    scan_start = min(scan_start, n)
    displaced = False
    mss = False
    for i in range(scan_start, n):
        s = int(disp.iloc[i])
        if bias == "bullish" and s > 0:
            displaced = True
            prior_h = [hi for hi in highs if hi + p["swing_k"] < i]
            if prior_h and cv[i] > hv[prior_h[-1]]:
                mss = True
        if bias == "bearish" and s < 0:
            displaced = True
            prior_l = [li for li in lows if li + p["swing_k"] < i]
            if prior_l and cv[i] < lv[prior_l[-1]]:
                mss = True
    return (mss, displaced)


class SmcPrescreen:
    name = "smc_prescreen"
    version = "0.1"     # stateless snapshot detector; challenger (bukan strategy aktif)

    def _analyze(self, bundle: Bundle, p: dict) -> dict | None:
        """Hitung checklist SMC penuh + parameter setup, TANPA gerbang keras/sesi.
        Return None kalau data kurang atau bias none. Dipakai evaluate() (gate keras)
        DAN screen() (shadow log-only: grade kandidat partial >= min_gates)."""
        h1, m15, m5 = _closed(bundle.df("H1")), _closed(bundle.df("M15")), _closed(bundle.df("M5"))
        if h1 is None or m5 is None or len(h1) < p["struct_lookback"] + 5 or len(m5) < 20:
            return None
        in_sess = _in_session(m5.index[-1], p["sessions_utc"], p.get("server_utc_offset", 0))

        # 1-2. bias H1 + BOS
        bias, bos, protected = detect_bias(h1, p)
        if bias == "none":
            return None

        # 4. premium/discount dari dealing range H1 (var: lo, hi, zone, correct_pd)
        lo, hi = dealing_range(h1, p, bias)
        zone = pd_zone(float(h1["close"].iloc[-1]), lo, hi)
        correct_pd = (bias == "bullish" and zone == "discount") or (bias == "bearish" and zone == "premium")

        # 5. sweep likuiditas M15→M5 + cek di dalam zona POI (§10: sweep harus di POI)
        sweep, sweep_bar = swept_liquidity(m15, m5, p, bias, lo, hi)

        # 6-7. displacement + MSS di M5 — HANYA setelah sweep (§10: jamin urutan)
        mss, displaced = _mss(m5, p, bias, sweep_bar if sweep else -1)

        # 3. POI fresh + ZONA ENTRY: FVG M5 searah bias di trigger window (§11).
        # Entry limit di 50% FVG (midpoint). Tanpa FVG → tak ada zona entry → setup gagal.
        win_i0 = len(m5) - p["trigger_lookback"]
        zones = [z for z in ind.fvg_zones(m5, bull=(bias == "bullish")) if z[0] >= win_i0]
        poi_fresh = bool(zones)
        price = float(bundle.price or m5["close"].iloc[-1])
        direction = "BUY" if bias == "bullish" else "SELL"

        # entry = 50% FVG M5 TERBARU searah bias (§11: limit, BUKAN market)
        entry = zones[-1][3] if zones else price          # midpoint zona terakhir
        fvg_lo, fvg_hi = (zones[-1][1], zones[-1][2]) if zones else (price, price)

        # SL di sisi invalidasi (sweep extreme M5) + buffer.
        # TP = opposing liquidity M15/H1 terdekat (§13), RR dari ENTRY AKTUAL.
        if bias == "bullish":
            sl = float(m5["low"].iloc[-3:].min()) - 0.05 * abs(hi - lo)
            target = find_tp_target(h1, m15, entry, bias, p) or hi
            risk = entry - sl
            rr = round((target - entry) / risk, 2) if risk > 0 else 0.0
            entry_low, entry_high = round(fvg_lo, 2), round(fvg_hi, 2)
        else:
            sl = float(m5["high"].iloc[-3:].max()) + 0.05 * abs(hi - lo)
            target = find_tp_target(h1, m15, entry, bias, p) or lo
            risk = sl - entry
            rr = round((entry - target) / risk, 2) if risk > 0 else 0.0
            entry_low, entry_high = round(fvg_lo, 2), round(fvg_hi, 2)

        # clamp RR ekstrem → TP realistis (lihat rr_cap). Cap SETELAH hitung, sebelum
        # mengalir ke gate/tier/TP. rr>=rr_min tetap lolos gate; cuma nilai atasnya dibatasi.
        rr = min(rr, float(p["rr_cap"]))

        checklist = {
            "h1_bias": bias, "bos": bos, "poi_fresh": poi_fresh, "correct_pd": correct_pd,
            "sweep_m15": sweep, "displacement": displaced, "mss": mss,
            "rr": rr, "session": in_sess, "zone": zone,
        }
        # jumlah gerbang boolean lolos (dari 7 kondisi inti + RR) — dipakai screen() utk partial
        gates_passed = sum(1 for k in ("bos", "poi_fresh", "correct_pd", "sweep_m15",
                                       "displacement", "mss") if checklist[k]) + \
            (1 if rr >= p["rr_min"] else 0)
        return dict(
            bias=bias, direction=direction, checklist=checklist, gates_passed=gates_passed,
            price=price, entry=entry, target=target, sl=sl, risk=risk, rr=rr,
            entry_low=entry_low, entry_high=entry_high, in_sess=in_sess, zone=zone,
        )

    def _mk_setup(self, symbol: str, a: dict, p: dict) -> Setup:
        """Rakit Setup dari hasil _analyze (dipakai evaluate & screen saat fire penuh)."""
        bias, entry, risk, rr = a["bias"], a["entry"], a["risk"], a["rr"]
        tier = "HIGH_CONF" if rr >= p["rr_aplus"] else "NORMAL"
        score = sum(1 for k in ("bos", "poi_fresh", "correct_pd", "sweep_m15", "displacement", "mss")
                    if a["checklist"][k]) + (1 if rr >= p["rr_aplus"] else 0)
        # TP dihitung dari ENTRY AKTUAL (50% FVG), bukan harga sekarang (§13).
        # sorted() jaga TP monoton walau rr<1.5. Utk rr>=1.5 urutan tak berubah.
        mults = sorted((1.5, rr, rr * 1.4))
        if bias == "bullish":
            tp = [round(entry + m * risk, 2) for m in mults]
        else:
            tp = [round(entry - m * risk, 2) for m in mults]
        return Setup(
            symbol=symbol, direction=a["direction"], tf="M5",
            entry_low=a["entry_low"], entry_high=a["entry_high"], sl=round(a["sl"], 2), tp=tp,
            tier=tier, score=score,
            reason=f"SMC {bias} · BOS · sweep · displacement · MSS · RR{rr} · {a['zone']}",
            gates=a["checklist"], experimental=True,   # SMC = challenger, tandai eksperimen
        )

    def evaluate(self, bundle: Bundle, params: dict) -> Setup | None:
        """Gerbang KERAS: fire hanya kalau 7 kondisi + RR>=rr_min + sesi semua lolos.
        Perilaku produksi (tak berubah dari versi tervalidasi)."""
        p = {**SMC_DEFAULTS, **(params or {})}
        a = self._analyze(bundle, p)
        if a is None:
            return None
        if p["require_session"] and not a["in_sess"]:
            return None
        cl = a["checklist"]
        hard = all([cl["h1_bias"] in ("bullish", "bearish"), cl["bos"], cl["poi_fresh"],
                    cl["correct_pd"], cl["sweep_m15"], cl["displacement"], cl["mss"],
                    a["rr"] >= p["rr_min"]])
        if not hard or a["risk"] <= 0:
            return None
        return self._mk_setup(bundle.symbol, a, p)

    def screen(self, bundle: Bundle, params: dict, min_gates: int = 5) -> dict | None:
        """SHADOW log-only (task #3): kembalikan checklist + setup buat kandidat yg lolos
        >= min_gates gerbang, walau belum fire penuh. TIDAK nge-gate apa pun — cuma bahan
        AI grade + jurnal. Return dict {checklist, gates_passed, fired, setup?} atau None."""
        p = {**SMC_DEFAULTS, **(params or {})}
        a = self._analyze(bundle, p)
        if a is None or a["risk"] <= 0:
            return None
        if a["gates_passed"] < min_gates:
            return None
        fired = (a["gates_passed"] == 7 and (not p["require_session"] or a["in_sess"]))
        return dict(
            checklist=a["checklist"], gates_passed=a["gates_passed"], fired=fired,
            setup=self._mk_setup(bundle.symbol, a, p),
        )
# PLACEHOLDER_CLASS
def _mk(rows: list[tuple], freq: str = "1h") -> pd.DataFrame:
    idx = pd.date_range("2026-01-05 08:00", periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 1000.0
    return df


def demo():
    p = SMC_DEFAULTS
    # detect_bias: konstruksi BOS bullish jelas (swing low, swing high, lalu close tembus high)
    rows = []
    base = 100.0
    for i in range(38):                       # noise datar
        rows.append((base, base + 0.4, base - 0.4, base))
    rows[10] = (100, 100.5, 97.0, 100)        # swing low jelas @ idx10
    rows[20] = (100, 103.0, 100, 100)         # swing high @ idx20
    rows.append((100, 100.5, 99.6, 100))
    rows.append((100, 104.5, 100, 104.2))     # close tembus di atas swing high → BOS up
    dfb = _mk(rows)
    bias, bos, prot = detect_bias(dfb, p)
    assert bias == "bullish" and bos, f"harus bullish BOS, dapat {bias} {bos}"
    print(f"[OK] detect_bias: {bias} BOS={bos} protected={prot:.1f}")

    # pd_zone: matematika premium/discount
    assert pd_zone(10, 0, 100) == "discount"
    assert pd_zone(90, 0, 100) == "premium"
    assert pd_zone(50, 0, 100) == "equilibrium"
    print("[OK] pd_zone: discount/premium/equilibrium")

    # _in_session: konversi jam broker → UTC (offset +2, VERIFIED 20/07)
    # offset 0: jam 09 UTC di London window, 03 di luar
    assert _in_session(pd.Timestamp("2026-01-05 09:00", tz="UTC"), p["sessions_utc"], 0)
    assert not _in_session(pd.Timestamp("2026-01-05 03:00", tz="UTC"), p["sessions_utc"], 0)
    # offset +2: candle stamp 09 broker = 07 UTC (masuk London 07-16); candle 08 broker = 06 UTC (di luar)
    assert _in_session(pd.Timestamp("2026-01-05 09:00", tz="UTC"), p["sessions_utc"], 2)
    assert not _in_session(pd.Timestamp("2026-01-05 08:00", tz="UTC"), p["sessions_utc"], 2)
    # candle 18 broker = 16 UTC (NY 12-21 masih, London tutup) → masuk NY
    assert _in_session(pd.Timestamp("2026-01-05 18:00", tz="UTC"), p["sessions_utc"], 2)
    print("[OK] in_session: konversi offset broker->UTC benar")

    # swept_liquidity bullish: M15 punya SWING LOW nyata @99, wick M5 tembus lalu ditolak
    m15rows = [(100, 100.6, 99.7, 100)] * 25
    m15rows[10] = (100, 100.5, 99.0, 100)      # swing low jelas @99 (lebih rendah dari tetangga)
    m15 = _mk(m15rows, "15min")
    m5rows = [(100, 100.5, 99.5, 100)] * 8
    m5rows[-3] = (100, 100.2, 98.5, 100.1)     # wick low 98.5 < swing_low(99), close 100.1 > 99
    m5 = _mk(m5rows, "5min")
    assert swept_liquidity(m15, m5, p, "bullish")[0], "harus deteksi sell-side sweep"
    print("[OK] swept_liquidity: sell-side sweep (swing-based)")

    # pipeline penuh: data datar → tak ada setup, TAK crash, return None
    flat = _mk([(100, 100.3, 99.7, 100)] * 60)
    b = Bundle("XAUUSD", price=100.0,
               tf={"H1": flat, "M15": _mk([(100, 100.3, 99.7, 100)] * 60, "15min"),
                   "M5": _mk([(100, 100.3, 99.7, 100)] * 60, "5min")})
    assert SmcPrescreen().evaluate(b, {}) is None, "data datar harus None"
    print("[OK] evaluate(flat) -> None (no false positive)")

    # _mk_setup: TP WAJIB monoton walau rr<1.5 (regresi bug audit — dulu tp[1]<tp[0])
    s = SmcPrescreen()
    for bias_, rr_ in (("bullish", 0.55), ("bearish", 0.55), ("bullish", 3.0), ("bearish", 3.0)):
        a = dict(bias=bias_, direction="BUY" if bias_ == "bullish" else "SELL",
                 price=100.0, entry=99.0, target=110.0, risk=5.0, rr=rr_, sl=95.0,
                 entry_low=98.0, entry_high=100.0,
                 checklist={k: True for k in ("bos", "poi_fresh", "correct_pd", "sweep_m15",
                                              "displacement", "mss")}, zone="discount")
        tp = s._mk_setup("X", a, p).tp
        mono = tp[0] <= tp[1] <= tp[2] if bias_ == "bullish" else tp[0] >= tp[1] >= tp[2]
        assert mono, f"TP tak monoton {bias_} rr={rr_}: {tp}"
    print("[OK] _mk_setup: TP monoton (rr<1.5 & rr>=1.5, BUY & SELL)")


if __name__ == "__main__":
    demo()
