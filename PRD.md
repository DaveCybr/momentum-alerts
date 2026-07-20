# PRD — Momentum Alert Engine

> Working title. Alat sinyal momentum untuk trader yang punya pekerjaan full-time.
> Status: Draft v0.1 · Owner: (kamu) · Terakhir update: 2026-07-18

---

## 1. Masalah & Tujuan

**Masalah nyata:** Owner adalah software developer (kerja 8 jam/hari) yang juga trading. Dia
kehilangan momentum karena tidak bisa memantau chart terus-menerus, dan ragu memasang limit
entry. Akibatnya setup bagus lewat begitu saja.

**Tujuan produk:** Memberi tahu owner **hanya saat ada setup probabilitas tinggi**, dengan plan
matang siap pakai (entry, SL, TP sudah dihitung), plus penjelasan singkat yang bisa di-judge
dalam 5 detik dari HP — tanpa harus buka chart.

**Filosofi inti (non-negotiable):**
- **Rule yang menarik pelatuk. AI yang menerjemahkan.** Trigger 100% deterministik &
  bisa diukur. AI tidak pernah menghitung/mengarang harga — ia hanya menjelaskan angka yang
  sudah dihitung engine dan membaca konteks (news/sentimen).
- **Human-in-the-loop.** Tool tidak eksekusi. Owner tetap pengambil keputusan akhir.
- **Kualitas alert > jumlah alert.** Alert fatigue adalah kegagalan produk, bukan sekadar UX.

## 2. Non-Goals (yang SENGAJA tidak dibangun)

- ❌ Auto-execute / EA / bot yang buka posisi sendiri.
- ❌ AI yang memprediksi harga atau memilih entry. (Riset: LLM halusinasi di angka finansial.)
- ❌ Backtester penuh sebagai syarat rilis. (Forward-test via jurnal alert — lihat §9.)
- ❌ Web dashboard yang berat / landing page marketing. (MVP: alert ke HP + admin minimal.)
- ❌ Multi-user / SaaS. Ini alat pribadi dulu.

## 3. Pengguna & Konteks

Satu user (owner). **Gaya trading: day trader, bukan scalper.** Entry timeframe minimal **M30–H1**;
di bawah itu dianggap noise & jebakan (dihindari). Bias/regime dari **H4 + Daily**. Perangkat utama
konsumsi: **HP (Telegram)**. Waktu perhatian: rendah & terputus (lagi kerja) — tapi setup M30/H1
kebentuk dalam hitungan puluhan menit, jadi masih sempat ditanggapi. Alert harus: (a) jarang
(realistis 0–3/hari), (b) padat, (c) actionable dalam sekali baca.

## 4. Prinsip Desain (diturunkan dari riset)

| Prinsip | Dasar |
|---|---|
| Trigger = confluence multi-kondisi | Alert 2+ faktor konfirmasi: false-positive 45% → <20% (riset MIT) |
| Urutan gate: **regime → momentum → volume** | Resep baku high-probability setup |
| Disiplin alert: cooldown, dedup, tier, cap harian | >100 alert/hari → +22% trade impulsif |
| AI grounded & structured output | Structured-gen 87–98% sukses; grounding hilangkan halusinasi |
| Jurnal = forward-test | 90% strategi bagus di backtest gagal out-of-sample (CFA) |
| Spread masuk hitungan SL/TP | XAUUSD spread 12–50 sen, material di scalping |

## 5. Arsitektur Sistem

```
                 ┌─────────────────────────────────────────────────┐
   MT5 Bridge ──▶│ 1. DATA LAYER (multi-pair)                      │
 (fallback:      │    fetch OHLCV M30/H1/H4/D1 · closed-candle only │
  TwelveData,    └───────────────────────┬─────────────────────────┘
  yfinance)                              │
                 ┌───────────────────────▼─────────────────────────┐
                 │ 2. RULE ENGINE (deterministik, per instrumen)    │
                 │    Gate A: REGIME  (HTF bias H1 — non-negotiable)│
                 │    Gate B: MOMENTUM(confluence score 0–N)        │
                 │    Gate C: VOLUME  (konfirmasi partisipasi)  ★baru│
                 │    → SETUP? hitung entry/SL/TP/lot (incl spread) │
                 └───────────────────────┬─────────────────────────┘
                                         │ (hanya jika SETUP valid)
                 ┌───────────────────────▼─────────────────────────┐
                 │ 3. ALERT ENGINE (disiplin)                       │
                 │    dedup candle · cooldown · tier · cap harian   │
                 │    → LOLOS filter?                               │
                 └───────────────────────┬─────────────────────────┘
                                         │
                 ┌───────────────────────▼─────────────────────────┐
                 │ 4. AI NARATOR (grounded, structured)             │
                 │    input: angka dari engine + news/sentimen      │
                 │    output: penjelasan + tier confidence          │
                 │    ⚠ DILARANG menghitung/ubah harga              │
                 └───────────────────────┬─────────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              ▼                          ▼                           ▼
    5. DELIVERY (Telegram)     6. JURNAL (SQLite)          (chart image opsional)
       teks + plan + narasi       simpan tiap alert +
                                   kolom: diambil? hasil?
```

## 6. Functional Requirements

### 6.1 Data Layer
- **FR-D1** Ambil OHLCV multi-timeframe (M30, H1, H4, D1) per instrumen dari **MT5 Bridge** (sumber
  kebenaran, harga broker asli termasuk spread). Entry di M30/H1; H4/D1 untuk regime.
- **FR-D2** Fallback otomatis ke Twelve Data → yfinance bila bridge down. Log sumber yang dipakai.
- **FR-D3** Selalu buang candle terakhir yang masih aktif — analisa hanya di closed candle.
- **FR-D4** Instrumen dari config (daftar pair). **v1 = `XAUUSD` saja** (data owner: edge di gold).
  Kapabilitas multi-pair tetap ada di config untuk Phase 3, tapi tidak diaktifkan di v1.
- **FR-D5** Gating jam pasar per instrumen (gold/forex sessions). Skip saat tutup.

### 6.2 Rule Engine (trigger deterministik)
- **FR-R1** **Gate A — Regime:** bias dari **H4 + Daily** asli. Long hanya saat HTF bullish, short
  hanya saat bearish, ranging → blokir semua. (Non-negotiable, veto keras.)
- **FR-R2** **Gate B — Momentum:** confluence score. Faktor: BoS searah bias, HTF align, liquidity
  sweep, candle konfirmasi (pin bar), ADX>threshold, EMA align, sesi London/NY. Threshold →
  SETUP / HIGH_CONF / WAIT. Semua threshold = **knob kalibrasi** (config, bukan hardcode).
- **FR-R3** **Gate C — Volume (BARU):** setup hanya valid bila ada konfirmasi volume/partisipasi
  di atas baseline. Bila data volume tidak tersedia dari sumber, degradasi ke proxy (mis. range
  expansion / ATR spike) dan tandai `volume_source`.
- **FR-R4** **Veto overextension:** tolak bila harga > k×ATR dari EMA acuan (anti kejar harga).
- **FR-R5** Hitung entry, SL, TP1/2/3, lot dari ATR — **SL/TP wajib memperhitungkan spread** dari
  bridge (bukan mid-market).
- **FR-R6** Output setup = objek terstruktur (signal, score, entry, sl, tp, rr, alasan per-gate).

**Strategi = plug-in (bisa diganti-ganti):**
- **FR-R7** Strategi diakses lewat satu interface: `evaluate(bundle, params) -> Setup | None`. Engine
  memuat strategi aktif **by name dari config**. Ganti strategi = ganti config, pipeline tak disentuh.
- **FR-R8** Dua level eksperimen: (a) **tuning** — threshold/params via config, strategi sama;
  (b) **strategi baru** — file baru yang implement interface. Keduanya tanpa mengubah engine/alert/AI.
- **FR-R9** **Shadow mode:** strategi non-aktif tetap dievaluasi tiap candle & dicatat ke jurnal
  (tanpa alert). Beberapa strategi jalan paralel di data pasar identik → bandingkan win-rate
  apple-to-apple (champion/challenger). Ini cara menemukan strategi yang cocok — bukan tebak feeling.
- **FR-R10** Interface fungsi-murni yang sama membuat strategi **backtestable**: replay candle historis
  lewat `evaluate()`. (Fase 3 — gratis dari desain, bukan modul terpisah.)
- **FR-R11** **Cara mendefinisikan strategi = 3 level**, semua deterministik (BUKAN prompt AI):
  (1) *tuning* param via config; (2) *resep deklaratif* (YAML) yang menyusun gate + faktor + bobot —
  "form" strategi; (3) *custom* Python `evaluate()` untuk logika yang tak terwakili resep. Level 2
  didukung setelah Gate momentum di-refactor jadi **registry faktor** (fungsi kecil per faktor:
  `bos()`, `ema_align()`, `adx()`, …). (Level 1 & 3 = MVP; Level 2 = Fase 2.)
- **FR-R12** **Prompt AI ≠ strategi.** Prompt milik narator, fixed, melayani semua strategi. Strategi
  tak pernah didefinisikan lewat teks bebas ke AI. *Escape hatch:* "AI-as-decider" boleh diuji HANYA
  sebagai strategi challenger di **shadow mode** (masuk jurnal, tak pernah kirim alert langsung) —
  biar datanya yang membuktikan layak/tidak, bukan asumsi.
- **FR-R13** **Strategi boleh stateful (state machine).** Strategi menyimpan state per-instrumen antar
  candle — dibutuhkan untuk setup berurutan seperti SMC: `liquidity → sweep → POI → konfirmasi`.
  Interface `evaluate()` tetap sama; state hidup di dalam objek strategi. Ada timeout/reset bila
  struktur rusak atau bias HTF flip.
- **FR-R14** **Strategi utama MVP = `smc_top_down`** (gaya owner): top-down D1/H4 → deteksi liquidity
  pool (EQH/EQL, PDH/PDL, hi/lo sesi) → tunggu sweep (tembus + close balik) → cari POI H1/M30
  (OB/FVG/supply-demand) searah tren → konfirmasi (CHoCH/rejection) → SETUP. Entry **selalu searah
  HTF** (Gate A veto). Reuse primitif SMC goldexai (`detect_smc_structure`: swing/OB/FVG/BOS/CHoCH).
- **FR-R15** **Skor kualitas POI** (titik subjektif SMC): mesin mendeteksi SEMUA OB/zone, tapi hanya
  yang berskor tinggi (fresh/belum ditest, konfluen FVG, nempel level HTF, ukuran wajar) yang jadi
  alert. Ambang skor = knob kalibrasi, dituning lewat jurnal (kalau tool sering pilih POI yang owner
  skip → ketatkan). Ini area iterasi utama.

### 6.3 Alert Engine (disiplin — inti pembeda produk)
- **FR-A1** **Dedup:** satu candle → maksimal satu evaluasi. Anti-dobel lintas worker (atomic
  reserve + leader lock, lihat NFR).
- **FR-A2** **Cooldown:** setelah alert untuk instrumen+arah tertentu, jeda minimal T sebelum alert
  sejenis boleh keluar lagi. Default diskala ke TF: **~2 jam / beberapa candle H1** (bukan menit —
  ini day-trading), kecuali regime berubah.
- **FR-A3** **Cap harian:** batas maks alert/hari per instrumen (default 5–10 total). Kelebihan →
  ditahan, dicatat di log ("N alert di-suppress").
- **FR-A4** **Tiering:** setiap alert diberi prioritas (mis. HIGH_CONF vs NORMAL) yang menentukan
  cara kirim (HIGH_CONF → push langsung; NORMAL → boleh digabung/diam).
- **FR-A5** Suppression tidak boleh senyap: selalu `log()` apa yang ditahan & alasannya.

### 6.4 AI Narator (grounded, structured)
- **FR-N1** Input ke AI: **hanya** angka yang sudah dihitung engine (indikator, gate results,
  entry/SL/TP) + berita/sentimen instrumen terkait. AI tidak menerima mandat menghitung harga.
- **FR-N2** Output = JSON terstruktur: `{ ringkasan_1_kalimat, kenapa_sekarang, risiko_utama[],
  konteks_news, tier_confidence }`. Divalidasi schema; retry bila tidak sesuai.
- **FR-N3** **Guard anti-halusinasi:** bila AI mengembalikan harga yang berbeda dari angka engine,
  abaikan harga AI — angka engine yang otoritatif. Narasi hanya teks penjelas.
- **FR-N4** AI opsional/degradable: bila API gagal/timeout, alert tetap terkirim tanpa narasi
  (rule-engine adalah tulang punggung, AI adalah lapisan penjelas).
- **FR-N5** Provider (Claude/Gemini) auto-detect dari bentuk key. **Model ID wajib dari config**
  dan diverifikasi valid saat startup (health-check) — hindari kegagalan senyap.

### 6.5 Delivery
- **FR-DL1** Kirim alert ke Telegram: teks plan (harga, entry, SL, TP1/2/3, RR, tier) + narasi AI.
- **FR-DL2** Chart image opsional (bisa dimatikan untuk hemat latency/kuota).
- **FR-DL3** Format ringkas, 1 layar HP, keputusan owner jadi biner (ambil / skip).

### 6.6 Jurnal & Feedback Loop (forward-test)
- **FR-J1** Setiap evaluasi (alert terkirim, di-suppress, maupun shadow) disimpan ke SQLite dengan
  snapshot lengkap + tag **`strategy_name` · `strategy_version` · `params`** — supaya win-rate bisa
  dibandingkan per strategi (syarat FR-R9 shadow mode).
- **FR-J2** Owner bisa menandai tiap alert: **`diambil` / `skip`**, dan hasilnya **`menang / kalah
  / BE`** (via balasan Telegram atau halaman admin minimal).
- **FR-J3** Ringkasan mingguan: berapa alert, berapa diambil, win-rate, dan estimasi "seandainya
  semua diambil". Ini metrik yang menentukan tool worth dilanjut atau tidak (§9).

## 7. Data & Instrumen

- Sumber utama: **MT5 Bridge** (URL+token sudah ada di infra lama). Fallback: Twelve Data, yfinance.
- Instrumen MVP: **XAUUSD-ONLY.** Data 547 trade asli owner (Jul–Des 2025) membuktikan edge
  terkonsentrasi di gold (XAU 66% WR = 80% profit; pair lain coinflip). Arsitektur tetap
  config-driven multi-pair, tapi v1 fokus gold. Pair lain nyusul hanya kalau kebukti edge.
- **Prior kalibrasi dari data:** favor runner (hold >12h = 74% profit) → target lebar & dorong nahan;
  Wed/Thu hari lemah (soft-filter); jangan over-filter sesi (menang di semua sesi). Caveat: sampel
  bull + long-only → nahan lama hanya jika HTF align; belum ada bukti edge short.
- Timeframe analisa: **M30 (utama) + H1** dengan bias **H4 + Daily**. Day-trading, bukan scalping —
  di bawah M30 dihindari (noise/jebakan). Scheduler evaluasi **selaras candle M30 close** (:00 & :30),
  bukan tiap 60 detik.
- Persistensi: SQLite di persistent volume (resolver: `/data` → volume → lokal), seperti infra lama.

## 8. Non-Functional Requirements

- **NFR-1 Reliabilitas anti-dobel:** dedup candle + atomic DB reserve + **leader lock lintas-platform**
  (bukan `fcntl`-only — harus jalan di Windows lokal & Linux prod).
- **NFR-2 Degradasi anggun:** kegagalan AI / sumber data / Telegram tidak menjatuhkan sistem;
  masing-masing punya fallback & log.
- **NFR-3 Observability:** health-check startup (bridge reachable? model ID valid? DB writable?),
  heartbeat scheduler, dan log suppression alert.
- **NFR-4 Konfigurasi, bukan hardcode:** semua threshold, cooldown, cap, spread, daftar instrumen,
  model ID → config/env. Ada knob kalibrasi.
- **NFR-5 Modular:** pisahkan `data/`, `engine/`, `alert/`, `ai/`, `delivery/`, `journal/`,
  `web/` — bukan monolit satu file.
- **NFR-6 Cross-platform:** dev di Windows, deploy di Linux (Coolify). Tidak ada asumsi path Unix.

## 9. Metrik Keberhasilan (satu-satunya yang penting)

Setelah 2–4 minggu jalan (forward-test via jurnal):
1. **Recall (yang penting):** dari setup yang owner *seharusnya* ambil, berapa % yang tool ping?
   (Tool gagal kalau melewatkan setup bagus.)
2. **Precision / kualitas:** dari alert yang bunyi, berapa % yang owner beneran ambil? (Proxy: kalau
   <~40% diambil → terlalu berisik, ketatkan threshold.)
3. **Volume alert:** rata-rata alert/hari harus di rentang sehat (target ≤5–10). >20/hari = fatigue.
4. **Trust:** owner masih membuka & membaca alert setelah 3 minggu (bukan mute).

> Kalau metrik #1 rendah → kendorkan gate. Kalau #2/#3 buruk → ketatkan. Kalibrasi berbasis data
> jurnal, bukan feeling. Inilah "walk-forward" versi human-in-the-loop.

## 10. Reuse dari goldexai (peta konkret)

| Modul target | Sumber di goldexai | Aksi |
|---|---|---|
| `data/bridge.py` | `app.py` `fetch_*_from_bridge`, `fetch_ohlcv_primary` | Ekstrak, rapikan |
| `engine/indicators.py` | `xauusd_ai_analyst.py` `calculate_indicators` | Reuse |
| `engine/structure.py` | `detect_smc_structure` | Reuse |
| `engine/signal.py` | `detect_berkah_signal`, `run_multi_timeframe_scan` | Reuse + **tambah Gate C volume** |
| `alert/engine.py` | (dedup/leader lock tersebar di `app.py`) | Ekstrak + **tambah cooldown/tier/cap** |
| `ai/narrator.py` | `vision_analyzer.py`, `call_claude_api` | Reuse pola, **paksa grounded/structured**, ganti model ID |
| `delivery/telegram.py` | `send_telegram_message`, format signal | Reuse |
| `journal/db.py` | schema `signals`, `trade_monitors` | Reuse + **tambah tabel jurnal/outcome** |
| — | sisi TypeScript, `detect_gainzalgo_signal`, template sampah | **Buang** |

## 11. Scope MVP & Fase

- **Fase 1 (MVP):** Data (MT5 + fallback) → Rule engine strategi **`smc_top_down`** (state machine:
  liquidity → sweep → POI + skor → konfirmasi, veto follow-trend) → Alert engine (dedup + cooldown +
  cap) → Telegram → Jurnal manual. AI narator boleh minimal/stub.
  *Cut line:* tanpa AI pun harus sudah berguna — rule-engine adalah produk minimum.
- **Fase 2:** AI narator grounded penuh + news/sentimen. Ringkasan mingguan otomatis.
- **Fase 3:** Kalibrasi berbasis jurnal, tuning per-instrumen, tambah pair. **Shadow-mode
  champion/challenger** antar strategi + backtest via replay `evaluate()`.

## 12. Open Questions / perlu diputuskan nanti

- Sumber & definisi **volume** untuk XAUUSD (spot gold sering tanpa volume asli) — pakai tick
  volume dari MT5 atau proxy range/ATR? (Gate C bergantung ini.)
- Cara owner menandai outcome: balas Telegram (bot handler) vs halaman admin. Pilih yang paling
  minim friksi.
- Model AI final + biaya per-alert (narasi tiap alert = biaya token). Batasi ke HIGH_CONF saja?
- Definisi operasional "setup yang seharusnya diambil" untuk mengukur recall (§9.1).

---

*Prinsip penutup: energi ke hal yang menentukan hidup-mati (trigger benar + disiplin alert +
jurnal), bukan ke yang keliatan (dashboard, chart cantik). Rule yang nyetir, AI penumpang cerewet.*
