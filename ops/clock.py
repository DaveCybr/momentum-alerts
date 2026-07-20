"""Waktu WIB (UTC+7) — semua waktu user-facing & filter berbasis waktu pakai ini."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))
_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def now_wib() -> datetime:
    return datetime.now(WIB)


def to_wib(dt: datetime) -> datetime:
    return dt.astimezone(WIB) if dt.tzinfo else dt.replace(tzinfo=timezone.utc).astimezone(WIB)


def wib_str(dt: datetime | None = None, fmt: str = "%d/%m/%Y %H:%M WIB") -> str:
    return (dt or now_wib()).astimezone(WIB).strftime(fmt)


def wib_day(dt: datetime | None = None) -> str:
    """'Mon'..'Sun' di WIB."""
    return _DAYS[(dt or now_wib()).astimezone(WIB).weekday()]


def is_market_open(symbol: str, dt: datetime | None = None) -> bool:
    """Gold/forex tutup weekend (jam WIB); crypto 24/7. Cegah evaluasi di candle basi."""
    s = symbol.upper()
    if "BTC" in s or "ETH" in s or "USDT" in s:
        return True
    now = (dt or now_wib()).astimezone(WIB)
    wd, hr = now.weekday(), now.hour
    if wd == 5:            # Sabtu — tutup mulai 05:00 WIB
        return hr < 5
    if wd == 6:            # Minggu — tutup
        return False
    if wd == 0:            # Senin — buka mulai 05:00 WIB
        return hr >= 5
    return True            # Selasa–Jumat
