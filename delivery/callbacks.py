"""Telegram callback — long-poll getUpdates. Aksi via INLINE BUTTON (callback_query):
Eksekusi / Ambil / Skip, menempel alert_id spesifik. Command teks /ambil /skip /eksekusi
tetap didukung (fallback, beroperasi pada alert terakhir)."""
from __future__ import annotations
import json
import os
import time
import urllib.parse as _uparse
import urllib.request as _ureq

from journal.db import Journal
from ops.clock import wib_str


def _do_execute(a, journal: Journal, cfg: dict) -> tuple[bool, str]:
    """Eksekusi satu alert row `a`. Return (ok, pesan_status). SELL dikunci kalau allow_short=false."""
    if a["direction"] == "SELL" and not cfg["execution"].get("allow_short", False):
        return False, "SHORT dikunci (allow_short=false)"
    tps = json.loads(a["tp_json"])
    idx = min(int(cfg["execution"]["target_tp"]), len(tps)) - 1
    order_tp = 0.0 if cfg["execution"].get("trailing", True) else tps[idx]   # runner: tanpa TP keras
    from execute import broker
    try:
        r = broker.place(cfg, a["symbol"], a["direction"], a["sl"], order_tp)
    except Exception as e:
        return False, f"eksekusi error: {e}"
    if r.get("ok"):
        journal.tag_taken(a["id"], "YES")
        if r.get("ticket"):
            journal.set_ticket(a["id"], r["ticket"])   # jembatan alert→posisi utk outcome riil
        exit_line = "trailing SL" if order_tp == 0.0 else f"TP {tps[idx]}"
        return True, f"lot {r['lot']} @ {r['price']} · SL {a['sl']} · {exit_line} · risk ~${r['est_risk']}"
    return False, f"gagal: {r.get('msg')}"


def handle_callback(data: str, journal: Journal, cfg: dict) -> tuple[str, str | None]:
    """Proses tombol. `data` = 'exec:<id>' | 'take:<id>' | 'skip:<id>'.
    Return (toast, status_suffix). suffix != None → pesan di-update + tombol dihapus."""
    try:
        action, sid = data.split(":", 1)
        aid = int(sid)
    except (ValueError, AttributeError):
        return "perintah tak dikenal", None
    a = journal.get_alert(aid)
    if not a:
        return "alert tak ditemukan", None

    if action == "take":
        journal.tag_taken(aid, "YES")
        return "✅ Ditandai DIAMBIL", f"✅ DIAMBIL · {wib_str()}"
    if action == "skip":
        journal.tag_taken(aid, "NO")
        return "⏭ Ditandai SKIP", f"⏭ DI-SKIP · {wib_str()}"
    if action == "exec":
        if not cfg.get("execution", {}).get("enabled"):
            return "Eksekusi dimatikan di config", None
        ok, msg = _do_execute(a, journal, cfg)
        if ok:
            return "\U0001F7E2 Eksekusi OK", f"\U0001F7E2 DIEKSEKUSI — {msg} · {wib_str()}"
        return f"❌ {msg}", None      # gagal → biarkan tombol, biar bisa dicoba lagi
    return "perintah tak dikenal", None


def handle_command(text: str, journal: Journal, cfg: dict) -> str | None:
    """Fallback command teks (alert TERAKHIR). Tombol adalah jalur utama."""
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
        ok, msg = _do_execute(a, journal, cfg)
        return (f"\U0001F7E2 EKSEKUSI OK — {a['direction']} {a['symbol']}\n{msg}" if ok
                else f"❌ eksekusi {msg}")
    return None


def _api(token: str, method: str, params: dict) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}?" + _uparse.urlencode(params)
    return json.loads(_ureq.urlopen(url, timeout=35).read())


def poll_loop(cfg: dict, journal: Journal):
    from delivery import telegram
    tg = cfg["delivery"]["telegram"]
    token = os.getenv(tg["bot_token_env"], "")
    owner = str(os.getenv(tg["chat_id_env"], ""))          # cuma chat ini yang diizinkan
    if not token or not owner:
        print("[callbacks] token/chat_id kosong - poll tidak jalan")
        return
    offset = int(journal.cfg_get("tg_offset", "0") or 0)
    print("[callbacks] telegram long-poll aktif (button + command)")
    while True:
        try:
            r = _api(token, "getUpdates", {"offset": offset, "timeout": 30})
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                journal.cfg_set("tg_offset", offset)

                cq = u.get("callback_query")
                if cq:                                     # ── tombol ditekan ──
                    if str(cq.get("message", {}).get("chat", {}).get("id")) != owner:
                        _api(token, "answerCallbackQuery", {"callback_query_id": cq["id"]})
                        continue
                    toast, suffix = handle_callback(cq.get("data", ""), journal, cfg)
                    _api(token, "answerCallbackQuery", {"callback_query_id": cq["id"], "text": toast})
                    if suffix is not None:                 # sukses → update pesan + hapus tombol
                        base = cq.get("message", {}).get("text", "")
                        telegram.edit_message(tg, cq["message"]["message_id"],
                                              base + "\n" + "━" * 16 + "\n" + suffix, reply_markup={})
                    continue

                msg = u.get("message") or {}               # ── command teks (fallback) ──
                if str(msg.get("chat", {}).get("id")) != owner:
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
    # ── command teks (fallback) ──
    assert handle_command("/ambil", j, cfg) == "belum ada alert untuk ditandai."
    s = Setup("XAUUSD", "BUY", "M30", 2980, 2995, 2961, [3046, 3097, 3165], "HIGH_CONF", 5, "r", {})
    aid = j.record(s, "C1", "tp", "0.1", sent=True)
    assert "DIAMBIL" in handle_command("/ambil", j, cfg)
    assert "SKIP" in handle_command("/skip", j, cfg)
    assert "dimatikan" in handle_command("/eksekusi", j, cfg)          # execution disabled
    assert handle_command("halo", j, cfg) is None
    # ── tombol (callback_query) — jalur utama ──
    toast, suffix = handle_callback(f"take:{aid}", j, cfg)
    assert "DIAMBIL" in toast and suffix and "DIAMBIL" in suffix, (toast, suffix)
    toast, suffix = handle_callback(f"skip:{aid}", j, cfg)
    assert "SKIP" in toast and suffix and "SKIP" in suffix
    toast, suffix = handle_callback(f"exec:{aid}", j, cfg)             # exec disabled → tak buka posisi
    assert "dimatikan" in toast.lower() and suffix is None
    assert handle_callback("bogus", j, cfg) == ("perintah tak dikenal", None)
    assert handle_callback("take:9999", j, cfg)[0] == "alert tak ditemukan"   # id tak ada
    # SELL locked (exec enabled tapi allow_short=false) — tombol exec tak buka posisi
    sid = j.record(Setup("XAUUSD", "SELL", "M30", 2010, 2020, 2039, [1990, 1970, 1950],
                         "HIGH_CONF", 5, "r", {}, experimental=True), "C2", "tp", "0.1", sent=True)
    cfg["execution"] = {"enabled": True, "allow_short": False, "target_tp": 3, "trailing": True}
    toast, suffix = handle_callback(f"exec:{sid}", j, cfg)
    assert "dikunci" in toast and suffix is None, (toast, suffix)
    print("[OK] callbacks: tombol exec/take/skip (id-spesifik, SELL-lock, id-invalid) + command fallback benar")


if __name__ == "__main__":
    demo()
