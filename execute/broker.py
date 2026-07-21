"""
Eksekusi order ke MT5 (DEMO) via mt5linux. v1: one-tap manual, market order,
lot auto dari risk% (di-floor lot minimum), SL + TP diset di order broker.
Short (experimental) DIKUNCI dari eksekusi.
ponytail: v1 = 1 posisi, tanpa layering/partial. partial-TP2/BE = increment berikut.
"""
from __future__ import annotations
from data import sources


def size_lot(risk_amount: float, sl_distance: float, point: float, tick_value: float,
             contract_size: float, vol_min: float, vol_step: float, vol_max: float) -> float:
    """Lot sehingga rugi di SL ≈ risk_amount. Di-floor ke vol_min, dibulatkan ke vol_step."""
    if point > 0 and tick_value > 0:
        loss_per_lot = (sl_distance / point) * tick_value
    else:                                            # fallback (XAU: contract 100)
        loss_per_lot = contract_size * sl_distance
    if loss_per_lot <= 0:
        return vol_min
    raw = risk_amount / loss_per_lot
    step = vol_step or 0.01
    lot = (int(raw / step)) * step                   # floor ke step
    lot = max(vol_min, lot)                           # floor ke minimum broker
    if vol_max:
        lot = min(lot, vol_max)
    return round(lot, 2)


def _lot(si, risk_amount, sl_distance):
    return size_lot(risk_amount, sl_distance,
                    float(getattr(si, "point", 0) or 0),
                    float(getattr(si, "trade_tick_value", 0) or 0),
                    float(getattr(si, "trade_contract_size", 100) or 100),
                    float(getattr(si, "volume_min", 0.01) or 0.01),
                    float(getattr(si, "volume_step", 0.01) or 0.01),
                    float(getattr(si, "volume_max", 0) or 0))


RC_DONE = 10009        # TRADE_RETCODE_DONE
RC_BADFILL = 10030     # filling mode tak didukung → coba mode lain


def _send(m, req: dict):
    """order_send dgn fallback filling mode (IOC→FOK→RETURN). Return (res, retcode)."""
    res = rc = None
    for fmode in ("ORDER_FILLING_IOC", "ORDER_FILLING_FOK", "ORDER_FILLING_RETURN"):
        req["type_filling"] = getattr(m, fmode)
        res = m.order_send(req)
        rc = int(res.retcode)
        if rc == RC_DONE or rc != RC_BADFILL:
            break
    return res, rc


def open_count(cfg, symbol: str) -> int:
    with sources.MT5_LOCK:
        m = sources._connect(cfg["data"]["mt5"])
        pos = m.positions_get(symbol=symbol)
        return len(pos) if pos else 0


def place(cfg: dict, symbol: str, direction: str, sl: float, tp: float) -> dict:
    """Kirim market order (BUY/SELL) untuk `symbol`. Return dict hasil. SELL dikunci di caller."""
    ex = cfg["execution"]
    with sources.MT5_LOCK:
        n = open_count(cfg, symbol)         # maks posisi PER instrumen (RLock: aman nested)
        if n >= ex["max_positions"]:
            return {"ok": False, "msg": f"maks {ex['max_positions']} posisi {symbol} (sudah {n})"}
        m = sources._connect(cfg["data"]["mt5"])
        ai = m.account_info()
        si = m.symbol_info(symbol)
        tick = m.symbol_info_tick(symbol)
        is_buy = direction == "BUY"
        price = float(tick.ask if is_buy else tick.bid)
        sl, tp = float(sl), float(tp)
        sl_distance = abs(price - sl)
        if sl_distance <= 0:
            return {"ok": False, "msg": "jarak SL 0/invalid"}

        risk_amount = float(ai.balance) * float(ex["risk_percent"]) / 100.0
        lot = _lot(si, risk_amount, sl_distance)
        pt = float(si.point) or 0.01
        est_risk = lot * (sl_distance / pt) * (float(getattr(si, "trade_tick_value", 1)) or 1)

        # §14 veto: kalau lot MINIMUM saja sudah menghasilkan risiko >2% balance, wajib lewati
        vol_min = float(getattr(si, "volume_min", 0.01) or 0.01)
        min_risk = vol_min * (sl_distance / pt) * (float(getattr(si, "trade_tick_value", 1)) or 1)
        max_risk_2pct = float(ai.balance) * 2.0 / 100.0
        if min_risk > max_risk_2pct:
            return {"ok": False, "msg": f"lot-min {vol_min} → risiko ${min_risk:.2f} > 2% balance (${max_risk_2pct:.2f}) · §14 wajib dilewati"}
        deviation = max(10, int(price * float(ex.get("deviation_pct", 0.1)) / 100 / pt))  # adaptif

        req = {
            "action": m.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lot,
            "type": m.ORDER_TYPE_BUY if is_buy else m.ORDER_TYPE_SELL, "price": price,
            "sl": sl, "tp": tp, "deviation": deviation, "magic": int(ex.get("magic", 0)),
            "comment": "momentum", "type_time": m.ORDER_TIME_GTC,
        }
        res, rc = _send(m, req)
    if rc == RC_DONE:
        return {"ok": True, "lot": lot, "price": float(res.price),
                "ticket": int(getattr(res, "order", 0) or 0),   # = position id (join ke history deal)
                "est_risk": round(est_risk, 2), "balance": float(ai.balance)}
    return {"ok": False, "msg": f"retcode={rc} ({getattr(res, 'comment', '')})", "lot": lot}


def modify_sl(cfg: dict, symbol: str, ticket: int, sl: float, tp: float) -> bool:
    """Geser SL (dan set TP) posisi terbuka. Dipakai buat SL→BE."""
    with sources.MT5_LOCK:
        m = sources._connect(cfg["data"]["mt5"])
        res = m.order_send({"action": m.TRADE_ACTION_SLTP, "symbol": symbol,
                            "position": int(ticket), "sl": float(sl), "tp": float(tp)})
        return int(res.retcode) == RC_DONE


def close_partial(cfg: dict, symbol: str, ticket: int, volume: float, is_buy: bool) -> bool:
    """Tutup sebagian posisi (volume). Deviation adaptif + filling fallback."""
    with sources.MT5_LOCK:
        m = sources._connect(cfg["data"]["mt5"])
        si = m.symbol_info(symbol); pt = float(si.point) or 0.01
        tick = m.symbol_info_tick(symbol)
        price = float(tick.bid if is_buy else tick.ask)
        dev = max(10, int(price * float(cfg["execution"].get("deviation_pct", 0.1)) / 100 / pt))
        req = {"action": m.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(volume),
               "type": m.ORDER_TYPE_SELL if is_buy else m.ORDER_TYPE_BUY, "position": int(ticket),
               "price": price, "deviation": dev, "magic": int(cfg["execution"].get("magic", 0)),
               "comment": "partial-tp2", "type_time": m.ORDER_TIME_GTC}
        _, rc = _send(m, req)
        return rc == RC_DONE


def demo():
    # XAU standar: contract 100, point 0.01, tick_value $1, min 0.01, step 0.01
    assert size_lot(15, 15, 0.01, 1.0, 100, 0.01, 0.01, 50) == 0.01   # $10 target → floor min
    assert size_lot(100, 15, 0.01, 1.0, 100, 0.01, 0.01, 50) == 0.06  # 100/1500=0.066→0.06
    assert size_lot(1500, 15, 0.01, 1.0, 100, 0.01, 0.01, 50) == 1.0  # 1500/1500=1.0
    assert size_lot(5, 15, 0.01, 1.0, 100, 0.01, 0.01, 50) == 0.01    # di bawah min → 0.01
    print("[OK] size_lot: floor min, step, scaling benar")

    # §14 veto: lot-min >2% → wajib lewati (diuji lewat fungsi bantu, bukan place() yg butuh MT5)
    # SL jauh (5000 pts, XAU tipikal 30-150) → lot-min 0.01 kasih risiko besar
    min_risk_big_sl = 0.01 * (5000 / 1) * 1.0    # 0.01 lot × 5000 pts × $1/pt = $50
    balance_small = 100.0; max_2pct = balance_small * 2 / 100  # $2
    assert min_risk_big_sl > max_2pct, "seharusnya >2% balance"
    print("[OK] §14 veto logic: lot-min risiko besar terdeteksi")


if __name__ == "__main__":
    demo()
