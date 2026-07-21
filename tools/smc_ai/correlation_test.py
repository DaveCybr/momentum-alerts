"""
Korelasi grade AI vs outcome (task #4) — GERBANG KEPUTUSAN: apakah AI earn kepercayaan?

Untuk tiap kandidat SMC independen (cooldown, tanpa tumpang-tindih) di history_xau.json:
  1. pre-screen SMC → checklist deterministik + setup (entry/SL/TP)
  2. simulate_outcome forward-walk (pesimis SL-duluan) → WIN/LOSS
  3. AI grade (log-only, temp=0, thinking off, forced tool) → A+/B/skip
Lalu ukur: win-rate per grade AI. Kalau A+ >> skip → AI punya sinyal, promosikan.
Kalau grade tak korelasi outcome → JANGAN masukkan ke trigger (tetap deterministik).

Jalankan:  python tools/smc_ai/correlation_test.py
Output ditulis ke tools/smc_ai/correlation_result.json (agar bisa dianalisis ulang).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # root repo → import engine/ai/monitor

import pandas as pd

from engine.models import Bundle
from engine.smc import SmcPrescreen
from monitor.watcher import simulate_outcome, pending_lifecycle
from ai import grader as ai_grader

HIST = Path(__file__).with_name("history_xau.json")
OUT = Path(__file__).with_name("correlation_result.json")
MIN_GATES = 5
CANDLE_EXPIRY = 3        # §11: pending batal kalau tak terisi dalam 3 candle M5 setelah MSS
MAX_FUTURE = 288        # telusuri hingga 24 jam M5 ke depan
class Row(dict):
    def __getitem__(self, k):
        return dict.__getitem__(self, k)


def _mkdf(rows):
    df = pd.DataFrame([dict(open=r["o"], high=r["h"], low=r["l"], close=r["c"], volume=r["v"]) for r in rows])
    df.index = pd.to_datetime([r["t"] for r in rows]).tz_localize("UTC")
    return df


def find_candidates(H1, M15, M5, s):
    """Kandidat independen (cooldown = lompat sampai trade selesai). Return list dict."""
    out = []
    end = 300
    while end < len(M5):
        now = M5.index[end]
        m5w, m15w, h1w = M5.iloc[:end + 1].iloc[-200:], M15[M15.index <= now].iloc[-200:], H1[H1.index <= now].iloc[-200:]
        if len(m15w) < 50 or len(h1w) < 50:
            end += 3; continue
        b = Bundle("XAUUSD.vx", price=float(m5w["close"].iloc[-1]), tf={"H1": h1w, "M15": m15w, "M5": m5w})
        sc = s.screen(b, {"require_session": False}, min_gates=MIN_GATES)
        if not sc:
            end += 3; continue
        su = sc["setup"]
        fut = M5.iloc[end + 1:end + 1 + MAX_FUTURE]
        # §11: pending limit di 50% FVG (entry = midpoint entry_low/high). Trade cuma mulai
        # kalau FILLED; kalau CANCELLED (target/sweep/kedaluwarsa) = cancelled setup, bukan trade.
        entry = (su.entry_low + su.entry_high) / 2
        state, reason, fbar = pending_lifecycle(su.direction, entry, su.sl, su.tp[-1],
                                                su.entry_low, su.entry_high, fut,
                                                max_candles=CANDLE_EXPIRY)
        if state != "FILLED":
            out.append(dict(ts=str(now), gates=sc["gates_passed"], fired=sc["fired"],
                            direction=su.direction, result="CANCELLED", hit=reason,
                            bars=fbar, filled=False, bundle=b))
            end += fbar + 1
            continue
        # outcome dihitung dari candle SETELAH fill
        after = M5.iloc[end + 1 + fbar:end + 1 + fbar + MAX_FUTURE]
        r = simulate_outcome(Row(direction=su.direction, sl=su.sl, tp_json=json.dumps(su.tp)), after)
        if r:
            out.append(dict(ts=str(now), gates=sc["gates_passed"], fired=sc["fired"],
                            direction=su.direction, result=r[0], hit=r[1], bars=r[3],
                            filled=True, bundle=b))
            end += fbar + r[3] + 1
        else:
            end += fbar + MAX_FUTURE
    return out


def main():
    d = json.loads(HIST.read_text())
    H1, M15, M5 = _mkdf(d["h1"]), _mkdf(d["m15"]), _mkdf(d["m5"])
    s = SmcPrescreen()
    cands = find_candidates(H1, M15, M5, s)
    print(f"{len(cands)} kandidat independen — mulai grade AI (temp=0, thinking off)...")

    rows = []
    for i, c in enumerate(cands):
        b = c["bundle"]
        prompt = ai_grader.build_prompt("XAUUSD.vx", b.df("H1"), b.df("M15"), b.df("M5"), anchor=c["ts"])
        g = ai_grader.call_grader(prompt, {})
        rec = dict(ts=c["ts"], gates=c["gates"], fired=c["fired"], direction=c["direction"],
                   result=c["result"], hit=c["hit"], bars=c["bars"],
                   ai_ok=g.get("ok"), ai_grade=g.get("grade"), latency_ms=g.get("latency_ms"),
                   ai_checklist=g.get("checklist"), error=g.get("error"))
        rows.append(rec)
        print(f"  [{i+1}/{len(cands)}] {c['ts']} g{c['gates']} {c['direction']} "
              f"outcome={c['result']} ai={g.get('grade')} ok={g.get('ok')} {g.get('latency_ms')}ms")

    OUT.write_text(json.dumps(rows, indent=2))
    summarize(rows)


def summarize(rows):
    ok = [r for r in rows if r["ai_ok"]]
    print("\n" + "=" * 60)
    print(f"AI ok: {len(ok)}/{len(rows)}")
    # win-rate per grade AI
    by = defaultdict(lambda: [0, 0])   # grade -> [wins, total]
    for r in ok:
        by[r["ai_grade"]][0] += 1 if r["result"] == "WIN" else 0
        by[r["ai_grade"]][1] += 1
    print("\nWin-rate per GRADE AI:")
    for grade in ("A+", "B", "skip"):
        w, t = by[grade]
        print(f"  {grade:4}: {w}/{t} = {(100*w/t) if t else 0:.0f}% win")
    # win-rate per gates deterministik (pembanding: apakah AI nambah info di atas gate count?)
    bg = defaultdict(lambda: [0, 0])
    for r in ok:
        bg[r["gates"]][0] += 1 if r["result"] == "WIN" else 0
        bg[r["gates"]][1] += 1
    print("\nWin-rate per GATES deterministik (pembanding):")
    for g in sorted(bg):
        w, t = bg[g]
        print(f"  {g}/7 : {w}/{t} = {(100*w/t) if t else 0:.0f}% win")
    print("=" * 60)
    aw, at = by["A+"]
    sw, st = by["skip"]
    a_wr = (aw / at) if at else 0
    s_wr = (sw / st) if st else 0
    print("VERDICT:")
    if at >= 3 and a_wr > s_wr + 0.15:
        print(f"  A+ ({100*a_wr:.0f}%) menang lebih sering dari skip ({100*s_wr:.0f}%) "
              f"-> AI PUNYA SINYAL. Kandidat promosi (butuh N lebih besar utk confirm).")
    else:
        print(f"  A+ ({100*a_wr:.0f}%) vs skip ({100*s_wr:.0f}%): belum ada pemisahan meyakinkan "
              f"(atau N kecil). JANGAN gate AI — tetap deterministik. Kumpulkan lebih banyak.")
    print("  CATATAN: N kecil (~47). Ini indikatif, bukan statistik final.")


if __name__ == "__main__":
    main()
