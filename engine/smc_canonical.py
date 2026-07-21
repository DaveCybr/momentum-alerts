"""
SmcCanonical — stateful SMC engine per spesifikasi xauusd-smc-trading-system.md.
Dibangun bertahap: tiap fungsi punya demo() sendiri.
"""
from __future__ import annotations
import pandas as pd

from engine.models import Bundle, Setup, SmcState
from engine import indicators as ind


def in_session(ts: pd.Timestamp, sessions_utc: list[list[int]], server_utc_offset: int = 0) -> bool:
    """True jika ts (waktu candle broker) di dalam salah satu jendela [start,end) UTC.
    entries: [start_h, start_m, end_h, end_m]."""
    utc_min = ((ts.hour - server_utc_offset) % 24) * 60 + ts.minute
    for sh, sm, eh, em in sessions_utc:
        if sh * 60 + sm <= utc_min < eh * 60 + em:
            return True
    return False


def demo():
    sess = [[7, 0, 10, 0], [12, 0, 15, 30]]
    T = lambda h, m: pd.Timestamp(f"2026-01-05 {h:02d}:{m:02d}", tz="UTC")

    assert in_session(T(7, 0), sess, 0)
    assert not in_session(T(10, 0), sess, 0)
    assert in_session(T(15, 29), sess, 0)
    assert not in_session(T(15, 30), sess, 0)
    assert not in_session(T(11, 0), sess, 0)

    assert in_session(T(9, 0), sess, 2)
    assert not in_session(T(8, 59), sess, 2)
    print("[OK] in_session: minute precision + offset")


if __name__ == "__main__":
    demo()
