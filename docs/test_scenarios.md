# Skenario dan Hasil Pengujian

Dokumen ini berisi prosedur uji RoadSense Lab beserta hasilnya. Hasil yang dicatat hanya yang didukung screenshot di `docs/screenshots/` atau output program. Informasi yang dilaporkan tim tetapi belum memiliki screenshot di repository ditandai *(dilaporkan, belum ada screenshot)*. Uji yang belum dilakukan ditandai **Belum diuji**.

Semua perintah dijalankan dari root repository. `python` berarti interpreter di `.venv` pada laptop, atau `python` bawaan Termux pada ponsel. **Di PowerShell Windows, gunakan `.\.venv\Scripts\python.exe` sebagai pengganti `python` pada perintah laptop apabila `.venv` belum diaktifkan.**

## Lingkungan uji

| | |
|---|---|
| Tanggal | 29 Oktober 2026 (WIB) |
| Skenario | Simulasi di atas meja; tidak ada uji di kendaraan atau di jalan |
| Edge A | Ponsel Android dengan Termux + Termux:API. Sensor: `ICM42632M Accelerometer` dan `ICM42632M Gyroscope`; gyroscope diset manual dengan `export GYRO_SENSOR_NAME="ICM42632M Gyroscope"` karena pemilihan otomatis memilih `VDIS Gyroscope` *(dilaporkan, belum ada screenshot)* |
| Edge B | Laptop Windows dengan webcam, Python `.venv`, OpenCV |
| Broker | `broker.hivemq.com` (TLS 8883 untuk Python, WSS 8884 untuk dashboard) |
| PROJECT_ID | `roadsense-v29lab` |
| Dashboard | `python -m http.server 8000 --bind 127.0.0.1` dari root repository, dibuka di `http://localhost:8000/dashboard/` |

## Alat verifikasi independen (selain dashboard)

Pantau semua pesan proyek langsung dari broker:
```bash
python tools/monitor.py --project-id roadsense-v29lab
```

Alternatif tanpa Python:
- `mosquitto_sub -h broker.hivemq.com -p 8883 --capath /etc/ssl/certs -t "roadsense/roadsense-v29lab/#" -v`
- HiveMQ WebSocket client di browser (host `broker.hivemq.com`, port `8884`, SSL aktif).

---

## Ringkasan hasil

| Uji | Hasil | Bukti |
|---|---|---|
| T0 Unit test edge A | Lulus (10/10, lingkungan review Linux) | output terminal, belum ada screenshot |
| T1 Sensor nyata A & B | Lulus | `t4_event_b_ke_a.jpeg`, `t4_event_a_ke_b.png` |
| T2 Telemetri independen melalui cloud | Lulus | `t4_event_b_ke_a.jpeg`, `t3_dashboard_both_fresh.png` |
| T3 Dashboard menampilkan A & B | Lulus | `t3_dashboard_both_fresh.png` |
| T4 Event lintas perangkat A → B dan B → A | Lulus | `t4_event_a_ke_b.png`, `t4_event_b_ke_a.jpeg` |
| T5 Kontrol dua arah dan ACK | Lulus | `t5_edge_a_ack.png`, `t5_edge_b_ack.png` |
| T6 Rotasi menghasilkan `DEVICE_MOVEMENT` | Sebagian | `t4_event_a_ke_b.png` |
| T7 Kelengkapan repository, PPT, video | Belum selesai | — |
| T8–T14 Uji ketahanan | Belum diuji | — |

---

## A. Uji otomatis

### T0 — Unit test edge A
| | |
|---|---|
| Langkah | `python -m unittest discover -s tests -v` |
| Cakupan | Pemilihan nama sensor, gyroscope tidak tersedia, output `termux-sensor` kosong, parsing JSON sensor, perhitungan RMS/jerk/rotasi dengan data sintetis, klasifikasi `NORMAL`/`BUMP_SUSPECTED`/`DEVICE_MOVEMENT`/`SENSOR_ERROR`, cooldown event, parser `SET_THRESHOLD` (target A diterapkan, target B diabaikan), nama topic |
| Tidak dicakup | Sensor fisik, koneksi MQTT, edge B, dashboard |
| Diharapkan | `Ran 10 tests ... OK` |
| **Hasil** | **Lulus.** `Ran 10 tests ... OK` di lingkungan review (Linux, Python 3.13). Belum dijalankan di Android. |
| Bukti | Output terminal. Screenshot `t0_unittest.png` belum dibuat (opsional). |

---

## B. Uji fisik

### T1 — Sensor nyata di kedua edge
| | |
|---|---|
| Langkah | 1) Di Termux: `termux-sensor -l`. 2) `export GYRO_SENSOR_NAME="<nama gyroscope fisik>"`, lalu `python -m edge_phone.main --project-id roadsense-v29lab --list-sensors`. 3) `python -m edge_phone.main --project-id roadsense-v29lab --check-once`. 4) Di laptop: `python edge_laptop/camera_edge.py --project-id roadsense-v29lab --preview`, lalu gerakkan tangan di depan kamera |
| Diharapkan | Edge A menghasilkan nilai dari accelerometer dan gyroscope. Edge B membuka webcam dan nilai `score`/`peak` berubah saat ada gerakan |
| **Hasil** | **Lulus.** Log edge A mencatat telemetri nyata, misalnya `"vibration_rms":0.17,"peak_jerk":31.19,"rotation_rms":0.24`. Nilai `rotation_rms` yang tidak nol menunjukkan data gyroscope terbaca. Log edge B mencatat `score`, `peak`, dan `delta` setiap ±1 detik, berubah dari `NORMAL` ke `MOTION_OBSERVED` saat ada gerakan |
| Bukti | `t4_event_b_ke_a.jpeg` (log edge A), `t4_event_a_ke_b.png` (log edge B). Screenshot `termux-sensor -l` / `--list-sensors` belum ada di repository |
| Nilai terukur | Laju sampling A dan fps B: belum diukur |

### T2 — Telemetri independen ke topic berbeda melalui cloud
| | |
|---|---|
| Langkah | Jalankan edge A, edge B, dan `tools/monitor.py` atau dashboard |
| Diharapkan | Telemetri A di `.../edge/A/telemetry` dengan `"device_id":"A","sensor":"imu"`; telemetri B di `.../edge/B/telemetry` dengan `"device_id":"B","sensor":"webcam"`; `ts_ms` berupa epoch milidetik; `seq` bertambah |
| **Hasil** | **Lulus.** Log edge A menunjukkan `PUB roadsense/roadsense-v29lab/edge/A/telemetry` dengan `"device_id":"A","sensor":"imu","seq":2803,"ts_ms":1793280858979`. Dashboard menerima telemetri A dan B bersamaan melalui broker. `tools/monitor.py` juga menerima kedua topic *(dilaporkan, belum ada screenshot)* |
| Bukti | `t4_event_b_ke_a.jpeg`, `t3_dashboard_both_fresh.png` |
| Nilai terukur | Pesan per menit: belum diukur |

### T3 — Kedua data tampil di dashboard dengan waktu terakhir diterima
| | |
|---|---|
| Langkah | `python -m http.server 8000 --bind 127.0.0.1`, buka `http://localhost:8000/dashboard/`, isi PROJECT_ID, lalu Connect |
| Diharapkan | Kartu A dan B *Fresh*; nilai dan `seq` bergerak; penghitung *Rejected* tetap 0 |
| **Hasil** | **Lulus.** Status *Connected*, base topic `roadsense/roadsense-v29lab`, kartu A dan B *Fresh* dengan status `NORMAL`, grafik real-time tampil, `Messages 80 · Rejected 0`. Nilai saat screenshot: A `vibration_rms` 0,050, `peak_jerk` 1,120, `rotation_rms` 0,000; B `motion_score` 1,18, `motion_delta` 0,45 |
| Bukti | `t3_dashboard_both_fresh.png` |
| Nilai terukur | *Missed seq*: tidak terlihat pada screenshot |

### T4 — Event lintas perangkat A → B dan B → A
| | |
|---|---|
| Langkah | 1) Ketuk ringan alas ponsel sampai edge A berstatus `BUMP_SUSPECTED`, lalu periksa log edge B. 2) Gerakkan tangan di depan webcam sampai edge B berstatus `MOTION_OBSERVED`, lalu periksa log edge A |
| Diharapkan | Log edge B mencetak `[SHARED EVENT] from edge A: ...`; log edge A mencetak `[CROSS-EDGE EVENT from B] ...` |
| **Hasil** | **Lulus.** Log edge B mencetak `[SHARED EVENT] from edge A: BUMP_SUSPECTED` dan beberapa `[SHARED EVENT] from edge A: DEVICE_MOVEMENT`. Log edge A mencetak `[CROSS-EDGE EVENT from B] type=MOTION_OBSERVED severity=INFO detail=Visual motion in tabletop camera view` pada pukul 20:34:18 WIB. Event dari A juga terekam di `tools/monitor.py` dengan severity `WARNING` *(dilaporkan, belum ada screenshot)* |
| Bukti | `t4_event_a_ke_b.png` (A → B), `t4_event_b_ke_a.jpeg` (B → A) |
| Belum didokumentasikan | Tampilan event di *Event timeline* dashboard (opsional) |

### T5 — Control → ACK → ambang berubah
| | |
|---|---|
| Langkah | 1) Kirim `SET_THRESHOLD` ke A dari dashboard. 2) Kirim `SET_THRESHOLD` ke B dengan nilai 0,1–150 |
| Diharapkan | Kotak ACK hijau dengan nilai yang diterapkan dan waktu round trip |
| **Hasil** | **Lulus.** Edge A: `✓ Edge A applied vibration_rms_threshold = 1, jerk_peak_threshold = 4`, round trip **1786 ms**, ACK ts 20:18:40.619. Edge B: `✓ Edge B applied motion_score_threshold = 5`, round trip **1173 ms**, ACK ts 20:17:09.424 |
| Catatan | Percobaan pertama ke edge B sempat menampilkan *No ACK from edge B within 10 s*, lalu berhasil saat diulang *(dilaporkan, belum ada screenshot)*. Ambang B kemudian diubah ke 1,5 untuk memicu event T4 *(dilaporkan)*. Perubahan perilaku status setelah ambang baru belum didokumentasikan dengan screenshot terpisah |
| Bukti | `t5_edge_a_ack.png`, `t5_edge_b_ack.png` |

### T6 — Rotasi menghasilkan DEVICE_MOVEMENT
| | |
|---|---|
| Langkah | Putar ponsel dengan tangan di atas alas selama 2–3 detik |
| Diharapkan | Status A `DEVICE_MOVEMENT` (bukan `BUMP_SUSPECTED`) dan event `DEVICE_MOVEMENT` (severity `INFO`) |
| **Hasil** | **Sebagian.** Log edge B menerima beberapa event `DEVICE_MOVEMENT` dari edge A. Berdasarkan kode, status ini hanya muncul jika `rotation_rms` ≥ ambang rotasi. Namun uji rotasi terkontrol dengan catatan nilai `rotation_rms` belum didokumentasikan |
| Bukti | `t4_event_a_ke_b.png` |
| Nilai terukur | `rotation_rms` saat diputar: belum dicatat |

### T7 — Kelengkapan repository, presentasi, dan video
| | |
|---|---|
| Periksa | README berisi perintah yang berhasil dijalankan; presentasi memuat masalah dan ide, arsitektur, sensor, processing dan algoritma, cloud, pengujian, serta link GitHub; video demo memuat disclaimer |
| **Hasil** | **Belum selesai.** Video belum direkam, PPT masih difinalkan, dan dokumen serta screenshot terbaru belum dipastikan sudah di-push ke GitHub |

---

## C. Uji ketahanan (tambahan) — belum diuji

| Uji | Langkah | Yang diharapkan | Hasil |
|---|---|---|---|
| T8 Deteksi stale | Hentikan edge B selama 15 detik, lalu jalankan lagi | Kartu B berubah *Stale* setelah lebih dari 5 detik, lalu *Fresh* lagi; dashboard mencatat `seq` dimulai ulang | Belum diuji |
| T9 Isolasi target | Kirim `SET_THRESHOLD` ke A | Hanya `ack/A` yang datang; log B tidak mencetak `[CONTROL]` | Belum diuji |
| T10 ACK timeout | Hentikan edge A, lalu kirim `SET_THRESHOLD` ke A | Setelah 10 detik muncul "No ACK from edge A within 10 s" | Belum diuji dengan prosedur ini (lihat catatan T5) |
| T11 Ambang B di luar rentang | Kirim `motion_score_threshold` = 200 ke B | ACK `success:false`, `error` "out of range (0.1..150.0)", ambang lama tetap berlaku | Belum diuji |
| T12 Reconnect jaringan | Matikan WiFi laptop selama 10 detik, lalu nyalakan lagi | Dashboard *Reconnecting…* lalu *Connected*; data kembali mengalir | Belum diuji |
| T13 Payload tidak valid | Lihat perintah di bawah, gunakan PROJECT_ID terpisah | *Rejected* bertambah 2 dan alasannya tercatat di *Activity log* | Belum diuji |
| T14 Anti-spam event | Ketuk alas terus-menerus selama 10 detik | Event A muncul kira-kira setiap 3 detik, bukan setiap jendela | Belum diuji |

Perintah T13. Pesan ini **sengaja dibuat salah** untuk menguji validasi dashboard. Jangan jalankan saat merekam demo, dan jangan gunakan hasilnya sebagai bukti sensor:
```bash
mosquitto_pub -h broker.hivemq.com -p 8883 --capath /etc/ssl/certs \
  -t "roadsense/roadsense-v29lab-test/edge/A/telemetry" -m '{"device_id":"B","sensor":"imu"}'
mosquitto_pub -h broker.hivemq.com -p 8883 --capath /etc/ssl/certs \
  -t "roadsense/roadsense-v29lab-test/edge/B/telemetry" -m 'bukan json'
```

---

## Pengamatan dari pengujian

- `peak_jerk` jauh lebih sensitif daripada `vibration_rms`. Log edge A mencatat `vibration_rms` 0,17 dengan `peak_jerk` 31,19. Penyebab yang paling mungkin adalah Δt yang dihitung dari waktu penerimaan sampel dengan batas minimum 5 ms (lihat `SPEC.md` §4.2). Untuk demo, `jerk_peak_threshold` sebaiknya dinaikkan sampai status ponsel diam tetap `NORMAL`.
- Edge B menentukan status dari nilai puncak jendela. Log B mencatat `score=2.90 peak=6.46 ... MOTION_OBSERVED`, artinya status bisa `MOTION_OBSERVED` meskipun rata-ratanya rendah.
- Ambang yang diubah lewat dashboard tidak disimpan. Setelah edge dijalankan ulang, ambang perlu dikirim ulang.
- Semua angka di dokumen ini berasal dari satu sesi uji fungsional. Angka ini bukan hasil kalibrasi atau pengukuran akurasi.
