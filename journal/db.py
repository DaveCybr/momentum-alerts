"""
Jurnal — tulang punggung. SQLite (WAL). Simpan SEMUA evaluasi (terkirim & di-suppress),
outcome auto (dari monitor), dan tag taken/skip (1 tap dari owner).
"""
from __future__ import annotations
import json
import sqlite3
import threading
from pathlib import Path

from engine.models import Setup
from ops.clock import wib_str, now_wib

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_wib      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    direction   TEXT NOT NULL,
    tf          TEXT NOT NULL,
    candle_id   TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    version     TEXT NOT NULL,
    tier        TEXT NOT NULL,
    score       INTEGER NOT NULL,
    entry_low   REAL, entry_high REAL, sl REAL, tp_json TEXT, rr REAL,
    reason      TEXT, gates_json TEXT,
    sent        INTEGER NOT NULL DEFAULT 1,   -- 1=terkirim, 0=di-suppress
    suppress    TEXT,                         -- alasan suppress kalau sent=0
    status      TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE | CLOSED (khusus yang sent=1)
    ticket      INTEGER                       -- posisi broker kalau dieksekusi (join ke history deal)
);
CREATE INDEX IF NOT EXISTS ix_alerts_candle ON alerts(candle_id, direction, sent);
CREATE INDEX IF NOT EXISTS ix_alerts_status ON alerts(status, sent);

CREATE TABLE IF NOT EXISTS outcomes (
    alert_id    INTEGER PRIMARY KEY,
    result      TEXT,          -- WIN | LOSS | BE
    hit         TEXT,          -- TP1/TP2/TP3/SL (simulasi) | REAL (dari broker history)
    exit_price  REAL,
    exit_ts_wib TEXT,
    profit      REAL,          -- PnL realized (broker) kalau outcome RIIL; NULL kalau simulasi
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);
CREATE TABLE IF NOT EXISTS tags (
    alert_id      INTEGER PRIMARY KEY,
    taken         TEXT,        -- YES | NO
    tagged_at_wib TEXT,
    FOREIGN KEY(alert_id) REFERENCES alerts(id)
);
CREATE TABLE IF NOT EXISTS config_kv (key TEXT PRIMARY KEY, value TEXT);
"""


class Journal:
    def __init__(self, db_path: str):
        self.path = db_path
        self._local = threading.local()        # 1 koneksi per-thread (dipakai ulang, tak buka-tutup)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._c() as c:
            c.executescript(_SCHEMA)
            self._migrate(c)

    def _migrate(self, c):
        """Kolom baru utk DB lama (CREATE IF NOT EXISTS tak menambah kolom). Idempoten."""
        for stmt in ("ALTER TABLE alerts ADD COLUMN ticket INTEGER",
                     "ALTER TABLE outcomes ADD COLUMN profit REAL"):
            try:
                c.execute(stmt)
            except sqlite3.OperationalError:
                pass   # kolom sudah ada

    def _c(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")   # WAL persisten → cukup sekali per koneksi
            self._local.conn = c
        return c

    # ── tulis ──
    def record(self, setup: Setup, candle_id: str, strategy: str, version: str,
               sent: bool, suppress: str | None = None, ts: str | None = None) -> int:
        with self._c() as c:
            cur = c.execute(
                """INSERT INTO alerts(ts_wib,symbol,direction,tf,candle_id,strategy,version,
                       tier,score,entry_low,entry_high,sl,tp_json,rr,reason,gates_json,sent,suppress,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ts or wib_str(), setup.symbol, setup.direction, setup.tf, candle_id, strategy, version,
                 setup.tier, setup.score, setup.entry_low, setup.entry_high, setup.sl,
                 json.dumps(setup.tp), setup.rr, setup.reason, json.dumps(setup.gates),
                 1 if sent else 0, suppress, "ACTIVE" if sent else "CLOSED"))
            return cur.lastrowid

    def label_outcome(self, alert_id: int, result: str, hit: str, exit_price: float,
                      profit: float | None = None):
        with self._c() as c:
            c.execute("INSERT OR REPLACE INTO outcomes VALUES(?,?,?,?,?,?)",
                      (alert_id, result, hit, exit_price, wib_str(), profit))
            c.execute("UPDATE alerts SET status='CLOSED' WHERE id=?", (alert_id,))

    def set_ticket(self, alert_id: int, ticket: int):
        """Simpan ticket posisi broker saat alert dieksekusi → jembatan ke history deal.
        status='ACTIVE' juga: kalau sim sempat nutup alert ini duluan, buka lagi biar
        reconcile ambil alih dgn outcome RIIL (INSERT OR REPLACE ganti outcome sim)."""
        with self._c() as c:
            c.execute("UPDATE alerts SET ticket=?, status='ACTIVE' WHERE id=?", (int(ticket), alert_id))

    def tag_taken(self, alert_id: int, taken: str):
        with self._c() as c:
            c.execute("INSERT OR REPLACE INTO tags VALUES(?,?,?)", (alert_id, taken, wib_str()))

    # ── baca (dipakai alert engine & monitor) ──
    def candle_sent(self, candle_id: str, direction: str) -> bool:
        with self._c() as c:
            r = c.execute("SELECT 1 FROM alerts WHERE candle_id=? AND direction=? AND sent=1 LIMIT 1",
                          (candle_id, direction)).fetchone()
            return r is not None

    def sent_today(self, symbol: str, ref=None) -> int:
        today = (ref or now_wib()).strftime("%d/%m/%Y")
        with self._c() as c:
            r = c.execute("SELECT COUNT(*) n FROM alerts WHERE symbol=? AND sent=1 AND ts_wib LIKE ?",
                          (symbol, today + "%")).fetchone()
            return r["n"]

    def last_sent(self, symbol: str, direction: str):
        with self._c() as c:
            return c.execute("""SELECT * FROM alerts WHERE symbol=? AND direction=? AND sent=1
                                ORDER BY id DESC LIMIT 1""", (symbol, direction)).fetchone()

    def open_alerts(self):
        """Terkirim, belum tutup, & BELUM dieksekusi → jalur simulasi (kualitas sinyal)."""
        with self._c() as c:
            return c.execute("SELECT * FROM alerts WHERE sent=1 AND status='ACTIVE' AND ticket IS NULL").fetchall()

    def open_executed(self):
        """Terkirim, belum tutup, & sudah dieksekusi (punya ticket) → jalur outcome RIIL."""
        with self._c() as c:
            return c.execute("SELECT * FROM alerts WHERE sent=1 AND status='ACTIVE' AND ticket IS NOT NULL").fetchall()

    def latest_sent(self, symbol: str | None = None):
        with self._c() as c:
            if symbol:
                return c.execute("SELECT * FROM alerts WHERE symbol=? AND sent=1 ORDER BY id DESC LIMIT 1",
                                 (symbol,)).fetchone()
            return c.execute("SELECT * FROM alerts WHERE sent=1 ORDER BY id DESC LIMIT 1").fetchone()

    def get_alert(self, alert_id: int):
        """Ambil satu alert by id — dipakai tombol Telegram (aksi kena alert SPESIFIK, bukan 'terakhir')."""
        with self._c() as c:
            return c.execute("SELECT * FROM alerts WHERE id=?", (int(alert_id),)).fetchone()

    def initial_sl_for_ticket(self, ticket: int) -> float | None:
        """SL ASLI (dari alert) posisi ber-ticket ini — buat hitung R di trailing grace-period.
        Beda dari SL broker yang sudah ke-trail; ini yang di jurnal, tak berubah."""
        with self._c() as c:
            r = c.execute("SELECT sl FROM alerts WHERE ticket=? ORDER BY id DESC LIMIT 1",
                          (int(ticket),)).fetchone()
            return float(r["sl"]) if r and r["sl"] is not None else None

    # ── config key-value (heartbeat, offset telegram, dsb) ──
    def cfg_set(self, key: str, value: str):
        with self._c() as c:
            c.execute("INSERT OR REPLACE INTO config_kv VALUES(?,?)", (key, str(value)))

    def cfg_get(self, key: str, default=None):
        with self._c() as c:
            r = c.execute("SELECT value FROM config_kv WHERE key=?", (key,)).fetchone()
            return r["value"] if r else default


def demo():
    import tempfile, os
    from engine.models import Setup
    p = os.path.join(tempfile.gettempdir(), "journal_test.db")
    for f in (p, p + "-wal", p + "-shm"):
        try: os.remove(f)
        except OSError: pass
    j = Journal(p)
    s = Setup("XAUUSD", "BUY", "M30", 2980, 2995, 2961, [3046, 3097, 3165], "HIGH_CONF", 5,
              "test", {"regime": "BULL"})
    aid = j.record(s, candle_id="C1", strategy="trend_pullback", version="0.1", sent=True)
    assert aid == 1
    assert j.candle_sent("C1", "BUY") is True
    assert j.candle_sent("C1", "SELL") is False
    assert j.sent_today("XAUUSD") == 1
    j.record(s, candle_id="C2", strategy="tp", version="0.1", sent=False, suppress="cooldown")
    assert j.sent_today("XAUUSD") == 1, "suppressed tidak dihitung ke cap"
    assert len(j.open_alerts()) == 1
    j.label_outcome(aid, "WIN", "TP1", 3046)
    assert len(j.open_alerts()) == 0, "outcome menutup alert"
    j.tag_taken(aid, "YES")
    # jalur executed: ticket memisahkan trade riil dari simulasi sinyal
    a2 = j.record(s, candle_id="C3", strategy="tp", version="0.1", sent=True)
    j.set_ticket(a2, 555)
    assert len(j.open_alerts()) == 0, "yg dieksekusi keluar dari jalur simulasi"
    assert [r["id"] for r in j.open_executed()] == [a2]
    j.label_outcome(a2, "WIN", "REAL", 3120.0, profit=82.8)
    assert len(j.open_executed()) == 0, "outcome riil menutup alert executed"
    print("[OK] journal: record/dedup/cap/outcome/tag + jalur executed jalan")


if __name__ == "__main__":
    demo()
