"""
MT5 Bridge — server kecil yang mengekspos data broker MT5 ke Momentum Alert Engine.
JALAN DI MESIN YANG ADA MetaTrader5 (WAJIB WINDOWS + MT5 login ke broker-mu).

Endpoint (dikonsumsi data/sources.py):
  GET /price                              -> {"ok":true,"price":float}
  GET /ohlcv?timeframe={5m|1h|4h|1d}&count=N
      -> {"ok":true,"symbol":..,"timeframe":..,"data":[{datetime,open,high,low,close,volume}]}
Header wajib: X-Bridge-Token: <BRIDGE_TOKEN>

Jalankan:
  pip install MetaTrader5
  set BRIDGE_TOKEN=rahasia-panjang-acak     (Windows: set / PowerShell: $env:BRIDGE_TOKEN=...)
  set MT5_SYMBOL=XAUUSD                      (sesuaikan nama simbol broker-mu, mis. XAUUSD, GOLD, XAUUSD.m)
  python server.py                          (default port 8765)
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import MetaTrader5 as mt5

TOKEN = os.getenv("BRIDGE_TOKEN", "")
SYMBOL = os.getenv("MT5_SYMBOL", "XAUUSD")
PORT = int(os.getenv("BRIDGE_PORT", "8765"))

_TF = {"5m": mt5.TIMEFRAME_M5, "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1}


def _ensure_mt5():
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize gagal: {mt5.last_error()}")
    if not mt5.symbol_select(SYMBOL, True):
        raise RuntimeError(f"Simbol {SYMBOL} tidak tersedia di broker ini")


def get_price() -> dict:
    t = mt5.symbol_info_tick(SYMBOL)
    if not t:
        return {"ok": False, "error": "no tick"}
    return {"ok": True, "price": (t.bid + t.ask) / 2}


def get_ohlcv(tf: str, count: int) -> dict:
    if tf not in _TF:
        return {"ok": False, "error": f"timeframe {tf} tidak didukung (pakai 5m/1h/4h/1d)"}
    rates = mt5.copy_rates_from_pos(SYMBOL, _TF[tf], 0, count)
    if rates is None or len(rates) == 0:
        return {"ok": False, "error": f"copy_rates kosong: {mt5.last_error()}"}
    import datetime as _dt
    data = [{
        "datetime": _dt.datetime.utcfromtimestamp(int(r["time"])).strftime("%Y-%m-%d %H:%M:%S"),
        "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
        "close": float(r["close"]), "volume": float(r["tick_volume"]),
    } for r in rates]
    return {"ok": True, "symbol": SYMBOL, "timeframe": tf, "count": len(data), "data": data}


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if TOKEN and self.headers.get("X-Bridge-Token", "") != TOKEN:
            return self._send({"ok": False, "error": "token salah"}, 401)
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/price":
                return self._send(get_price())
            if u.path == "/ohlcv":
                tf = q.get("timeframe", ["5m"])[0]
                count = int(q.get("count", ["200"])[0])
                return self._send(get_ohlcv(tf, count))
            return self._send({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            return self._send({"ok": False, "error": str(e)}, 500)

    def log_message(self, *a):
        pass  # senyap


if __name__ == "__main__":
    if not TOKEN:
        print("WARNING: BRIDGE_TOKEN kosong — endpoint TIDAK terproteksi. Set BRIDGE_TOKEN dulu.")
    _ensure_mt5()
    print(f"[bridge] MT5 OK · simbol={SYMBOL} · listen 0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
