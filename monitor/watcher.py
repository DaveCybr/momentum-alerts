"""
Monitor — auto-outcome (bunuh pembunuh #1: males jurnal) + dead-man's switch.
Jalan tiap ~1 menit. Owner cukup 1 tap; menang/kalah di-track sendiri.

Dua jalur outcome (dipisah oleh ada/tidaknya ticket di alert):
  · TAK dieksekusi → simulasi `outcome_for` vs TP referensi (ukur KUALITAS SINYAL).
  · Dieksekusi     → `reconcile_executed`: PnL realized RIIL dari history deal broker (runner jujur).
ponytail: sim = snapshot ~1mnt, tutup di sentuhan TP1; jalur riil menunggu posisi tutup di broker.
"""
from __future__ import annotations
import json
from datetime import datetime

from journal.db import Journal
from ops.clock import WIB, now_wib, wib_str


def outcome_for(alert_row, price: float):
    """(result, hit) kalau sudah terminal, else None. Long & short."""
    d = alert_row["direction"]
    sl = alert_row["sl"]
    tp = json.loads(alert_row["tp_json"])
    if d == "BUY":
        if price <= sl:
            return ("LOSS", "SL")
        if price >= tp[0]:
            return ("WIN", "TP3" if price >= tp[2] else "TP2" if price >= tp[1] else "TP1")
    else:  # SELL (belum dipakai v1 long-only, tapi siap)
        if price >= sl:
            return ("LOSS", "SL")
        if price <= tp[0]:
            return ("WIN", "TP3" if price <= tp[2] else "TP2" if price <= tp[1] else "TP1")
    return None


def run_pass(journal: Journal, cfg: dict) -> int:
    """Cek semua alert terbuka vs harga (per-simbol). Return jumlah yang ditutup."""
    from data.sources import fetch_price
    closed = 0
    price_cache: dict[str, float] = {}
    for a in journal.open_alerts():
        sym = a["symbol"]
        if sym not in price_cache:
            price_cache[sym] = fetch_price(cfg["data"], sym)
        price = price_cache[sym]
        if price <= 0:
            continue
        oc = outcome_for(a, price)
        if oc:
            journal.label_outcome(a["id"], oc[0], oc[1], price)
            print(f"[monitor] alert #{a['id']} {sym} {oc[0]} ({oc[1]}) @ {price}")
            closed += 1
    return closed


def realized_outcome(deals: list[dict]) -> tuple[str, float, float]:
    """Dari deal-deal SATU posisi → (result, exit_price, net_profit). Murni, testable.
    deal = {profit,swap,commission,price,time,entry}. entry: 0=IN, 1=OUT (DEAL_ENTRY_OUT)."""
    net = sum(d["profit"] + d["swap"] + d["commission"] for d in deals)
    outs = [d for d in deals if d.get("entry") == 1] or deals        # exit deals (fallback: semua)
    exit_price = max(outs, key=lambda d: d["time"])["price"]         # exit terakhir
    result = "WIN" if net > 0 else "LOSS" if net < 0 else "BE"
    return result, float(exit_price), round(net, 2)


def reconcile_executed(journal: Journal, cfg: dict) -> int:
    """Alert DIEKSEKUSI (punya ticket) yg posisinya sudah tutup di broker → catat outcome RIIL
    (WIN/LOSS/BE + PnL realized) dari history deal. Return jumlah direkonsiliasi."""
    from data import sources
    rows = journal.open_executed()
    if not rows:
        return 0
    n = 0
    with sources.MT5_LOCK:
        m = sources._connect(cfg["data"]["mt5"])
        for a in rows:
            tk = int(a["ticket"])
            # JANGAN obtain(): TradePosition/TradeDeal tak bisa di-pickle server wine-python
            # (sama seperti tick — akses atribut netref langsung, lihat data/sources.py).
            pos = m.positions_get(ticket=tk)
            if pos is None or len(pos) > 0:               # None=error, >0=masih terbuka → JANGAN finalisasi
                continue
            raw = m.history_deals_get(position=tk)
            deals = [{"profit": float(d.profit), "swap": float(d.swap),
                      "commission": float(d.commission), "price": float(d.price),
                      "time": int(d.time), "entry": int(d.entry)} for d in (raw or [])]
            if not any(d["entry"] == 1 for d in deals):   # belum ada deal exit → histori belum siap, tunggu
                continue
            result, exit_price, net = realized_outcome(deals)
            journal.label_outcome(a["id"], result, "REAL", exit_price, net)
            print(f"[reconcile] alert #{a['id']} {a['symbol']} {result} PnL={net} @ {exit_price}")
            n += 1
    return n


def check_deadman(journal: Journal, cfg_sched: dict, tg_cfg: dict, now: datetime | None = None) -> bool:
    """Kalau scheduler diam > ambang, teriak ke Telegram. Return True kalau alarm dikirim."""
    from delivery import telegram
    now = now or now_wib()
    hb = journal.cfg_get("heartbeat_wib")
    if not hb:
        return False
    age_min = (now - datetime.strptime(hb.replace(" WIB", ""), "%d/%m/%Y %H:%M").replace(tzinfo=WIB)).total_seconds() / 60
    limit = cfg_sched.get("deadman_min", 90)   # ~2x M30 + buffer
    if age_min <= limit:
        return False
    last = journal.cfg_get("deadman_last")
    if last and (now - datetime.strptime(last.replace(" WIB", ""), "%d/%m/%Y %H:%M").replace(tzinfo=WIB)).total_seconds() / 60 < limit:
        return False  # sudah dialarm baru-baru ini, jangan spam
    telegram.send(f"⚠️ Momentum Alert BUTA — scheduler diam {age_min:.0f} menit "
                  f"(heartbeat terakhir {hb}). Cek bridge/proses.", tg_cfg)
    journal.cfg_set("deadman_last", wib_str(now))
    return True


# ── Trailing stop chandelier (pengganti TP3 keras) — fungsi murni, testable tanpa MT5 ──
def chandelier(is_buy: bool, extreme: float, atr: float, mult: float) -> float:
    """Level stop dari extreme favorable sejak entry (highest-high BUY / lowest-low SELL)."""
    return extreme - mult * atr if is_buy else extreme + mult * atr


def next_trail_sl(is_buy: bool, cur_sl: float, extreme: float, atr: float,
                  mult: float, price: float, min_dist: float) -> float | None:
    """SL baru setelah ratchet (cuma gerak ke arah profit) + clamp jarak-minimum broker.
    Return None kalau tak ada perbaikan → jangan modify (hemat order + tak pernah mengendur)."""
    raw = chandelier(is_buy, extreme, atr, mult)
    if is_buy:
        raw = min(raw, price - min_dist)         # SL wajib di bawah harga ≥ min_dist (else broker tolak)
        return raw if raw > cur_sl else None     # naik doang
    raw = max(raw, price + min_dist)             # SELL: SL wajib di atas harga ≥ min_dist
    return raw if raw < cur_sl else None          # turun doang


def trail_after_1r(is_buy: bool, entry: float, initial_sl: float, cur_sl: float,
                   extreme: float, atr: float, mult: float, price: float,
                   min_dist: float, activate_r: float = 1.0) -> float | None:
    """Trailing DENGAN grace-period. SL diam di initial sampai profit ≥ activate_r×R,
    baru SL loncat ke MINIMAL breakeven lalu ratchet chandelier ngunci profit.
    Cegah whipsaw di zona rugi: sebelum trade 'buktikan diri' (1R), SL nggak didekatin.
      R = |entry − initial_sl|. reached = extreme sudah bergerak ≥ activate_r×R ke arah profit.
    Return SL baru, atau None (jangan modify)."""
    R = abs(entry - initial_sl)
    if R <= 0:
        return None
    moved = (extreme - entry) if is_buy else (entry - extreme)   # profit terjauh sejak entry
    if moved < activate_r * R:
        return None                              # grace-period: biarkan SL initial (lebar)
    raw = chandelier(is_buy, extreme, atr, mult)
    if is_buy:
        raw = max(raw, entry)                    # minimal BE (jangan di bawah entry)
        raw = min(raw, price - min_dist)         # clamp broker
        return raw if raw > cur_sl else None     # ratchet naik
    raw = min(raw, entry)                        # SELL: minimal BE (jangan di atas entry)
    raw = max(raw, price + min_dist)             # clamp broker
    return raw if raw < cur_sl else None         # ratchet turun


def manage_positions(cfg: dict, journal: Journal | None = None):
    """Trailing chandelier per posisi (magic kita): order tanpa TP keras → runner bebas jalan.
    Grace-period: SL diam di initial sampai profit ≥ activate_r×R, baru loncat ke BE lalu
    ratchet ngunci profit. Saat lock pertama ke BE: bank separuh. Butuh `journal` utk initial SL."""
    import pandas as pd
    from data import sources
    from engine import indicators as ind
    from execute import broker
    ex = cfg["execution"]; magic = int(ex.get("magic", 0))
    if not ex.get("trailing", True):        # L1: mode TP-keras → broker yg kelola exit, jangan trail
        return
    tr = ex.get("trail", {})
    tf = tr.get("tf", "M30"); ap = int(tr.get("atr_period", 14))
    mult = float(tr.get("atr_mult", 3.0)); count = int(tr.get("count", 200))
    do_partial = bool(tr.get("partial_on_lock", True))
    activate_r = float(tr.get("activate_r", 1.0))            # trail mulai setelah profit ≥ activate_r×R
    with sources.MT5_LOCK:                                    # serialisasi akses MT5 (RLock reentrant)
        m = sources._connect(cfg["data"]["mt5"])
        for sym in cfg["instruments"]:
            pos = [p for p in (m.positions_get(symbol=sym) or []) if int(p.magic) == magic]
            if not pos:
                continue
            df = sources._fetch(m, sym, tf, count)             # pakai `m` yg sama, tak re-lock
            if df is None or len(df) < ap + 2:
                continue
            closed = df.iloc[:-1]                               # buang candle forming
            atr = float(ind.atr(closed, ap).iloc[-1])
            if atr <= 0:
                continue
            si = m.symbol_info(sym); point = float(si.point) or 0.01
            digits = int(getattr(si, "digits", 2) or 2)
            min_dist = float(getattr(si, "trade_stops_level", 0) or 0) * point
            vmin, vstep = float(si.volume_min), float(si.volume_step)
            for p in pos:
                is_buy = int(p.type) == 0
                entry = float(p.price_open); cur_sl = float(p.sl); vol = float(p.volume)
                since = pd.to_datetime(int(p.time), unit="s")
                win = closed[closed.index >= since]
                if len(win) == 0:                              # ponytail: holding > count bar → pakai N terakhir
                    win = closed.tail(ap)
                extreme = float(win["high"].max() if is_buy else win["low"].min())
                tick = m.symbol_info_tick(sym)
                price = float(tick.bid if is_buy else tick.ask)
                # initial SL (dari jurnal) → R. Fallback: cur_sl (kalau belum pernah trail, itu = initial).
                initial_sl = (journal.initial_sl_for_ticket(int(p.ticket)) if journal else None) or cur_sl
                new_sl = trail_after_1r(is_buy, entry, initial_sl, cur_sl, extreme, atr,
                                        mult, price, min_dist, activate_r)
                if new_sl is None:
                    continue
                new_sl = round(new_sl, digits)
                locked_before = cur_sl >= entry if is_buy else cur_sl <= entry
                locks_now = new_sl >= entry if is_buy else new_sl <= entry
                # Geser SL DULU. Partial hanya kalau geser sukses → cur_sl pasti pindah,
                # jadi transisi lock-BE tak terulang (cegah double-partial saat modify gagal).
                if not broker.modify_sl(cfg, sym, int(p.ticket), new_sl, 0.0):   # tp=0 → tanpa cap
                    print(f"[manage] {sym} #{int(p.ticket)} modify SL gagal (new_sl={new_sl})")
                    continue
                print(f"[manage] {sym} #{int(p.ticket)} trail SL->{new_sl} (atr={atr:.2f})")
                if do_partial and locks_now and not locked_before and vol >= 2 * vmin:
                    half = max(vmin, int((vol / 2) / vstep) * vstep)
                    if broker.close_partial(cfg, sym, int(p.ticket), half, is_buy):
                        print(f"[manage] {sym} #{int(p.ticket)} partial {half} @ lock-BE")


def demo():
    # trailing chandelier: ratchet + clamp jarak-min, BUY & SELL
    assert next_trail_sl(True, 2961, 3100, 10, 3, 3105, 1.0) == 3070   # 3100-3*10, naik dari 2961
    assert next_trail_sl(True, 3080, 3100, 10, 3, 3105, 1.0) is None   # ratchet: sudah lebih tinggi
    assert next_trail_sl(True, 2961, 3100, 10, 3, 3072, 5.0) == 3067   # clamp: SL ≤ price-min_dist
    assert next_trail_sl(False, 2039, 2000, 10, 3, 1995, 1.0) == 2030  # SELL cermin: 2000+3*10
    assert next_trail_sl(False, 2020, 2000, 10, 3, 1995, 1.0) is None  # SELL ratchet
    # trail_after_1r: grace-period 1R + snap ke BE. entry=4001, initial_sl=4029 → R=28.
    #   SELL: profit = entry - extreme. 1R tercapai kalau extreme ≤ 4001-28 = 3973.
    assert trail_after_1r(False, 4001, 4029, 4029, 3983, 12, 3, 3990, 0.01, 1.0) is None  # low 3983: baru 18<28 → DIAM
    #   extreme 3970 (profit 31 ≥ 28), harga 3975 masih < BE → chandelier=3970+36=4006 → min BE=4001 → SL=4001
    assert trail_after_1r(False, 4001, 4029, 4029, 3970, 12, 3, 3975, 0.01, 1.0) == 4001   # snap ke BE
    #   extreme jauh 3930 (profit 71) → chandelier=3930+36=3966 < BE → SL=3966 (kunci profit)
    assert trail_after_1r(False, 4001, 4029, 4001, 3930, 12, 3, 3950, 0.01, 1.0) == 3966
    #   clamp broker: harga sudah balik naik ke 4008 saat 1R baru kena → SL tak bisa < price+min_dist
    assert trail_after_1r(False, 4001, 4029, 4029, 3970, 12, 3, 4008, 0.01, 1.0) == 4008.01
    #   BUY cermin: entry=3000, initial_sl=2972 → R=28. high 3035 (profit 35 ≥ 28), harga 3025 > BE → SL=BE 3000
    assert trail_after_1r(True, 3000, 2972, 2972, 3035, 12, 3, 3025, 0.01, 1.0) == 3000
    assert trail_after_1r(True, 3000, 2972, 2972, 3015, 12, 3, 3010, 0.01, 1.0) is None    # high 3015: profit 15<28 → DIAM
    # realized outcome dari history deal (executed → PnL riil, bukan simulasi)
    dz = [{"profit": 0.0, "swap": 0.0, "commission": -0.5, "price": 3000.0, "time": 1, "entry": 0},
          {"profit": 85.0, "swap": -1.2, "commission": -0.5, "price": 3085.0, "time": 2, "entry": 1}]
    assert realized_outcome(dz) == ("WIN", 3085.0, 82.8), realized_outcome(dz)
    dz2 = [{"profit": -40.0, "swap": 0.0, "commission": -0.5, "price": 2950.0, "time": 2, "entry": 1}]
    assert realized_outcome(dz2)[0] == "LOSS"
    class Row(dict):
        def __getitem__(self, k): return dict.__getitem__(self, k)
    buy = Row(direction="BUY", sl=2961.0, tp_json=json.dumps([3046.0, 3097.0, 3165.0]))
    assert outcome_for(buy, 2960) == ("LOSS", "SL")
    assert outcome_for(buy, 3000) is None          # antara SL & TP1 → masih terbuka
    assert outcome_for(buy, 3050) == ("WIN", "TP1")
    assert outcome_for(buy, 3100) == ("WIN", "TP2")
    assert outcome_for(buy, 3200) == ("WIN", "TP3")
    sell = Row(direction="SELL", sl=3100.0, tp_json=json.dumps([3050.0, 3000.0, 2950.0]))
    assert outcome_for(sell, 3110) == ("LOSS", "SL")
    assert outcome_for(sell, 2940) == ("WIN", "TP3")
    print("[OK] monitor outcome: BUY & SELL, SL/TP1/TP2/TP3 benar")


if __name__ == "__main__":
    demo()
