# Phase 0 — Log Setup Manual (2 minggu, tanpa kode)

**Tujuan:** buktikan dua hal SEBELUM ngoding apa pun —
1. **Kamu beneran konsisten nyatet?** (uji pembunuh #1: males jurnal)
2. **Setup-mu cukup konsisten/terdefinisi buat dikodekan?** (uji pembunuh #2: deteksi ≠ matamu)

Sekalian mulai kumpulin bukti expectancy (pembunuh #5).

## Cara pakai
Tiap kali kamu **lihat setup SMC** (yang biasanya kamu perhatiin), catat SATU baris di tabel bawah.
Nggak usah rapi — 30 detik. Isi kolom outcome belakangan pas trade kelar. Target: lakukan tiap hari
trading selama **14 hari**.

Kolom:
- **Waktu** — tgl + jam WIB, TF (M30/H1)
- **Pair**
- **Bias** — D1 & H4 (▲/▼/ranging)
- **Liquidity** — pool apa yang tersapu (EQL/EQH, PDH/PDL, low/high sesi)
- **POI** — jenis + level (OB/FVG/S-D @ harga)
- **Arah** — BUY/SELL (harus searah bias)
- **Plan** — entry / SL / TP
- **Konviksi** — A+ / A / B (seberapa yakin)
- **Diambil?** — YA/TIDAK (jujur — ini uji "takut entry" #4)
- **Hasil** — WIN/LOSS/BE + berapa R (isi belakangan)
- **Catatan** — kenapa ambil/skip, apa yang bikin ragu

## Tabel

| Waktu | Pair | Bias D1/H4 | Liquidity | POI | Arah | Entry/SL/TP | Konv. | Diambil? | Hasil (R) | Catatan |
|---|---|---|---|---|---|---|---|---|---|---|
| 18/07 20:00 H1 | XAUUSD | ▲/▲ | sweep low Asia 3344 | OB H1 @3345–48 | BUY | 3347/3334/3363-77-92 | A+ | YA | WIN +1.8R | contoh — hapus |
|  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |  |

*(tambah baris sesuai kebutuhan)*

---

## Review mingguan (isi tiap Minggu malam)

**Minggu 1**
- Jumlah setup dicatat: ___
- Berapa hari trading kamu lewat tanpa nyatet: ___
- Berapa diambil / berapa skip: ___ / ___
- Win-rate yang diambil: ___
- Jujur: pola setup-ku konsisten atau berubah-ubah tiap kali? ___

**Minggu 2**
- (idem)

---

## GATE go/no-go (setelah 14 hari)

Lanjut ke Phase 1 (mulai ngoding) **hanya jika SEMUA ya:**

- [ ] **Konsisten:** nggak lewat >2 hari trading tanpa nyatet. → kalau gagal: kamu nggak akan pakai
      jurnal tool-nya. **STOP proyek** — hemat 3 bulan.
- [ ] **Terdefinisi:** setup-mu ngikutin pola berulang yang bisa ditulis jadi rule (bias→liquidity→
      sweep→POI→konfirmasi kelihatan konsisten). → kalau gagal: beresin definisi dulu, jangan ngoding
      sesuatu yang kamu sendiri nggak konsisten.
- [ ] **Ada sinyal edge:** dari yang diambil, hasilnya nggak jelek-jelek amat (bukan syarat ketat,
      cuma sanity check). → kalau semua LOSS: strategimu, bukan tool-nya, yang perlu dibenahi dulu.

**Lolos semua → kabarin, kita mulai Phase 1 (skeleton + data layer MT5 + `smc_top_down`).**
