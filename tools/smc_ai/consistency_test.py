"""
Tes konsistensi AI grader (task #1) — GATE KEPUTUSAN sebelum bangun apa pun.

Pertanyaan yang dijawab: kalau setup SMC yang SAMA PERSIS dikirim ke AI N kali,
apakah jawabannya identik? Kalau ya → AI layak dikejar sebagai grader.
Kalau varian → itu noise yang TAK BOLEH masuk trigger (lihat smc-ai-pivot-decision).

Desain guardrail (semua sudah diverifikasi feasible via 9router ac-prod):
  - temperature: 0            → tekan varian sampling
  - thinking dimatikan        → cegah reasoning adaptif bikin jawaban beda tiap run
  - forced tool use (grade)   → AI CUMA isi boolean per sub-pertanyaan SMC;
                                KODE INI yang turunkan A+/B/skip (deterministik).
                                AI membaca fakta, kode memutuskan grade.

Input = fixture lokal (tools/smc_ai/fixture_xau.json), bukan live — biar 10 run
dapat input byte-identik. AI di localhost, data dari fixture: dua jalur terpisah.

Jalankan:  python tools/smc_ai/consistency_test.py
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.request
import urllib.error
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # root repo → import ai.grader
from ai.grader import derive_grade   # SATU sumber kebenaran (audit: hapus duplikat lokal)

BASE_URL = os.getenv("SMC_AI_BASE_URL", "http://localhost:20128/v1")
# Provider ac-prod punya kuota (cc/ kena rate limit). String dirakit bertahap
# BUKAN gaya, tapi supaya tak ke-mangle. Router me-remap ke Opus 4.8 (Bedrock) apa pun ini.
_MODEL = "ac-prod/claude-sonnet"
MODEL = _MODEL + "-5"
N_RUNS = int(os.getenv("SMC_AI_RUNS", "10"))
FIXTURE = Path(__file__).with_name("fixture_xau.json")
# PLACEHOLDER_CONFIG
# 7 sub-pertanyaan boolean dari spek SMC (xauusd-smc-trading-system.md) + RR numerik.
# AI HANYA menjawab fakta-fakta ini. Grade diturunkan oleh kode, bukan AI.
GRADE_TOOL = {
    "type": "function",
    "function": {
        "name": "grade_setup",
        "description": "Report the SMC checklist for the current XAUUSD setup based strictly on the provided OHLCV data. Answer each field factually; do not decide an overall grade.",
        "parameters": {
            "type": "object",
            "properties": {
                "h1_bias": {"type": "string", "enum": ["bullish", "bearish", "none"],
                            "description": "H1 directional bias: BOS + protected level intact + liquidity target open + POI on correct premium/discount side."},
                "bos_confirmed": {"type": "boolean", "description": "H1 broke structure with a body close beyond a confirmed structural swing."},
                "poi_fresh": {"type": "boolean", "description": "A valid H1 POI (OB+FVG from the same displacement) exists and has NOT been retested since forming."},
                "correct_pd": {"type": "boolean", "description": "Price is on the correct side of the dealing range (discount for buy bias, premium for sell bias)."},
                "liq_swept_m15": {"type": "boolean", "description": "A marked M15 liquidity pool has been swept on M5 near/inside the POI."},
                "displacement": {"type": "boolean", "description": "M5 displacement: body/range >= 0.65 AND range >= 1.5x ATR(14), leaving an FVG."},
                "mss_confirmed": {"type": "boolean", "description": "M5 MSS: body close beyond the last structural swing after the sweep, leaving an FVG."},
                "rr_to_target": {"type": "number", "description": "Reward-to-risk to the next opposing liquidity target from the entry zone. 0 if no valid entry."},
            },
            "required": ["h1_bias", "bos_confirmed", "poi_fresh", "correct_pd",
                         "liq_swept_m15", "displacement", "mss_confirmed", "rr_to_target"],
            "additionalProperties": False,
        },
    },
}
# PLACEHOLDER_SCHEMA
SYSTEM = (
    "You are a strict SMC (Smart Money Concepts) setup checker for XAUUSD intraday. "
    "You are given closed-candle OHLCV data for H1, M15, and M5. Evaluate the setup "
    "ONLY against the data provided — never invent price levels. Answer every checklist "
    "field factually via the grade_setup tool. Do not decide an overall grade; a separate "
    "deterministic step does that. If evidence for a field is absent, answer the "
    "conservative value (false / none / 0)."
)


def _fmt(rows: list[dict]) -> str:
    return "\n".join(f"{r['t']} O{r['o']} H{r['h']} L{r['l']} C{r['c']} V{r['v']}" for r in rows)


def build_user_prompt(fix: dict) -> str:
    return (
        f"Symbol: {fix['symbol']}  (last closed H1 candle: {fix['anchor_h1']})\n\n"
        f"=== H1 (bias & POI) ===\n{_fmt(fix['h1'])}\n\n"
        f"=== M15 (liquidity map) ===\n{_fmt(fix['m15'])}\n\n"
        f"=== M5 (sweep / displacement / MSS / entry) ===\n{_fmt(fix['m5'])}\n\n"
        "Fill the grade_setup checklist for the setup as of the last M5 candle."
    )
# PLACEHOLDER_PROMPT
def call_once(user_prompt: str, attempt_backoff: float = 3.0) -> dict:
    """Satu panggilan grader. Return dict argumen tool grade_setup. Retry 429 dgn backoff."""
    payload = {
        "model": MODEL,
        "temperature": 0,
        "stream": False,
        "max_tokens": 600,
        "reasoning_effort": "none",   # matikan thinking (OpenAI-style); router terjemahkan
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        "tools": [GRADE_TOOL],
        "tool_choice": {"type": "function", "function": {"name": "grade_setup"}},
    }
    data = json.dumps(payload).encode()
    for attempt in range(8):
        req = urllib.request.Request(
            f"{BASE_URL}/chat/completions", data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode())
            msg = body["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            if not calls:
                raise RuntimeError(f"no tool_calls (finish={body['choices'][0].get('finish_reason')})")
            return json.loads(calls[0]["function"]["arguments"])
        except urllib.error.HTTPError as e:
            txt = e.read().decode()[:200]
            if e.code == 429:
                wait = attempt_backoff * (attempt + 1)
                print(f"  [429] backoff {wait:.0f}s (attempt {attempt+1})")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {txt}")
    raise RuntimeError("gagal setelah 8 attempt (rate limit)")
# PLACEHOLDER_CALL
# derive_grade diimpor dari ai.grader (satu sumber kebenaran) — lihat import di atas.


def summarize(runs: list[dict]) -> None:
    fields = ["h1_bias", "bos_confirmed", "poi_fresh", "correct_pd",
              "liq_swept_m15", "displacement", "mss_confirmed", "rr_to_target"]
    print("\n" + "=" * 60)
    print(f"HASIL {len(runs)} RUN - distribusi per field:")
    for f in fields:
        vals = Counter(str(r[f]) for r in runs)
        stable = "STABIL" if len(vals) == 1 else f"VARIAN({len(vals)})"
        print(f"  {f:16} {stable:12} {dict(vals)}")
    grades = Counter(derive_grade(r) for r in runs)
    all_stable = all(len(Counter(str(r[f]) for r in runs)) == 1 for f in fields)
    print(f"\n  GRADE akhir     {dict(grades)}")
    print("=" * 60)
    if all_stable and len(grades) == 1:
        print("VERDICT: 10/10 IDENTIK -> AI konsisten. Layak dikejar sebagai grader.")
    else:
        print("VERDICT: ADA VARIAN -> inilah noise yang TAK BOLEH masuk trigger.")
        print("         (lihat memory smc-ai-pivot-decision - ini yang kita debatkan)")
# PLACEHOLDER_GRADE
def main() -> None:
    fix = json.loads(FIXTURE.read_text())
    prompt = build_user_prompt(fix)
    print(f"Model diminta : {MODEL} (router bisa remap)")
    print(f"Fixture       : {FIXTURE.name}  anchor={fix['anchor_h1']}")
    print(f"Runs          : {N_RUNS}  (temperature=0, thinking off, forced tool)\n")
    runs = []
    for i in range(N_RUNS):
        try:
            a = call_once(prompt)
        except Exception as e:
            print(f"Run {i+1}: GAGAL — {e}")
            continue
        g = derive_grade(a)
        print(f"Run {i+1:2}: grade={g:4} bias={a['h1_bias']:8} "
              f"bos={int(a['bos_confirmed'])} poi={int(a['poi_fresh'])} "
              f"pd={int(a['correct_pd'])} sweep={int(a['liq_swept_m15'])} "
              f"disp={int(a['displacement'])} mss={int(a['mss_confirmed'])} "
              f"rr={a['rr_to_target']}")
        runs.append(a)
        time.sleep(1.0)   # jeda kecil biar tak trigger rate limit
    if runs:
        summarize(runs)
    else:
        print("\nTidak ada run sukses — cek rate limit / endpoint.")


if __name__ == "__main__":
    main()
