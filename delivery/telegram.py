"""Kirim alert ke Telegram (teks + inline button). v1 tanpa AI/chart. urllib."""
from __future__ import annotations
import json
import os
import urllib.request as _ureq

from engine.models import Setup
from ops.clock import wib_str


def format_alert(setup: Setup, now=None) -> str:
    emoji = "\U0001F7E2" if setup.direction == "BUY" else "\U0001F534"
    tier = "\U0001F525 HIGH CONFIDENCE" if setup.tier == "HIGH_CONF" else "NORMAL"
    tp = setup.tp
    lines = [f"{emoji} <b>{setup.symbol} — {setup.direction}</b>   {tier}", "━" * 16]
    if setup.experimental:
        lines += ["\U0001F9EA <b>EKSPERIMEN</b> — short belum terbukti edge-nya.",
                  "Tandai buat DATA, jangan dibet dulu.", "━" * 16]
    lines += [
        f"\U0001F4C8 {setup.tf} · entry <b>{setup.entry_low}–{setup.entry_high}</b>",
        f"\U0001F6D1 SL  : {setup.sl}",
        f"✅ TP  : {tp[0]} / {tp[1]} / {tp[2]}",
        f"\U0001F4CA RR  : {setup.rr}  · skor {setup.score}/7",
        f"\U0001F9ED {setup.reason}",
        "━" * 16,
        f"\U0001F550 {wib_str(now)}",
    ]
    return "\n".join(lines)


def alert_keyboard(alert_id: int) -> dict:
    """Inline keyboard: aksi menempel alert_id spesifik (bukan 'alert terakhir')."""
    return {"inline_keyboard": [[
        {"text": "\U0001F7E2 Eksekusi", "callback_data": f"exec:{alert_id}"},
        {"text": "✅ Ambil",           "callback_data": f"take:{alert_id}"},
        {"text": "⏭ Skip",             "callback_data": f"skip:{alert_id}"},
    ]]}


def _post(cfg: dict, method: str, payload: dict) -> dict | None:
    token = os.getenv(cfg["bot_token_env"], "")
    if not token:
        print("[telegram] token kosong di env - skip")
        return None
    try:
        url = f"https://api.telegram.org/bot{token}/{method}"
        data = json.dumps(payload).encode()
        req = _ureq.Request(url, data=data, headers={"Content-Type": "application/json"})
        return json.loads(_ureq.urlopen(req, timeout=10).read())
    except Exception as e:
        print(f"[telegram] {method} error: {e}")
        return None


def send(text: str, cfg: dict, reply_markup: dict | None = None) -> int | None:
    """Kirim pesan. Return message_id (buat di-edit tombolnya nanti), atau None kalau gagal."""
    chat = os.getenv(cfg["chat_id_env"], "")
    if not chat:
        print("[telegram] chat kosong di env - skip kirim")
        return None
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    r = _post(cfg, "sendMessage", payload)
    if r and r.get("ok"):
        return r["result"]["message_id"]
    return None


def edit_message(cfg: dict, message_id: int, text: str, reply_markup: dict | None = None) -> bool:
    """Update teks pesan + (opsional) ganti/hapus tombol. reply_markup={} → hapus tombol."""
    chat = os.getenv(cfg["chat_id_env"], "")
    if not chat:
        return False
    payload = {"chat_id": chat, "message_id": int(message_id), "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    r = _post(cfg, "editMessageText", payload)
    return bool(r and r.get("ok"))


def demo():
    from engine.models import Setup
    s = Setup("XAUUSD", "BUY", "M30", 2979.72, 2995.0, 2961.01, [3045.98, 3096.96, 3164.94],
              "HIGH_CONF", 5, "regime BULL · pullback · konfirmasi", {})
    msg = format_alert(s)
    assert "XAUUSD" in msg and "BUY" in msg and "3045.98" in msg and "SL" in msg
    assert "/ambil" not in msg and "/skip" not in msg, "command teks harus hilang dari body (diganti tombol)"
    kb = alert_keyboard(42)
    btns = kb["inline_keyboard"][0]
    assert [b["callback_data"] for b in btns] == ["exec:42", "take:42", "skip:42"]
    assert len(btns) == 3 and "Eksekusi" in btns[0]["text"]
    print("[OK] telegram: format tanpa command + keyboard exec/take/skip nempel alert_id")
    print(msg.encode("ascii", "replace").decode())   # ASCII-safe utk console Windows


if __name__ == "__main__":
    demo()
