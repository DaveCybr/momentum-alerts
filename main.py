"""
Momentum Alert Engine — entrypoint.
  python main.py once       # satu evaluasi (buat tes / manual)
  python main.py once --dry # evaluasi tanpa kirim telegram & tanpa nulis jurnal
  python main.py loop       # produksi: tick tiap M30 close + monitor (Phase 1 lanjutan)
"""
from __future__ import annotations
import sys
from pathlib import Path
import yaml

import threading

from data.sources import get_bundle
from engine.strategy import TrendPullback
from alert.engine import decide
from journal.db import Journal
from delivery import telegram, callbacks
from monitor.watcher import run_pass, check_deadman, manage_positions, reconcile_executed
from ops import scheduler
from ops.clock import now_wib, wib_str, is_market_open


def load_config() -> dict:
    return yaml.safe_load(open(Path(__file__).parent / "config.yaml", encoding="utf-8"))


def run_scan(cfg: dict, journal: Journal | None, strat, *, dry: bool = False):
    """Evaluasi SEMUA instrumen sekali. Tiap simbol punya disiplin alert sendiri (per-symbol di jurnal)."""
    params = {**cfg["strategy"]["params"], "direction": cfg["direction"], "entry_tfs": cfg["data"]["entry_tfs"]}
    for symbol in cfg["instruments"]:
        if not is_market_open(symbol):
            print(f"[main] {symbol}: pasar tutup - skip")
            continue
        bundle = get_bundle(cfg["data"], symbol)
        if bundle is None:
            print(f"[main] {symbol}: data tak tersedia - skip")
            continue
        setup = strat.evaluate(bundle, params)
        if setup is None:
            print(f"[main] {wib_str()} · {symbol} price={bundle.price} · tidak ada setup")
            continue
        df = bundle.df(setup.tf)
        candle_id = str(df.index[-2])       # -1 = forming (dibuang strategi)
        now = now_wib()
        send, why = decide(setup, candle_id, cfg["alert"], journal, now) if journal else (True, "dry")
        print(f"[main] {wib_str(now)} · {symbol} {setup.direction} {setup.tf} tier={setup.tier} "
              f"score={setup.score} RR={setup.rr} -> {'KIRIM' if send else 'SUPPRESS ('+why+')'}")
        if dry:
            continue
        if journal:
            aid = journal.record(setup, candle_id, strat.name, strat.version,
                                 sent=send, suppress=None if send else why, ts=wib_str(now))
            if send:
                mid = telegram.send(telegram.format_alert(setup, now), cfg["delivery"]["telegram"],
                                    reply_markup=telegram.alert_keyboard(aid))
                if mid:
                    journal.cfg_set(f"msg_{aid}", str(mid))   # simpan message_id (jejak, bisa dipakai nanti)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    dry = "--dry" in sys.argv
    cfg = load_config()
    strat = TrendPullback()

    if cmd == "once":
        journal = None if dry else Journal(cfg["journal"]["db_path"])
        run_scan(cfg, journal, strat, dry=dry)
    elif cmd == "loop":
        run_loop(cfg, strat)
    else:
        print(__doc__)


def run_loop(cfg: dict, strat):
    journal = Journal(cfg["journal"]["db_path"])
    sc = cfg["scheduler"]

    def tick():
        run_scan(cfg, journal, strat)
        journal.cfg_set("heartbeat_wib", wib_str())

    def monitor_tick():
        run_pass(journal, cfg)                       # sim outcome — alert TAK dieksekusi (kualitas sinyal)
        if cfg.get("execution", {}).get("enabled"):
            reconcile_executed(journal, cfg)         # outcome RIIL — alert dieksekusi (PnL runner jujur)
            manage_positions(cfg)                    # trailing chandelier
        check_deadman(journal, sc, cfg["delivery"]["telegram"])

    threading.Thread(target=scheduler.run_interval_loop, args=(monitor_tick, sc["monitor_sec"]),
                     daemon=True, name="monitor").start()
    threading.Thread(target=callbacks.poll_loop, args=(cfg, journal),
                     daemon=True, name="tg-poll").start()
    print("[main] loop aktif — scheduler(M30) + monitor(60s) + telegram-poll")
    journal.cfg_set("heartbeat_wib", wib_str())
    scheduler.run_candle_loop(tick, sc["minutes"], sc["offset_sec"])


if __name__ == "__main__":
    main()
