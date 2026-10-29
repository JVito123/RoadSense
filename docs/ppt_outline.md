# RoadSense Lab — Outline Awal PPT (Arsip, 8 Slide)

> **Catatan:** Dokumen ini merupakan rancangan awal presentasi RoadSense Lab yang terdiri dari 8 slide. Presentasi telah dikembangkan menjadi 16 slide. Dokumen ini dipertahankan sebagai arsip perencanaan, bukan versi presentasi final.

> Basis: [`SPEC.md`](../SPEC.md) (1 ponsel Android + 1 laptop). Semua angka pada slide pengujian **harus** berasal dari pengukuran nyata saat uji/demonstrasi — bagian bertanda `[ISI: …]` sengaja dibiarkan kosong. Jangan mengisi dengan angka contoh dari SPEC.

Info judul (taruh di slide 1 atau sebagai header kecil di semua slide):
**RoadSense Lab — Prototipe IoT Dua Edge untuk Pemantauan Getaran dan Konteks Gerak Visual (Simulasi Meja)**
`[ISI: nama anggota / NIM]` · `[ISI: mata kuliah, dosen]` · `[ISI: tanggal]`

---

## Slide 1 — Masalah
**Poin utama**
- Jalan berlubang/tidak rata menimbulkan guncangan pada kendaraan; laporan kerusakan jalan sering manual dan lambat.
- Ponsel sudah punya sensor gerak (akselerometer, giroskop) — bisakah dipakai sebagai sensor getaran murah?
- Tantangan teknis: membedakan *getaran/benturan* dari *ponsel yang sekadar digerakkan/diputar*, dan mengirim data secara real-time ke cloud.
- Lingkup proyek ini: **simulasi terkendali di atas meja**, bukan uji di jalan raya.

**Visual:** ilustrasi sederhana guncangan → sinyal getaran; ikon ponsel + cloud.
**Catatan pembicara:** tekankan sejak awal bahwa ini prototipe pembelajaran IoT, bukan detektor lubang yang tervalidasi.

---

## Slide 2 — Ide & Manfaat
**Ide:** dua perangkat edge yang masing-masing membaca sensornya sendiri, memproses data di perangkat (edge processing), lalu bertukar data lewat broker MQTT publik.
- Edge A (ponsel Android) → pola getaran dari IMU.
- Edge B (laptop + webcam) → *konteks gerak visual* di area meja.
- Dashboard web → memantau keduanya dan mengubah ambang (threshold) dari jarak jauh.

**Manfaat (sebagai prototipe):**
- Menunjukkan alur IoT lengkap: sensor → pemrosesan edge → cloud → dashboard → perintah balik → ACK.
- Biaya rendah (perangkat yang sudah dimiliki).
- Hanya ringkasan numerik yang dikirim — tidak ada gambar/video/identitas.

**Catatan pembicara:** manfaat nyata untuk jalan raya butuh GPS, validasi lapangan, dan data berlabel — di luar lingkup.

---

## Slide 3 — Arsitektur 2 Edge
**Diagram** (gambar ulang dari diagram arsitektur di `README.md`):
```
[Edge A: Android]  --TLS 8883-->  ┐
  Termux:API IMU                  │
[Edge B: Laptop]   --TLS 8883-->  ├── broker.hivemq.com ──WSS 8884──> [Dashboard browser]
  OpenCV webcam                   │                     <──control──
                                  ┘ <──control / ──> ack
```
- Topik dasar: `roadsense/{PROJECT_ID}`
- `edge/A/telemetry`, `edge/B/telemetry`, `events`, `control`, `ack/A`, `ack/B`
- A = PONSEL (`imu`), B = LAPTOP (`webcam`) — tetap, tidak pernah ditukar.
- Ponsel dan laptop di WiFi/hotspot yang sama; masing-masing terhubung **sendiri** ke broker cloud.
- Dashboard **bukan** edge ketiga.

**Catatan pembicara:** laptop dihitung edge karena ia membaca webcam dan memproses frame sendiri — bukan karena menampilkan dashboard. `[ISI: status konfirmasi dosen bahwa laptop boleh dihitung sebagai edge]`

---

## Slide 4 — Sensor & Algoritma Edge
| | Edge A — Ponsel | Edge B — Laptop |
|---|---|---|
| Sensor | Akselerometer + giroskop (Termux:API) | Webcam (OpenCV) |
| Sampling (konfigurasi) | interval diminta 50 ms (`SENSOR_DELAY_MS`); laju terukur `[ISI]` Hz | jeda 60 ms antar-frame; laju terukur `[ISI]` fps |
| Jendela | sampel sejak publish sebelumnya (±1 detik, minimal 8 sampel) | ±1 detik; frame grayscale 160 × 120 |
| Pemrosesan 1 | Vibration RMS = √mean((‖a‖ − 9,80665)²), m/s² | `score` = mean\|frameₜ − frameₜ₋₁\| (~0–255) |
| Pemrosesan 2 | Peak jerk = max ‖Δa‖/Δt, m/s³ (perkiraan) | `motion_score` = rata-rata `score`; `motion_delta` = rata-rata \|Δscore\| per jendela |
| Pemrosesan 3 | Rotation RMS = √mean(‖ω‖²), rad/s | — |

**Catatan pembicara:** sebutkan bahwa laju sampling Termux:API terbatas dan tidak selalu stabil, timestamp diambil saat sampel diterima sehingga jerk bersifat perkiraan, dan `motion_score` **bukan** satuan fisik terkalibrasi. Rumus lengkap ada di `SPEC.md` §4–5.

---

## Slide 5 — Komunikasi Cloud Dua Arah (MQTT)
- Protokol: MQTT over TLS — Python edge port 8883; dashboard WebSocket aman `wss://broker.hivemq.com:8884/mqtt`.
- **Uplink:** telemetri A & B (topik terpisah), event lintas-perangkat di `events`.
- **Downlink:** dashboard → `control` (`SET_THRESHOLD` dengan `target` A atau B).
- **Konfirmasi:** edge → `ack/A` atau `ack/B` berisi nilai ambang yang benar-benar diterapkan.
- Edge mengabaikan perintah dengan `target` lain.

**Visual:** diagram urutan (sequence): Dashboard → control → Edge A → ack/A → Dashboard.
Tampilkan contoh payload JSON dari SPEC (diberi label "format", bukan hasil).
**Bukti:** `[SCREENSHOT: log TX/ACK di dashboard]`, `[ISI: round-trip ACK terukur, ms]`

---

## Slide 6 — Aturan Keputusan & Event
**Edge A (dievaluasi berurutan):**
1. Sensor gagal atau nilai tidak valid → `SENSOR_ERROR`
2. `rotation_rms ≥ 0,8 rad/s` → `DEVICE_MOVEMENT` (artefak gerakan tangan, bukan getaran)
3. `vibration_rms ≥ 0,8 m/s²` **atau** `peak_jerk ≥ 3,0 m/s³` → `BUMP_SUSPECTED`
4. Selain itu → `NORMAL`

Angka di atas adalah nilai default. Ambang getaran dan jerk dapat diubah lewat MQTT; ambang rotasi hanya lewat variabel lingkungan.

**Edge B:** nilai `score` **tertinggi** dalam jendela ±1 detik ≥ `motion_score_threshold` (default 12,0; rentang 0,1–150) → `MOTION_OBSERVED`, selain itu `NORMAL`.

**Event (anti-spam):** dikirim saat status non-`NORMAL` berubah, lalu diulang paling cepat setiap 3 detik (A) atau 12 detik (B) selama kondisi berlanjut. Event A tercatat di dashboard dan di log edge B (`[SHARED EVENT]`).
**Ambang dapat diubah** dari dashboard tanpa me-restart edge.

---

## Slide 7 — Bukti Pengujian
Isi **hanya** dengan hasil nyata dari `docs/test_scenarios.md`.

| Uji | Hasil | Bukti |
|---|---|---|
| T0 Unit test edge A (otomatis) | 10 test lulus di mesin review (Linux, Python 3.13) — jalankan ulang dan catat hasilnya sendiri | `[SCREENSHOT: python -m unittest discover -s tests -v]` |
| T1 Sensor nyata A & B | `[ISI]` | `[SCREENSHOT: --list-sensors / --check-once + log edge B]` |
| T2 Telemetri terpisah via cloud | `[ISI]` | `[SCREENSHOT: tools/monitor.py]` |
| T3 Dashboard + last-seen | `[ISI]` | `[SCREENSHOT: dashboard dua kartu Fresh]` |
| T4 Event A → dashboard & log B | `[ISI]` | `[SCREENSHOT: timeline + log B]` |
| T5 Control → ACK | `[ISI]` | `[SCREENSHOT: kotak ACK hijau]` |

Angka terukur (opsional, jika diukur): baseline diam `[ISI]`, saat ketukan `[ISI]`, jumlah missed seq `[ISI]`, round-trip ACK `[ISI]`.

---

## Slide 8 — Kesimpulan, Keterbatasan & Tautan
**Kesimpulan**
- Dua edge nyata (ponsel IMU + laptop webcam) memproses data secara lokal dan berkomunikasi dua arah via MQTT/TLS.
- Aturan sederhana dapat membedakan getaran vs. gerakan ponsel dalam simulasi meja.

**Keterbatasan (wajib disampaikan jujur)**
- Hanya simulasi meja; **tidak** diuji di kendaraan/jalan.
- Edge A hanya menandai pola getaran; **bukan** deteksi lubang yang tervalidasi.
- Webcam hanya konteks gerak visual; **bukan** inspeksi kondisi jalan.
- Tidak ada GPS → tidak ada peringatan berbasis lokasi atau "di depan rute".
- Broker publik tanpa autentikasi: siapa pun yang tahu PROJECT_ID bisa membaca/mengirim pesan.
- Laju sampling Termux:API terbatas & tidak selalu stabil; ambang dipilih manual, bukan dari data berlabel.

**Pengembangan lanjut:** GPS, broker privat dengan autentikasi, kalibrasi dan dataset berlabel, uji lapangan yang aman.

**Tautan:** GitHub `[ISI: URL repo]` · Video demo `[ISI: URL video]`
