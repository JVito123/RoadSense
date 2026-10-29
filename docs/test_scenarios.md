# Skenario Pengujian

Kolom **Hasil** dan **Nilai terukur** sengaja dikosongkan. Isi hanya setelah uji dijalankan dengan perangkat nyata, lalu simpan screenshot di `docs/screenshots/` dengan nama yang disebutkan. Jangan menyalin angka contoh dari `SPEC.md` sebagai hasil.

Semua perintah dijalankan dari root repository. `python` berarti interpreter di `.venv` pada laptop, atau `python` bawaan Termux pada ponsel. **Di PowerShell Windows, gunakan `.\.venv\Scripts\python.exe` sebagai pengganti `python` pada perintah laptop apabila `.venv` belum diaktifkan.** Contoh memakai `roadsense-v29lab`; ganti dengan PROJECT_ID milikmu jika diperlukan.

## Alat verifikasi independen (selain dashboard)

Pantau semua pesan proyek langsung dari broker:
```bash
python tools/monitor.py --project-id roadsense-v29lab
```

Alternatif tanpa Python:
- `mosquitto_sub -h broker.hivemq.com -p 8883 --capath /etc/ssl/certs -t "roadsense/roadsense-v29lab/#" -v`
- HiveMQ WebSocket client di browser (host `broker.hivemq.com`, port `8884`, SSL aktif).

---

## A. Uji otomatis

### T0 — Unit test edge A
| | |
|---|---|
| Langkah | `python -m unittest discover -s tests -v` |
| Cakupan | Pemilihan nama sensor, gyroscope tidak tersedia, output `termux-sensor` kosong, parsing JSON sensor, perhitungan RMS/jerk/rotasi dengan data sintetis, klasifikasi `NORMAL`/`BUMP_SUSPECTED`/`DEVICE_MOVEMENT`/`SENSOR_ERROR`, cooldown event, parser `SET_THRESHOLD` (target A diterapkan, target B diabaikan), nama topic |
| Tidak dicakup | Sensor fisik, koneksi MQTT, edge B, dashboard |
| Diharapkan | `Ran 10 tests ... OK` |
| Catatan | Sudah lulus di mesin review (Linux, Python 3.13). Jalankan ulang di perangkat sendiri dan lampirkan hasilnya. |
| Bukti | `t0_unittest.png` |
| Hasil | ☐ Lulus ☐ Gagal — catatan: |

---

## B. Uji fisik wajib

### T1 — Sensor nyata di kedua edge
| | |
|---|---|
| Langkah | 1) Di Termux: `termux-sensor -l`. 2) `python -m edge_phone.main --project-id roadsense-v29lab --list-sensors` → catat `selected_accelerometer` dan `selected_gyroscope`. 3) `python -m edge_phone.main --project-id roadsense-v29lab --check-once` saat ponsel diam, lalu ulangi sambil mengetuk alas. 4) Di laptop: `python edge_laptop/camera_edge.py --project-id roadsense-v29lab --preview`, lalu lambaikan tangan di depan kamera |
| Diharapkan | A memilih accelerometer dan gyroscope (bukan `null`); `--check-once` mencetak `TELEMETRY:` dengan status selain `SENSOR_ERROR`, dan nilainya berbeda antara kondisi diam dan diketuk. B mencetak `[CAM] Webcam open`, dan nilai `score`/`peak` naik saat ada gerakan |
| Bukti | `t1_termux_sensor_list.png`, `t1_check_once.png`, `t1_edge_b_log.png` |
| Nilai terukur | Jumlah sampel per jendela A (dari log `DEBUG`, opsional): ____ · Laju frame B: ____ fps |
| Hasil | ☐ Lulus ☐ Gagal — catatan: |

### T2 — Telemetri independen ke topic berbeda melalui cloud
| | |
|---|---|
| Langkah | Jalankan edge A, edge B, dan `tools/monitor.py`; biarkan berjalan 60 detik |
| Diharapkan | Topic `.../edge/A/telemetry` hanya berisi `"device_id":"A","sensor":"imu"`; topic `.../edge/B/telemetry` hanya berisi `"device_id":"B","sensor":"webcam"`; `ts_ms` berupa epoch milidetik (13 digit); `seq` bertambah |
| Bukti | `t2_monitor.png` |
| Nilai terukur | Pesan A per menit: ____ · Pesan B per menit: ____ |
| Hasil | ☐ Lulus ☐ Gagal — catatan: |

### T3 — Kedua data tampil di dashboard dengan waktu terakhir diterima
| | |
|---|---|
| Langkah | `python -m http.server 8000`, buka `http://localhost:8000/dashboard/`, lalu Connect |
| Diharapkan | Kartu A dan B **Fresh**; nilai dan `seq` bergerak; *Last received* diperbarui; penghitung *Rejected* tetap 0 |
| Bukti | `t3_dashboard_both_fresh.png` |
| Nilai terukur | *Missed seq* A: ____ · B: ____ (setelah ____ menit) |
| Hasil | ☐ Lulus ☐ Gagal — catatan: |

### T4 — Event getaran A sampai ke dashboard dan log B
| | |
|---|---|
| Langkah | Ponsel diam di alas empuk selama 10 detik, lalu ketuk ringan alas 3–5 kali |
| Diharapkan | Status A `BUMP_SUSPECTED`; event `BUMP_SUSPECTED` (severity `WARNING`) muncul di *Event timeline*; terminal edge B mencetak `[SHARED EVENT] from edge A: BUMP_SUSPECTED` |
| Bukti | `t4_event_timeline.png`, `t4_edge_b_log_event.png` |
| Nilai terukur | `vibration_rms` diam: ____ · saat diketuk: ____ · `peak_jerk` saat diketuk: ____ |
| Hasil | ☐ Lulus ☐ Gagal — catatan: |

### T5 — Control → ACK → ambang berubah
| | |
|---|---|
| Langkah | 1) Kirim `SET_THRESHOLD` ke A dari dashboard. 2) Kirim `SET_THRESHOLD` ke B dengan nilai 0,1–150. 3) Ulangi ketukan/gerakan yang sama seperti sebelumnya |
| Diharapkan | Kotak ACK hijau dengan nilai yang diterapkan; *Applied thresholds* dan garis putus-putus berubah; log A mencetak `Applied SET_THRESHOLD`, log B mencetak `[CONTROL] B motion_score_threshold = ...`; perilaku status berubah sesuai ambang baru |
| Bukti | `t5_ack_a.png`, `t5_ack_b.png` |
| Nilai terukur | Round-trip ACK A: ____ ms · B: ____ ms (ditampilkan dashboard) |
| Hasil | ☐ Lulus ☐ Gagal — catatan: |

### T6 — Rotasi menghasilkan DEVICE_MOVEMENT
| | |
|---|---|
| Langkah | Putar ponsel dengan tangan di atas alas selama 2–3 detik |
| Diharapkan | Status A `DEVICE_MOVEMENT` (bukan `BUMP_SUSPECTED`) dan event `DEVICE_MOVEMENT` (severity `INFO`) |
| Bukti | `t6_device_movement.png` |
| Nilai terukur | `rotation_rms` saat diputar: ____ rad/s |
| Hasil | ☐ Lulus ☐ Gagal — catatan: |

### T7 — Kelengkapan repository, presentasi, dan video
| | |
|---|---|
| Periksa | README berisi perintah yang berhasil dijalankan; presentasi 8 slide berisi hasil nyata; video ±3 menit sesuai `demo_script.md` dan memuat disclaimer |
| Hasil | ☐ Lulus ☐ Gagal — catatan: |

---

## C. Uji ketahanan (tambahan)

### T8 — Deteksi stale
Hentikan edge B (Ctrl+C) selama 15 detik, lalu jalankan lagi.
**Diharapkan:** kartu B berubah menjadi **Stale** setelah lebih dari 5 detik (dapat diatur di *Stale after*) dan dashboard mencatatnya di log; kartu kembali **Fresh** saat edge berjalan lagi. Karena `seq` dimulai ulang dari 1, dashboard mencatat "edge restarted or duplicate".
Bukti: `t8_stale.png` · Hasil: ☐ Lulus ☐ Gagal

### T9 — Isolasi target
Kirim `SET_THRESHOLD` ke A.
**Diharapkan:** hanya `ack/A` yang datang, dan log edge B tidak mencetak `[CONTROL]`.
Hasil: ☐ Lulus ☐ Gagal

### T10 — ACK timeout
Hentikan edge A, lalu kirim `SET_THRESHOLD` ke A.
**Diharapkan:** setelah 10 detik dashboard menampilkan "No ACK from edge A within 10 s".
Hasil: ☐ Lulus ☐ Gagal

### T11 — Nilai ambang ditolak edge B
Kirim `motion_score_threshold` = 200 ke B dari dashboard.
**Diharapkan:** ACK B dengan `success:false` dan `error` "out of range (0.1..150.0)"; dashboard menampilkan kotak merah; ambang lama tetap berlaku.
Hasil: ☐ Lulus ☐ Gagal

### T12 — Reconnect jaringan
Matikan WiFi laptop selama 10 detik, lalu nyalakan lagi.
**Diharapkan:** indikator berubah menjadi *Reconnecting…* lalu *Connected*, dan data kembali mengalir tanpa memuat ulang halaman. Catat juga apakah edge B dan edge A tersambung kembali tanpa di-restart.
Hasil: ☐ Lulus ☐ Gagal — catatan:

### T13 — Penolakan payload yang tidak sesuai kontrak (uji robustness, BUKAN data sensor)
> ⚠ Pesan di bawah **sengaja dibuat salah** untuk menguji validasi dashboard. Jalankan dengan PROJECT_ID terpisah (misalnya `roadsense-v29lab-test`), **jangan** saat merekam demo, dan **jangan** gunakan screenshot-nya sebagai bukti sensor.
```bash
mosquitto_pub -h broker.hivemq.com -p 8883 --capath /etc/ssl/certs \
  -t "roadsense/roadsense-v29lab-test/edge/A/telemetry" -m '{"device_id":"B","sensor":"imu"}'
mosquitto_pub -h broker.hivemq.com -p 8883 --capath /etc/ssl/certs \
  -t "roadsense/roadsense-v29lab-test/edge/B/telemetry" -m 'bukan json'
```
**Diharapkan** (dashboard terhubung ke `roadsense-v29lab-test`): penghitung *Rejected* bertambah 2, *Activity log* menyebut alasannya (`device_id must be "A"…`, `not valid JSON`), dan kartu tetap "No data yet".
Hasil: ☐ Lulus ☐ Gagal

### T14 — Anti-spam event
Ketuk alas terus-menerus selama 10 detik.
**Diharapkan:** event A tidak dikirim di setiap jendela. Dengan cooldown default 3 detik, selama status `BUMP_SUSPECTED` berlanjut event muncul kira-kira setiap 3 detik.
Nilai terukur: jumlah event dalam 10 detik: ____
Hasil: ☐ Lulus ☐ Gagal

---

## Ringkasan (isi setelah semua uji)
| Uji | Hasil | Tanggal | Penguji |
|---|---|---|---|
| T0 | | | |
| T1 | | | |
| T2 | | | |
| T3 | | | |
| T4 | | | |
| T5 | | | |
| T6 | | | |
| T7 | | | |
| T8–T14 | | | |
