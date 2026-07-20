# CLAUDE.md — Momentum Alert Engine

Context file untuk sesi coding. Baca ini dulu sebelum ngerjakan apa pun di repo ini.
Dokumen ini disinkronkan dengan kode nyata per 2026-07-20 (bukan cita-cita lama).

## Apa ini
Alat sinyal untuk **day trader yang kerja full-time** (owner: software dev, trading sambilan).
Tujuan: kasih alert **hanya saat ada setup probabilitas tinggi** + plan siap pakai (entry/SL/TP) +
penjelasan singkat, biar owner nggak ketinggalan momentum tanpa mantengin chart.

**Human-in-the-loop tetap dipegang.** Tool TIDAK auto-execute. Tapi kode kini punya jalur
**one-tap execution**: owner balas `/eksekusi` di Telegram → tool kirim market order (DEMO) dengan
lot dari risk%, SL/TP diset, lalu trailing + auto-outcome. Keputusan tetap manusia, tiap trade.
SELL = eksperimen: di DEMO **boleh dieksekusi** (`allow_short: true`) untuk ngumpulin data short —
**wajib dikunci (`allow_short: false`) sebelum LIVE**. Lihat "Prinsip" #2.

## Prinsip yang mengikat SEMUA keputusan
1. **Rule yang trigger, AI yang narasi.** Trigger 100% deterministik & terukur. AI **tak pernah**
   menghitung/mengarang harga — hanya menjelaskan angka yang sudah dihitung engine. (AI masih STUB
   di config; `ai.enabled: false`.)
2. **Human-in-the-loop, one-tap.** Tak ada auto-execute / EA / bot yang entry sendiri. Alert masuk →
   owner mutuskan → kalau mau, balas `/eksekusi` (manual, per trade). Guardrail di kode:
   - hanya chat_id owner yang diterima (pengirim lain ditolak diam-diam),
   - SELL = eksperimen: `allow_short: true` di DEMO (boleh exec, ngumpulin data) → set `false` utk LIVE,
   - `execution.enabled` bisa dimatikan → tool balik jadi alert-only murni,
   - `max_positions` per instrumen (v1 = 1).
3. **Ship tipis.** Bangun katedral setelah kapel jalan. Tiap fitur canggih tunggu gerbang fase.
4. **Jurnal otomatis.** Outcome di-track sendiri oleh monitor; beban manusia = 1 tap. Jurnal =
   forward-test (BUKAN backtester sebagai syarat rilis).

## Owner & gaya trading
- Day trader, **bukan scalper**. Entry TF **M30 (utama) + H1**; di bawah M30 = noise/jebakan, dihindari.
- Regime/bias dari **H4 + Daily**.
- Strategi aktif = **trend_pullback** (lihat bawah). Follow the trend, tahan runner, target lebar.

## Scope: XAU + BTC (dari data 547 trade asli, Jul–Des 2025)
Jurnal broker owner membuktikan edge NYATA tapi terkonsentrasi: overall 54% WR, PF 1.86,
expectancy +5.29/trade. **XAU = 66% WR** (80% dari total profit), **BTC ≈ 61% WR**. NAS100/USDJPY
= coinflip (47–49%), ETH = bocor. Maka **v1 = `XAUUSD.vx` + `BTCUSD.vx`** (lihat `config.instruments`);
pair lain hanya nyusul kalau kebukti. Pembunuh #5 (no-edge) sudah terjawab untuk gold & BTC.

**Prior kalibrasi dari data (bukan tebakan):**
- **Runner > scalp:** 74% profit XAU dari hold >12h (75% WR). Trade <1 jam nyaris impas. Tool harus
  dorong nahan/trail dengan target lebar (`tp_r: [1.5, 3.0, 5.0]` + trailing chandelier), bukan TP cepat.
- **Wed/Thu = hari lemah** (47–53% WR) → soft-filter naikkan ambang skor. Sen/Sel/Jum 71–77%.
- **Jangan over-filter sesi:** WR rata 62–68% di SEMUA sesi (Asia pun 67%). Alert 24 jam market buka.
  (Hanya subuh WIB 04–06 di-skip, sampel kecil.)
- **CAVEAT:** sampel 5 bln pasar bullish + 99% Buy (long-only). Pola "nahan=menang" itu trend-
  continuation bull; belum tentu berlaku di range/bear. **Owner belum punya bukti edge short** —
  SELL v1 = eksperimen, ditandai di alert. Di DEMO boleh dieksekusi (`allow_short: true`) semata buat
  ngumpulin data short; **dikunci sebelum LIVE**. BUY = jalur utama (edge terbukti).
- TODO: konfirmasi timezone timestamp jurnal (WIB/GMT/server) sebelum pakai prior sesi/jam.
  `config.source_tz` masih placeholder — daily candle ter-stamp 07:00, verifikasi dulu.

## Arsitektur (sesuai kode)
**Satu proses Python, 3 thread** (`main.py loop`):
- `scheduler` — tick tiap M30 close (:00/:30 WIB + offset), evaluasi semua instrumen (`ops/scheduler.py`).
- `monitor` — tiap 60s: auto-outcome + reconcile executed + trailing + dead-man's switch (`monitor/watcher.py`).
- `telegram-poll` — getUpdates long-poll, tanpa webhook (`delivery/callbacks.py`).

Tanpa gunicorn multi-worker → tanpa leader lock. State machine di-rebuild dari data saat boot
(tak ada state store terpisah).

**Modul (seam bersih, tiap file punya `demo()` self-check):**
- `data/sources.py` — OHLCV multi-TF dari MT5 (Valetax) via mt5linux RPyC. Satu koneksi dibagi 3
  thread, diserialisasi `MT5_LOCK` (RLock). Buang candle aktif di strategi.
- `engine/indicators.py` — EMA, RSI (Wilder), ATR (Wilder RMA). Pure pandas/numpy, tanpa lib `ta`.
- `engine/models.py` — `Bundle` (snapshot multi-TF) + `Setup` (hasil evaluate, dgn `.rr`).
- `engine/strategy.py` — `Strategy` Protocol + `TrendPullback` (strategi aktif).
- `alert/engine.py` — `decide()`: disiplin bias-ke-diam (tier → soft-day → skip-jam → dedup → cooldown → cap).
- `delivery/telegram.py` — format + kirim alert (HTML, urllib). `delivery/callbacks.py` — handle
  `/ambil` `/skip` `/eksekusi`.
- `journal/db.py` — SQLite (WAL). Tabel `alerts` · `outcomes` · `tags` · `config_kv`. 1 koneksi/thread.
- `monitor/watcher.py` — outcome sim + reconcile riil + trailing chandelier + deadman.
- `execute/broker.py` — market order, sizing lot dari risk%, modify SL (BE/trail), partial close.
- `ops/clock.py` — waktu WIB + `is_market_open` (gold/forex tutup weekend, crypto 24/7).
- `ops/scheduler.py` — `next_tick` (boundary M30) + loop candle/interval.

## Strategy interface (kontrak inti)
```python
class Strategy(Protocol):
    name: str; version: str
    def evaluate(self, bundle, params) -> Setup | None: ...
```
Strategi = **resep rule deterministik**, BUKAN prompt AI. Interface ini seam pluggable buat nanti.

### trend_pullback (aktif, `version 0.2`)
Follow trend → tunggu pullback ke EMA → konfirmasi momentum. Deterministik penuh.
- **Gate A — Regime (veto keras, H4+D1):** BULL kalau `price4 > EMA200(H4)` & `EMA20 > EMA50 (H4)` &
  `D1 close > EMA50(D1)`. BEAR = cermin. Selain itu → diam. BULL→BUY, BEAR→SELL (eksperimen).
- **Gate B — Setup (per entry TF M30/H1):** uptrend TF (`EMA20>EMA50`, `price>EMA50`) → pullback
  turun nyentuh EMA20 (`pullback_atr`×ATR) → candle bounce konfirmasi (`close>open` & `close>EMA20`).
- **Gate C — Volume (skor, bukan veto):** `volume > vol_mult × avg20`.
- **Skor:** base 2 + close kuat (≥0.66 body) + RSI searah/zona + volume. `tier=HIGH_CONF` kalau
  skor ≥ `high_conf_score` (4). `min_tier` di alert = HIGH_CONF (bias-ke-diam).
- **Plan:** SL = min(swing, price − 1.5×ATR) − buffer. TP = `[1.5, 3.0, 5.0]×risk`. Entry zone =
  pullback (EMA20..price). RR dihitung dari TP1.

Area iterasi utama = kalibrasi skor/threshold (semua di `config.yaml`, jangan hardcode).

> SMC top-down (liquidity→sweep→POI) **tidak dipakai** — di-drop demi rule yang lebih deterministik
> & gampang dikalibrasi. Jangan hidupkan lagi tanpa keputusan owner.

## Eksekusi & monitor outcome (dua jalur)
Dipisah oleh ada/tidaknya `ticket` di baris alert:
- **TAK dieksekusi** → `monitor.run_pass` simulasi outcome vs TP referensi (ukur **kualitas sinyal**;
  tutup di sentuhan TP1, snapshot ~1 mnt).
- **Dieksekusi** (`/eksekusi` → `broker.place` set `ticket`) → `monitor.reconcile_executed` baca
  history deal broker → **PnL realized RIIL** saat posisi tutup (runner jujur).

Trailing = **chandelier** (`extreme_sejak_entry ∓ mult×ATR`), ratchet-only, clamp jarak-min broker.
Order runner dikirim **tanpa TP keras** (`trailing:true`) → exit lewat SL yang naik. Sekali, saat
trail pertama kunci SL ≥ BE: **bank separuh** (`partial_on_lock`). Semua knob di `config.execution`.

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
- **⚠️ Belum ada git di repo ini** (per 2026-07-20). ~1.5k baris kode koheren tanpa version control —
  init + commit baseline sebelum refactor besar.
- **Model AI dari config + health-check saat startup** kalau AI dihidupkan (Phase 2). Jangan warisi
  model ID mati secara senyap.

## Entrypoint
- `python main.py once`       — satu evaluasi (tes/manual)
- `python main.py once --dry` — evaluasi tanpa kirim telegram & tanpa nulis jurnal
- `python main.py loop`       — produksi: scheduler(M30) + monitor(60s) + telegram-poll
- `python <modul>.py`         — tiap modul inti punya `demo()` self-check (jalankan langsung)

## Rencana berfase — JANGAN lompat gerbang
- **Phase 1 (sekarang):** `trend_pullback` · XAU+BTC · alert · one-tap execute (DEMO) · jurnal
  auto-outcome · trailing. Tanpa AI narator.
- **Phase 2:** AI narator (grounded, wajib sebut invalidasi) · digest mingguan · perkuat dead-man's switch.
- **Phase 3:** multi-pair lebih luas (kalau kebukti) · strategi pluggable (challenger) · shadow
  champion/challenger · backtest via replay candle (seam `data/sources.py` sudah disiapkan).
- **Sebelum LIVE:** matikan `allow_short`, review risk%, verifikasi timezone jurnal, git + backup DB.

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
