"""Kirim alert ke Telegram (teks). v1 tanpa AI/chart. Reuse pola goldexai (urllib)."""
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
                  "Tandai /ambil /skip buat DATA, jangan dibet dulu.", "━" * 16]
    lines += [
        f"\U0001F4C8 {setup.tf} · entry <b>{setup.entry_low}–{setup.entry_high}</b>",
        f"\U0001F6D1 SL  : {setup.sl}",
        f"✅ TP  : {tp[0]} / {tp[1]} / {tp[2]}",
        f"\U0001F4CA RR  : {setup.rr}  · skor {setup.score}/7",
        f"\U0001F9ED {setup.reason}",
        "━" * 16,
        "Ambil trade ini?  balas  /ambil  atau  /skip",
        f"\U0001F550 {wib_str(now)}",
    ]
    return "\n".join(lines)


def send(text: str, cfg: dict) -> bool:
    token = os.getenv(cfg["bot_token_env"], "")
    chat = os.getenv(cfg["chat_id_env"], "")
    if not token or not chat:
        print("[telegram] token/chat kosong di env - skip kirim")
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
        req = _ureq.Request(url, data=payload, headers={"Content-Type": "application/json"})
        _ureq.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[telegram] error: {e}")
        return False


def demo():
    from engine.models import Setup
    s = Setup("XAUUSD", "BUY", "M30", 2979.72, 2995.0, 2961.01, [3045.98, 3096.96, 3164.94],
              "HIGH_CONF", 5, "regime BULL · pullback · konfirmasi", {})
    msg = format_alert(s)
    assert "XAUUSD" in msg and "BUY" in msg and "3045.98" in msg and "SL" in msg
    print("[OK] telegram format:")
    print(msg.encode("ascii", "replace").decode())   # ASCII-safe utk console Windows


if __name__ == "__main__":
    demo()
