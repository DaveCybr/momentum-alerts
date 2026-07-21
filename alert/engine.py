"""
Alert engine — disiplin. Bias-KE-DIAM. Ubah Setup jadi keputusan kirim/suppress.
Urutan cek (return alasan pertama yang gagal): tier → soft-day → skip-jam →
dedup candle → cooldown → cap harian. Semua alasan di-log ke jurnal (no silent caps).
"""
from __future__ import annotations
from datetime import datetime, timedelta

from engine.models import Setup
from journal.db import Journal
from ops.clock import WIB, wib_day

_TIER_RANK = {"NORMAL": 1, "HIGH_CONF": 2}


def _parse_wib(ts: str) -> datetime:
    return datetime.strptime(ts.replace(" WIB", ""), "%d/%m/%Y %H:%M").replace(tzinfo=WIB)


def decide(setup: Setup, candle_id: str, cfg: dict, journal: Journal,
           now: datetime) -> tuple[bool, str]:
    """Return (kirim?, alasan). Alasan selalu terisi (buat log)."""
    # 1. tier minimum
    if _TIER_RANK.get(setup.tier, 0) < _TIER_RANK.get(cfg["min_tier"], 2):
        return False, f"tier {setup.tier} < min {cfg['min_tier']}"

    # 2. hari lemah (WIB) → naikkan ambang skor
    if wib_day(now) in cfg.get("soft_filter_days_wib", []) and setup.score < cfg.get("soft_min_score", 99):
        return False, f"hari lemah {wib_day(now)} — skor {setup.score} < {cfg['soft_min_score']}"

    # 3. jam skip (subuh WIB)
    if now.hour in cfg.get("skip_hours_wib", []):
        return False, f"jam skip {now.hour:02d} WIB"

    # 4. dedup candle
    if journal.candle_sent(setup.symbol, candle_id, setup.direction):
        return False, f"dup candle {candle_id}"

    # 5. cooldown
    last = journal.last_sent(setup.symbol, setup.direction)
    if last is not None:
        elapsed_h = (now - _parse_wib(last["ts_wib"])).total_seconds() / 3600
        if elapsed_h < cfg.get("cooldown_hours", 0):
            return False, f"cooldown {elapsed_h:.1f}h < {cfg['cooldown_hours']}h"

    # 6. cap harian
    sent = journal.sent_today(setup.symbol, now)
    if sent >= cfg.get("max_per_day", 99):
        return False, f"cap harian {sent}/{cfg['max_per_day']}"

    return True, "lolos"


def demo():
    import tempfile, os
    from engine.models import Setup
    p = os.path.join(tempfile.gettempdir(), "alert_test.db")
    for f in (p, p + "-wal", p + "-shm"):
        try: os.remove(f)
        except OSError: pass
    j = Journal(p)
    cfg = dict(min_tier="HIGH_CONF", max_per_day=2, cooldown_hours=2,
               skip_hours_wib=[4, 5, 6], soft_filter_days_wib=["Wed", "Thu"], soft_min_score=5)

    def mk(tier="HIGH_CONF", score=5):
        return Setup("XAUUSD", "BUY", "M30", 2980, 2995, 2961, [3046, 3097, 3165], tier, score, "r", {})

    from ops.clock import wib_str
    mon = datetime(2026, 7, 20, 10, 0, tzinfo=WIB)   # Senin 10:00 (bukan hari lemah/skip, tetap 1 hari)

    # NORMAL tier ditolak
    assert decide(mk(tier="NORMAL"), "C1", cfg, j, mon)[0] is False
    # HIGH_CONF lolos
    ok, why = decide(mk(), "C1", cfg, j, mon); assert ok, why
    j.record(mk(), "C1", "tp", "0.1", sent=True, ts=wib_str(mon))
    # dedup candle sama
    assert decide(mk(), "C1", cfg, j, mon)[0] is False
    # cooldown: candle beda tapi masih < 2h
    assert decide(mk(), "C2", cfg, j, mon + timedelta(minutes=30))[0] is False
    # setelah cooldown lewat → lolos (candle beda)
    ok, why = decide(mk(), "C2", cfg, j, mon + timedelta(hours=3)); assert ok, why
    j.record(mk(), "C2", "tp", "0.1", sent=True, ts=wib_str(mon + timedelta(hours=3)))
    # cap harian (sudah 2 terkirim hari ini)
    assert decide(mk(), "C3", cfg, j, mon + timedelta(hours=4))[0] is False
    # jam skip
    assert decide(mk(), "C9", cfg, j, mon.replace(hour=5))[0] is False
    # hari lemah (Rabu) skor 4 < 5
    wed = datetime(2026, 7, 22, 20, 0, tzinfo=WIB)
    assert decide(mk(score=4), "C9", cfg, j, wed)[0] is False
    print("[OK] alert engine: tier/soft-day/skip/dedup/cooldown/cap semua benar")


if __name__ == "__main__":
    demo()
