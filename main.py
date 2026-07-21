"""
Momentum Alert Engine — entrypoint.
  python main.py once         # satu evaluasi
  python main.py once --dry   # tanpa kirim telegram & tanpa nulis jurnal
  python main.py loop         # produksi: tick tiap M5 close + monitor 60s + telegram-poll
"""
from __future__ import annotations
import sys
from pathlib import Path
import yaml

import threading

from data.sources import get_bundle
from engine.smc_canonical import SmcCanonical
from engine.models import SmcState
from alert.engine import decide
from journal.db import Journal
from delivery import telegram, callbacks
from monitor.watcher import run_pass, check_deadman, manage_pending, reconcile_executed, daily_stop_hit
from ops import scheduler
from ops.clock import now_wib, wib_str, is_market_open


def load_config() -> dict:
    return yaml.safe_load(open(Path(__file__).parent / "config.yaml", encoding="utf-8"))


def build_strategy(cfg: dict):
    params = {**cfg.get("smc_canonical", {}), "direction": cfg["direction"]}
    return SmcCanonical(), params


def run_scan(cfg: dict, journal: Journal | None, strat, params: dict | None = None, *, dry: bool = False):
    for symbol in cfg["instruments"]:
        if not is_market_open(symbol):
            print(f"[main] {symbol}: pasar tutup - skip")
            continue
        bundle = get_bundle(cfg["data"], symbol)
        if bundle is None:
            print(f"[main] {symbol}: data tak tersedia - skip")
            continue
        st_name, st_blob = (journal.load_state(symbol) if journal else ("IDLE", None))
        state = SmcState.from_json(symbol, st_name, st_blob)
        setup, state = strat.evaluate(bundle, params, state)
        if journal and not dry:
            journal.save_state(symbol, state.state, state.to_json())
        if setup is None:
            print(f"[main] {wib_str()} · {symbol} state={state.state} · tidak ada setup")
            continue
        df = bundle.df(setup.tf)
        candle_id = str(df.index[-2])
        now = now_wib()
        if journal:
            hit, why = daily_stop_hit(journal, cfg, now)
            if hit:
                print(f"[main] {symbol} daily-stop ({why}) · suppress")
                journal.record(setup, candle_id, strat.name, strat.version, sent=False,
                               suppress=f"daily-stop {why}", ts=wib_str(now),
                               state_snapshot=state.to_json())
                continue
        send, why = decide(setup, candle_id, cfg["alert"], journal, now) if journal else (True, "dry")
        print(f"[main] {wib_str(now)} · {symbol} {setup.direction} tier={setup.tier} "
              f"RR={setup.rr} -> {'KIRIM' if send else 'SUPPRESS ('+why+')'}")
        if dry or not journal:
            continue
        aid = journal.record(setup, candle_id, strat.name, strat.version, sent=send,
                             suppress=None if send else why, ts=wib_str(now),
                             news_filter_applied=0, state_snapshot=state.to_json())
        if send:
            mid = telegram.send(telegram.format_alert(setup, now), cfg["delivery"]["telegram"],
                                reply_markup=telegram.alert_keyboard(aid))
            if mid:
                journal.cfg_set(f"msg_{aid}", str(mid))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    dry = "--dry" in sys.argv
    cfg = load_config()
    strat, params = build_strategy(cfg)
    print(f"[main] strategi aktif: {strat.name} v{strat.version}")

    if cmd == "once":
        journal = None if dry else Journal(cfg["journal"]["db_path"])
        run_scan(cfg, journal, strat, params, dry=dry)
    elif cmd == "loop":
        run_loop(cfg, strat, params)
    else:
        print(__doc__)


def run_loop(cfg: dict, strat, params: dict | None = None):
    journal = Journal(cfg["journal"]["db_path"])
    sc = cfg["scheduler"]

    def tick():
        run_scan(cfg, journal, strat, params)
        journal.cfg_set("heartbeat_wib", wib_str())

    def monitor_tick():
        run_pass(journal, cfg)
        if cfg.get("execution", {}).get("enabled"):
            manage_pending(journal, cfg)
            reconcile_executed(journal, cfg)
        check_deadman(journal, sc, cfg["delivery"]["telegram"])

    threading.Thread(target=scheduler.run_interval_loop, args=(monitor_tick, sc["monitor_sec"]),
                     daemon=True, name="monitor").start()
    threading.Thread(target=callbacks.poll_loop, args=(cfg, journal),
                     daemon=True, name="tg-poll").start()
    print("[main] loop aktif — scheduler(M5) + monitor(60s) + telegram-poll")
    journal.cfg_set("heartbeat_wib", wib_str())
    scheduler.run_candle_loop(tick, sc["minutes"], sc["offset_sec"])


if __name__ == "__main__":
    main()
