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
from engine.smc import SmcPrescreen
from alert.engine import decide
from journal.db import Journal
from delivery import telegram, callbacks
from ai import grader as ai_grader
from monitor.watcher import run_pass, check_deadman, manage_positions, reconcile_executed
from ops import scheduler
from ops.clock import now_wib, wib_str, is_market_open


def load_config() -> dict:
    return yaml.safe_load(open(Path(__file__).parent / "config.yaml", encoding="utf-8"))


def build_strategy(cfg: dict):
    """Factory config-driven: baca strategy.active → (instance, params).
    Params diambil dari sumber yang benar per strategi (SMC dari cfg['smc'],
    trend_pullback dari cfg['strategy']['params']). Prasyarat flip apa pun."""
    active = cfg["strategy"].get("active", "trend_pullback")
    if active == "smc_prescreen":
        params = {**cfg.get("smc", {}), "direction": cfg["direction"]}
        return SmcPrescreen(), params
    if active == "trend_pullback":
        params = {**cfg["strategy"]["params"], "direction": cfg["direction"],
                  "entry_tfs": cfg["data"]["entry_tfs"]}
        return TrendPullback(), params
    raise ValueError(f"strategy.active tak dikenal: {active!r} (pilih trend_pullback | smc_prescreen)")


def shadow_grade(cfg: dict, journal: Journal, bundle):
    """AI grader LOG-ONLY (task #3). Jalankan pre-screen SMC bayangan; kalau ada kandidat
    >= min_gates, catat sebagai alert sent=0 (JEJAK, bukan kirim), lalu AI grade → ai_grades.
    TAK PERNAH nge-gate / kirim apa pun. Dibungkus pemanggilnya dgn try/except: kegagalan AI
    tak boleh menjatuhkan scan produksi."""
    aicfg = cfg.get("ai", {})
    if not aicfg.get("enabled"):
        return
    scfg = {**cfg.get("smc", {}), "require_session": cfg.get("smc", {}).get("require_session", True)}
    sc = SmcPrescreen().screen(bundle, scfg, min_gates=aicfg.get("shadow_min_gates", 5))
    if sc is None:
        return
    setup = sc["setup"]
    df = bundle.df(setup.tf)
    candle_id = str(df.index[-2])
    # dedup: tick berulang di candle+arah sama tak boleh spam AI call (~10s) + baris duplikat.
    # (candle_sent cuma cek sent=1; shadow row sent=0 → butuh guard sendiri)
    if journal.shadow_graded(candle_id, setup.direction):
        return
    # jejak alert (sent=0, suppress='shadow') — TAK dikirim, cuma anchor buat ai_grades + outcome #4
    aid = journal.record(setup, candle_id, "smc_shadow", SmcPrescreen.version,
                         sent=False, suppress="shadow", ts=wib_str())
    prompt = ai_grader.build_prompt(setup.symbol, bundle.df("H1"), bundle.df("M15"),
                                    bundle.df("M5"), anchor=candle_id)
    g = ai_grader.call_grader(prompt, aicfg.get("grader", {}))
    journal.record_grade(aid, g, gates_passed=sc["gates_passed"], fired=sc["fired"])
    print(f"[ai] {setup.symbol} shadow gates={sc['gates_passed']}/7 fired={sc['fired']} "
          f"-> ai_grade={g.get('grade')} ok={g.get('ok')} lat={g.get('latency_ms')}ms")


def run_scan(cfg: dict, journal: Journal | None, strat, params: dict | None = None, *, dry: bool = False):
    """Evaluasi SEMUA instrumen sekali. Tiap simbol punya disiplin alert sendiri (per-symbol di jurnal).
    params dari build_strategy() (sumber benar per strategi). Fallback ke trend_pullback params
    kalau None (kompat lama)."""
    if params is None:
        params = {**cfg["strategy"]["params"], "direction": cfg["direction"], "entry_tfs": cfg["data"]["entry_tfs"]}
    for symbol in cfg["instruments"]:
        if not is_market_open(symbol):
            print(f"[main] {symbol}: pasar tutup - skip")
            continue
        bundle = get_bundle(cfg["data"], symbol)
        if bundle is None:
            print(f"[main] {symbol}: data tak tersedia - skip")
            continue
        # AI grader shadow (log-only) — terpisah dari strategy aktif, tak pernah nge-gate.
        # try/except: AI lambat/error TAK boleh menjatuhkan scan produksi.
        if journal and not dry:
            try:
                shadow_grade(cfg, journal, bundle)
            except Exception as e:
                print(f"[ai] shadow grade error (diabaikan): {type(e).__name__}: {e}")
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
        run_pass(journal, cfg)                       # sim outcome — alert TAK dieksekusi (kualitas sinyal)
        if cfg.get("execution", {}).get("enabled"):
            reconcile_executed(journal, cfg)         # outcome RIIL — alert dieksekusi (PnL runner jujur)
            manage_positions(cfg, journal)           # trailing chandelier (grace-period 1R → BE)
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
