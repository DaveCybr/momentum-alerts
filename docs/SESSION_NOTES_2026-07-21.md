# Session Notes — SMC Canonical Deploy & Debug (2026-07-21)

Catatan sesi untuk pemulihan konteks. Dibaca bersama `CLAUDE.md`,
`docs/superpowers/specs/2026-07-26-smc-canonical-migration-design.md`,
dan `docs/superpowers/plans/2026-07-26-smc-canonical-migration.md`.

## Status: LIVE di VPS, execution OFF (alert-only)

### Deploy
- **VPS:** `root@31.97.66.91` (hostname srv1818945)
- **GitHub:** `github.com/DaveCybr/momentum-alerts` branch `smc-canonical`
- **Path VPS:** `/root/momentum-alerts/` (compose) · app di `/root/momentum-alerts/app/`
- **Repo clone VPS:** `/root/repo-momentum/` (git pull dari sini → cp ke app/)
- **Containers:** `momentum-tool` (engine) + `momentum-mt5` (gmag11 Wine bridge)
- **Deploy flow:** push GitHub → `cd /root/repo-momentum && git pull` → `cp -r * ../momentum-alerts/app/` → `docker compose up -d --build tool`

### MT5 Account (Valetax DEMO)
- Login `372062346` · Server `ValetaxIntl-Live2` · Balance ~$966
- **Password akun MT5:** `@Tayooleng87` (BEDA dari password VNC `886f250c13f32d9c5746`)
- Symbols: `XAUUSD.vx` + `BTCUSD.vx` (suffix `.vx` wajib)

## Bug MT5 bridge yang SUDAH diperbaiki (kalau rebuild container, ULANGI)

Root cause `initialize()` hang / `result expired`:
1. **numpy** — Linux-side numpy 2.4.6 di `/config/.local/` mengalahkan numpy win32 1.26.4 di Wine.
   Fix: `start.sh` pin `numpy==1.26.4` di wine python, DAN hapus numpy Linux:
   `rm -rf /config/.local/lib/python3.11/site-packages/numpy*`
2. **plumbum** — `plumbum 2.x` pecah RPyC handshake. Fix: pin `plumbum==1.7.0` di
   wine python + linux python (`start.sh` + kedua container).
3. **MT5 auto-login** — `initialize()` tanpa arg hang non-interaktif. Fix dua lapis:
   - `start.sh` terminal launch: `/login:372062346 /password:@Tayooleng87 /server:ValetaxIntl-Live2`
   - `data/sources.py` `_connect()` baca env `MT5_LOGIN/MT5_PASSWORD/MT5_SERVER` →
     `m.initialize(login=, password=, server=)`
   - `docker-compose.yml` tool env: `MT5_LOGIN/MT5_PASSWORD/MT5_SERVER`
4. **MT5 build 6033** enum timeframe non-standar (`H1=16385`, `D1=16408`) — sudah aman
   karena `_fetch()` pakai `getattr(m, "TIMEFRAME_H1")`, bukan angka hardcoded.

Verifikasi konek: buat script `from mt5linux import MetaTrader5; m=MetaTrader5(host="mt5",port=8001); m.initialize(login=..,password=..,server=..)` di container tool.

## Kondisi pasar saat sesi (21 Jul 2026, ~19:00 UTC / 02:00 WIB)
- **XAU:** BEARISH, harga ~4082 di premium 98%, protected 4084 (harga uji level ini —
  tembus=bias mati, reject=setup sell lahir). Belum ada OB sell valid (displacement lemah).
- **BTC:** BULLISH, harga ~66700 premium 86%, protected 65022. 3 POI di 64200-65200,
  harga masih di ATAS semua POI → nunggu retrace.
- Semua state=IDLE, belum ada alert (kondisi normal — market di premium, nunggu retrace).

## Gap analysis vs playbook (sudah diperbaiki 4 dari 9)
FIXED (commit e62ff58): #1 TP priority chain (H1 ext > PDH/PDL > M15), #7 order/position
ticket lifecycle, #2 POI re-check saat pending, #3 session-end cancel pending.
DEFERRED (belum urgent): #4 spread abnormal check, #5 news filter, #6 NY-close daily stop,
#8 MAE/MFE recording, #9 shadow sent=0 distinction.

## Next steps (belum dikerjakan)
1. Activation gate: verifikasi ≥10 alert vs spec §18, lalu `execution.enabled: true` +
   `demo_verified: true` di config.
2. Kumpulkan blok 25 trade → evaluasi expectancy/PF/rule-adherence.
3. Deferred gaps kalau perlu.

## Cara analisa live (script scratch di C:\Users\queen\AppData\Local\Temp\opencode\)
Pattern: tulis script python → scp ke VPS → docker cp ke momentum-tool → exec.
Contoh: `xau_check.py`, `btc_check.py`, `sl_tp_analysis.py`, `xau_ascii.py`,
`dump_data.py` (JSON→chart lokal `render_chart.py`).

## Aturan SMC entry (7 gate, sudah dikonfirmasi owner paham)
① Bias BEARISH/BULLISH + protected alive
② Harga di zona benar (premium utk sell, discount utk buy)
③ OB H1 + FVG terbentuk dari displacement kuat (≥1.5×ATR)
④ Retrace ke POI
⑤ SWEEP: wick M5 ambil liquidity M15 SAAT harga di dalam POI
⑥ MSS: displacement M5 + FVG, pecah swing pra-sweep
⑦ Entry LIMIT 50% FVG **M5** · SL = sweep extreme ± spread · TP = liquidity H1 · RR ≥ 2.5R · dalam sesi

Sesi UTC: London 07:00-10:00, NY 12:00-15:30. Log/alert/jurnal pakai WIB (UTC+7).
