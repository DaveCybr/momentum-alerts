# Rulebook SMC (Smart Money Concepts)

**Catatan penting:** SMC tidak punya standar universal. Istilah berbeda antarmentor. Supaya konsisten, gunakan satu aturan mekanis, dokumentasikan, lalu backtest minimal 100–200 setup per pair dan sesi. Jangan menganggap OB/FVG otomatis menyebabkan harga berbalik.

---

# 1. Hierarki analisis

Gunakan tiga lapisan timeframe:

| Fungsi | Swing | Intraday | Scalping |
|---|---:|---:|---:|
| Bias utama | Weekly/Daily | Daily/H4 | H4/H1 |
| Struktur kerja | Daily/H4 | H1/M15 | M15/M5 |
| Entry | H4/H1 | M5/M1 | M1 |

Contoh intraday:

1. **Daily/H4:** arah, dealing range, lokasi premium/discount.
2. **H1/M15:** target likuiditas dan struktur internal.
3. **M5/M1:** sweep, displacement, MSS/CHoCH, retracement entry.

Jangan mencampur struktur. **CHoCH M1 tidak otomatis membalik trend H4.**

---

# 2. Swing high dan swing low valid

## Fractal dasar

Dengan sensitivitas 2 candle:

- **Swing High:** high candle tengah lebih tinggi daripada high dua candle kiri dan dua candle kanan.
- **Swing Low:** low candle tengah lebih rendah daripada low dua candle kiri dan dua candle kanan.

Ini hanya mendeteksi pivot, belum menentukan apakah pivot tersebut **protected/structural**.

## Structural high/low

Dalam struktur bullish:

- **Structural high:** high yang ditembus dengan displacement sehingga mencetak HH.
- **Protected low:** low signifikan terakhir yang menjadi asal impuls pemecah structural high.
- Low kecil di dalam impuls disebut **internal low**, bukan protected low.

Dalam struktur bearish:

- **Structural low:** low yang ditembus dengan displacement sehingga mencetak LL.
- **Protected high:** high signifikan terakhir yang menjadi asal impuls pemecah structural low.
- High kecil di dalam impuls disebut **internal high**.

### Rule protected low bullish

Low dapat dianggap protected jika:

1. Terbentuk sebelum impuls bullish.
2. Impuls tersebut menembus swing high eksternal yang sudah terkonfirmasi.
3. Penembusan memakai **body close**, bukan wick saja.
4. Impuls memperlihatkan displacement.
5. Belum ada candle yang close di bawah low itu.

Kebalikannya berlaku untuk protected high bearish.

## Strong dan weak high/low

Dalam bullish trend:

- **Protected low = strong low**, karena mempertahankan struktur.
- **High terbaru = weak high**, karena secara teoritis menjadi target buy-side liquidity.

Dalam bearish trend:

- **Protected high = strong high**.
- **Low terbaru = weak low**.

“Strong” bukan berarti pasti bertahan. Itu hanya level invalidasi struktur saat ini.

---

# 3. Struktur pasar valid

## Bullish structure

Urutan ideal:

```text
Protected Low → HH → HL → BOS ke atas → HH
```

Syarat BOS bullish:

1. Level yang ditembus adalah **confirmed structural swing high**, bukan micro-high acak.
2. Candle **close** di atas swing high.
3. Ada displacement atau ekspansi range yang jelas.
4. Penembusan tidak langsung seluruhnya ditolak.
5. Struktur dinilai pada timeframe yang sama.

## Bearish structure

```text
Protected High → LL → LH → BOS ke bawah → LL
```

Syarat BOS bearish sama, dibalik.

## Wick versus close

Gunakan definisi tetap:

- **Wick melewati level, close kembali:** liquidity sweep.
- **Body close melewati level:** kandidat BOS/MSS.
- **Close tipis tanpa displacement:** penembusan lemah; tunggu follow-through atau retest.
- **Close kuat lalu harga bertahan:** penembusan lebih valid.

Jangan mengganti aturan close/wick setelah melihat hasil trade.

---

# 4. Displacement valid

Displacement merupakan bukti agresi order, bukan sekadar candle hijau/merah besar.

Kandidat displacement kuat:

1. Candle body relatif besar dibanding candle sebelumnya.
2. Body minimal sekitar **60–70% dari total range candle**.
3. Range lebih besar daripada rata-rata 10–20 candle terakhir; ATR dapat dipakai.
4. Menutup melewati level struktur atau liquidity pool.
5. Meninggalkan FVG/imbalance.
6. Diikuti continuation, bukan langsung engulf berlawanan.
7. Terjadi setelah sweep atau dari area HTF penting.

Aturan objektif opsional:

```text
Range candle displacement ≥ 1.5 × ATR(14)
Body / total range ≥ 0.65
```

Angka tersebut bukan hukum pasar; gunakan sebagai filter backtest.

---

# 5. BOS, CHoCH, dan MSS

## BOS

BOS biasanya berarti **continuation**.

Bullish BOS:

- Trend sudah bullish.
- Harga close di atas structural high/weak high.
- Protected low tetap utuh.

Bearish BOS: kebalikannya.

## CHoCH

CHoCH merupakan **peringatan pertama** bahwa order flow berubah, bukan konfirmasi reversal penuh.

Bullish-to-bearish CHoCH:

1. Sebelumnya terbentuk HH dan HL.
2. Harga gagal melanjutkan atau menyapu buy-side liquidity.
3. Harga turun dengan displacement.
4. Candle close di bawah **protected low** yang menghasilkan HH terakhir.

Jika hanya low internal yang pecah, itu biasanya **internal CHoCH**, bukan pembalikan struktur eksternal.

## MSS

Banyak trader menggunakan MSS sebagai CHoCH yang disertai liquidity sweep dan displacement.

Rule bullish MSS high-probability:

1. Konteks HTF bullish atau harga berada di HTF discount/demand.
2. Sell-side liquidity disapu.
3. Harga bereaksi cepat ke atas.
4. Terjadi displacement bullish.
5. Candle close di atas internal swing high terakhir.
6. Impuls meninggalkan FVG.
7. Entry saat retrace ke FVG/OB; invalidasi di bawah sweep low.

## Konfirmasi reversal lebih kuat

Jangan mengandalkan satu CHoCH. Urutan yang lebih kuat:

```text
Liquidity sweep
→ displacement
→ CHoCH/MSS
→ retracement bertahan
→ BOS searah reversal
```

CHoCH menunjukkan kemungkinan perubahan. BOS setelahnya mengonfirmasi struktur baru lebih baik.

---

# 6. Liquidity

Likuiditas adalah area tempat order kemungkinan terkumpul, bukan garis ajaib.

## External liquidity

Berada di luar dealing range:

- Previous day/week high atau low.
- Major swing high/low.
- Equal highs/equal lows.
- Session high/low.
- Range high/low.

Biasanya menjadi target utama.

## Internal liquidity

Berada di dalam range:

- Minor swing high/low.
- Trendline liquidity.
- Internal equal highs/lows.
- Inducement.
- High/low retracement kecil.

Biasanya diambil dalam perjalanan menuju external liquidity.

## Liquidity sweep valid

1. Ada pool likuiditas yang jelas sebelum kejadian.
2. Wick atau harga melampaui level.
3. Harga segera ditolak kembali ke dalam range.
4. Ada displacement berlawanan.
5. Struktur internal pecah setelah sweep.
6. Sweep terjadi di lokasi HTF yang relevan.

Wick tanpa displacement/structure shift hanya sapuan, belum sinyal entry.

---

# 7. Inducement

Inducement adalah struktur atau level yang mengundang trader masuk terlalu cepat dan menempatkan stop di lokasi yang mudah diambil.

Contoh bullish:

1. Harga mulai naik dari demand/OB.
2. Membentuk minor HL yang terlihat rapi.
3. Trader membeli dan menaruh SL di bawah minor HL.
4. Harga turun menyapu minor HL.
5. Harga kemudian bergerak bullish dari POI sebenarnya.

## Rule identifikasi

Inducement yang masuk akal biasanya:

- Berada sebelum POI utama.
- Tampak sebagai support/resistance obvious.
- Berisi minor swing atau equal highs/lows.
- Belum menyentuh origin utama.
- Menawarkan entry “terlalu mudah”.
- Likuiditasnya diambil sebelum displacement sesungguhnya.

Inducement sangat subjektif. Jangan melabeli setiap minor swing sebagai inducement setelah harga bergerak. Tandai sebelum kejadian.

---

# 8. Order Block valid

## Bullish OB

Candle bearish terakhir—atau cluster kecil—sebelum displacement bullish yang:

1. Menyapu sell-side liquidity atau berasal dari discount/HTF demand.
2. Menyebabkan BOS/MSS.
3. Meninggalkan FVG.
4. Belum dimitigasi sepenuhnya.
5. Memiliki origin jelas.

## Bearish OB

Candle bullish terakhir sebelum displacement bearish yang memenuhi rule sebaliknya.

## Yang bukan OB berkualitas

- Setiap candle lawan warna sebelum kenaikan/penurunan.
- Candle yang tidak menghasilkan BOS/MSS.
- Candle di tengah sideways noise.
- Candle sudah disentuh berulang kali.
- Candle tanpa displacement.
- Candle melawan konteks HTF tanpa liquidity event.

## Refinement OB

Pilihan zona:

- **Full range:** high sampai low candle OB.
- **Body:** open sampai close.
- **50% mean threshold:** titik tengah OB.
- **Open candle:** entry agresif.

Gunakan satu metode konsisten. Jangan mempersempit zona setelah trade hampir menyentuh SL.

## High-probability OB checklist

Nilai satu poin:

- Sejalan bias HTF.
- Berada di premium/discount yang tepat.
- Mendahului liquidity sweep.
- Menghasilkan displacement.
- Memecah struktur.
- Meninggalkan FVG.
- Fresh/first mitigation.
- Berada dekat session timing relevan.
- Target liquidity jelas.
- Memberikan invalidasi logis dan R:R memadai.

Skor contoh:

- **8–10:** A setup.
- **6–7:** B setup.
- **≤5:** skip.

Batas skor harus diuji, bukan dipercaya mentah.

## Invalidation OB

Bullish OB biasanya invalid jika candle close tegas di bawah low OB atau protected low. Bearish OB kebalikannya. Wick singkat dapat menjadi sweep; tetap harus mengikuti rule yang sudah dipilih.

---

# 9. Supply dan demand valid

## Demand

Area base sebelum rally impulsif:

```text
Drop–Base–Rally
Rally–Base–Rally
```

## Supply

Area base sebelum drop impulsif:

```text
Rally–Base–Drop
Drop–Base–Drop
```

## Base berkualitas

1. Base singkat, sekitar 1–6 candle.
2. Candle base relatif kecil/kompresi.
3. Departure cepat dan kuat.
4. Departure memecah struktur atau menghilangkan opposing zone.
5. Ada imbalance.
6. Zona fresh.
7. Sedikit waktu di zona menunjukkan order imbalance lebih besar.

## Penentuan zona

Bullish demand:

- **Distal line:** wick terendah base.
- **Proximal line:** bagian body/open terdekat dengan harga departure.

Bearish supply:

- **Distal line:** wick tertinggi base.
- **Proximal line:** bagian body/open terdekat dengan departure.

## Freshness

- **Fresh:** belum pernah diretest.
- **Mitigated:** pernah disentuh.
- **Consumed:** disentuh berulang atau ditembus dalam.

Secara umum, setiap retest dapat mengonsumsi resting orders. First touch biasanya lebih baik daripada touch ketiga/keempat.

## Supply/demand high-probability

- Lokasi HTF tepat.
- Departure kuat.
- Memecah struktur.
- Mengambil opposing liquidity.
- Fresh.
- Base sempit.
- Sedikit overlap.
- Ruang menuju opposing zone cukup besar.
- Sejalan target liquidity.

---

# 10. FVG/imbalance valid

Bullish FVG menggunakan tiga candle:

```text
High candle 1 < Low candle 3
```

Area gap berada antara high candle 1 dan low candle 3.

Bearish FVG:

```text
Low candle 1 > High candle 3
```

## FVG berkualitas

1. Terbentuk karena displacement.
2. Displacement memecah struktur.
3. Terletak dalam POI HTF atau beririsan dengan OB.
4. Belum penuh terisi.
5. Sejalan bias.
6. Target liquidity masih terbuka.

FVG di tengah range tanpa konteks biasanya lemah.

## Consequent encroachment

Titik 50% FVG sering digunakan sebagai refinement. Itu bukan kewajiban harga untuk menyentuh atau berbalik.

## Inversion FVG

Jika FVG ditembus dan harga menerima sisi seberangnya, area tersebut dapat bertindak sebagai resistance/support terbalik. Minta retest dan displacement, jangan entry hanya karena nama pola.

---

# 11. Premium, discount, dealing range

Tentukan dealing range menggunakan dua swing eksternal yang jelas:

- Bullish leg: protected low sampai external high.
- Bearish leg: protected high sampai external low.

Kemudian:

- **0–50%:** discount.
- **50%:** equilibrium.
- **50–100%:** premium.

Rule sederhana:

- Cari buy di discount.
- Cari sell di premium.
- Hindari buy di premium kecuali continuation kuat dan struktur timeframe lebih tinggi mendukung.
- Hindari sell di discount dengan alasan sama.

Pemilihan anchor adalah sumber subjektivitas terbesar. Anchor harus berasal dari swing yang menciptakan BOS, bukan swing kecil pilihan bebas.

---

# 12. Entry model mekanis

## Model bullish

1. Bias HTF bullish.
2. Harga berada di HTF discount/demand/OB.
3. Sell-side liquidity jelas tersedia.
4. Harga menyapu liquidity tersebut.
5. Muncul bullish displacement.
6. Candle close di atas internal structural high: MSS.
7. Displacement meninggalkan FVG atau bullish OB.
8. Tunggu retracement pertama.
9. Entry pada FVG/OB sesuai rule.
10. SL di bawah sweep low atau invalidation POI.
11. TP pertama di internal liquidity.
12. TP utama di external buy-side liquidity.

## Model bearish

Semua rule dibalik.

## Entry agresif versus konservatif

**Agresif:**

- Limit order di HTF OB/FVG.
- SL lebih kecil.
- Win rate biasanya lebih rendah.
- Bisa masuk sebelum konfirmasi.

**Konservatif:**

- Tunggu sweep, MSS, retrace.
- Entry sering terlewat.
- Konfirmasi lebih kuat.
- SL dapat lebih logis.

Jangan mencampur statistik kedua model.

---

# 13. Kondisi no-trade

Skip jika:

- Harga berada tepat di tengah dealing range.
- Bias HTF bertentangan antar-timeframe.
- Tidak ada liquidity target jelas.
- Tidak ada displacement.
- Struktur hanya pecah memakai wick.
- POI telah disentuh berkali-kali.
- Entry mengejar candle impulsif.
- R:R menuju target pertama terlalu kecil.
- Spread tinggi.
- Beberapa menit sebelum berita berdampak tinggi.
- Market sedang sangat tipis atau sideways.
- Setup hanya terlihat setelah diperbesar/diperkecil berulang kali.

---

# 14. Risk management

Struktur sempurna tetap bisa gagal.

Rule aman:

- Risiko **0,25–1%** per trade.
- SL berdasarkan invalidasi, bukan nominal uang.
- Sesuaikan lot berdasarkan jarak SL.
- Target awal minimal sekitar **1:2**, tetapi expectancy lebih penting.
- Batasi kerugian harian, misalnya **2R**.
- Setelah dua atau tiga loss berturut-turut, berhenti untuk sesi tersebut.
- Jangan memindahkan SL lebih jauh.
- Jangan menambah posisi pada trade rugi tanpa sistem teruji.

Rumus position sizing:

```text
Risiko uang = Ekuitas × Persentase risiko
Ukuran posisi = Risiko uang ÷ Nilai kerugian pada jarak SL
```

---

# 15. Checklist final sebelum entry

```text
[ ] Bias HTF jelas
[ ] Dealing range dan premium/discount jelas
[ ] External liquidity target jelas
[ ] Harga berada di POI HTF
[ ] Liquidity sweep terjadi
[ ] Displacement terjadi
[ ] MSS/CHoCH memakai body close
[ ] Level yang pecah benar-benar structural
[ ] FVG/OB fresh tersedia
[ ] Entry bukan mengejar harga
[ ] SL berada di titik invalidasi
[ ] R:R ke target realistis
[ ] Tidak dekat berita besar
[ ] Risiko sesuai batas
```

Setup terbaik bukan yang punya label SMC terbanyak. Setup terbaik adalah yang **definisinya tetap, dapat ditandai sebelum harga bergerak, dan mempunyai expectancy positif berdasarkan jurnal/backtest**.
