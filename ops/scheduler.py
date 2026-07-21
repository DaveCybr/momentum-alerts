"""Scheduler — loop selaras candle M30 close (:00/:30 WIB) + loop interval (monitor)."""
from __future__ import annotations
import time
from datetime import datetime, timedelta

from ops.clock import now_wib


def next_tick(now: datetime, minutes: int = 30, offset_sec: int = 5) -> datetime:
    """Boundary M30 berikutnya (:00/:30) + offset detik (biar candle sudah closed di bridge)."""
    base = now.replace(second=0, microsecond=0)
    step = (now.minute // minutes + 1) * minutes
    nxt = (base + timedelta(hours=1)).replace(minute=0) if step >= 60 else base.replace(minute=step)
    return nxt + timedelta(seconds=offset_sec)


def run_candle_loop(tick, minutes: int = 30, offset_sec: int = 5):
    """Blok: tidur sampai M30 close berikutnya, panggil tick(), ulang."""
    print(f"[scheduler] mulai — tick tiap {minutes}m close (+{offset_sec}s)")
    while True:
        nt = next_tick(now_wib(), minutes, offset_sec)
        wait = (nt - now_wib()).total_seconds()
        print(f"[scheduler] tick berikutnya {nt.strftime('%H:%M:%S')} WIB (in {wait:.0f}s)")
        if wait > 0:
            time.sleep(wait)
        try:
            tick()
        except Exception as e:
            print(f"[scheduler] tick error: {e}")


def run_interval_loop(fn, seconds: int = 60):
    """Blok: panggil fn() tiap N detik (buat monitor)."""
    while True:
        try:
            fn()
        except Exception as e:
            print(f"[interval] error: {e}")
        time.sleep(seconds)


def demo():
    d = datetime
    from ops.clock import WIB
    assert next_tick(d(2026, 7, 20, 10, 15, tzinfo=WIB), 30, 5) == d(2026, 7, 20, 10, 30, 5, tzinfo=WIB)
    assert next_tick(d(2026, 7, 20, 10, 45, tzinfo=WIB), 30, 5) == d(2026, 7, 20, 11, 0, 5, tzinfo=WIB)
    assert next_tick(d(2026, 7, 20, 10, 0, tzinfo=WIB), 30, 5) == d(2026, 7, 20, 10, 30, 5, tzinfo=WIB)
    assert next_tick(d(2026, 7, 20, 23, 45, tzinfo=WIB), 30, 5) == d(2026, 7, 21, 0, 0, 5, tzinfo=WIB)
    # M5 boundary
    assert next_tick(d(2026, 7, 20, 10, 3, tzinfo=WIB), 5, 5) == d(2026, 7, 20, 10, 5, 5, tzinfo=WIB)
    assert next_tick(d(2026, 7, 20, 10, 55, tzinfo=WIB), 5, 5) == d(2026, 7, 20, 11, 0, 5, tzinfo=WIB)
    print("[OK] scheduler next_tick: M30/M5 boundary + rollover benar")


if __name__ == "__main__":
    demo()
