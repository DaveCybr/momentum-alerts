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
    entry = setup.entry or (setup.entry_high if setup.direction == "BUY" else setup.entry_low)
    lines += [
        f"\U0001F4C8 {setup.tf} · {setup.entry_type} entry <b>{entry}</b> (FVG {setup.entry_low}–{setup.entry_high})",
        f"\U0001F6D1 SL  : {setup.sl}",
        f"✅ TP  : {tp[0]}" + (f" / {tp[1]} / {tp[2]}" if len(tp) >= 3 else ""),
        f"\U0001F4CA RR  : {setup.rr}  · skor {setup.score}/7",
        f"\U0001F9ED {setup.reason}",
        "━" * 16,
        f"\U0001F550 {wib_str(now)}",
    ]
    return "\n".join(lines)


def alert_keyboard(alert_id: int) -> dict:
    return {"inline_keyboard": [[
        {"text": "\U0001F7E2 Eksekusi Limit", "callback_data": f"exec:{alert_id}"},
        {"text": "✅ Ambil",                  "callback_data": f"take:{alert_id}"},
        {"text": "⏭ Skip",                    "callback_data": f"skip:{alert_id}"},
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
    # SMC-style alert: single TP, LIMIT entry
    s = Setup("XAUUSD.vx", "BUY", "M5", 2979.0, 2985.0, 2970.0, [3010.0],
              "HIGH_CONF", 7, "SMC bullish · POI · sweep · MSS · RR3.0", {},
              entry_type="LIMIT", entry=2982.0, rr_planned=3.0)
    msg = format_alert(s)
    assert "LIMIT" in msg and "2982" in msg and "3010" in msg
    assert "/ambil" not in msg and "/skip" not in msg
    kb = alert_keyboard(42)
    btns = kb["inline_keyboard"][0]
    assert [b["callback_data"] for b in btns] == ["exec:42", "take:42", "skip:42"]
    assert "Limit" in btns[0]["text"]
    print("[OK] telegram: single-TP limit alert")
    print(msg.encode("ascii", "replace").decode())


if __name__ == "__main__":
    demo()
