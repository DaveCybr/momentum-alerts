"""Telegram callback — long-poll getUpdates, tangani /ambil /skip /eksekusi."""
from __future__ import annotations
import json
import os
import time
import urllib.parse as _uparse
import urllib.request as _ureq

from journal.db import Journal


def handle_command(text: str, journal: Journal, cfg: dict) -> str | None:
    """Return balasan kalau command dikenali, else None. Beroperasi pada alert TERAKHIR (lintas simbol)."""
    t = (text or "").strip().lower()

    if t.startswith(("/ambil", "/take")):
        a = journal.latest_sent()
        if not a:
            return "belum ada alert untuk ditandai."
        journal.tag_taken(a["id"], "YES")
        return f"✅ dicatat: alert #{a['id']} {a['symbol']} DIAMBIL"

    if t.startswith("/skip"):
        a = journal.latest_sent()
        if not a:
            return "belum ada alert untuk ditandai."
        journal.tag_taken(a["id"], "NO")
        return f"⏭ dicatat: alert #{a['id']} {a['symbol']} di-SKIP"

    if t.startswith(("/eksekusi", "/entry", "/exec")):
        if not cfg.get("execution", {}).get("enabled"):
            return "eksekusi dimatikan di config."
        a = journal.latest_sent()
        if not a:
            return "belum ada alert untuk dieksekusi."
        if a["direction"] == "SELL" and not cfg["execution"].get("allow_short", False):
            return "\U0001F9EA SHORT dikunci (allow_short=false). Tandai /ambil /skip buat data."
        tps = json.loads(a["tp_json"])
        idx = min(int(cfg["execution"]["target_tp"]), len(tps)) - 1
        order_tp = 0.0 if cfg["execution"].get("trailing", True) else tps[idx]  # runner: tanpa TP keras
        from execute import broker
        try:
            r = broker.place(cfg, a["symbol"], a["direction"], a["sl"], order_tp)
        except Exception as e:
            return f"eksekusi error: {e}"
        if r.get("ok"):
            journal.tag_taken(a["id"], "YES")
            if r.get("ticket"):
                journal.set_ticket(a["id"], r["ticket"])   # jembatan alert→posisi utk outcome riil
            exit_line = "exit: trailing SL (chandelier)" if order_tp == 0.0 else f"TP {tps[idx]}"
            return (f"\U0001F7E2 EKSEKUSI OK — {a['direction']} {a['symbol']}\n"
                    f"lot {r['lot']} @ {r['price']} · SL {a['sl']} · {exit_line}\n"
                    f"risk ~${r['est_risk']} dari ${r['balance']}")
        return f"❌ eksekusi gagal: {r.get('msg')}"

    return None


def _api(token: str, method: str, params: dict) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}?" + _uparse.urlencode(params)
    return json.loads(_ureq.urlopen(url, timeout=35).read())


def poll_loop(cfg: dict, journal: Journal):
    tg = cfg["delivery"]["telegram"]
    token = os.getenv(tg["bot_token_env"], "")
    owner = str(os.getenv(tg["chat_id_env"], ""))          # H1: cuma chat ini yang diizinkan
    if not token or not owner:
        print("[callbacks] token/chat_id kosong - poll tidak jalan")
        return
    offset = int(journal.cfg_get("tg_offset", "0") or 0)
    print("[callbacks] telegram long-poll aktif")
    while True:
        try:
            r = _api(token, "getUpdates", {"offset": offset, "timeout": 30})
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                journal.cfg_set("tg_offset", offset)
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != owner:   # TOLAK pengirim lain diam-diam
                    continue
                reply = handle_command(msg.get("text", ""), journal, cfg)
                if reply:
                    _api(token, "sendMessage", {"chat_id": owner, "text": reply})
        except Exception as e:
            print(f"[callbacks] error: {e}")
            time.sleep(5)


def demo():
    import tempfile
    from engine.models import Setup
    p = os.path.join(tempfile.gettempdir(), "cb_test.db")
    for f in (p, p + "-wal", p + "-shm"):
        try: os.remove(f)
        except OSError: pass
    j = Journal(p)
    cfg = {"execution": {"enabled": False}}
    assert handle_command("/ambil", j, cfg) == "belum ada alert untuk ditandai."
    s = Setup("XAUUSD", "BUY", "M30", 2980, 2995, 2961, [3046, 3097, 3165], "HIGH_CONF", 5, "r", {})
    j.record(s, "C1", "tp", "0.1", sent=True)
    assert "DIAMBIL" in handle_command("/ambil", j, cfg)
    assert "SKIP" in handle_command("/skip", j, cfg)
    assert "dimatikan" in handle_command("/eksekusi", j, cfg)          # execution disabled
    assert handle_command("halo", j, cfg) is None
    # SELL locked
    j.record(Setup("XAUUSD", "SELL", "M30", 2010, 2020, 2039, [1990, 1970, 1950], "HIGH_CONF", 5, "r", {}, experimental=True), "C2", "tp", "0.1", sent=True)
    cfg["execution"]["enabled"] = True
    assert "dikunci" in handle_command("/eksekusi", j, cfg)
    print("[OK] callbacks: /ambil /skip /eksekusi (disabled + SELL-lock) benar")


if __name__ == "__main__":
    demo()
