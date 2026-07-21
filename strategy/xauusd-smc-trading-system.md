# Sistem Trading XAUUSD SMC Intraday

## 1. Tujuan dan batas sistem

Sistem ini digunakan untuk trading demo XAUUSD intraday dengan satu model entry yang tetap selama fase validasi 100 trade. Tujuan fase awal bukan mengejar target keuntungan harian, melainkan membuktikan bahwa aturan menghasilkan expectancy positif dan dapat dieksekusi secara konsisten.

Aturan inti:

- Instrumen: XAUUSD saja.
- Sesi: London dan New York.
- Bias dan POI: H1.
- Pemetaan likuiditas: M15.
- Sweep, displacement, MSS, dan entry: M5.
- Satu model: reversal dari POI H1 setelah sweep dan MSS M5.
- Satu posisi aktif; tanpa layering.
- Eksekusi set-and-forget.
- Validasi awal: 100 trade demo.

---

## 2. Definisi timeframe

### H1 — bias dan POI

H1 digunakan untuk:

- Menentukan struktur eksternal.
- Menentukan protected high atau protected low.
- Menentukan dealing range.
- Menentukan premium, equilibrium, dan discount.
- Menentukan target likuiditas eksternal.
- Menentukan POI utama.

### M15 — peta likuiditas

M15 digunakan untuk:

- Menandai equal highs dan equal lows.
- Menandai session high dan session low.
- Menandai internal swing high dan swing low.
- Menentukan liquidity pool yang dapat disapu di dalam atau dekat POI H1.
- Menentukan target likuiditas setelah entry.

### M5 — konfirmasi dan entry

M5 digunakan untuk:

- Mengonfirmasi liquidity sweep.
- Mengidentifikasi displacement.
- Mengonfirmasi MSS.
- Menentukan FVG dan OB entry.
- Menentukan entry dan SL.

Struktur dari timeframe berbeda tidak boleh dicampur. MSS M5 hanya trigger entry, bukan bukti bahwa struktur H1 telah berbalik.

---

## 3. Jadwal trading

Trading hanya dilakukan selama jendela sesi yang sudah ditentukan di platform berdasarkan waktu broker dan perubahan DST.

Jendela operasional:

- London: tiga jam pertama setelah London open.
- New York: tiga setengah jam pertama setelah New York open.
- Tidak membuka posisi di luar jendela tersebut.
- Tidak membuka posisi baru 15 menit sebelum sampai 15 menit sesudah berita high-impact USD.
- Pending order dibatalkan ketika memasuki jendela berita.
- Posisi yang sudah terbuka tetap mengikuti SL dan TP awal.

Jam WIB tidak ditulis permanen karena pergeseran DST dapat mengubah waktu sesi. Kalender ekonomi dan jam sesi harus diperiksa sebelum trading.

---

## 4. Bias H1

### Bias bullish

Bias H1 bullish hanya jika semua kondisi berikut terpenuhi:

1. Struktur H1 telah menghasilkan BOS bullish dengan body close di atas structural high.
2. Protected low H1 belum ditembus body close.
3. Ada buy-side liquidity H1 atau M15 yang masih terbuka sebagai target.
4. POI buy berada di discount dari dealing range H1 yang aktif.

### Bias bearish

Bias H1 bearish hanya jika semua kondisi berikut terpenuhi:

1. Struktur H1 telah menghasilkan BOS bearish dengan body close di bawah structural low.
2. Protected high H1 belum ditembus body close.
3. Ada sell-side liquidity H1 atau M15 yang masih terbuka sebagai target.
4. POI sell berada di premium dari dealing range H1 yang aktif.

### No-trade bias

Tidak ada trade jika:

- Struktur H1 tidak jelas.
- Harga berada dekat equilibrium tanpa POI yang jelas.
- Tidak ada target likuiditas yang jelas.
- Bias memerlukan pencampuran swing dari timeframe berbeda.
- Dealing range tidak dapat ditentukan sebelum harga bergerak.

---

## 5. Dealing range H1

Gunakan impuls H1 terakhir yang menghasilkan BOS eksternal.

- Bullish dealing range: protected low sampai external high yang dibentuk impuls.
- Bearish dealing range: protected high sampai external low yang dibentuk impuls.
- Area 0–50% dianggap discount.
- Titik 50% dianggap equilibrium.
- Area 50–100% dianggap premium.

Anchor tidak boleh diganti setelah setup terbentuk untuk membuat POI terlihat valid.

---

## 6. POI H1 valid

Sistem hanya menggunakan OB H1 yang memiliki FVG atau imbalance dari displacement yang sama.

### Bullish POI

POI bullish valid jika semua syarat berikut terpenuhi:

1. Berada di discount dealing range H1.
2. Berasal dari bearish candle terakhir atau base kecil sebelum displacement bullish.
3. Displacement tersebut menghasilkan BOS bullish H1 atau mengambil liquidity lalu menghasilkan struktur bullish yang jelas.
4. Displacement meninggalkan bullish FVG.
5. OB dan FVG beririsan atau berdekatan sebagai satu area reaksi.
6. Zona masih fresh; belum pernah diretest sejak displacement.
7. Target buy-side liquidity masih terbuka.

### Bearish POI

POI bearish valid jika semua syarat berikut terpenuhi:

1. Berada di premium dealing range H1.
2. Berasal dari bullish candle terakhir atau base kecil sebelum displacement bearish.
3. Displacement tersebut menghasilkan BOS bearish H1 atau mengambil liquidity lalu menghasilkan struktur bearish yang jelas.
4. Displacement meninggalkan bearish FVG.
5. OB dan FVG beririsan atau berdekatan sebagai satu area reaksi.
6. Zona masih fresh; belum pernah diretest sejak displacement.
7. Target sell-side liquidity masih terbuka.

### Batas POI

- Gunakan full range candle OB H1 sebagai zona awal.
- M15 boleh digunakan untuk mempersempit batas zona, tetapi origin H1 tidak boleh diganti.
- POI invalid jika candle H1 close menembus distal edge zona sebelum trigger entry.
- POI yang sudah disentuh sebelumnya tidak digunakan selama validasi awal.

---

## 7. Liquidity pool M15

Sebelum harga memasuki POI, tandai liquidity pool M15 yang jelas:

- Equal highs atau equal lows.
- Swing high atau swing low yang terlihat jelas.
- Asia high atau Asia low.
- London high atau London low untuk setup New York.
- Previous day high atau previous day low.
- Internal high atau low yang menjadi tempat stop entry prematur.

Liquidity pool valid harus sudah ditandai sebelum disapu. Level tidak boleh diberi label liquidity setelah reversal terjadi.

Prioritas target:

1. Previous day high atau low.
2. Session high atau low.
3. Equal highs atau equal lows.
4. Structural swing M15.
5. Internal swing M15.

---

## 8. Liquidity sweep M5

### Bullish sweep

Sweep bullish valid jika:

1. Harga berada di dalam atau menyentuh bullish POI H1.
2. Harga M5 melewati sell-side liquidity M15 yang sudah ditandai.
3. Candle M5 close kembali di atas level liquidity atau candle berikutnya segera merebut kembali level tersebut.
4. Setelah sweep muncul displacement bullish.

### Bearish sweep

Sweep bearish valid jika:

1. Harga berada di dalam atau menyentuh bearish POI H1.
2. Harga M5 melewati buy-side liquidity M15 yang sudah ditandai.
3. Candle M5 close kembali di bawah level liquidity atau candle berikutnya segera merebut kembali level tersebut.
4. Setelah sweep muncul displacement bearish.

Wick tanpa displacement dan MSS bukan trigger entry.

---

## 9. Displacement M5

Displacement valid harus memenuhi semua kondisi berikut:

1. Bergerak berlawanan dari arah sweep dan sesuai bias trade.
2. Rasio body terhadap total range candle minimal 65%.
3. Total range candle minimal 1,5 kali ATR(14) M5 pada saat candle close.
4. Meninggalkan FVG M5.
5. Menembus structural swing M5 dengan body close.

Jika displacement terdiri dari beberapa candle, setidaknya satu candle harus memenuhi rasio body dan ekspansi range. Rangkaian tersebut harus membentuk gerakan satu arah dengan overlap kecil dan menghasilkan MSS.

---

## 10. MSS M5

### Bullish MSS

Bullish MSS valid jika:

1. Sell-side liquidity telah disapu di POI H1.
2. Harga bergerak bullish dengan displacement.
3. Candle M5 close di atas structural swing high M5 terakhir yang terbentuk sebelum sweep.
4. Penembusan meninggalkan bullish FVG.

### Bearish MSS

Bearish MSS valid jika:

1. Buy-side liquidity telah disapu di POI H1.
2. Harga bergerak bearish dengan displacement.
3. Candle M5 close di bawah structural swing low M5 terakhir yang terbentuk sebelum sweep.
4. Penembusan meninggalkan bearish FVG.

Penembusan wick saja tidak valid. Pecah micro-swing di dalam satu impuls tanpa struktur yang jelas tidak dihitung sebagai MSS.

---

## 11. Entry M5

### Zona entry

Entry dilakukan pada retracement pertama ke area overlap antara:

- FVG M5 yang dibentuk displacement MSS; dan
- OB M5 asal displacement tersebut.

Jika FVG dan OB tidak overlap, gunakan FVG sebagai zona entry. Metode ini harus tetap selama satu blok evaluasi 25 trade.

### Harga entry

- Entry limit ditempatkan pada 50% FVG M5.
- Jika harga tidak retrace ke 50% FVG, trade dilewatkan.
- Tidak melakukan market entry karena takut tertinggal.
- Tidak memindahkan pending order untuk mengejar harga.

### Masa berlaku entry

Pending order dibatalkan jika salah satu kondisi terjadi:

- Tidak terisi dalam tiga candle M5 setelah MSS.
- Target liquidity tersentuh sebelum entry.
- Sweep extreme ditembus sebelum entry.
- POI H1 invalid.
- Jendela sesi selesai.
- Masuk jendela berita high-impact USD ±15 menit.
- Rasio reward terhadap risk turun di bawah 2,5R.

---

## 12. Stop-loss

### Buy

SL ditempatkan di bawah sweep low ditambah buffer untuk spread.

### Sell

SL ditempatkan di atas sweep high ditambah buffer untuk spread.

Aturan buffer:

- Gunakan spread aktual broker saat order dibuat.
- Tambahkan satu kali spread aktual di luar sweep extreme.
- Jarak SL tidak boleh dipersempit hanya untuk memenuhi R:R.
- SL tidak boleh dipindahkan menjauh setelah entry.

---

## 13. Take-profit

TP ditempatkan pada liquidity M15 atau H1 berikutnya yang searah bias trade.

Prioritas TP:

1. External liquidity H1.
2. Previous day high atau low.
3. Session high atau low.
4. Equal highs atau equal lows M15.
5. Structural swing M15.

Trade hanya boleh diambil jika target likuiditas menyediakan reward minimal 2,5 kali risiko dari entry aktual.

```text
R:R = jarak entry ke TP / jarak entry ke SL
```

Jika target pertama kurang dari 2,5R:

- Jangan memindahkan TP melewati liquidity pertama untuk memaksakan R:R.
- Jangan mempersempit SL untuk memaksakan R:R.
- Lewati trade.

---

## 14. Position sizing

Target risiko adalah 1% dari equity. Risiko aktual boleh berada antara 1% dan 2% hanya karena batas minimum lot broker sebesar 0,01.

```text
Risiko uang target = equity × 1%
Risiko aktual = jarak SL × nilai pergerakan per lot × ukuran lot
```

Aturan:

- Hitung risiko berdasarkan spesifikasi kontrak XAUUSD broker, bukan asumsi umum.
- Gunakan lot terkecil yang tersedia dan paling dekat dengan risiko target.
- Jika 0,01 lot menghasilkan risiko di bawah 1%, trade boleh diambil dengan risiko lebih kecil.
- Jika 0,01 lot menghasilkan risiko antara 1% dan 2%, trade boleh diambil.
- Jika 0,01 lot menghasilkan risiko lebih dari 2%, trade wajib dilewati.
- Tidak menaikkan lot untuk mengejar target profit.
- Tidak menambah posisi atau layering.

---

## 15. Manajemen posisi

Sistem menggunakan set-and-forget:

- Satu entry.
- Satu SL.
- Satu TP.
- Tanpa partial close.
- Tanpa break-even.
- Tanpa trailing stop.
- Tanpa averaging down atau averaging up.
- Tanpa penutupan manual karena takut, kecuali terjadi kesalahan order teknis.

Posisi yang sudah terbuka tetap mengikuti SL dan TP saat masuk jendela berita. Slippage dicatat di jurnal.

---

## 16. Batas trading harian

Trading berhenti ketika salah satu kondisi pertama tercapai:

- Dua trade loss dalam satu hari.
- Net profit harian mencapai +2,5R atau lebih.
- Tiga trade selesai dalam satu hari.
- Sesi New York berakhir.

Aturan tambahan:

- Satu posisi aktif pada satu waktu.
- Trade profit yang melanggar aturan tetap dihitung sebagai invalid trade.
- Tidak ada kewajiban menghasilkan profit setiap hari.
- Hari tanpa setup valid adalah hasil yang sah.
- Tidak melakukan revenge trade setelah loss.

Dengan risiko aktual 1–2%, dua loss dapat menghasilkan drawdown harian 2–4%. Batas ini agresif dan tidak boleh dinaikkan selama validasi.

---

## 17. Kondisi no-trade

Lewati setup jika salah satu kondisi berikut terjadi:

- Bias H1 tidak jelas.
- POI H1 tidak fresh.
- POI berada di sisi dealing range yang salah.
- Tidak ada liquidity M15 yang jelas untuk disapu.
- Tidak ada target liquidity dengan minimal 2,5R.
- Sweep terjadi di luar POI H1.
- Tidak ada displacement valid.
- MSS hanya berupa wick.
- FVG tidak terbentuk.
- Harga sudah bergerak menuju target sebelum retracement entry.
- Pending order kedaluwarsa.
- Spread abnormal dibanding kondisi sesi normal.
- Berada dalam jendela berita high-impact USD ±15 menit.
- Batas loss, profit, atau jumlah trade harian tercapai.
- Risiko minimum 0,01 lot melebihi 2%.

---

## 18. Checklist pre-trade

```text
[ ] Instrumen XAUUSD
[ ] Berada dalam sesi London atau New York
[ ] Di luar berita high-impact USD ±15 menit
[ ] Bias H1 jelas
[ ] Protected high/low H1 jelas
[ ] Dealing range H1 jelas
[ ] POI H1 berada di premium/discount yang benar
[ ] POI H1 fresh
[ ] POI memiliki OB dan FVG
[ ] Liquidity M15 sudah ditandai sebelum sweep
[ ] Harga berada di POI H1
[ ] Liquidity M15 disapu pada M5
[ ] M5 reclaim setelah sweep
[ ] Displacement M5 body/range ≥65%
[ ] Displacement M5 range ≥1,5 × ATR(14)
[ ] Displacement meninggalkan FVG
[ ] MSS M5 memakai body close
[ ] Entry adalah retracement pertama
[ ] Pending order belum kedaluwarsa
[ ] TP berada di liquidity M15/H1 berikutnya
[ ] R:R minimal 2,5R
[ ] Risiko aktual tidak lebih dari 2%
[ ] Batas harian belum tercapai
```

Satu jawaban "tidak" berarti trade dilewati.

---

## 19. Checklist post-trade

```text
[ ] Screenshot H1 sebelum entry
[ ] Screenshot M15 sebelum entry
[ ] Screenshot M5 sebelum entry
[ ] Screenshot M5 setelah trade selesai
[ ] Entry, SL, TP, spread, dan lot dicatat
[ ] Risiko aktual dalam persen dicatat
[ ] Hasil dalam R dicatat
[ ] MAE dan MFE dicatat
[ ] Slippage dicatat
[ ] Kepatuhan rule dicatat
[ ] Kesalahan eksekusi dicatat
```

Klasifikasi hasil:

- Valid win: semua rule dipenuhi dan TP tercapai.
- Valid loss: semua rule dipenuhi dan SL tercapai.
- Invalid win: profit tetapi ada rule yang dilanggar.
- Invalid loss: loss dan ada rule yang dilanggar.
- Missed valid trade: setup valid terlewat.
- Cancelled setup: setup batal sesuai aturan.

Invalid win tidak boleh dianggap bukti bahwa pelanggaran aturan efektif.

---

## 20. Format jurnal

```text
Nomor trade:
Tanggal:
Sesi: London / New York
Waktu broker:
Waktu lokal:
Berita high-impact terdekat:

Bias H1:
Protected high/low:
Dealing range:
POI H1:
Premium/discount:
Target liquidity:

Liquidity M15 yang disapu:
Waktu sweep:
Displacement valid: ya/tidak
Body/range displacement:
Range/ATR displacement:
MSS valid: ya/tidak
FVG entry:
OB entry:

Entry:
SL:
TP:
Lot:
Risiko uang:
Risiko persen:
R:R awal:
Spread:

Hasil uang:
Hasil R:
MAE:
MFE:
Slippage:

Semua rule dipenuhi: ya/tidak
Klasifikasi hasil:
Kesalahan eksekusi:
Catatan:
Screenshot H1:
Screenshot M15:
Screenshot M5 sebelum:
Screenshot M5 sesudah:
```

---

## 21. Protokol validasi

### Sampel

- Jalankan 100 trade demo.
- Bagi menjadi empat blok, masing-masing 25 trade.
- Jangan mengubah aturan dalam satu blok.
- Setelah 25 trade, evaluasi data tanpa langsung menambah setup baru.
- Jika satu aturan diubah, dokumentasikan tanggal dan mulai blok baru.

### Metrik wajib

```text
Win rate = jumlah valid win / seluruh valid trade
Average win = total R dari valid win / jumlah valid win
Average loss = total R dari valid loss / jumlah valid loss
Expectancy = win rate × average win − loss rate × average loss
Profit factor = total positive R / absolute total negative R
Rule adherence = trade tanpa pelanggaran / seluruh trade
Maximum drawdown = penurunan equity terbesar dari peak ke trough
```

Pisahkan statistik berdasarkan:

- London dan New York.
- Buy dan sell.
- Hari dalam minggu.
- Jenis liquidity yang disapu.
- Jenis target liquidity.
- Risiko aktual 0–1%, 1–1,5%, dan 1,5–2%.

### Kriteria lulus awal

Sistem layak dilanjutkan ke fase demo berikutnya jika setelah 100 valid trade:

- Expectancy lebih besar dari 0R.
- Profit factor lebih besar dari 1.
- Rule adherence minimal 90%.
- Maximum drawdown dapat diterima secara psikologis dan operasional.
- Hasil tidak bergantung pada satu trade outlier.

Tidak ada klaim profit konsisten sebelum sampel selesai.

---

## 22. Urutan eksekusi harian

### Sebelum sesi

1. Periksa kalender berita high-impact USD.
2. Tandai previous day high dan previous day low.
3. Tandai Asia high dan Asia low.
4. Tentukan struktur dan bias H1.
5. Tentukan dealing range H1.
6. Tandai POI H1 fresh.
7. Tandai liquidity M15 di sekitar POI.
8. Tandai target liquidity M15/H1.
9. Buat alert pada POI; jangan menatap chart tanpa rencana.

### Saat harga masuk POI

1. Turun ke M5.
2. Tunggu sweep liquidity M15.
3. Tunggu reclaim.
4. Ukur displacement terhadap ATR(14).
5. Konfirmasi MSS dengan body close.
6. Tandai FVG dan OB displacement.
7. Hitung entry, SL, target, R:R, dan risiko aktual.
8. Tempatkan order hanya jika seluruh checklist valid.

### Setelah entry

1. Jangan mengubah SL atau TP.
2. Jangan membuka posisi kedua.
3. Biarkan trade selesai.
4. Simpan screenshot dan isi jurnal.
5. Periksa batas trading harian.

---

## 23. Prinsip final

- Setup valid boleh kalah.
- Setup invalid tetap salah meskipun profit.
- Target 2,5R merupakan filter setup, bukan jaminan hasil.
- Target liquidity lebih penting daripada memaksakan persentase keuntungan harian.
- Risiko dihitung dari SL dan spesifikasi kontrak broker, bukan hanya ukuran lot.
- Tidak ada entry tanpa POI H1, sweep liquidity M15, displacement M5, dan MSS M5.
- Tidak mengubah sistem berdasarkan beberapa loss beruntun.
- Disiplin dan data menentukan apakah sistem memiliki edge.