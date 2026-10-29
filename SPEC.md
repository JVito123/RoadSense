# Spesifikasi Teknis RoadSense Lab

Versi dokumen 2.0 · selaras dengan paket `edge_phone` 2.0.0, `edge_laptop/camera_edge.py`, `dashboard/`, dan `tools/`.

Dokumen ini menjelaskan peran perangkat, algoritma pemrosesan di edge, dan kontrak MQTT yang diimplementasikan. Nama topic, nama field JSON, dan nilai status di dokumen ini adalah kontrak antar-komponen dan tidak boleh diubah sepihak oleh salah satu komponen.

## 1. Tujuan dan batasan

RoadSense Lab adalah prototipe IoT dengan **dua edge device**, **tiga jenis sensor**, dan komunikasi **dua arah** melalui broker MQTT cloud. Prototipe ini dipakai untuk memantau pola getaran dan konteks gerak visual dalam **simulasi terkendali di atas meja**.

Prototipe ini **tidak** dimaksudkan sebagai:
- detektor lubang atau kerusakan jalan yang tervalidasi;
- alat ukur kualitas jalan atau sistem pemetaan jalan;
- sistem peringatan berbasis lokasi. Tidak ada GPS, sehingga tidak ada informasi posisi maupun peringatan "di depan rute".

## 2. Komponen dan peran

| ID | Perangkat | Sensor | Pemrosesan lokal | Implementasi |
|---|---|---|---|---|
| **A** | Ponsel Android (Termux + Termux:API) | Accelerometer, gyroscope (`sensor: "imu"`) | Vibration RMS, peak jerk, rotation RMS, klasifikasi berbasis aturan | `edge_phone/` (dijalankan dengan `python -m edge_phone.main`) |
| **B** | Laptop dengan webcam internal/USB (OpenCV) | Webcam (`sensor: "webcam"`) | Frame differencing grayscale, agregasi per jendela 1 detik, klasifikasi berbasis aturan | `edge_laptop/camera_edge.py` |
| — | Dashboard browser | — | Validasi dan visualisasi pesan, pengiriman perintah ambang | `dashboard/` |
| — | Alat bantu CLI | — | Memantau topic dan mengirim perintah tanpa dashboard | `tools/monitor.py`, `tools/send_control.py` |

- ID `A` selalu ponsel (IMU) dan ID `B` selalu laptop (webcam). Keduanya tidak pernah ditukar.
- Ketiga jenis sensor adalah accelerometer, gyroscope, dan webcam.
- Laptop diperlakukan sebagai edge karena melakukan akuisisi webcam dan pemrosesan frame secara lokal. Dashboard tidak dihitung sebagai edge, meskipun berjalan di laptop yang sama.
- Ponsel dan laptop berada di jaringan WiFi/hotspot yang sama. Masing-masing terhubung **langsung dan independen** ke broker cloud; tidak ada komunikasi langsung antar-perangkat di jaringan lokal.

## 3. Kebutuhan fungsional

1. Setiap edge membaca sensor fisiknya sendiri. Tidak ada data sensor yang disimulasikan.
2. Dua metode pemrosesan data yang berbeda:
   - Edge A: vibration RMS dan peak jerk dari accelerometer, ditambah rotation RMS dari gyroscope.
   - Edge B: frame differencing pada frame grayscale yang diperkecil, lalu dirata-ratakan per jendela 1 detik.
3. Keputusan berbasis aturan dengan ambang yang dapat diubah:
   - Edge A: `NORMAL`, `BUMP_SUSPECTED`, `DEVICE_MOVEMENT`, `SENSOR_ERROR`.
   - Edge B: `NORMAL`, `MOTION_OBSERVED`.
4. Komunikasi MQTT over TLS: telemetri dari kedua edge, event lintas perangkat, perintah dashboard → edge, dan ACK edge → dashboard.
5. Hanya ringkasan numerik yang dikirim ke broker. Tidak ada gambar, video, nama, atau lokasi.

## 4. Edge A — pemrosesan IMU

### 4.1 Akuisisi sensor
- Nama sensor dicari otomatis dengan `termux-sensor -l`. Sensor yang mengandung kata `accelerometer` dan `gyroscope` dipilih; varian yang mengandung `uncalibrated`, `linear`, `gravity`, `wakeup`, `tilt`, atau `step` diprioritaskan paling akhir. Di antara kandidat dengan prioritas sama, nama terpendek yang dipilih.
- Nama sensor dapat dipaksa melalui variabel lingkungan `ACCEL_SENSOR_NAME` dan `GYRO_SENSOR_NAME`. Pada ponsel uji, aturan nama terpendek memilih `VDIS Gyroscope`, bukan sensor gyroscope chip IMU `ICM42632M Gyroscope`, sehingga `GYRO_SENSOR_NAME="ICM42632M Gyroscope"` diset manual.
- Pembacaan berjalan sebagai stream latar belakang `termux-sensor -s <accel>,<gyro> -d <SENSOR_DELAY_MS>` (default 50 ms, minimum 20 ms). Buffer menyimpan maksimum 64 sampel per sensor.
- Satu jendela berisi semua sampel yang masuk sejak pembacaan sebelumnya, minimal `SAMPLES_PER_WINDOW` (default 8). Bila sampel kurang sampai batas `SENSOR_TIMEOUT_SEC` (default 4 detik), program memakai sampel yang tersedia atau melakukan pembacaan sekali jalan `termux-sensor ... -n <jumlah>`.
- Timestamp sampel adalah waktu sampel diterima oleh program (`time.time()`), bukan timestamp perangkat keras sensor.
- Jika gyroscope tidak ditemukan, program tetap berjalan dengan `rotation_rms = 0.0`. Dalam kondisi ini status `DEVICE_MOVEMENT` tidak dapat muncul.
- Telemetri dipublikasikan kira-kira setiap `PUBLISH_INTERVAL_SEC` (default 1 detik).

### 4.2 Perhitungan
Untuk sampel accelerometer *aᵢ = (xᵢ, yᵢ, zᵢ)* dan gyroscope *ωᵢ*, dengan *g* = 9,80665 m/s²:

| Besaran | Rumus | Satuan |
|---|---|---|
| `vibration_rms` | √( mean( (‖aᵢ‖ − g)² ) ) | m/s² |
| `peak_jerk` | max ‖aᵢ − aᵢ₋₁‖ / Δtᵢ | m/s³ |
| `rotation_rms` | √( mean( ‖ωᵢ‖² ) ) | rad/s |

Ketentuan `peak_jerk`:
- Sampel terakhir dari jendela sebelumnya ikut dipakai agar perhitungan antar-jendela tetap kontinu.
- Bila Δt ≤ 1 ms atau Δt > 2 s, dipakai Δt default sebesar `SENSOR_DELAY_MS`. Δt minimum adalah 5 ms.
- Karena Δt berasal dari waktu penerimaan, nilai jerk merupakan **perkiraan** yang dipengaruhi jitter.

Nilai yang dipublikasikan dibulatkan ke 2 angka desimal.

### 4.3 Aturan klasifikasi (dievaluasi berurutan)
1. `SENSOR_ERROR` — pembacaan gagal, jendela tanpa sampel accelerometer, atau ada nilai tidak hingga.
2. `DEVICE_MOVEMENT` — `rotation_rms ≥ rotation_rms_threshold`. Status ini menandai artefak gerakan atau rotasi ponsel oleh tangan.
3. `BUMP_SUSPECTED` — `vibration_rms ≥ vibration_rms_threshold` **atau** `peak_jerk ≥ jerk_peak_threshold`.
4. `NORMAL` — selain kondisi di atas.

Karena `DEVICE_MOVEMENT` dievaluasi lebih dahulu, getaran yang terjadi saat ponsel diputar akan diklasifikasikan sebagai `DEVICE_MOVEMENT`, bukan `BUMP_SUSPECTED`.

### 4.4 Konfigurasi
Konfigurasi dibaca dari variabel lingkungan saat program dimulai. `--project-id` mengesampingkan `PROJECT_ID`. File `.env` **tidak** dibaca otomatis.

| Variabel | Default | Keterangan |
|---|---|---|
| `PROJECT_ID` | `roadsense-demo01` | Huruf kecil, angka, tanda hubung |
| `MQTT_BROKER_HOST` | `broker.hivemq.com` | |
| `MQTT_BROKER_PORT` | `8883` | TLS |
| `VIBRATION_RMS_THRESHOLD` | `0.8` | m/s²; dapat diubah lewat MQTT |
| `JERK_PEAK_THRESHOLD` | `3.0` | m/s³; dapat diubah lewat MQTT |
| `ROTATION_RMS_THRESHOLD` | `0.8` | rad/s; **hanya** lewat variabel lingkungan |
| `EVENT_COOLDOWN_SEC` | `3.0` | detik |
| `PUBLISH_INTERVAL_SEC` | `1.0` | detik |
| `SENSOR_DELAY_MS` | `50` | interval yang diminta ke `termux-sensor` |
| `SAMPLES_PER_WINDOW` | `8` | sampel accelerometer minimum per jendela |
| `SENSOR_TIMEOUT_SEC` | `4.0` | batas tunggu pembacaan sensor |
| `ACCEL_SENSOR_NAME`, `GYRO_SENSOR_NAME` | kosong | memaksa nama sensor tertentu |

Nilai ambang default bersifat sementara dan belum dikalibrasi terhadap data berlabel.

## 5. Edge B — pemrosesan webcam

### 5.1 Alur per frame
1. Frame dibaca dari kamera (`--camera`, default indeks `0`).
2. Frame dikonversi ke grayscale dan diperkecil menjadi 160 × 120 piksel.
3. `score = mean(|frameₜ − frameₜ₋₁|)` — rata-rata selisih intensitas absolut antara dua frame berurutan. Rentang teoretisnya 0–255.
4. `delta = |scoreₜ − scoreₜ₋₁|`.

Frame mentah tidak disimpan dan tidak dikirim. Opsi `--preview` hanya menampilkan gambar kamera di layar laptop.

### 5.2 Agregasi dan klasifikasi per jendela ±1 detik
| Nilai | Definisi | Dikirim sebagai |
|---|---|---|
| `mean_score` | rata-rata `score` dalam jendela | `motion_score` (3 desimal) |
| `mean_delta` | rata-rata `delta` dalam jendela | `motion_delta` (3 desimal) |
| `peak_score` | `score` tertinggi dalam jendela | tidak dikirim; hanya dicetak di log |

Aturan status: `MOTION_OBSERVED` bila `peak_score ≥ motion_score_threshold`, selain itu `NORMAL`.

> Catatan: status ditentukan oleh **puncak** jendela, sedangkan `motion_score` yang dikirim adalah **rata-rata** jendela. Karena itu `MOTION_OBSERVED` dapat muncul walaupun `motion_score` di dashboard berada di bawah ambang.

- `motion_score` bukan satuan fisik terkalibrasi dan sensitif terhadap perubahan cahaya serta auto-exposure kamera.
- Loop memberi jeda 60 ms di antara frame. Laju frame aktual bergantung pada kamera dan belum diukur.
- Status `SENSOR_ERROR` termasuk dalam kontrak, tetapi **tidak** dipublikasikan oleh implementasi saat ini. Jika frame gagal dibaca, program mencetak pesan lalu mencoba lagi; dashboard akan menampilkan edge B sebagai *Stale*. Jika kamera gagal dibuka saat start, program berhenti dengan pesan galat.

### 5.3 Parameter CLI
| Opsi | Default | Keterangan |
|---|---|---|
| `--project-id` | wajib | sama dengan edge A dan dashboard |
| `--camera` | `0` | indeks webcam |
| `--threshold` | `12.0` | ambang awal `motion_score_threshold`, rentang 0,1–150 |
| `--preview` | nonaktif | tampilkan jendela kamera lokal; tekan `q` untuk berhenti |

## 6. Kontrak MQTT

### 6.1 Broker dan identitas proyek
| Klien | Endpoint |
|---|---|
| Edge A, edge B, `tools/` (Python, paho-mqtt 2.x) | `broker.hivemq.com:8883` (MQTT 3.1.1 over TLS, sertifikat server diverifikasi) |
| Dashboard (MQTT.js 5.x via CDN) | `wss://broker.hivemq.com:8884/mqtt` |

`BASE = roadsense/{PROJECT_ID}`.

Gunakan `PROJECT_ID` yang sama di semua klien, dengan format **3–64 karakter berupa huruf kecil, angka, atau tanda hubung** (contoh `roadsense-abc123`). Format ini memenuhi validasi ketiga komponen: edge A menolak huruf besar, dashboard membatasi panjang 3–64 karakter, sedangkan edge B menerima huruf dan angka apa pun ditambah tanda hubung.

### 6.2 Topic
| Topic | Publisher | Subscriber | QoS publish |
|---|---|---|---|
| `BASE/edge/A/telemetry` | Edge A | Dashboard, `monitor.py` | 0 |
| `BASE/edge/B/telemetry` | Edge B | Dashboard, `monitor.py` | 0 |
| `BASE/events` | Edge A, edge B | Dashboard, edge A, edge B, `monitor.py` | 1 |
| `BASE/control` | Dashboard, `send_control.py` | Edge A, edge B | 1 |
| `BASE/ack/A` | Edge A | Dashboard, `monitor.py`, `send_control.py` | 1 |
| `BASE/ack/B` | Edge B | Dashboard, `monitor.py`, `send_control.py` | 1 |

Tidak ada pesan retained. Edge A mencatat event dari edge lain di log (`[CROSS-EDGE EVENT from B] ...`), dan edge B mencetak event dari edge lain (`[SHARED EVENT] from edge A: ...`).

### 6.3 Telemetri edge A
```json
{"device_id":"A","sensor":"imu","seq":1,"ts_ms":1790000000000,"vibration_rms":0.45,"peak_jerk":1.12,"rotation_rms":0.03,"status":"NORMAL"}
```

| Field | Tipe | Keterangan |
|---|---|---|
| `device_id` | string | selalu `"A"` |
| `sensor` | string | selalu `"imu"` |
| `seq` | integer | dimulai dari 1 dan bertambah setiap jendela; kembali ke 1 jika program dijalankan ulang |
| `ts_ms` | integer | Unix epoch dalam milidetik, diambil saat jendela diproses |
| `vibration_rms` | number | m/s², 2 desimal |
| `peak_jerk` | number | m/s³, 2 desimal |
| `rotation_rms` | number | rad/s, 2 desimal; `0.0` bila gyroscope tidak tersedia |
| `status` | string | `NORMAL`, `BUMP_SUSPECTED`, `DEVICE_MOVEMENT`, `SENSOR_ERROR` |

Pada `SENSOR_ERROR`, ketiga nilai numerik dikirim sebagai `0.0`.

### 6.4 Telemetri edge B
```json
{"device_id":"B","sensor":"webcam","seq":1,"ts_ms":1790000000000,"motion_score":2.4,"motion_delta":0.5,"status":"NORMAL"}
```

| Field | Tipe | Keterangan |
|---|---|---|
| `device_id` | string | selalu `"B"` |
| `sensor` | string | selalu `"webcam"` |
| `seq` | integer | dimulai dari 1, bertambah setiap jendela ±1 detik |
| `ts_ms` | integer | Unix epoch dalam milidetik |
| `motion_score` | number | rata-rata selisih intensitas per jendela, kira-kira 0–255, 3 desimal |
| `motion_delta` | number | rata-rata perubahan `score` antar-frame per jendela, 3 desimal |
| `status` | string | `NORMAL`, `MOTION_OBSERVED` (`SENSOR_ERROR` disediakan kontrak, belum dipakai) |

### 6.5 Event
```json
{"device_id":"A","ts_ms":1790000000000,"type":"BUMP_SUSPECTED","severity":"WARNING","detail":"Abnormal vibration in tabletop demonstration"}
```

| Sumber | `type` | `severity` | `detail` | Kapan dikirim |
|---|---|---|---|---|
| A | `BUMP_SUSPECTED` | `WARNING` | `Abnormal vibration in tabletop demonstration` | status bukan `NORMAL` **dan** (status berubah **atau** sudah ≥ `EVENT_COOLDOWN_SEC` sejak event A terakhir) |
| A | `DEVICE_MOVEMENT` | `INFO` | `Large device rotation/handling artifact in tabletop demonstration` | sama seperti di atas |
| A | `SENSOR_ERROR` | `ERROR` | alasan galat, atau `IMU sensor read failure on Edge A` | sama seperti di atas |
| B | `MOTION_OBSERVED` | `INFO` | `Visual motion in tabletop camera view` | status `MOTION_OBSERVED` **dan** (status sebelumnya berbeda **atau** > 12 detik sejak event B terakhir) |

Tidak ada event untuk status `NORMAL`. Selama kondisi non-`NORMAL` berlanjut, event diulang paling cepat setiap 3 detik untuk edge A dan setiap 12 detik untuk edge B.

### 6.6 Perintah kontrol
Ke edge A:
```json
{"command":"SET_THRESHOLD","target":"A","vibration_rms_threshold":0.8,"jerk_peak_threshold":3.0}
```
Ke edge B:
```json
{"command":"SET_THRESHOLD","target":"B","motion_score_threshold":12.0}
```

Setiap edge mengabaikan perintah dengan `target` lain. Nilai numerik boleh dikirim sebagai bilangan bulat atau pecahan; misalnya dashboard menulis `3.0` sebagai `3`.

| Aspek | Edge A | Edge B |
|---|---|---|
| Field yang dibaca | `vibration_rms_threshold`, `jerk_peak_threshold`. Salah satu boleh tidak ada; nilai yang tidak dikirim tetap memakai nilai lama | `motion_score_threshold` (wajib) |
| Validasi | bilangan hingga dan > 0 | bilangan hingga, 0,1–150 |
| Nilai yang diterapkan | dibulatkan ke 4 desimal | apa adanya |
| JSON rusak | diabaikan, tanpa ACK | diabaikan, tanpa ACK |
| `command` selain `SET_THRESHOLD` | ACK `success:false` | diabaikan, tanpa ACK |
| Kedua field ambang tidak ada | ACK `success:false` | ACK `success:false` dengan `error` |

Ambang `rotation_rms_threshold` edge A **tidak** dapat diubah lewat MQTT.

### 6.7 Acknowledgment
Edge A selalu menyertakan kedua ambang yang **sedang berlaku**: nilai baru jika berhasil, nilai lama jika gagal.
```json
{"device_id":"A","command":"SET_THRESHOLD","success":true,"vibration_rms_threshold":0.8,"jerk_peak_threshold":3.0,"ts_ms":1790000000000}
```
Edge B saat berhasil:
```json
{"device_id":"B","command":"SET_THRESHOLD","success":true,"motion_score_threshold":12.0,"ts_ms":1790000000000}
```
Edge B saat gagal; field ambang tidak disertakan:
```json
{"device_id":"B","command":"SET_THRESHOLD","success":false,"error":"out of range (0.1..150.0)","ts_ms":1790000000000}
```

## 7. Dashboard

- Berjalan di browser tanpa proses build. Library MQTT.js 5.x dimuat dari unpkg, dengan jsDelivr sebagai cadangan.
- Setiap pesan divalidasi terhadap kontrak di bagian 6: kecocokan `device_id` dengan topic, nilai `sensor`, `seq` berupa bilangan bulat ≥ 0, `ts_ms` berupa epoch milidetik, nilai `status`, dan field numerik. Pesan yang tidak valid tidak ditampilkan; pesan tersebut menambah penghitung *Rejected* dan alasannya dicatat di *Activity log*.
- Status kesegaran data: *Fresh*, atau *Stale* bila tidak ada telemetri lebih lama dari batas yang dapat diatur (default 5 detik, rentang 1–120 detik).
- Grafik menampilkan 60 detik terakhir dari sampel yang benar-benar diterima. Garis terputus saat ada jeda dan tidak ada interpolasi. Garis putus-putus pada grafik menunjukkan ambang yang dikonfirmasi lewat ACK.
- Untuk edge B, garis ambang dibandingkan secara visual dengan rata-rata `motion_score`, sedangkan edge B mengklasifikasi berdasarkan nilai puncak (lihat 5.2).
- Batas input form: A `vibration_rms_threshold` 0,001–100 dan `jerk_peak_threshold` 0,001–10000; B `motion_score_threshold` 0,001–255. Nilai B di luar 0,1–150 tetap dikirim, lalu ditolak edge B melalui ACK `success:false`.
- Bila ACK tidak diterima dalam 10 detik, dashboard menampilkan pesan *No ACK*.
- Hanya `PROJECT_ID` yang disimpan, yaitu di `localStorage` browser. Parameter URL `?project=<id>` mengisi kolom PROJECT_ID secara otomatis.

## 8. Keamanan dan privasi

- Koneksi ke broker dienkripsi TLS, tetapi broker publik **tidak memakai autentikasi**. Siapa pun yang mengetahui `PROJECT_ID` dapat membaca dan mempublikasikan pesan, termasuk perintah `SET_THRESHOLD`. Jangan gunakan PROJECT_ID yang mudah ditebak.
- Hanya ringkasan numerik yang dikirim. Tidak ada gambar, video, kata sandi, nama, identitas perangkat selain `A` atau `B`, maupun lokasi.
- Dashboard menampilkan teks dari pesan sebagai teks biasa (tanpa interpretasi HTML).

## 9. Kriteria penerimaan

Prosedur rinci ada di [`docs/test_scenarios.md`](docs/test_scenarios.md).

1. Edge A menampilkan accelerometer dan gyroscope melalui `--list-sensors` dan menghasilkan nilai nyata melalui `--check-once`. Edge B berhasil membuka webcam dan mempublikasikan statistik gerak.
2. Masing-masing edge mempublikasikan telemetri ke topic yang berbeda melalui broker cloud.
3. Dashboard menampilkan data kedua edge beserta waktu terakhir diterima.
4. Event getaran dari edge A diterima dashboard dan tercatat di log edge B.
5. Perintah `SET_THRESHOLD` ke A dan B menghasilkan ACK yang sesuai, dan ambang yang diterapkan berubah.
6. Repository, presentasi, dan video demo memuat bukti pengukuran nyata dan keterbatasan sistem secara jujur.

## 10. Keterbatasan

- Pengujian dibatasi pada skenario meja; belum ada uji di kendaraan atau di jalan.
- Ambang default dipilih manual dan belum dikalibrasi terhadap data berlabel. Tidak ada klaim akurasi maupun presisi.
- `vibration_rms` dihitung terhadap gravitasi standar, sehingga offset kalibrasi accelerometer ponsel dapat menghasilkan nilai dasar yang tidak nol saat ponsel diam.
- Laju sampling Termux:API terbatas dan tidak selalu stabil. Timestamp sampel berasal dari waktu penerimaan, sehingga `peak_jerk` bersifat perkiraan.
- Rotasi ponsel oleh tangan dapat memengaruhi pembacaan getaran. Status `DEVICE_MOVEMENT` hanya tersedia bila gyroscope ada.
- `motion_score` bersifat relatif terhadap kamera dan pencahayaan; nilai ini bukan inspeksi kondisi jalan.
- Tidak ada GPS, sehingga tidak ada peringatan berbasis lokasi.
- Sistem bergantung pada koneksi internet dan ketersediaan broker publik.
