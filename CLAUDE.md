# CLAUDE.md — Momentum Alert Engine

Context file untuk sesi coding. Baca ini dulu sebelum ngerjakan apa pun di repo ini.
Dokumen ini disinkronkan dengan kode nyata per 2026-07-20 (bukan cita-cita lama).

## Apa ini
Alat sinyal untuk **day trader yang kerja full-time** (owner: software dev, trading sambilan).
Tujuan: kasih alert **hanya saat ada setup probabilitas tinggi** + plan siap pakai (entry/SL/TP) +
penjelasan singkat, biar owner nggak ketinggalan momentum tanpa mantengin chart.

**Human-in-the-loop tetap dipegang.** Tool TIDAK auto-execute. Tapi kode kini punya jalur
**one-tap execution**: owner tap `Eksekusi Limit` di Telegram → tool kirim pending LIMIT (DEMO) di
50% FVG, SL/TP diset, auto-cancel oleh monitor, auto-outcome. Keputusan tetap manusia, tiap trade.
SELL = eksperimen: di DEMO **boleh dieksekusi** (`allow_short: true`) untuk ngumpulin data short —
**wajib dikunci (`allow_short: false`) sebelum LIVE**. Lihat "Prinsip" #2.

## Prinsip yang mengikat SEMUA keputusan
1. **Rule yang trigger, AI yang narasi.** Trigger 100% deterministik & terukur. AI **tak pernah**
   menghitung/mengarang harga — hanya menjelaskan angka yang sudah dihitung engine. (AI masih STUB
   di config; `ai.enabled: false`.)
2. **Human-in-the-loop, one-tap.** Tak ada auto-execute / EA / bot yang entry sendiri. Alert masuk →
   owner mutuskan — kalau mau, tap `Eksekusi Limit` (manual, per trade, pending LIMIT di 50% FVG). Guardrail:
   - hanya chat_id owner yang diterima (pengirim lain ditolak diam-diam),
   - SELL = eksperimen: `allow_short: true` di DEMO (boleh exec, ngumpulin data) → set `false` utk LIVE,
   - `execution.enabled` bisa dimatikan → tool balik jadi alert-only murni,
   - `max_positions` = 1 per instrumen,
   - `daily_stop` (2 loss / 3 trade / +2.5R) hentikan trading harian.
3. **Ship tipis.** Bangun katedral setelah kapel jalan. Tiap fitur canggih tunggu gerbang fase.
4. **Jurnal otomatis.** Outcome di-track sendiri oleh monitor; beban manusia = 1 tap. Jurnal =
   forward-test (BUKAN backtester sebagai syarat rilis).

## Strategy canonical
Satu-satunya strategi aktif: **smc_canonical** — stateful, deterministik, M5 cadence.
Per-instrument state machine (IDLE → BIAS_OK → POI_TAGGED → SWEPT → MSS_CONFIRMED → PENDING_ORDER → FILLED/EXPIRED/CANCELLED),
persisten di SQLite. Entry LIMIT 50% FVG, set-and-forget (tanpa trailing/BE/partial).

## Owner & gaya trading
- Day trader, **bukan scalper**. Trigger TF **M5** (sweep/MSS/entry); struktur & bias dari **H1 + M15**.
- Regime/bias dari **H1** (BOS struktural).
- Strategi aktif = **smc_canonical** (stateful SMC). Entry di retrace ke 50% FVG, target liquidity lebar.

## Scope: XAU + BTC (dari data 547 trade asli, Jul–Des 2025, era trend_pullback)
Jurnal broker owner membuktikan edge NYATA tapi terkonsentrasi: overall 54% WR, PF 1.86,
expectancy +5.29/trade. **XAU = 66% WR** (80% dari total profit), **BTC ≈ 61% WR**.

**Prior kalibrasi dari data (bukan tebakan):**
- **Runner > scalp:** 74% profit XAU dari hold >12h (75% WR). Trade <1 jam nyaris impas. Tool harus
  dorong nahan/trail dengan target lebar (`tp_r: [1.5, 3.0, 5.0]` + trailing chandelier), bukan TP cepat.
- **Wed/Thu = hari lemah** (47–53% WR) → soft-filter naikkan ambang skor. Sen/Sel/Jum 71–77%.
- **Jangan over-filter sesi:** WR rata 62–68% di SEMUA sesi (Asia pun 67%). Alert 24 jam market buka.
  (Hanya subuh WIB 04–06 di-skip, sampel kecil.)
- **CAVEAT:** sampel 5 bln pasar bullish + 99% Buy (long-only, era trend_pullback). Pola mungkin berubah
  di regime berbeda. **Owner belum punya bukti edge short** —
  SELL v1 = eksperimen, ditandai di alert. Di DEMO boleh dieksekusi (`allow_short: true`) semata buat
  ngumpulin data short; **dikunci sebelum LIVE**. BUY = jalur utama (edge terbukti di XAU).

## Arsitektur (sesuai kode)
**Satu proses Python, 3 thread** (`main.py loop`):
- `scheduler` — tick tiap **M5 close** (:00/:05/…/:55), evaluasi semua instrumen (`ops/scheduler.py`).
- `monitor` — tiap 60s: auto-outcome + pending-lifecycle + dead-man's switch (`monitor/watcher.py`).
- `telegram-poll` — getUpdates long-poll, tanpa webhook (`delivery/callbacks.py`).

Tanpa gunicorn multi-worker → tanpa leader lock. State machine di-rebuild dari data saat boot
(tak ada state store terpisah).

**Modul (seam bersih, tiap file punya `demo()` self-check):**
- `data/sources.py` — OHLCV multi-TF dari MT5 (Valetax) via mt5linux RPyC. Satu koneksi dibagi 3
  thread, diserialisasi `MT5_LOCK` (RLock). Buang candle aktif di strategi.
- `engine/smc_canonical.py` — state machine SMC canonical + pure helpers (bias, POI, sweep, MSS, SL/TP/RR).
- `engine/indicators.py` — EMA, RSI (Wilder), ATR (Wilder RMA), swings, FVG, displacement. Pure pandas/numpy, tanpa lib `ta`.
- `engine/models.py` — `Bundle` (snapshot multi-TF) + `Setup` (hasil evaluate, dgn `.rr`) + `SmcState`.
- `alert/engine.py` — `decide()`: disiplin bias-ke-diam (tier → soft-day → skip-jam → dedup → cooldown → cap).
- `delivery/telegram.py` — format + kirim alert (HTML, urllib). `delivery/callbacks.py` — handle
  `/ambil` `/skip` `/eksekusi`.
- `journal/db.py` — SQLite (WAL). Tabel `alerts` · `outcomes` · `tags` · `config_kv`. 1 koneksi/thread.
- `monitor/watcher.py` — outcome sim + reconcile riil + pending lifecycle + deadman + daily stop.
- `execute/broker.py` — pending limit order + cancel, sizing lot dari equity risk%, demo guard, spread.
- `ops/clock.py` — waktu WIB + `is_market_open` (gold/forex tutup weekend, crypto 24/7).
- `ops/scheduler.py` — `next_tick` (boundary M30) + loop candle/interval.

## Strategy interface (kontrak inti)
```python
class SmcCanonical:
    name: str; version: str
    def evaluate(self, bundle, params, state: SmcState) -> tuple[Setup | None, SmcState]: ...
```
Strategi = **resep rule deterministik**, BUKAN prompt AI. State machine per instrumen, dipersistenkan ke SQLite `smc_state`.

### smc_canonical (satu-satunya, `version 1.0`)
Aktif: canonical SMC. Cadence M5, stateful, entry LIMIT di 50% FVG.
Deteksi: bias H1 → POI H1 (OB+FVG) → sweep M15/M5 di dalam POI → displacement + MSS M5 memecah swing pra-sweep.
Plan: SL = sweep extreme + 1× spread, TP = liquidity terdekat H1/M15, minimal RR 2.5R.
Eksekusi: set-and-forget (1 entry, 1 SL, 1 TP, tanpa trailing/BE/partial).
Guard: daily stop global (2 loss / 3 trade / +2.5R), sesi London 07:00-10:00 ∪ NY 12:00-15:30 UTC, filter berita ditunda (block 1 ditandai `news_filter_applied=0`).
Referensi: `strategy/xauusd-smc-trading-system.md`

## Eksekusi & monitor outcome (dua jalur)
Dipisah oleh ada/tidaknya `ticket` di baris alert:
- **TAK dieksekusi** → `monitor.run_pass` simulasi outcome vs TP referensi (ukur **kualitas sinyal**;
  tutup di sentuhan TP1, snapshot ~1 mnt). Juga mencakup shadow alert (`sent=0`).
- **Dieksekusi** (tap `Eksekusi Limit` → `broker.place_limit` set `order_ticket`) → `monitor.reconcile_executed` baca
  history deal broker → **PnL realized RIIL** saat posisi tutup (runner jujur).

Eksekusi = **pending LIMIT** di 50% FVG, auto-cancel oleh monitor. Trailing/BE/partial dimatikan untuk SMC (set-and-forget).

## Data source — MT5 Valetax via gmag11 container (WORKING 2026-07-18)
- Broker **Valetax** demo, server **`ValetaxIntl-Live2`**. **Simbol gold = `XAUUSD.vx`** (suffix `.vx`!),
  BTC = `BTCUSD.vx`. Config `instruments` HARUS pakai suffix `.vx`.
- Data via **mt5linux RPyC di `localhost:8001`**. `MetaTrader5("localhost",8001).initialize()`.
  MT5 kasih **semua TF native** (M30/H1/H4/D1) → tak perlu resample.
- **Volume tersedia** (tick volume) → Gate C punya sumber asli.
- **Fix penting (kalau container di-rebuild dari nol, ulangi):**
  1. gmag11 `start.sh` [7/7] harus jalan di **wine python**: `wine python -m mt5linux --host 0.0.0.0 -p 8001`
     (bukan `python3 ... -w` — mt5linux 1.0.3 tak punya `-w`). start.sh di-patch + di-mount via compose.
  2. **numpy di wine python harus <2** (`numpy==1.26.4`) — MetaTrader5 5.0.36 di-build utk numpy 1.x.
  3. rpyc **5.2.3** di linux python (mt5linux 1.0.3 pin), persist di /config/.local.
  Client tool pin: `mt5linux` + `rpyc==5.2.3` (samain server).
- Deploy: `/root/momentum-alerts/docker-compose.yml`, volume `./mt5-config:/config`.

## Catatan historis: goldexai (pihak ketiga) — SUDAH DITINGGALKAN
`goldexai.com` cuma di-HOST di VPS owner (owner root), APP + credential-nya milik orang lain. Saat
dev awal, pipeline sempat dites pakai bridge goldexai (`85.209.163.165` + token). **Itu sudah diganti**
ke MT5 Valetax milik owner sendiri (container gmag11 di atas). JANGAN reuse credential goldexai
(MT5 bridge/token, Telegram bot/chat, Gemini key) untuk apa pun. Repo ini ditulis ulang, bukan copy.

## Stack & konvensi
- Python 3.11+ (Dockerfile `python:3.11-slim`), SQLite (WAL), Telegram long-poll (urllib, tanpa lib).
- **Semua threshold = knob di `config.yaml`. Jangan hardcode.**
- **Cross-platform:** dev di Windows, deploy di Linux (Docker/Coolify). Jangan asumsi path Unix.
- **Model AI dari config + health-check saat startup** kalau AI dihidupkan (Phase 2). Jangan warisi
  model ID mati secara senyap.

## Entrypoint
- `python main.py once`       — satu evaluasi (tes/manual)
- `python main.py once --dry` — evaluasi tanpa kirim telegram & tanpa nulis jurnal
- `python main.py loop`       — produksi: scheduler(M5) + monitor(60s) + telegram-poll
- `python <modul>.py`         — tiap modul inti punya `demo()` self-check (jalankan langsung)

## Rencana berfase — JANGAN lompat gerbang
- **Phase 1 (sekarang):** `smc_canonical` · XAU+BTC · alert · one-tap pending-limit (DEMO) · jurnal
  auto-outcome + daily stop. News filter ditunda. Tanpa AI narator.
- **Phase 2:** AI narator (grounded, wajib sebut invalidasi) · digest mingguan · perkuat dead-man's switch · news filter.
- **Phase 3:** multi-pair lebih luas (kalau kebukti) · strategi pluggable (challenger) · shadow
  champion/challenger · backtest via replay candle (seam `data/sources.py` sudah disiapkan).
- **Sebelum LIVE:** matikan `allow_short`, review risk%, verifikasi timezone jurnal, git + backup DB, news diaktifkan.

## Failure modes yang harus selalu diingat
- **#1 owner berhenti isi jurnal** → auto-outcome + 1-tap menjawab ini. Kalau tag taken/skip berhenti
  masuk, edge nggak keukur → prioritas #1 perbaiki.
- **#2 deteksi ≠ mata owner** → kalibrasi skor dari data, tool = subset mata dulu (presisi > recall).
- **#3 eksekusi ≠ niat** → one-tap manual + guardrail (chat owner, SELL-lock, max_positions). Jangan
  longgarkan tanpa alasan data.
- **#6 over-engineering** → lawan nafsu bikin engine. Tiap fitur canggih tunggu gerbang.
- **#4 takut entry & #5 no-edge** → tool cuma MENGUNGKAP + memudahkan eksekusi, tak bisa memperbaiki
  psikologi. Jangan janjikan lebih.

## Dokumen terkait
- `PRD.md` — requirement lengkap (FR bernomor). ⚠️ mungkin ikut ketinggalan; verifikasi vs kode.
- `ARCHITECTURE.html` — blueprint + diagram. ⚠️ dokumen lama (era SMC), cek relevansi.
- `phase0/` — kit logging Phase 0 (`SETUP_LOG.md`, `jurnal-trade.csv`, `fills.csv`).
