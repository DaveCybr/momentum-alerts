"""
AI grader (task #3) — LOG-ONLY. Menilai kandidat SMC via router lokal, catat grade,
TAPI TAK PERNAH nge-gate keputusan kirim. Grade cuma bahan buat ukur korelasi
grade↔outcome (task #4) SEBELUM AI boleh diberi kuasa.

Guardrail (terverifikasi, lihat memory smc-ai-pivot-decision):
  - endpoint 9router lokal, provider ac-prod (punya kuota)
  - temperature: 0, thinking off (reasoning_effort:none), forced tool use grade_setup
  - AI CUMA isi boolean per sub-pertanyaan; derive_grade() (KODE) putuskan A+/B/skip.

Tes konsistensi (task #1) menunjukkan lapisan mentah AI stokastik (2/5 fixture flip),
tapi derive_grade() meredamnya. Modul ini merekam KEDUANYA: checklist mentah AI +
grade turunan, biar #4 bisa ukur flip DAN korelasi outcome.
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
import urllib.error

DEFAULTS = dict(
    base_url="http://localhost:20128/v1",
    provider="ac-prod",              # punya kuota (cc/ kena rate limit)
    model_base="claude-sonnet",      # dirakit bertahap di _model() — jangan tulis penuh
    model_suffix="-5",               # router bisa remap ke opus-4-8; itu OK utk grading
    temperature=0,
    max_tokens=600,
    rr_min=2.5,
    rr_aplus=3.0,
    timeout_sec=120,
    max_retries=6,
    backoff_base=3.0,
)


def _model(cfg: dict) -> str:
    """Rakit id model bertahap (provider/base+suffix). Dipisah biar tak ke-mangle jadi 404."""
    return f"{cfg['provider']}/{cfg['model_base']}{cfg['model_suffix']}"
# Schema sama seperti consistency_test (task #1) — AI cuma isi fakta boolean, bukan grade.
GRADE_TOOL = {
    "type": "function",
    "function": {
        "name": "grade_setup",
        "description": "Report the SMC checklist for the current XAUUSD setup based strictly on the provided OHLCV data. Answer each field factually; do not decide an overall grade.",
        "parameters": {
            "type": "object",
            "properties": {
                "h1_bias": {"type": "string", "enum": ["bullish", "bearish", "none"],
                            "description": "H1 directional bias from BOS + protected level + open liquidity target + POI side."},
                "bos_confirmed": {"type": "boolean", "description": "H1 broke structure with a body close beyond a confirmed structural swing."},
                "poi_fresh": {"type": "boolean", "description": "A valid H1 POI (OB+FVG from the same displacement) exists and has NOT been retested since forming."},
                "correct_pd": {"type": "boolean", "description": "Price is on the correct side of the dealing range (discount for buy, premium for sell)."},
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

SYSTEM = (
    "You are a strict SMC (Smart Money Concepts) setup checker for XAUUSD intraday. "
    "You are given closed-candle OHLCV data for H1, M15, and M5. Evaluate the setup "
    "ONLY against the data provided — never invent price levels. Answer every checklist "
    "field factually via the grade_setup tool. Do not decide an overall grade; a separate "
    "deterministic step does that. If evidence for a field is absent, answer the "
    "conservative value (false / none / 0)."
)
def _fmt(rows) -> str:
    """OHLCV rows (list dict t/o/h/l/c/v ATAU DataFrame) → teks kompak."""
    out = []
    if hasattr(rows, "itertuples"):
        for r in rows.itertuples():
            out.append(f"{r.Index} O{r.open} H{r.high} L{r.low} C{r.close} V{int(r.volume)}")
    else:
        for r in rows:
            out.append(f"{r['t']} O{r['o']} H{r['h']} L{r['l']} C{r['c']} V{r['v']}")
    return "\n".join(out)


def build_prompt(symbol: str, h1, m15, m5, anchor: str = "") -> str:
    """Prompt user dari 3 TF. h1/m15/m5 = DataFrame (live) atau list dict (fixture)."""
    def tail(x, n):
        return x.iloc[-n:] if hasattr(x, "iloc") else x[-n:]
    return (
        f"Symbol: {symbol}  {('(last closed H1: '+anchor+')') if anchor else ''}\n\n"
        f"=== H1 (bias & POI) ===\n{_fmt(tail(h1, 60))}\n\n"
        f"=== M15 (liquidity map) ===\n{_fmt(tail(m15, 120))}\n\n"
        f"=== M5 (sweep / displacement / MSS / entry) ===\n{_fmt(tail(m5, 120))}\n\n"
        "Fill the grade_setup checklist for the setup as of the last M5 candle."
    )
def derive_grade(a: dict, rr_min: float = 2.5, rr_aplus: float = 3.0) -> str:
    """A+/B/skip diturunkan DARI boolean AI oleh KODE — deterministik, bukan AI.
    Inti guardrail (task #1): AI baca fakta, kode putuskan grade. Satu sumber kebenaran
    (consistency_test.py mengimpor dari sini)."""
    rr = float(a.get("rr_to_target", 0) or 0)
    hard = (
        a.get("h1_bias") in ("bullish", "bearish")
        and a.get("bos_confirmed")
        and a.get("poi_fresh")
        and a.get("correct_pd")
        and a.get("liq_swept_m15")
        and a.get("displacement")
        and a.get("mss_confirmed")
        and rr >= rr_min
    )
    if not hard:
        return "skip"
    return "A+" if rr >= rr_aplus else "B"
def call_grader(prompt: str, cfg: dict | None = None) -> dict:
    """Satu panggilan grader ke router. Return dict:
      {ok, checklist?, grade?, model, latency_ms, error?}. TAK melempar — log-only
      tak boleh menjatuhkan pipeline utama; kegagalan direkam sebagai ok=False."""
    c = {**DEFAULTS, **(cfg or {})}
    model = _model(c)
    payload = {
        "model": model, "temperature": c["temperature"], "stream": False,
        "max_tokens": c["max_tokens"], "reasoning_effort": "none",   # thinking off
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "tools": [GRADE_TOOL],
        "tool_choice": {"type": "function", "function": {"name": "grade_setup"}},
    }
    data = json.dumps(payload).encode()
    t0 = time.time()
    for attempt in range(c["max_retries"]):
        req = urllib.request.Request(f"{c['base_url']}/chat/completions", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=c["timeout_sec"]) as resp:
                body = json.loads(resp.read().decode())
            msg = body["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            if not calls:
                return dict(ok=False, model=model, latency_ms=int((time.time() - t0) * 1000),
                            error=f"no tool_calls (finish={body['choices'][0].get('finish_reason')})")
            checklist = json.loads(calls[0]["function"]["arguments"])
            grade = derive_grade(checklist, c["rr_min"], c["rr_aplus"])
            return dict(ok=True, checklist=checklist, grade=grade, model=model,
                        latency_ms=int((time.time() - t0) * 1000))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < c["max_retries"] - 1:
                time.sleep(c["backoff_base"] * (attempt + 1))
                continue
            return dict(ok=False, model=model, latency_ms=int((time.time() - t0) * 1000),
                        error=f"HTTP {e.code}: {e.read().decode()[:150]}")
        except Exception as e:
            return dict(ok=False, model=model, latency_ms=int((time.time() - t0) * 1000),
                        error=f"{type(e).__name__}: {e}")
    return dict(ok=False, model=model, latency_ms=int((time.time() - t0) * 1000),
                error="rate limited after retries")
def demo():
    # derive_grade: deterministik, tanpa jaringan
    full = dict(h1_bias="bullish", bos_confirmed=True, poi_fresh=True, correct_pd=True,
                liq_swept_m15=True, displacement=True, mss_confirmed=True, rr_to_target=3.5)
    assert derive_grade(full) == "A+", "7/7 + RR3.5 harus A+"
    assert derive_grade({**full, "rr_to_target": 2.7}) == "B", "RR2.7 harus B"
    assert derive_grade({**full, "mss_confirmed": False}) == "skip", "1 gerbang gagal → skip"
    assert derive_grade({**full, "rr_to_target": 2.0}) == "skip", "RR<2.5 → skip"
    print("[OK] derive_grade: A+/B/skip deterministik")

    # build_prompt: bentuk dari list dict (fixture) tak error & memuat 3 TF
    rows = [dict(t="2026-07-20 09:00", o=4000, h=4005, l=3998, c=4003, v=1200)] * 3
    p = build_prompt("XAUUSD.vx", rows, rows, rows, anchor="2026-07-20 09:00")
    assert "H1 (bias" in p and "M15 (liquidity" in p and "M5 (sweep" in p
    print("[OK] build_prompt: 3 TF tersusun")

    # _model: dirakit dari provider/base+suffix (bangun ekspektasi via cara yg sama, tak hardcode)
    expected = DEFAULTS["provider"] + "/" + DEFAULTS["model_base"] + DEFAULTS["model_suffix"]
    assert _model(DEFAULTS) == expected, f"{_model(DEFAULTS)} != {expected}"
    print(f"[OK] _model: {_model(DEFAULTS)}")

    # mode live opsional (hit router) hanya kalau diminta eksplisit
    if os.getenv("GRADER_LIVE") == "1":
        r = call_grader(build_prompt("XAUUSD.vx", rows, rows, rows), {})
        print(f"[LIVE] ok={r['ok']} grade={r.get('grade')} model={r['model']} "
              f"lat={r['latency_ms']}ms err={r.get('error')}")


if __name__ == "__main__":
    demo()
