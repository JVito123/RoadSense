# RoadSense Lab

Prototipe IoT dua edge untuk memantau pola getaran dan konteks gerak visual dalam simulasi di atas meja. Sistem terdiri dari satu ponsel Android dan satu laptop dengan webcam, yang terhubung ke broker MQTT cloud.

> **Batasan penting.** Prototipe ini **belum dapat memvalidasi kerusakan jalan secara langsung**. Edge A (ponsel) hanya menandai pola getaran, sedangkan edge B (webcam laptop) hanya memberi konteks gerak visual. Sistem ini tidak memiliki GPS, sehingga tidak ada informasi lokasi maupun peringatan berbasis lokasi. Seluruh pengujian dirancang untuk simulasi meja yang terkendali, bukan untuk pengujian di jalan.

Spesifikasi teknis lengkap (algoritma, kontrak MQTT, payload JSON) tersedia di [`SPEC.md`](SPEC.md).

## Ringkasan sistem

| | Edge A — ponsel Android | Edge B — laptop |
|---|---|---|
| Sensor | Accelerometer + gyroscope melalui Termux:API | Webcam melalui OpenCV |
| Pemrosesan di edge | Vibration RMS, peak jerk, rotation RMS | Frame differencing grayscale, rata-rata per jendela 1 detik |
| Status | `NORMAL`, `BUMP_SUSPECTED`, `DEVICE_MOVEMENT`, `SENSOR_ERROR` | `NORMAL`, `MOTION_OBSERVED` |
| Program | `python -m edge_phone.main` | `edge_laptop/camera_edge.py` |

- Tiga jenis sensor: accelerometer, gyroscope, dan webcam.
- Dua metode pemrosesan: analisis getaran IMU (RMS dan jerk) dan frame differencing webcam.
- Komunikasi dua arah melalui MQTT over TLS: telemetri dan event dari edge, perintah `SET_THRESHOLD` dari dashboard, lalu ACK dari edge.
- Dashboard browser memantau kedua edge dan mengirim perintah ambang. Dashboard tidak dihitung sebagai edge.

## Arsitektur

```mermaid
flowchart LR
  subgraph LAN["Jaringan WiFi / hotspot yang sama"]
    A["Edge A · Android<br/>Termux:API IMU<br/>RMS, jerk, rotasi"]
    B["Edge B · Laptop<br/>OpenCV webcam<br/>frame differencing"]
    D["Dashboard browser<br/>(di laptop)"]
  end
  H[("broker.hivemq.com<br/>MQTT publik")]
  A -- "TLS 8883 · edge/A/telemetry, events, ack/A" --> H
  B -- "TLS 8883 · edge/B/telemetry, events, ack/B" --> H
  H -- "control, events" --> A
  H -- "control, events" --> B
  H -- "WSS 8884 · telemetry, events, ack/A, ack/B" --> D
  D -- "control (SET_THRESHOLD)" --> H
```

Semua topic berada di bawah `roadsense/{PROJECT_ID}/`. Setiap perangkat terhubung langsung ke broker; tidak ada komunikasi langsung antar-perangkat di jaringan lokal.

## Struktur repository

```
.
├── SPEC.md                    # spesifikasi teknis dan kontrak MQTT
├── README.md
├── edge_phone/                # Edge A (paket Python, dijalankan di Termux)
│   ├── main.py                # entry point CLI
│   ├── config.py              # konfigurasi & variabel lingkungan
│   ├── sensors.py             # penemuan sensor & stream termux-sensor
│   ├── processor.py           # perhitungan & klasifikasi
│   ├── mqtt_client.py         # MQTT, kontrol, ACK
│   └── requirements.txt
├── edge_laptop/               # Edge B
│   ├── camera_edge.py
│   └── requirements.txt
├── dashboard/                 # index.html, style.css, app.js (statis, tanpa build)
├── tools/
│   ├── monitor.py             # memantau telemetry, events, dan ACK dari terminal
│   └── send_control.py        # mengirim SET_THRESHOLD dari terminal
├── tests/
│   └── test_edge_phone.py     # unit test edge A (unittest)
└── docs/
    ├── ppt_outline.md
    ├── demo_script.md
    ├── test_scenarios.md
    └── screenshots/
```

## Status implementasi dan pengujian

Semua fitur di bawah ini sudah diimplementasikan. Pengujian fisik dilakukan pada 29 Oktober 2026 di atas meja, memakai satu ponsel Android (edge A), satu laptop Windows dengan webcam (edge B), broker HiveMQ publik, dan PROJECT_ID `roadsense-v29lab`.

| Fitur | Unit test | Uji fisik (tabletop) | Bukti |
|---|---|---|---|
| Pembacaan accelerometer dan gyroscope via Termux:API | ✓ dengan mock | ✓ | [t4_event_b_ke_a.jpeg](docs/screenshots/t4_event_b_ke_a.jpeg), [t3_dashboard_both_fresh.png](docs/screenshots/t3_dashboard_both_fresh.png) |
| Vibration RMS, peak jerk, rotation RMS | ✓ dengan data sintetis | ✓ nilai nyata terkirim (belum dikalibrasi) | sama seperti di atas |
| Klasifikasi status dan cooldown event edge A | ✓ | ✓ `NORMAL`, `BUMP_SUSPECTED`, `DEVICE_MOVEMENT` teramati | [t3_dashboard_both_fresh.png](docs/screenshots/t3_dashboard_both_fresh.png), [t4_event_a_ke_b.png](docs/screenshots/t4_event_a_ke_b.png) |
| Frame differencing dan klasifikasi edge B | — | ✓ `NORMAL` dan `MOTION_OBSERVED` teramati | [t4_event_a_ke_b.png](docs/screenshots/t4_event_a_ke_b.png) |
| Telemetri A dan B melalui MQTT/TLS ke HiveMQ | — | ✓ | [t3_dashboard_both_fresh.png](docs/screenshots/t3_dashboard_both_fresh.png) |
| Dashboard (koneksi WSS, kartu Fresh, grafik) | — | ✓ | [t3_dashboard_both_fresh.png](docs/screenshots/t3_dashboard_both_fresh.png) |
| `SET_THRESHOLD` dan ACK edge A | ✓ (fungsi parser) | ✓ | [t5_edge_a_ack.png](docs/screenshots/t5_edge_a_ack.png) |
| `SET_THRESHOLD` dan ACK edge B | — | ✓ | [t5_edge_b_ack.png](docs/screenshots/t5_edge_b_ack.png) |
| Event A → B dan B → A | — | ✓ | [t4_event_a_ke_b.png](docs/screenshots/t4_event_a_ke_b.png), [t4_event_b_ke_a.jpeg](docs/screenshots/t4_event_b_ke_a.jpeg) |
| Nama topic edge A | ✓ | ✓ terlihat di log edge A | [t4_event_b_ke_a.jpeg](docs/screenshots/t4_event_b_ke_a.jpeg) |
| Event di *Event timeline* dashboard | — | belum ada screenshot | — |
| Rotasi terkontrol → `DEVICE_MOVEMENT` | ✓ (data sintetis) | sebagian: event muncul di log B, tetapi uji rotasi terkontrol belum didokumentasikan | [t4_event_a_ke_b.png](docs/screenshots/t4_event_a_ke_b.png) |
| Deteksi *Stale*, ACK timeout, ambang B di luar rentang, payload tidak valid | — | belum diuji | — |
| Reconnect otomatis setelah koneksi terputus | — | belum diuji | — |
| `tools/send_control.py` | — | belum ada bukti | — |

Pemeriksaan otomatis lain:
- 10 unit test di `tests/test_edge_phone.py` lulus (`python -m unittest discover -s tests -v`) pada Python 3.13 di Linux. Unit test ini belum dijalankan di perangkat Android.
- Opsi `--help` pada keempat program Python berjalan tanpa galat, dan `dashboard/app.js` lolos pemeriksaan sintaks `node --check`.

Rincian hasil ada di [Hasil pengujian](#hasil-pengujian) dan [`docs/test_scenarios.md`](docs/test_scenarios.md).

## Prasyarat

**Laptop (edge B, dashboard, tools)**
- Python 3.10 atau lebih baru
- Webcam internal atau USB
- Browser modern (Chrome, Edge, atau Firefox) dengan akses internet, karena MQTT.js dimuat dari CDN

**Ponsel Android (edge A)**
- Aplikasi Termux dan Termux:API dari sumber yang sama (misalnya keduanya dari F-Droid)
- Paket Termux `python`, `git`, dan `termux-api`

**Jaringan**
- Ponsel dan laptop berada di WiFi/hotspot yang sama dan memiliki akses internet
- Port keluar 8883 (MQTT/TLS) dan 8884 (WSS) tidak diblokir

## Instalasi dan menjalankan

Semua perintah dijalankan dari **root repository**.

### 1. Tentukan PROJECT_ID

Gunakan satu nilai yang sama di edge A, edge B, dashboard, dan tools. Formatnya 3–64 karakter berupa huruf kecil, angka, atau tanda hubung. Contoh instruksi di bawah memakai `roadsense-v29lab`, yaitu PROJECT_ID yang digunakan dalam pengujian project ini. Pada broker publik, siapa pun yang mengetahui ID dapat memantau atau mengirim perintah; gunakan ID acak yang lebih sulit ditebak jika dipakai di luar demo.

### 2. Siapkan laptop

Windows (PowerShell):
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r edge_laptop/requirements.txt
```

Linux/macOS:
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r edge_laptop/requirements.txt
```

`edge_laptop/requirements.txt` berisi `opencv-python` dan `paho-mqtt`, sehingga cukup untuk edge B dan `tools/`. Pada contoh selanjutnya, `python` berarti interpreter di dalam `.venv`, yaitu `.\.venv\Scripts\python.exe` di Windows atau `.venv/bin/python` di Linux/macOS. **Di PowerShell Windows, jika `.venv` belum diaktifkan, ganti awalan `python` pada setiap perintah laptop dengan `.\.venv\Scripts\python.exe`** agar dependensi terpasang ditemukan. Contoh: `.\.venv\Scripts\python.exe edge_laptop/camera_edge.py --project-id roadsense-v29lab --preview`.

Untuk memeriksa apakah kamera bisa dibuka:
```bash
python -c "import cv2; c = cv2.VideoCapture(0); print(c.isOpened()); c.release()"
```

### 3. Jalankan unit test (opsional)

```bash
python -m unittest discover -s tests -v
```

Unit test hanya membutuhkan pustaka standar Python dan tidak mengakses sensor maupun broker.

### 4. Pantau broker (terminal 1)

```bash
python tools/monitor.py --project-id roadsense-v29lab
```

Program ini mencetak setiap pesan pada `edge/+/telemetry`, `events`, dan `ack/+`. Hentikan dengan Ctrl+C.

### 5. Jalankan edge B — laptop (terminal 2)

```bash
python edge_laptop/camera_edge.py --project-id roadsense-v29lab --preview
```

| Opsi | Default | Keterangan |
|---|---|---|
| `--project-id` | wajib | |
| `--camera` | `0` | coba `--camera 1` jika kamera tidak terbuka |
| `--threshold` | `12.0` | ambang awal `motion_score_threshold` (0,1–150) |
| `--preview` | nonaktif | menampilkan gambar kamera **secara lokal**; tekan `q` untuk keluar |

Tanpa `--preview`, hentikan program dengan Ctrl+C. Log edge B menampilkan `seq`, `score`, `peak`, `delta`, dan status setiap ±1 detik, serta event dari edge A dengan awalan `[SHARED EVENT]`.

### 6. Buka dashboard (terminal 3)

```bash
python -m http.server 8000 --bind 127.0.0.1
```

Opsi `--bind 127.0.0.1` membatasi server agar hanya bisa diakses dari laptop itu sendiri, sehingga isi folder repository tidak terbuka ke perangkat lain di jaringan. Perintah ini yang dipakai saat pengujian. Dashboard tetap terhubung ke broker cloud melalui WSS.

Buka <http://localhost:8000/dashboard/>, isi PROJECT_ID, lalu klik **Connect**. Kolom PROJECT_ID juga dapat diisi otomatis melalui <http://localhost:8000/dashboard/?project=roadsense-v29lab>.

Dashboard menampilkan:
- status koneksi broker;
- kartu A dan B, berisi nilai terbaru, status, *Fresh/Stale*, `seq`, jumlah `seq` yang terlewat, waktu terakhir diterima, dan ambang yang dikonfirmasi ACK;
- grafik 60 detik dari data yang benar-benar diterima;
- form `SET_THRESHOLD` untuk A dan B, termasuk hasil ACK, pesan galat, dan batas waktu 10 detik;
- *Event timeline* dan *Activity log*, termasuk pesan yang ditolak karena tidak sesuai kontrak.

### 7. Jalankan edge A — ponsel (Termux)

Pasang paket yang diperlukan:
```bash
pkg update
pkg install python git termux-api
```

Ambil kode, lalu masuk ke root repository:
```bash
git clone https://github.com/<username>/<nama-repo>.git
cd <nama-repo>
pip install -r edge_phone/requirements.txt
```

Periksa sensor, lalu jalankan edge A:
```bash
termux-sensor -l                                                       # daftar sensor dari Termux:API
python -m edge_phone.main --project-id roadsense-v29lab --list-sensors # sensor yang dipilih program
python -m edge_phone.main --project-id roadsense-v29lab --check-once   # satu jendela data, tanpa MQTT
python -m edge_phone.main --project-id roadsense-v29lab                # publish/subscribe MQTT terus-menerus
```

> Jalankan sebagai modul (`python -m edge_phone.main`) dari root repository. Perintah `python edge_phone/main.py` akan gagal karena paket memakai import `from edge_phone...`.

**Periksa gyroscope yang dipilih.** Jika ada beberapa sensor dengan kata `gyroscope`, program memilih nama terpendek yang tidak mengandung kata seperti `uncalibrated` atau `wakeup`. Pada ponsel uji, cara ini memilih `VDIS Gyroscope`, padahal yang dibutuhkan adalah gyroscope dari chip IMU, `ICM42632M Gyroscope`. Karena itu nama sensor diset manual sebelum menjalankan edge A:
```bash
export GYRO_SENSOR_NAME="ICM42632M Gyroscope"   # sesuaikan dengan nama di output termux-sensor -l
python -m edge_phone.main --project-id roadsense-v29lab --list-sensors
```
`export` hanya berlaku untuk sesi Termux yang sedang terbuka. Ulangi perintah ini setiap kali Termux dibuka ulang. Jika tidak diulang, `rotation_rms` bisa tetap 0 dan status `DEVICE_MOVEMENT` tidak akan muncul.

Opsi tambahan: `--log-level DEBUG|INFO|WARNING|ERROR`.

Kode keluar program:
- `2` — PROJECT_ID tidak valid;
- `1` — sensor tidak ditemukan, atau `--check-once` menghasilkan `SENSOR_ERROR`;
- `0` — selesai normal.

Parameter lain diatur melalui variabel lingkungan. File `.env` **tidak** dibaca otomatis. Contoh:
```bash
VIBRATION_RMS_THRESHOLD=1.0 ROTATION_RMS_THRESHOLD=1.2 \
  python -m edge_phone.main --project-id roadsense-v29lab
```
Daftar lengkap variabel dan nilai default ada di [`SPEC.md` §4.4](SPEC.md#44-konfigurasi).

### 8. Ubah ambang dari terminal (opsional)

Selain melalui dashboard, perintah ambang dapat dikirim dari laptop:
```bash
python tools/send_control.py --project-id roadsense-v29lab --target B --value 8
python tools/send_control.py --project-id roadsense-v29lab --target A --value 1.0 --jerk 4.0
```

Untuk target A, `--value` adalah `vibration_rms_threshold` dan `--jerk` adalah `jerk_peak_threshold` (default `3.0`, selalu ikut dikirim). Program menunggu ACK selama 4 detik.

## Ringkasan kontrak MQTT

| Topic (di bawah `roadsense/{PROJECT_ID}/`) | Arah | Isi utama |
|---|---|---|
| `edge/A/telemetry` | A → broker | `vibration_rms`, `peak_jerk`, `rotation_rms`, `status` |
| `edge/B/telemetry` | B → broker | `motion_score`, `motion_delta`, `status` |
| `events` | A/B → semua | `type`, `severity`, `detail` |
| `control` | dashboard/tools → edge | `SET_THRESHOLD` dengan `target` `A` atau `B` |
| `ack/A`, `ack/B` | edge → dashboard/tools | `success` dan ambang yang diterapkan |

Contoh payload, aturan event, dan validasi lengkap tercantum di [`SPEC.md` §6](SPEC.md#6-kontrak-mqtt).

## Hasil pengujian

Pengujian fisik dilakukan pada 29 Oktober 2026 dalam simulasi di atas meja dengan PROJECT_ID `roadsense-v29lab`. Hasil di bawah adalah pengamatan dari satu sesi uji fungsional, bukan pengukuran akurasi. Prosedur dan rincian setiap uji ada di [`docs/test_scenarios.md`](docs/test_scenarios.md).

| Uji | Hasil | Yang teramati | Bukti |
|---|---|---|---|
| T1 Sensor nyata A & B | Lulus | Edge A mengirim nilai dari accelerometer dan gyroscope ponsel, termasuk `rotation_rms` 0,24 rad/s. Edge B menghitung `score`, `peak`, dan `delta` dari webcam setiap ±1 detik. | [t4_event_b_ke_a.jpeg](docs/screenshots/t4_event_b_ke_a.jpeg), [t4_event_a_ke_b.png](docs/screenshots/t4_event_a_ke_b.png) |
| T2 Telemetri terpisah melalui cloud | Lulus | Edge A mempublikasikan ke `roadsense/roadsense-v29lab/edge/A/telemetry`; telemetri A dan B diterima bersamaan oleh dashboard melalui HiveMQ. | [t4_event_b_ke_a.jpeg](docs/screenshots/t4_event_b_ke_a.jpeg), [t3_dashboard_both_fresh.png](docs/screenshots/t3_dashboard_both_fresh.png) |
| T3 Dashboard menampilkan A & B | Lulus | Status *Connected*, kartu A dan B *Fresh*, grafik real-time tampil, `Messages 80 · Rejected 0`. | [t3_dashboard_both_fresh.png](docs/screenshots/t3_dashboard_both_fresh.png) |
| T4 Event lintas perangkat | Lulus | Log edge B: `[SHARED EVENT] from edge A: BUMP_SUSPECTED`. Log edge A: `[CROSS-EDGE EVENT from B] type=MOTION_OBSERVED severity=INFO`. | [t4_event_a_ke_b.png](docs/screenshots/t4_event_a_ke_b.png), [t4_event_b_ke_a.jpeg](docs/screenshots/t4_event_b_ke_a.jpeg) |
| T5 Kontrol dua arah dan ACK | Lulus | Edge A menerapkan `vibration_rms_threshold` = 1,0 dan `jerk_peak_threshold` = 4,0 (round trip 1786 ms). Edge B menerapkan `motion_score_threshold` = 5,0 (round trip 1173 ms). | [t5_edge_a_ack.png](docs/screenshots/t5_edge_a_ack.png), [t5_edge_b_ack.png](docs/screenshots/t5_edge_b_ack.png) |

![Dashboard saat pengujian: kedua edge Fresh](docs/screenshots/t3_dashboard_both_fresh.png)

Catatan dari pengujian:
- Satu percobaan pertama mengirim perintah ke edge B sempat berakhir dengan *No ACK within 10 s*, lalu berhasil saat diulang. Pengiriman perintah tidak dijamin selalu berhasil pada percobaan pertama.
- `peak_jerk` jauh lebih sensitif daripada `vibration_rms`. Contohnya, log edge A mencatat `vibration_rms` 0,17 dan `peak_jerk` 31,19 dengan status `BUMP_SUSPECTED`. Penyebab yang paling mungkin: Δt dihitung dari waktu sampel diterima program (minimum 5 ms), sehingga sampel yang datang berdekatan memperbesar nilai jerk.
- Status `MOTION_OBSERVED` dapat muncul walaupun `score` rata-rata rendah, karena edge B memakai nilai puncak jendela. Contohnya, di log B tercatat `score=2.90 peak=6.46 ... MOTION_OBSERVED`.
- Uji yang belum dilakukan: rotasi terkontrol, deteksi *Stale*, ACK timeout dengan edge dimatikan, nilai ambang di luar rentang, payload tidak valid, dan reconnect jaringan.

Daftar screenshot dan isinya ada di [`docs/screenshots/`](docs/screenshots/README.md).

## Dokumen pendukung

- [`docs/test_scenarios.md`](docs/test_scenarios.md) — skenario uji dan formulir hasil
- [`docs/demo_script.md`](docs/demo_script.md) — skrip video demo ±3 menit
- [`docs/ppt_outline.md`](docs/ppt_outline.md) — kerangka presentasi 8 slide

## Pemecahan masalah

| Gejala | Penyebab yang mungkin | Tindakan |
|---|---|---|
| `Binary 'termux-sensor' not found` | Paket atau aplikasi Termux:API belum terpasang | `pkg install termux-api`, lalu pasang aplikasi Termux:API dari sumber yang sama dengan Termux |
| `termux-sensor -l` timeout atau kosong | Termux:API belum berjalan atau belum diberi izin | Buka aplikasi Termux:API, periksa izinnya, lalu coba lagi |
| `ModuleNotFoundError: No module named 'edge_phone'` | Program dijalankan sebagai skrip (`python edge_phone/main.py`) atau dari dalam folder `edge_phone/` | Jalankan `python -m edge_phone.main` dari root repository |
| `Camera could not be opened` | Kamera sedang dipakai aplikasi lain atau indeks kamera salah | Tutup aplikasi lain, lalu coba `--camera 1` |
| Kartu dashboard tetap *No data* / *Stale* | PROJECT_ID berbeda, atau edge berhenti | Samakan PROJECT_ID dan periksa log edge serta `tools/monitor.py` |
| Penghitung *Rejected* bertambah | Payload tidak sesuai kontrak | Baca alasannya di *Activity log* |
| *No ACK within 10 s* | Edge belum tersambung ke broker, edge tidak berjalan, PROJECT_ID berbeda, atau nilai ambang tidak valid | Tunggu sampai log edge B menampilkan `[MQTT] connect reason:` sebelum mengirim, lalu kirim ulang. Untuk B, gunakan nilai 0,1–150 |
| `rotation_rms` selalu 0 dan `DEVICE_MOVEMENT` tidak pernah muncul | Gyroscope yang terpilih otomatis bukan sensor yang diinginkan, atau ponsel tidak punya gyroscope | Jalankan `termux-sensor -l`, lalu set `export GYRO_SENSOR_NAME="<nama gyroscope chip IMU>"` di sesi Termux yang sama |
| `BUMP_SUSPECTED` muncul padahal ponsel diam | `peak_jerk` melonjak karena jitter waktu sampel | Naikkan `jerk_peak_threshold` dari dashboard sampai status diam kembali `NORMAL` |
| Status B `MOTION_OBSERVED` padahal grafik di bawah garis ambang | B mengklasifikasi berdasarkan nilai **puncak** jendela, sedangkan grafik menampilkan nilai **rata-rata** | Perilaku ini sesuai implementasi; lihat [`SPEC.md` §5.2](SPEC.md#52-agregasi-dan-klasifikasi-per-jendela-1-detik) |
| Dashboard: "MQTT.js did not load" | CDN tidak dapat diakses | Periksa koneksi internet, lalu muat ulang halaman |

## Keamanan dan privasi

- Koneksi dienkripsi dengan TLS, tetapi broker HiveMQ publik **tanpa autentikasi**. Siapa pun yang mengetahui PROJECT_ID dapat membaca pesan dan mengirim perintah.
- Yang dikirim hanya ringkasan numerik. Frame webcam tidak disimpan maupun dikirim; `--preview` hanya tampil di layar laptop.
- Jangan mengirim nama, lokasi, kata sandi, atau informasi sensitif melalui topic proyek.
- Dashboard hanya menyimpan PROJECT_ID di `localStorage` browser.

## Keterbatasan

- Pengujian dirancang untuk skenario meja; belum ada uji di kendaraan atau di jalan.
- Ambang default (A: 0,8 m/s², 3,0 m/s³, rotasi 0,8 rad/s; B: 12,0) dipilih manual dan belum dikalibrasi. Tidak ada klaim akurasi.
- Laju sampling Termux:API terbatas dan tidak selalu stabil, sehingga `peak_jerk` bersifat perkiraan. Dalam pengujian, nilainya bisa mencapai puluhan m/s³ walaupun `vibration_rms` rendah, sehingga ambang jerk perlu dinaikkan agar tidak terlalu sering memicu `BUMP_SUSPECTED`.
- Ambang yang diubah lewat dashboard hanya tersimpan di memori. Saat edge dijalankan ulang, ambang kembali ke nilai awal: variabel lingkungan atau default untuk A, dan `--threshold` untuk B.
- Pemilihan gyroscope otomatis dapat memilih sensor yang tidak diinginkan jika ponsel memiliki beberapa sensor bernama *gyroscope*. Pada ponsel uji, nama sensor perlu diset manual dengan `GYRO_SENSOR_NAME`.
- Offset kalibrasi accelerometer dapat membuat `vibration_rms` tidak nol saat ponsel diam.
- Tanpa gyroscope, `rotation_rms` bernilai 0 dan status `DEVICE_MOVEMENT` tidak dapat muncul.
- `motion_score` sensitif terhadap cahaya dan bukan inspeksi kondisi jalan.
- Tidak ada GPS, sehingga tidak ada peringatan berbasis lokasi.
- Sistem bergantung pada koneksi internet dan ketersediaan broker publik.

Uraian lengkap ada di [`SPEC.md` §10](SPEC.md#10-keterbatasan).

## Publikasi ke GitHub

```bash
git init
git add .
git commit -m "RoadSense Lab: prototipe IoT dua edge (Android IMU + laptop webcam)"
git branch -M main
git remote add origin https://github.com/<username>/<nama-repo>.git
git push -u origin main
```

File `.gitignore` sudah mengecualikan `.venv/`, `__pycache__/`, `.env`, `*.log`, dan file video. Sebelum melakukan push, pastikan tidak ada kata sandi, token, foto/video webcam mentah, atau data pribadi di repository.

## Tautan

- Presentasi: *ditambahkan setelah final*
- Video demo: *ditambahkan setelah direkam*
