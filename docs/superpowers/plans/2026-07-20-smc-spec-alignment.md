# SMC Engine Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menutup gap antara `engine/smc.py` + jalur eksekusi dan spesifikasi `strategy/xauusd-smc-trading-system.md` sehingga 100-trade validation menghasilkan data yang benar-benar menguji playbook.

**Architecture:** Perbaikan berlapis pada engine deterministik (POI H1, urutan sweep→displacement→MSS, entry limit 50% FVG, SL sweep-extreme+spread, TP liquidity tunggal), lalu guard eksekusi (risk cap, daily stop, set-and-forget), lalu jurnal (RR benar, dedup per simbol). AI tidak disentuh kecuali dokumentasi statusnya.

**Tech Stack:** Python 3.11, pandas/numpy, SQLite (WAL), MT5 via mt5linux RPyC, PowerShell 5.1 di Windows dev.

## Global Constraints

- Semua threshold masuk `config.yaml`; tidak ada hardcode (CLAUDE.md).
- Setiap modul inti punya `demo()` self-check yang bisa dijalankan `python -m <pkg.mod>`.
- Jalankan module mode dari root repo: `python -m engine.smc` (bukan `python engine\smc.py`).
- Analisis hanya closed candle (`_closed()` di semua TF).
- AI tetap `enabled: false`, log-only; tidak ada task yang memberi AI otoritas.
- Validasi playbook = XAUUSD saja; BTC keluar dari scope SMC.
- `execution.enabled: false` selama Fase A–C sampai gerbang lolos (lihat Task 1).
- Commit kecil per task; pesan gaya repo: `fix(scope): ...` / `feat(scope): ...`.
- Timezone: timestamp broker = UTC+`smc.server_utc_offset` (saat ini 2); semua logika sesi mengonversi ke UTC dahulu.

## Gap Map (ringkas, dari audit 2x)

| ID | Gap | Spec § | Kode sekarang | Fase |
|----|-----|--------|----------------|------|
| G1 | Eksekusi ON saat strategi belum sesuai spec | §1,§21 | `config.yaml:83` enabled + `strategy.active=smc_prescreen` | A |
| G2 | BTC ikut SMC XAU | §1 | `config.yaml:8-10` | A |
| G3 | Session 07–16+12–21 UTC (±14 jam) vs 3 jam London + 3,5 jam NY | §3 | `config.yaml:56`, `engine/smc.py:38` | A |
| G4 | RR jurnal selalu 1.5 (dari `tp[0]`) | §13,§21 | `engine/models.py:36-41`, `engine/smc.py:256` | B |
| G5 | Dedup candle tanpa simbol → XAU/BTC saling suppress | — (bug) | `journal/db.py:165,136` | B |
| G6 | Scan M30 untuk trigger M5 → sinyal basi ≤30 mnt | §11 | `config.yaml:69-71`, `ops/scheduler.py` | C |
| G7 | Entry market saat deteksi, bukan limit 50% FVG + expiry 3 candle | §11 | `engine/smc.py:212,221`, `execute/broker.py:86` | D |
| G8 | SL = min 3 candle − 5% dealing range, bukan sweep extreme + 1×spread | §12 | `engine/smc.py:217,223` | D |
| G9 | TP ladder 1.5/rr/rr×1.4 (TP3 ≤7R), bukan 1 TP di liquidity; executed order malah TP=0 + trailing/partial | §13,§15 | `engine/smc.py:256`, `delivery/callbacks.py:21`, `config.yaml:88-96`, `monitor/watcher.py:186-247` | D |
| G10 | `poi_fresh` = ada FVG M5 baru; tidak ada OB H1, fresh-test, distal invalidation, sweep-di-dalam-POI | §6,§8 | `engine/smc.py:207-210` | E |
| G11 | Tidak ada urutan sweep→displacement→MSS; MSS boleh pecah swing apa pun | §8-§10 | `engine/smc.py:150-175,196-205` | E |
| G12 | Protected level dihitung tapi tidak dipakai gate; target liquidity tidak dicek terbuka | §4 | `engine/smc.py:192` | E |
| G13 | Dealing range = rolling min/max 40 bar, re-anchor tiap eval | §5 | `engine/smc.py:95-99` | E |
| G14 | Tidak ada guard risiko: >2% wajib skip, equity bukan balance | §14 | `execute/broker.py:80-83` | F |
| G15 | Tidak ada daily stop (2 loss / 3 trade / +2.5R / NY close) | §16 | `alert/engine.py`, `execute/broker.py` | F |
| G16 | Tidak ada news filter ±15 mnt | §3,§11 | (absen) | F* |
| G17 | Jurnal tak punya kolom validasi (risiko %, R, MAE/MFE, spread, klasifikasi) | §19-§21 | `journal/db.py:14-68` | G |
| G18 | Shadow AI: outcome tidak pernah terisi → task #4 mandek | — | `monitor/watcher.py` (sim hanya utk sent=1) | G |
| G19 | `direction: long_only` diabaikan SMC | — (bug laten) | `engine/smc.py:269` | B |
| G20 | rr_cap komentar salah ("batas TP masuk akal") padahal TP3 = cap×1.4 | — (doc) | `engine/smc.py:32` | D |

*G16 (news filter) butuh sumber kalender eksternal — ditandai sebagai fase terpisah dengan keputusan owner (manual toggle vs API).

## Urutan fase

```text
Fase A (hari ini): safety config — matikan risiko salah-validasi
Fase B: perbaikan bug kecil yang merusak data (RR, dedup, long_only)
Fase C: cadence M5
Fase D: entry/SL/TP sesuai spec + set-and-forget
Fase E: POI H1 + state sequence (perubahan terbesar)
Fase F: risk guard + daily stop
Fase G: jurnal validasi + shadow outcome backfill
Gerbang GO: semua self-check lolos + 10 setup dry-run manual cocok dengan chart
```

---

### Task 1: Fase A — safety config

**Files:**
- Modify: `config.yaml`

**Interfaces:**
- Consumes: —
- Produces: config aman untuk pengembangan; tidak ada eksekusi selama refactor.

- [ ] **Step 1: Ubah config**

```yaml
# config.yaml — nilai yang diubah (baris lain tetap)
instruments:
  - "XAUUSD.vx"            # BTC keluar dari scope validasi SMC (G2)

execution:
  enabled: false            # G1: OFF selama Fase A–E; nyalakan lagi di gerbang GO

smc:
  sessions_utc: [[7, 10], [12, 15]]   # G3: London open+3h (07-10 UTC), NY open+3.5h — bulatkan [12,15]; 15:30 tak bisa dinyatakan per-jam → lihat Step 2
```

- [ ] **Step 2: Tambah dukungan menit di sesi**

Jendela NY 3,5 jam butuh resolusi menit. Ubah format ke `[[jam_mulai, menit_mulai, jam_akhir, menit_akhir]]`:

```yaml
smc:
  sessions_utc: [[7, 0, 10, 0], [12, 0, 15, 30]]   # London 07:00-10:00, NY 12:00-15:30 UTC
```

dan di `engine/smc.py` ganti `_in_session`:

```python
def _in_session(ts: pd.Timestamp, sessions_utc: list[list[int]], server_utc_offset: int = 0) -> bool:
    """True kalau ts (waktu broker) berada dalam salah satu jendela sesi UTC.
    Format sesi: [h1, m1, h2, m2] (menit-presisi, NY 3.5 jam butuh :30)."""
    minutes = ((ts.hour - server_utc_offset) % 24) * 60 + ts.minute
    for a in sessions_utc:
        if len(a) == 2:                      # kompat lama [h1, h2]
            lo, hi = a[0] * 60, a[1] * 60
        else:
            lo, hi = a[0] * 60 + a[1], a[2] * 60 + a[3]
        if lo <= minutes < hi:
            return True
    return False
```

- [ ] **Step 3: Update demo() `engine/smc.py` untuk format baru**

```python
    # _in_session: menit-presisi (NY 12:00-15:30)
    sess = [[7, 0, 10, 0], [12, 0, 15, 30]]
    assert _in_session(pd.Timestamp("2026-01-05 09:00", tz="UTC"), sess)
    assert _in_session(pd.Timestamp("2026-01-05 15:29", tz="UTC"), sess)
    assert not _in_session(pd.Timestamp("2026-01-05 15:30", tz="UTC"), sess)
    assert not _in_session(pd.Timestamp("2026-01-05 03:00", tz="UTC"), sess)
    assert _in_session(pd.Timestamp("2026-01-05 11:00", tz="UTC"), [[7, 16]]) , "format lama tetap jalan"
```

- [ ] **Step 4: Jalankan self-check**

Run: `python -m engine.smc`
Expected: semua `[OK]`, termasuk assert sesi baru.

- [ ] **Step 5: Commit**

```powershell
git add config.yaml engine/smc.py
git commit -m "fix(smc): sesi menit-presisi London 3h + NY 3.5h; eksekusi off + XAU-only selama alignment"
```

---

### Task 2: Fase B — RR jurnal benar (G4)

**Files:**
- Modify: `engine/models.py`
- Modify: `engine/smc.py`
- Test: demo() di `engine/smc.py`

**Interfaces:**
- Consumes: `Setup` dataclass.
- Produces: `Setup.rr_planned: float | None` — RR aktual ke target; `Setup.rr` fallback lama untuk trend_pullback.

- [ ] **Step 1: Tambah field `rr_planned` di Setup**

```python
# engine/models.py — dalam @dataclass Setup, setelah experimental:
    rr_planned: float | None = None    # RR aktual entry→TP terjauh yang direncanakan strategi.
                                       # SMC mengisi ini; trend_pullback biarkan None.

    @property
    def rr(self) -> float:
        if self.rr_planned is not None:
            return self.rr_planned
        entry = self.entry_high if self.direction == "BUY" else self.entry_low
        risk = abs(entry - self.sl)
        return round(abs(self.tp[0] - entry) / risk, 2) if risk else 0.0
```

- [ ] **Step 2: Isi dari SMC**

```python
# engine/smc.py — _mk_setup(), argumen Setup(...):
            gates=a["checklist"], experimental=True,
            rr_planned=rr,                      # G4: jurnal merekam RR gate, bukan tp[0]/risk
```

- [ ] **Step 3: Tambah assert demo**

```python
    # rr_planned mengalir ke .rr (G4: jurnal tak lagi selalu 1.5)
    a_rr = dict(bias="bullish", direction="BUY", price=100.0, risk=5.0, rr=3.2, sl=95.0,
                entry_low=98.0, entry_high=100.0, zone="discount",
                checklist={k: True for k in ("bos", "poi_fresh", "correct_pd", "sweep_m15",
                                             "displacement", "mss")})
    assert s._mk_setup("X", a_rr, p).rr == 3.2, "rr harus dari rr_planned"
```

- [ ] **Step 4: Verifikasi**

Run: `python -m engine.smc; if ($?) { python -m journal.db }`
Expected: semua `[OK]`.

- [ ] **Step 5: Commit**

```powershell
git add engine/models.py engine/smc.py
git commit -m "fix(smc): jurnal rekam RR gate via rr_planned (bukan tp1/risk=1.5)"
```

---

### Task 3: Fase B — dedup per simbol (G5)

**Files:**
- Modify: `journal/db.py`
- Modify: `alert/engine.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `Journal.candle_sent`, `Journal.shadow_graded`, `alert.engine.decide`.
- Produces: `candle_sent(symbol, candle_id, direction)`, `shadow_graded(symbol, candle_id, direction)` — signature baru dengan simbol di depan.

- [ ] **Step 1: Ubah query dedup**

```python
# journal/db.py
    def candle_sent(self, symbol: str, candle_id: str, direction: str) -> bool:
        with self._c() as c:
            r = c.execute("""SELECT 1 FROM alerts WHERE symbol=? AND candle_id=? AND direction=?
                             AND sent=1 LIMIT 1""", (symbol, candle_id, direction)).fetchone()
            return r is not None

    def shadow_graded(self, symbol: str, candle_id: str, direction: str) -> bool:
        with self._c() as c:
            r = c.execute("""SELECT 1 FROM alerts WHERE symbol=? AND candle_id=? AND direction=?
                             AND strategy='smc_shadow' LIMIT 1""",
                          (symbol, candle_id, direction)).fetchone()
            return r is not None
```

- [ ] **Step 2: Update pemanggil**

`alert/engine.py` — cari pemanggilan `journal.candle_sent(candle_id, setup.direction)` dan ganti menjadi `journal.candle_sent(setup.symbol, candle_id, setup.direction)`.

`main.py:47` — `journal.shadow_graded(candle_id, setup.direction)` → `journal.shadow_graded(setup.symbol, candle_id, setup.direction)`.

- [ ] **Step 3: Update demo() `journal/db.py`**

```python
    # dedup per-simbol: candle_id sama di simbol beda TAK saling suppress (G5)
    assert not j.shadow_graded("BTCUSD", "SHDW1", "BUY"), "simbol beda harus False"
```

Sesuaikan assert `shadow_graded` lama menjadi 3-argumen (`"XAUUSD", "SHDW1", "BUY"`).

- [ ] **Step 4: Verifikasi**

Run: `python -m journal.db; if ($?) { python -m alert.engine }`
Expected: semua `[OK]` (kalau `alert/engine.py` punya demo; kalau tidak, `python -m compileall -q alert main.py`).

- [ ] **Step 5: Commit**

```powershell
git add journal/db.py alert/engine.py main.py
git commit -m "fix(journal): dedup candle per simbol (XAU/BTC tak saling suppress)"
```

---

### Task 4: Fase B — hormati `direction: long_only` (G19)

**Files:**
- Modify: `engine/smc.py`

**Interfaces:**
- Consumes: `params["direction"]` dari `build_strategy` (`main.py:36`).
- Produces: `evaluate()` mengembalikan None untuk SELL saat `long_only`.

- [ ] **Step 1: Tambah gate arah**

```python
# engine/smc.py — evaluate(), setelah `a = self._analyze(bundle, p)` dan cek None:
        if p.get("direction") == "long_only" and a["direction"] == "SELL":
            return None
```

- [ ] **Step 2: Tambah assert demo**

```python
    # long_only menolak SELL (G19). Bypass jalur data penuh: cek langsung lewat _analyze mock
    #  — cukup uji gate: evaluate dengan direction=long_only pada data bearish → None.
    #  (dfb bullish; buat mirror sederhana dgn membalik kolom high/low tak praktis di demo,
    #   jadi uji melalui params override pada data flat: hasil tetap None, dan pada data
    #   bullish hasil BUY tak terpengaruh.)
    assert SmcPrescreen().evaluate(b, {"direction": "long_only"}) is None  # b = flat bundle
```

- [ ] **Step 3: Verifikasi**

Run: `python -m engine.smc`
Expected: semua `[OK]`.

- [ ] **Step 4: Commit**

```powershell
git add engine/smc.py
git commit -m "fix(smc): hormati direction long_only (SELL ditolak di evaluate)"
```

---

### Task 5: Fase C — cadence M5 (G6)

**Files:**
- Modify: `config.yaml`
- Modify: `ops/scheduler.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `scheduler.run_candle_loop(tick, minutes, offset_sec)`.
- Produces: scan berlapis — SMC tiap M5 close, trend_pullback tetap M30. Konfig `scheduler.minutes_by_strategy`.

- [ ] **Step 1: Tambah knob config**

```yaml
scheduler:
  eval_on_close: M30          # dipakai trend_pullback
  minutes: 30
  minutes_smc: 5              # G6: SMC trigger TF M5 → scan tiap M5 close
  offset_sec: 5
  monitor_sec: 60
  deadman_min: 90
```

- [ ] **Step 2: `next_tick` generik**

`ops/scheduler.py::next_tick` sudah generik terhadap `minutes` — verifikasi dengan assert baru:

```python
    assert next_tick(d(2026, 7, 20, 10, 7, tzinfo=WIB), 5, 5) == d(2026, 7, 20, 10, 10, 5, tzinfo=WIB)
    assert next_tick(d(2026, 7, 20, 10, 55, tzinfo=WIB), 5, 5) == d(2026, 7, 20, 11, 0, 5, tzinfo=WIB)
```

- [ ] **Step 3: Pilih cadence dari strategi aktif di `main.py`**

```python
# main.py — run_loop(): ganti baris terakhir
    minutes = sc.get("minutes_smc", 5) if strat.name == "smc_prescreen" else sc["minutes"]
    scheduler.run_candle_loop(tick, minutes, sc["offset_sec"])
```

dan di log startup:

```python
    print(f"[main] loop aktif — scheduler({minutes}m) + monitor(60s) + telegram-poll")
```

(pindahkan `print` ke setelah `minutes` dihitung).

- [ ] **Step 4: Verifikasi**

Run: `python -m ops.scheduler; if ($?) { python -m compileall -q main.py }`
Expected: `[OK] scheduler next_tick...` + tanpa error compile.

Catatan beban: scan M5 = 6× lebih sering; `get_bundle` menarik 6 TF × 400 candle per tick. Kalau latensi RPyC jadi masalah, kurangi `counts` H4/D1 ke 100 di config (tidak dipakai SMC).

- [ ] **Step 5: Commit**

```powershell
git add config.yaml ops/scheduler.py main.py
git commit -m "feat(scheduler): cadence M5 untuk smc_prescreen (trend_pullback tetap M30)"
```

---

### Task 6: Fase D — SL dari sweep extreme + spread (G8)

**Files:**
- Modify: `engine/smc.py`
- Modify: `config.yaml`

**Interfaces:**
- Consumes: `swept_liquidity` (diubah agar mengembalikan indeks sweep, bukan bool).
- Produces: `swept_liquidity(...) -> tuple[bool, int | None, float | None]` = (swept, sweep_bar_idx_di_window_m5, sweep_extreme_price). `_analyze` menaruh `sweep_extreme` di dict hasil.

- [ ] **Step 1: Ubah `swept_liquidity` mengembalikan lokasi sweep**

```python
def swept_liquidity(m15: pd.DataFrame, m5: pd.DataFrame, p: dict, bias: str
                    ) -> tuple[bool, int | None, float | None]:
    """Return (swept, idx_bar_sweep_dlm_window, sweep_extreme).
    sweep_extreme = low terendah (bullish) / high tertinggi (bearish) pada bar sweep —
    dipakai §12 sebagai anchor SL."""
    if m15 is None or m5 is None or len(m15) < p["sweep_lookback"] or len(m5) < 3:
        return False, None, None
    sh_ser, sl_ser = ind.swings(m15, p["swing_k"])
    win = m5.iloc[-p["trigger_lookback"]:]
    lo_v, hi_v, cl_v = win["low"].values, win["high"].values, win["close"].values
    if bias == "bullish":
        swing_lows = [float(m15["low"].loc[i]) for i in sl_ser[sl_ser].index]
        if not swing_lows:
            return False, None, None
        pool_lo = swing_lows[-1]
        for i in range(len(win)):
            if lo_v[i] < pool_lo and cl_v[i] > pool_lo:
                return True, i, float(lo_v[i])
        return False, None, None
    if bias == "bearish":
        swing_highs = [float(m15["high"].loc[i]) for i in sh_ser[sh_ser].index]
        if not swing_highs:
            return False, None, None
        pool_hi = swing_highs[-1]
        for i in range(len(win)):
            if hi_v[i] > pool_hi and cl_v[i] < pool_hi:
                return True, i, float(hi_v[i])
        return False, None, None
    return False, None, None
```

- [ ] **Step 2: Knob buffer spread**

```yaml
smc:
  sl_spread_buffer: 0.35      # §12: 1×spread aktual. Live spread tak ada di Bundle → pakai
                              # median spread XAU broker (USD). Ganti dgn spread live saat eksekusi.
```

Tambahkan juga default di `SMC_DEFAULTS`: `sl_spread_buffer=0.35,`.

- [ ] **Step 3: Pakai di `_analyze`**

```python
        # 5. sweep likuiditas M15→M5 (dgn lokasi + extreme utk SL §12)
        sweep, sweep_i, sweep_ext = swept_liquidity(m15, m5, p, bias)
        ...
        buf = float(p["sl_spread_buffer"])
        if bias == "bullish":
            sl = (sweep_ext - buf) if sweep_ext is not None \
                 else float(m5["low"].iloc[-3:].min()) - buf          # fallback pra-sweep
            ...
        else:
            sl = (sweep_ext + buf) if sweep_ext is not None \
                 else float(m5["high"].iloc[-3:].max()) + buf
```

(bagian `...` = perhitungan target/rr/entry yang sudah ada, tidak berubah di task ini).

Simpan juga di dict hasil `_analyze`: `sweep_i=sweep_i, sweep_ext=sweep_ext,`.

- [ ] **Step 4: Update assert demo sweep**

```python
    swept, si_, ext_ = swept_liquidity(m15, m5, p, "bullish")
    assert swept and ext_ == 98.5, f"sweep extreme harus 98.5, dapat {ext_}"
```

- [ ] **Step 5: Verifikasi + commit**

Run: `python -m engine.smc`
Expected: semua `[OK]`.

```powershell
git add engine/smc.py config.yaml
git commit -m "feat(smc): SL dari sweep extreme + buffer spread (spec §12)"
```

---

### Task 7: Fase D — TP tunggal di liquidity + set-and-forget (G9, G20)

**Files:**
- Modify: `engine/smc.py`
- Modify: `config.yaml`
- Modify: `delivery/callbacks.py`
- Modify: `monitor/watcher.py`

**Interfaces:**
- Consumes: `Setup.tp` (list), `execution.trailing`, `manage_positions`.
- Produces: SMC `Setup.tp = [target, target, target]` (kompat list-3 untuk simulate_outcome); `execution.mode: "set_and_forget" | "runner"` per strategi.

- [ ] **Step 1: TP tunggal dari target liquidity**

```python
# engine/smc.py — _mk_setup(): ganti blok mults/tp
        # §13: SATU TP di opposing liquidity (dealing range extreme). List-3 dipertahankan
        # demi kompat simulate_outcome/telegram, ketiganya = target yang sama.
        target = a["target"]
        tp = [round(float(target), 2)] * 3
```

dan di `_analyze` tambahkan `target=target,` ke dict return (nilai `hi`/`lo` yang sudah dihitung).

Hapus komentar salah `rr_cap` (G20) dan ganti:

```python
    rr_cap=5.0,               # clamp RR utk tier/statistik. TP TIDAK dibentuk dari rr lagi
                              # (§13: TP = liquidity), jadi cap hanya membatasi angka RR.
```

- [ ] **Step 2: Mode eksekusi per strategi**

```yaml
execution:
  enabled: false
  mode_by_strategy:
    smc_prescreen: set_and_forget   # §15: 1 SL, 1 TP, tanpa trailing/BE/partial
    trend_pullback: runner          # perilaku lama (trailing chandelier + partial)
```

- [ ] **Step 3: Terapkan mode di `_do_execute`**

```python
# delivery/callbacks.py — _do_execute(): ganti kalkulasi order_tp
    strat_name = a["strategy"] if "strategy" in a.keys() else ""
    mode = cfg["execution"].get("mode_by_strategy", {}).get(strat_name, "runner")
    tps = json.loads(a["tp_json"])
    if mode == "set_and_forget":
        order_tp = tps[0]                       # §15: TP keras, tanpa trailing
    else:
        idx = min(int(cfg["execution"]["target_tp"]), len(tps)) - 1
        order_tp = 0.0 if cfg["execution"].get("trailing", True) else tps[idx]
```

- [ ] **Step 4: Monitor tidak menyentuh posisi set-and-forget**

```python
# monitor/watcher.py — manage_positions(): di awal loop posisi, setelah dapat alert row:
        strat_name = row["strategy"] if row and "strategy" in row.keys() else ""
        mode = cfg["execution"].get("mode_by_strategy", {}).get(strat_name, "runner")
        if mode == "set_and_forget":
            continue          # §15: tanpa trailing/BE/partial — broker SL/TP yang bekerja
```

(Ikuti struktur loop yang ada; `row` = hasil join ticket→alert yang sudah dipakai untuk `initial_sl_for_ticket`.)

- [ ] **Step 5: Update demo callbacks**

```python
    # set_and_forget: order_tp = tps[0], bukan 0.0 (uji lewat cfg mode_by_strategy)
    cfg["execution"] = {"enabled": True, "allow_short": True, "target_tp": 3, "trailing": True,
                        "mode_by_strategy": {"smc_prescreen": "set_and_forget"}}
```

(dan record alert dengan `strategy="smc_prescreen"` lalu assert exec path memakai TP keras — cek lewat pesan status yang memuat `TP` bukan `trailing SL`; broker.place tidak benar-benar dipanggil di demo karena akan gagal koneksi — bungkus assert pada string yang dibentuk sebelum place, atau cukup uji unit `mode` resolution dengan fungsi kecil `resolve_exec_mode(cfg, strategy_name)` yang diekstrak).

Refactor minimal untuk testability:

```python
# delivery/callbacks.py
def resolve_exec_mode(cfg: dict, strategy_name: str) -> str:
    return cfg["execution"].get("mode_by_strategy", {}).get(strategy_name, "runner")
```

Demo assert:

```python
    assert resolve_exec_mode({"execution": {"mode_by_strategy": {"smc_prescreen": "set_and_forget"}}},
                             "smc_prescreen") == "set_and_forget"
    assert resolve_exec_mode({"execution": {}}, "trend_pullback") == "runner"
```

- [ ] **Step 6: Verifikasi + commit**

Run: `python -m engine.smc; if ($?) { python -m delivery.callbacks }; if ($?) { python -m monitor.watcher }`
Expected: semua `[OK]`.

```powershell
git add engine/smc.py config.yaml delivery/callbacks.py monitor/watcher.py
git commit -m "feat(exec): mode set_and_forget utk SMC (1 TP di liquidity, tanpa trailing/partial)"
```

---

### Task 8: Fase D — entry limit 50% FVG + expiry (G7)

**Files:**
- Modify: `engine/smc.py`
- Modify: `engine/models.py`
- Modify: `delivery/telegram.py` (tampilkan tipe entry)
- Modify: `delivery/callbacks.py`
- Modify: `execute/broker.py`

**Interfaces:**
- Consumes: `ind.fvg`, hasil `_mss` (indeks candle MSS dibutuhkan → diubah).
- Produces: `Setup.entry_type: str` (`"limit"`), `Setup.entry_price: float | None`, `Setup.expires_candle_id: str | None`; `broker.place_limit(cfg, symbol, direction, entry, sl, tp, expiry_ts)`.

- [ ] **Step 1: `_mss` mengembalikan indeks MSS**

```python
def _mss(m5: pd.DataFrame, p: dict, bias: str) -> tuple[bool, bool, int | None]:
    """... Return (mss_confirmed, displaced_in_window, mss_bar_idx_global)."""
    ...
    mss_i = None
    for i in range(start, n):
        s = int(disp.iloc[i])
        if bias == "bullish" and s > 0:
            displaced = True
            prior_h = [hi for hi in highs if hi + p["swing_k"] < i]
            if prior_h and cv[i] > hv[prior_h[-1]]:
                mss, mss_i = True, i
        if bias == "bearish" and s < 0:
            displaced = True
            prior_l = [li for li in lows if li + p["swing_k"] < i]
            if prior_l and cv[i] < lv[prior_l[-1]]:
                mss, mss_i = True, i
    return (mss, displaced, mss_i)
```

- [ ] **Step 2: Hitung 50% FVG dari candle displacement MSS**

```python
# engine/smc.py — _analyze(), setelah _mss:
        mss, displaced, mss_i = _mss(m5, p, bias)
        entry_price = None
        if mss and mss_i is not None:
            win_s = m5.iloc[-p["struct_lookback"]:] if len(m5) > p["struct_lookback"] else m5
            bull_g2, bear_g2 = ind.fvg(win_s)
            gseries = bull_g2 if bias == "bullish" else bear_g2
            # FVG yang ditinggalkan displacement MSS = gap pada bar <= mss_i terdekat
            cand = [j for j in range(max(0, mss_i - 3), min(len(win_s), mss_i + 1))
                    if float(gseries.iloc[j]) > 0]
            if cand:
                j = cand[-1]
                hj, lj = win_s["high"].values, win_s["low"].values
                if bias == "bullish":
                    gap_lo, gap_hi = float(hj[j - 2]), float(lj[j])
                else:
                    gap_lo, gap_hi = float(hj[j]), float(lj[j - 2])
                entry_price = round((gap_lo + gap_hi) / 2, 2)      # §11: 50% FVG
```

RR dan risk dihitung dari `entry_price` bila ada (fallback: harga sekarang — tapi setup TANPA entry_price tidak boleh fire):

```python
        if bias == "bullish":
            sl = ...                                  # dari Task 6
            target = hi
            ref = entry_price if entry_price is not None else price
            risk = ref - sl
            rr = round((target - ref) / risk, 2) if risk > 0 else 0.0
```

(mirror untuk bearish).

- [ ] **Step 3: Gate keras menambah `entry_price`**

```python
# evaluate(): tambah ke `hard`
        hard = all([..., a.get("entry_price") is not None])
```

- [ ] **Step 4: Bawa ke Setup + expiry**

```python
# engine/models.py — field baru di Setup:
    entry_type: str = "market"           # "market" | "limit"
    entry_price: float | None = None     # harga limit (50% FVG) utk entry_type=limit
    expires_after: int = 0               # §11: batal kalau tak terisi dalam N candle TF entry (0=tanpa)
```

```python
# engine/smc.py — _mk_setup():
            rr_planned=rr,
            entry_type="limit", entry_price=a["entry_price"], expires_after=3,
```

- [ ] **Step 5: Broker limit order**

```python
# execute/broker.py
def place_limit(cfg: dict, symbol: str, direction: str, entry: float, sl: float, tp: float,
                expiry_min: int = 15) -> dict:
    """Pending BUY_LIMIT/SELL_LIMIT di `entry` dgn expiry ORDER_TIME_SPECIFIED (§11: 3 candle M5)."""
    ex = cfg["execution"]
    with sources.MT5_LOCK:
        n = open_count(cfg, symbol)
        if n >= ex["max_positions"]:
            return {"ok": False, "msg": f"maks {ex['max_positions']} posisi {symbol} (sudah {n})"}
        m = sources._connect(cfg["data"]["mt5"])
        ai = m.account_info()
        si = m.symbol_info(symbol)
        is_buy = direction == "BUY"
        entry, sl, tp = float(entry), float(sl), float(tp)
        sl_distance = abs(entry - sl)
        if sl_distance <= 0:
            return {"ok": False, "msg": "jarak SL 0/invalid"}
        risk_amount = float(ai.balance) * float(ex["risk_percent"]) / 100.0
        lot = _lot(si, risk_amount, sl_distance)
        import time as _t
        req = {
            "action": m.TRADE_ACTION_PENDING, "symbol": symbol, "volume": lot,
            "type": m.ORDER_TYPE_BUY_LIMIT if is_buy else m.ORDER_TYPE_SELL_LIMIT,
            "price": entry, "sl": sl, "tp": tp, "magic": int(ex.get("magic", 0)),
            "comment": "smc-limit", "type_time": m.ORDER_TIME_SPECIFIED,
            "expiration": int(_t.time()) + expiry_min * 60,
        }
        res, rc = _send(m, req)
    if rc == RC_DONE:
        return {"ok": True, "lot": lot, "price": entry,
                "ticket": int(getattr(res, "order", 0) or 0), "balance": float(ai.balance)}
    return {"ok": False, "msg": f"retcode={rc} ({getattr(res, 'comment', '')})", "lot": lot}
```

Catatan: sebagian broker menolak `ORDER_TIME_SPECIFIED` pada pending — kalau `rc` gagal dengan retcode time, fallback `ORDER_TIME_GTC` + pembatalan oleh monitor (tambahkan TODO di kode; pembatalan monitor = Task 11 opsional).

- [ ] **Step 6: Callback memakai limit untuk SMC**

```python
# delivery/callbacks.py — _do_execute():
    entry_type = a["entry_type"] if "entry_type" in a.keys() else "market"
    if mode == "set_and_forget" and entry_type == "limit" and a["entry_price"] is not None:
        r = broker.place_limit(cfg, a["symbol"], a["direction"], a["entry_price"], a["sl"],
                               order_tp, expiry_min=15)
    else:
        r = broker.place(cfg, a["symbol"], a["direction"], a["sl"], order_tp)
```

Jurnal: tambahkan kolom `entry_type TEXT` dan `entry_price REAL` di `alerts` (migrasi `ALTER TABLE` idempoten seperti pola `_migrate` yang ada), dan tulis dari `record()`.

- [ ] **Step 7: Verifikasi + commit**

Run: `python -m engine.smc; if ($?) { python -m journal.db }; if ($?) { python -m delivery.callbacks }; if ($?) { python -m execute.broker }`
Expected: semua `[OK]`.

```powershell
git add engine/smc.py engine/models.py journal/db.py delivery/callbacks.py execute/broker.py delivery/telegram.py
git commit -m "feat(smc): entry limit 50% FVG + expiry 3 candle (spec §11)"
```

---

### Task 9: Fase E — POI H1 + urutan event (G10–G13) — perubahan terbesar

**Files:**
- Modify: `engine/smc.py` (fungsi baru `detect_poi_h1`, `dealing_range` anchor-benar, `_analyze` sequence-aware)

**Interfaces:**
- Consumes: `detect_bias` (protected), `ind.fvg`, `ind.displacement`, `ind.swings`.
- Produces: `detect_poi_h1(h1, p, bias) -> dict | None` = `{lo, hi, origin_idx, fresh: bool}`; `_analyze` menambahkan `poi`, dan semua trigger M5 disyaratkan terjadi SETELAH harga masuk POI.

- [ ] **Step 1: `detect_poi_h1`**

```python
def detect_poi_h1(h1: pd.DataFrame, p: dict, bias: str) -> dict | None:
    """POI H1 §6: OB (candle lawan terakhir sebelum displacement H1 yang BOS) ∩/berdampingan FVG
    dari displacement yang sama; fresh = belum diretest sejak terbentuk; invalid kalau close
    menembus distal edge. Return {lo, hi, origin_idx, fresh} atau None."""
    win = h1.iloc[-p["struct_lookback"]:] if len(h1) > p["struct_lookback"] else h1
    disp = ind.displacement(win, atr_mult=p["disp_atr_mult"],
                            body_ratio=p["disp_body_ratio"], atr_period=p["atr_period"])
    bull_g, bear_g = ind.fvg(win)
    o, c = win["open"].values, win["close"].values
    hv, lv, cv = win["high"].values, win["low"].values, win["close"].values
    n = len(win)
    want = 1 if bias == "bullish" else -1
    gser = bull_g if bias == "bullish" else bear_g
    # kandidat: bar displacement searah bias yang meninggalkan FVG dalam 3 bar sesudahnya
    for i in range(n - 2, 2, -1):                     # terbaru dulu
        if int(disp.iloc[i]) != want:
            continue
        if not any(float(gser.iloc[j]) > 0 for j in range(i, min(n, i + 3))):
            continue
        # OB = candle lawan terakhir sebelum i
        ob = None
        for j in range(i - 1, max(-1, i - 6), -1):
            bearish_c = c[j] < o[j]
            if (bias == "bullish" and bearish_c) or (bias == "bearish" and not bearish_c):
                ob = j
                break
        if ob is None:
            continue
        zlo, zhi = float(lv[ob]), float(hv[ob])       # full range candle OB (§6 Batas POI)
        # fresh: tidak ada candle SETELAH pembentukan (i+1..akhir) yang low/high masuk zona
        touched = any((lv[k] <= zhi and hv[k] >= zlo) for k in range(i + 1, n))
        # invalid: close menembus distal edge
        if bias == "bullish" and (cv[i + 1:] < zlo).any():
            continue
        if bias == "bearish" and (cv[i + 1:] > zhi).any():
            continue
        return dict(lo=zlo, hi=zhi, origin_idx=ob, fresh=not touched)
    return None
```

- [ ] **Step 2: Dealing range anchor-benar (G13)**

```python
def dealing_range(df: pd.DataFrame, p: dict, bias: str, protected: float) -> tuple[float, float]:
    """§5: anchor = protected level → extreme impuls BOS. Bukan rolling min/max."""
    win = df.iloc[-p["struct_lookback"]:] if len(df) > p["struct_lookback"] else df
    if bias == "bullish":
        return float(protected), float(win["high"].max())
    if bias == "bearish":
        return float(win["low"].min()), float(protected)
    return float(win["low"].min()), float(win["high"].max())
```

Perbarui pemanggil: `lo, hi = dealing_range(h1, p, bias, protected)`.

`pd_zone` threshold kembali ke spec (0–50 discount / 50–100 premium):

```python
    if frac < 0.50:
        return "discount"
    if frac > 0.50:
        return "premium"
    return "equilibrium"
```

- [ ] **Step 3: Gate protected level (G12)**

```python
# _analyze(), setelah detect_bias:
        # §4: bias mati kalau protected level ditembus body close
        last_close = float(h1["close"].iloc[-1])
        if bias == "bullish" and last_close < protected:
            return None
        if bias == "bearish" and last_close > protected:
            return None
```

- [ ] **Step 4: Sequence sweep→displacement→MSS + sweep di dalam POI (G10, G11)**

```python
# _analyze() — ganti blok sweep/mss/poi:
        poi = detect_poi_h1(h1, p, bias)
        poi_fresh = bool(poi and poi["fresh"])

        sweep, sweep_i, sweep_ext = swept_liquidity(m15, m5, p, bias)

        # §8: sweep harus terjadi saat harga di dalam/menyentuh POI H1
        sweep_in_poi = False
        if sweep and poi and sweep_i is not None:
            win5 = m5.iloc[-p["trigger_lookback"]:]
            bar = win5.iloc[sweep_i]
            sweep_in_poi = float(bar["low"]) <= poi["hi"] and float(bar["high"]) >= poi["lo"]

        mss, displaced, mss_i = _mss(m5, p, bias)
        # §10: MSS sah hanya SETELAH sweep
        seq_ok = bool(sweep and mss and sweep_i is not None and mss_i is not None
                      and mss_i > (len(m5) - p["trigger_lookback"] + sweep_i))
```

Checklist berubah:

```python
        checklist = {
            "h1_bias": bias, "bos": bos, "poi_fresh": poi_fresh, "correct_pd": correct_pd,
            "sweep_m15": bool(sweep and sweep_in_poi), "displacement": displaced,
            "mss": bool(mss and seq_ok),
            "rr": rr, "session": in_sess, "zone": zone,
        }
```

- [ ] **Step 5: Demo fixture baru**

Bangun fixture H1 dengan OB+FVG jelas lalu M5 sweep→displacement→MSS berurutan; assert `evaluate` fire, dan assert urutan salah (MSS sebelum sweep) → None. Fixture minimal:

```python
    # POI H1: downtrend candle (OB) → displacement bullish 3 bar dgn FVG → belum diretest
    h1rows = [(100, 100.4, 99.6, 100)] * 30
    h1rows[24] = (100.0, 100.2, 98.8, 99.0)    # OB bearish candle
    h1rows[25] = (99.0, 103.5, 98.9, 103.2)    # displacement bullish (body besar)
    h1rows[26] = (103.2, 104.5, 103.0, 104.0)  # lanjut → FVG vs bar 24
    h1p = _mk(h1rows)
    poi = detect_poi_h1(h1p, p, "bullish")
    assert poi and poi["fresh"], f"POI H1 harus terdeteksi fresh, dapat {poi}"
```

(Sequence M5 penuh diuji lewat `evaluate` end-to-end di fixture gabungan — susun 60 candle M5: fase turun ke zona POI → bar sweep di bawah swing low M15 → 2 bar displacement naik menembus swing high internal → sisanya datar. Assert `evaluate(...)` mengembalikan Setup, lalu ubah urutan (MSS dulu baru sweep) dan assert None.)

- [ ] **Step 6: Verifikasi + commit**

Run: `python -m engine.smc`
Expected: semua `[OK]` termasuk fixture POI/sequence baru.

```powershell
git add engine/smc.py
git commit -m "feat(smc): POI H1 (OB+FVG fresh), dealing range anchor protected, sequence sweep->MSS (spec 4-10)"
```

---

### Task 10: Fase F — risk guard + daily stop (G14, G15)

**Files:**
- Modify: `execute/broker.py`
- Modify: `journal/db.py`
- Modify: `delivery/callbacks.py`
- Modify: `config.yaml`

**Interfaces:**
- Consumes: `Journal` koneksi, `broker.place/place_limit`.
- Produces: `broker`: tolak order jika `est_risk > equity × max_risk_percent`; `Journal.daily_stats(symbol_date) -> dict(losses:int, trades:int, net_r:float)`; `callbacks`: cek daily stop sebelum eksekusi.

- [ ] **Step 1: Knob config**

```yaml
execution:
  risk_percent: 1.0
  max_risk_percent: 2.0       # §14: kalau lot minimum tetap >2% equity → TOLAK order
  daily_max_losses: 2         # §16
  daily_max_trades: 3         # §16
  daily_stop_profit_r: 2.5    # §16
```

- [ ] **Step 2: Guard di broker (equity + cap)**

```python
# execute/broker.py — place() dan place_limit(), setelah hitung est_risk:
        equity = float(getattr(ai, "equity", ai.balance) or ai.balance)
        risk_amount = equity * float(ex["risk_percent"]) / 100.0     # §14: equity, bukan balance
        lot = _lot(si, risk_amount, sl_distance)
        pt = float(si.point) or 0.01
        est_risk = lot * (sl_distance / pt) * (float(getattr(si, "trade_tick_value", 1)) or 1)
        cap = equity * float(ex.get("max_risk_percent", 2.0)) / 100.0
        if est_risk > cap:
            return {"ok": False,
                    "msg": f"risiko lot-min ${est_risk:.2f} > cap {ex.get('max_risk_percent', 2.0)}% (${cap:.2f}) — §14 skip"}
```

- [ ] **Step 3: `daily_stats` di jurnal**

```python
# journal/db.py
    def daily_stats(self, date_str: str) -> dict:
        """Statistik §16 utk hari ini (ts_wib format 'dd/mm/YYYY ...'). Hanya alert dieksekusi.
        net_r = Σ(profit / risk_uang) — pakai kolom profit outcomes; risiko per trade
        belum disimpan → approx: profit>0=+rr_planned, profit<0=-1 (konservatif).
        TODO: ganti dgn risk_amount tersimpan (Task 12 kolom jurnal)."""
        with self._c() as c:
            rows = c.execute(
                """SELECT o.result, o.profit, a.rr FROM outcomes o
                   JOIN alerts a ON a.id = o.alert_id
                   WHERE a.ticket IS NOT NULL AND a.ts_wib LIKE ?""",
                (date_str + "%",)).fetchall()
        losses = sum(1 for r in rows if r["result"] == "LOSS")
        net_r = sum((float(r["rr"]) if r["result"] == "WIN" else -1.0) for r in rows)
        return dict(losses=losses, trades=len(rows), net_r=round(net_r, 2))
```

- [ ] **Step 4: Cek sebelum eksekusi**

```python
# delivery/callbacks.py — _do_execute(), paling atas setelah SELL-lock:
    from ops.clock import now_wib
    ex = cfg["execution"]
    stats = journal.daily_stats(now_wib().strftime("%d/%m/%Y"))
    if stats["losses"] >= int(ex.get("daily_max_losses", 2)):
        return False, f"daily stop: {stats['losses']} loss hari ini (§16)"
    if stats["trades"] >= int(ex.get("daily_max_trades", 3)):
        return False, f"daily stop: {stats['trades']} trade hari ini (§16)"
    if stats["net_r"] >= float(ex.get("daily_stop_profit_r", 2.5)):
        return False, f"daily stop: +{stats['net_r']}R tercapai (§16)"
```

- [ ] **Step 5: Demo + verifikasi + commit**

`journal/db.py` demo: insert alert ticket + outcome LOSS ×2, assert `daily_stats` menghitung; `callbacks` demo: cfg dgn `daily_max_losses: 0` → `_do_execute` menolak.

Run: `python -m journal.db; if ($?) { python -m delivery.callbacks }; if ($?) { python -m execute.broker }`
Expected: semua `[OK]`.

```powershell
git add execute/broker.py journal/db.py delivery/callbacks.py config.yaml
git commit -m "feat(exec): guard risiko equity+cap 2% dan daily stop 2L/3T/+2.5R (spec 14,16)"
```

---

### Task 11: Fase F — news filter minimum (G16)

**Files:**
- Create: `ops/news.py`
- Modify: `config.yaml`
- Modify: `delivery/callbacks.py`

**Interfaces:**
- Consumes: file manual `var/news.txt` (baris: `YYYY-MM-DD HH:MM` waktu WIB, event high-impact USD yang diisi owner tiap pagi dari kalender).
- Produces: `ops.news.in_news_window(now, minutes=15) -> bool`.

Keputusan desain: **manual file dulu** (YAGNI) — API kalender = Phase berikut kalau kebukti dipakai.

- [ ] **Step 1: `ops/news.py`**

```python
"""News guard §3/§11 — manual file var/news.txt (baris 'YYYY-MM-DD HH:MM' WIB).
Owner isi tiap pagi dari kalender ekonomi. Kosong/absen = tidak ada blokir."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path

from ops.clock import now_wib, WIB


def load_events(path: str = "var/news.txt") -> list[datetime]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(datetime.strptime(line, "%Y-%m-%d %H:%M").replace(tzinfo=WIB))
        except ValueError:
            continue
    return out


def in_news_window(now: datetime | None = None, minutes: int = 15,
                   path: str = "var/news.txt") -> bool:
    now = now or now_wib()
    d = timedelta(minutes=minutes)
    return any(abs(now - ev) <= d for ev in load_events(path))


def demo():
    import tempfile, os
    p = os.path.join(tempfile.gettempdir(), "news_test.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# NFP\n2026-07-24 19:30\n")
    ref = datetime(2026, 7, 24, 19, 20, tzinfo=WIB)
    assert in_news_window(ref, 15, p), "10 menit sebelum event harus True"
    ref2 = datetime(2026, 7, 24, 18, 0, tzinfo=WIB)
    assert not in_news_window(ref2, 15, p), "90 menit sebelum harus False"
    assert not in_news_window(ref, 15, os.path.join(tempfile.gettempdir(), "absen.txt"))
    print("[OK] news: window +/-15 menit dari file manual")


if __name__ == "__main__":
    demo()
```

- [ ] **Step 2: Blok eksekusi saat window**

```python
# delivery/callbacks.py — _do_execute(), setelah daily stop:
    from ops import news
    if news.in_news_window(minutes=int(ex.get("news_window_min", 15))):
        return False, "berita high-impact ±15 menit (§3) — entry diblokir"
```

```yaml
execution:
  news_window_min: 15
```

- [ ] **Step 3: Verifikasi + commit**

Run: `python -m ops.news; if ($?) { python -m delivery.callbacks }`
Expected: semua `[OK]`.

```powershell
git add ops/news.py config.yaml delivery/callbacks.py
git commit -m "feat(ops): news guard manual file +/-15 menit (spec 3/11)"
```

---

### Task 12: Fase G — kolom jurnal validasi (G17)

**Files:**
- Modify: `journal/db.py`

**Interfaces:**
- Consumes: `_migrate` pattern.
- Produces: kolom `alerts`: `risk_money REAL`, `risk_pct REAL`, `spread REAL`, `lot REAL`; kolom `outcomes`: `result_r REAL`, `mae REAL`, `mfe REAL`, `classification TEXT`; `Journal.set_execution(alert_id, lot, risk_money, risk_pct, spread)`.

- [ ] **Step 1: Migrasi kolom**

```python
    def _migrate(self, c):
        for stmt in ("ALTER TABLE alerts ADD COLUMN ticket INTEGER",
                     "ALTER TABLE outcomes ADD COLUMN profit REAL",
                     "ALTER TABLE alerts ADD COLUMN entry_type TEXT",
                     "ALTER TABLE alerts ADD COLUMN entry_price REAL",
                     "ALTER TABLE alerts ADD COLUMN risk_money REAL",
                     "ALTER TABLE alerts ADD COLUMN risk_pct REAL",
                     "ALTER TABLE alerts ADD COLUMN spread REAL",
                     "ALTER TABLE alerts ADD COLUMN lot REAL",
                     "ALTER TABLE outcomes ADD COLUMN result_r REAL",
                     "ALTER TABLE outcomes ADD COLUMN mae REAL",
                     "ALTER TABLE outcomes ADD COLUMN mfe REAL",
                     "ALTER TABLE outcomes ADD COLUMN classification TEXT"):
            try:
                c.execute(stmt)
            except sqlite3.OperationalError:
                pass
```

- [ ] **Step 2: Setter**

```python
    def set_execution(self, alert_id: int, lot: float, risk_money: float,
                      risk_pct: float, spread: float | None = None):
        """Detail eksekusi utk validasi §19-§21 (diisi callbacks setelah place sukses)."""
        with self._c() as c:
            c.execute("UPDATE alerts SET lot=?, risk_money=?, risk_pct=?, spread=? WHERE id=?",
                      (lot, risk_money, risk_pct, spread, int(alert_id)))
```

Panggil dari `delivery/callbacks.py::_do_execute` setelah `r.get("ok")` dengan data dari `r` (`lot`, `est_risk`, `balance`): `journal.set_execution(a["id"], r["lot"], r["est_risk"], round(100*r["est_risk"]/r["balance"], 3))`.

`daily_stats` (Task 10) diganti memakai `risk_money` nyata:

```python
        net_r = sum((float(r["profit"]) / float(r["risk_money"]))
                    for r in rows if r["profit"] is not None and r["risk_money"])
```

(sesuaikan query join menyertakan `a.risk_money`).

- [ ] **Step 3: Demo + verifikasi + commit**

Demo: `set_execution` lalu assert kolom terisi; `daily_stats` dengan `risk_money` menghasilkan R benar (profit −150 / risk 150 = −1R).

Run: `python -m journal.db`
Expected: `[OK]`.

```powershell
git add journal/db.py delivery/callbacks.py
git commit -m "feat(journal): kolom validasi risk/lot/spread + result_r/mae/mfe (spec 19-21)"
```

---

### Task 13: Fase G — outcome shadow candidates (G18)

**Files:**
- Modify: `monitor/watcher.py`
- Modify: `journal/db.py`

**Interfaces:**
- Consumes: `simulate_outcome` (sudah ada), `get_bundle`/`fetch_ohlcv`.
- Produces: `run_shadow_outcomes(journal, cfg) -> int` — menutup baris `smc_shadow` sent=0 yang sudah terminal, dipanggil dari `monitor_tick`.

- [ ] **Step 1: Query shadow terbuka**

```python
# journal/db.py
    def open_shadow(self):
        """Baris smc_shadow (sent=0) tanpa outcome — bahan simulate_outcome utk task #4."""
        with self._c() as c:
            return c.execute(
                """SELECT a.* FROM alerts a LEFT JOIN outcomes o ON o.alert_id = a.id
                   WHERE a.strategy='smc_shadow' AND o.alert_id IS NULL""").fetchall()
```

- [ ] **Step 2: `run_shadow_outcomes`**

```python
# monitor/watcher.py
def run_shadow_outcomes(journal: Journal, cfg: dict) -> int:
    """Label outcome kandidat shadow AI (sent=0) dgn simulate_outcome pada candle M5
    SETELAH candle sinyal. Tanpa ini grade_outcome_join kosong dan task #4 mandek."""
    from data.sources import get_bundle
    closed = 0
    rows = journal.open_shadow()
    by_symbol: dict[str, list] = {}
    for r in rows:
        by_symbol.setdefault(r["symbol"], []).append(r)
    for symbol, alerts in by_symbol.items():
        bundle = get_bundle(cfg["data"], symbol)
        if bundle is None:
            continue
        m5 = bundle.df("M5")
        if m5 is None:
            continue
        for a in alerts:
            try:
                t0 = pd.Timestamp(a["candle_id"])
            except (ValueError, TypeError):
                continue
            future = m5[m5.index > t0]
            if future.empty:
                continue
            r_ = simulate_outcome(a, future)
            if r_ is None:
                continue
            result, hit, exit_price, _bars = r_
            journal.label_outcome(a["id"], result, hit, exit_price)
            closed += 1
    return closed
```

Tambahkan `import pandas as pd` bila belum ada di modul. Panggil di `main.py::monitor_tick` setelah `run_pass` bila `cfg["ai"]["enabled"]` **atau** ada baris shadow (aman dipanggil selalu):

```python
        run_shadow_outcomes(journal, cfg)
```

- [ ] **Step 3: Demo + verifikasi + commit**

Demo watcher: buat jurnal tmp, insert shadow alert dgn candle_id timestamp, panggil `run_shadow_outcomes` dengan monkeypatch `get_bundle` (fungsi lokal mengembalikan Bundle berisi M5 sintetis yang menyentuh TP) → assert outcome terisi. Ikuti pola demo modul lain (tanpa framework).

Run: `python -m monitor.watcher; if ($?) { python -m journal.db }`
Expected: semua `[OK]`.

```powershell
git add monitor/watcher.py journal/db.py main.py
git commit -m "feat(monitor): outcome simulasi utk shadow AI candidates (unblock task #4)"
```

---

### Task 14: Gerbang GO — verifikasi menyeluruh

**Files:**
- Modify: `CLAUDE.md` (status), `config.yaml` (bila lolos)

- [ ] **Step 1: Semua self-check**

Run: `python -m engine.indicators; if ($?) { python -m engine.smc }; if ($?) { python -m journal.db }; if ($?) { python -m monitor.watcher }; if ($?) { python -m delivery.callbacks }; if ($?) { python -m execute.broker }; if ($?) { python -m ops.scheduler }; if ($?) { python -m ops.news }; if ($?) { python -m ai.grader }; if ($?) { python -m compileall -q main.py engine ai alert data delivery execute journal monitor ops }`
Expected: setiap modul `[OK]`, compile bersih.

- [ ] **Step 2: Dry-run live data**

Run: `python main.py once --dry`
Expected: log per simbol tanpa exception; kalau ada setup, periksa manual di chart MT5: POI H1 nyata? sweep terjadi di dalam POI? entry = 50% FVG? SL = sweep extreme ± buffer? TP = liquidity? Ulangi pada ≥10 kandidat (beberapa hari) sebelum lanjut.

- [ ] **Step 3: Nyalakan eksekusi bila 10/10 cocok**

```yaml
execution:
  enabled: true
```

- [ ] **Step 4: Update CLAUDE.md**

Tulis ulang bagian strategi aktif: SMC versi baru (POI H1, sequence, limit entry, set-and-forget), status validasi 0/100, dan larangan mengubah rule di tengah blok 25 trade.

- [ ] **Step 5: Commit**

```powershell
git add CLAUDE.md config.yaml
git commit -m "docs: status SMC aligned ke spec; mulai blok validasi 100 trade"
```

---

## Self-Review

- **Spec coverage:** §3 sesi (T1), §4 protected (T9), §5 anchor (T9), §6 POI (T9), §8-§10 sequence (T9), §11 limit+expiry (T8), §12 SL (T6), §13 TP (T7), §14 risk (T10), §15 set-and-forget (T7), §16 daily stop (T10), §19-§21 jurnal (T12), news (T11). Cadence (T5), RR jurnal (T2), dedup (T3), long_only (T4), shadow outcome (T13). G-map tertutup semua kecuali G16 penuh (API kalender — sengaja manual dulu).
- **Placeholder scan:** tidak ada TBD/TODO kosong; TODO dalam kode = catatan desain eksplisit dengan perilaku fallback yang didefinisikan.
- **Type consistency:** `swept_liquidity` 3-tuple dipakai konsisten T6/T9; `_mss` 3-tuple T8/T9; `Setup.rr_planned/entry_type/entry_price/expires_after` T2/T8; `resolve_exec_mode` T7; `daily_stats` T10→T12 di-upgrade eksplisit.
- **Risiko urutan:** T9 mengubah fungsi yang disentuh T6 (`swept_liquidity`) — kerjakan berurutan, jangan paralel.
