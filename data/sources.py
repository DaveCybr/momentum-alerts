"""
Data layer — OHLCV multi-TF untuk XAU dari MT5 (broker Valetax) via mt5linux RPyC.
Server = container gmag11 (wine MT5), RPyC di host:port. MT5 kasih SEMUA TF native
(M30/H1/H4/D1) — tak perlu resample.

Kontrak client: from mt5linux import MetaTrader5; m=MetaTrader5(host,port); m.initialize()
  copy_rates_from_pos(symbol, TIMEFRAME_x, 0, count) -> structured array (obtain dulu).
  symbol_info_tick(symbol).bid/.ask (akses langsung, JANGAN obtain — gagal pickle).
PENTING: rpyc client HARUS 5.2.3 (samain server), simbol = 'XAUUSD.vx'.
"""
from __future__ import annotations
import os
import threading
import pandas as pd

from engine.models import Bundle

_OHLCV = ["open", "high", "low", "close", "volume"]
_TF = {"M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "M30": "TIMEFRAME_M30",
       "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"}
_state = {"m": None}

# Satu koneksi RPyC dibagi thread scheduler/monitor/telegram → serialisasi biar tak interleave.
# RLock: aman kalau operasi (mis. manage_positions) memanggil operasi lain (broker) di thread sama.
MT5_LOCK = threading.RLock()


def _connect(mt5_cfg: dict):
    if _state["m"] is not None:
        return _state["m"]
    from mt5linux import MetaTrader5
    host = os.getenv(mt5_cfg.get("host_env", "MT5_HOST"), mt5_cfg.get("host", "localhost"))
    port = int(os.getenv(mt5_cfg.get("port_env", "MT5_PORT"), mt5_cfg.get("port", 8001)))
    m = MetaTrader5(host=host, port=port)
    # Pass login credentials jika tersedia (env var). Diperlukan di Wine/mt5linux
    # karena m.initialize() tanpa arg hang di lingkungan non-interaktif.
    login_env = os.getenv("MT5_LOGIN")
    pass_env = os.getenv("MT5_PASSWORD")
    server_env = os.getenv("MT5_SERVER")
    if login_env and pass_env and server_env:
        if not m.initialize(login=int(login_env), password=pass_env, server=server_env):
            raise RuntimeError(f"MT5 initialize gagal ({host}:{port})")
    else:
        if not m.initialize():
            raise RuntimeError(f"MT5 initialize gagal ({host}:{port})")
    _state["m"] = m
    return m


def _reset():
    _state["m"] = None


def _fetch(m, symbol: str, tf_name: str, count: int) -> pd.DataFrame | None:
    from rpyc.utils.classic import obtain
    rates = m.copy_rates_from_pos(symbol, getattr(m, _TF[tf_name]), 0, count)
    if rates is None:
        return None
    rates = obtain(rates)                       # bawa struktur array ke lokal (1 round-trip)
    if len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df.index = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume": "volume"})
    return df[_OHLCV].astype(float).sort_index()


def get_bundle(cfg: dict, symbol: str) -> Bundle | None:
    """cfg = config['data']. Rakit Bundle M30/H1/H4/D1 dari MT5 untuk `symbol`."""
    frames, sources = {}, {}
    try:
        with MT5_LOCK:
            m = _connect(cfg["mt5"])
            try:
                m.symbol_select(symbol, True)
            except Exception:
                pass
            for name, count in cfg["counts"].items():
                df = _fetch(m, symbol, name, count)
                if df is not None and not df.empty:
                    frames[name] = df
                    sources[name] = "mt5"
    except Exception as e:
        print(f"[data] MT5 error: {e} - reset koneksi")
        _reset()
        return None

    if "H1" not in frames:
        print("[data] [FAIL] H1 tak tersedia dari MT5")
        return None
    price = float(frames["H1"]["close"].iloc[-1])
    return Bundle(symbol=symbol, price=price, tf=frames, sources=sources)


def fetch_price(cfg: dict, symbol: str) -> float:
    """Harga live ringan (buat monitor). Akses .bid/.ask langsung, tanpa obtain."""
    try:
        with MT5_LOCK:
            m = _connect(cfg["mt5"])
            t = m.symbol_info_tick(symbol)
            if not t:
                return 0.0
            return float((t.bid + t.ask) / 2)
    except Exception as e:
        print(f"[data] price error: {e}")
        _reset()
        return 0.0
