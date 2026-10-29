# Skrip Demo (~3 menit) — Simulasi Meja, Tanpa Berkendara

Tujuan video: membuktikan **dua edge sensor yang hidup** (ponsel Android = A, laptop webcam = B) dan **komunikasi MQTT cloud dua arah**, sambil menyampaikan keterbatasan secara jujur.

## Keselamatan
- **Tidak ada pengambilan data di jalan atau di kendaraan.** Semua dilakukan di atas meja.
- Letakkan ponsel di atas **alas empuk** (handuk terlipat / bantal tipis), jauh dari tepi meja.
- Getaran = **ketukan ringan dengan jari** di meja/alas, bukan membanting ponsel.
- Kabel charger rapi agar tidak menarik ponsel/laptop.

## Privasi
- Arahkan webcam ke **permukaan meja** saja. Hindari wajah, layar lain, dokumen, atau benda yang menunjukkan lokasi.
- Ingat: yang dikirim edge B hanya angka (`motion_score`, `motion_delta`); tidak ada gambar ke broker.
- Jangan perlihatkan password WiFi, akun, atau notifikasi pribadi di layar saat merekam.

## Persiapan (sebelum merekam, ±10 menit)
1. Pakai PROJECT_ID yang **identik** di ponsel, laptop, dan dashboard. PROJECT_ID yang dipakai saat pengujian adalah `roadsense-v29lab`.
2. Ponsel dan laptop terhubung ke WiFi/hotspot yang sama dan punya internet.
3. Edge A (Termux, dari root repository):
   ```bash
   cd ~/RoadSense
   export GYRO_SENSOR_NAME="ICM42632M Gyroscope"
   python -m edge_phone.main --project-id roadsense-v29lab --check-once
   python -m edge_phone.main --project-id roadsense-v29lab
   ```
   `export` wajib diulang setiap kali Termux dibuka ulang. Tanpa itu, program memilih `VDIS Gyroscope` dan status `DEVICE_MOVEMENT` mungkin tidak muncul. Pastikan log menampilkan baris `PUB .../edge/A/telemetry` dan nilai `rotation_rms` tidak selalu 0 saat ponsel digerakkan.
4. Edge B (laptop, PowerShell):
   ```powershell
   .\.venv\Scripts\python.exe edge_laptop/camera_edge.py --project-id roadsense-v29lab --preview
   ```
   Pastikan muncul `[CAM] Webcam open`, `[MQTT] connect reason: ...`, dan baris `[B] seq=...`.
5. Dashboard: jalankan `.\.venv\Scripts\python.exe -m http.server 8000 --bind 127.0.0.1` dari root repository, buka `http://localhost:8000/dashboard/`, isi PROJECT_ID, lalu klik **Connect**. Kedua kartu harus berstatus **Fresh**.
6. Posisikan webcam **stabil** (tidak dipegang), melihat meja tempat ponsel berada.
7. **Atur ambang setelah semua program berjalan.** Ambang dari dashboard hilang setiap kali edge dijalankan ulang. Kirim ulang ambang yang sudah terbukti di pengujian (A: `vibration_rms_threshold` 1,0 dan `jerk_peak_threshold` 4,0; B: `motion_score_threshold` 5,0 atau 1,5), lalu tunggu kotak ACK hijau. Jika muncul *No ACK*, kirim ulang.
8. Biarkan ponsel diam 10–20 detik dan pastikan status A tetap `NORMAL`. Jika `BUMP_SUSPECTED` muncul sendiri karena `peak_jerk` melonjak, naikkan `jerk_peak_threshold` sampai kondisi diam stabil `NORMAL`. Catat nilai yang **terlihat**, jangan ditebak.
9. Agar garis getaran tidak tertekan oleh lonjakan jerk di grafik edge A, klik legend **Peak jerk** untuk menyembunyikannya sementara.
10. Siapkan perekam layar + kamera kedua/ponsel lain untuk merekam perangkat fisik (atau gunakan picture-in-picture).

## Alur & Narasi

| Waktu | Yang ditampilkan | Narasi (contoh, sesuaikan) |
|---|---|---|
| 0:00–0:20 | Judul + meja: ponsel di alas empuk, laptop dengan webcam | "Ini RoadSense Lab, prototipe IoT dua edge. Edge A adalah ponsel Android yang membaca akselerometer dan giroskopnya sendiri. Edge B adalah laptop yang membaca webcam-nya sendiri. Ini simulasi di atas meja — bukan detektor lubang jalan yang tervalidasi." |
| 0:20–0:40 | Terminal Termux (A) dan terminal edge B berjalan; dashboard **Connected**, kedua kartu **Fresh**, `seq` naik | "Kedua perangkat terhubung sendiri-sendiri ke broker MQTT publik HiveMQ lewat TLS. Di dashboard terlihat telemetri A dan B dengan waktu terakhir diterima." |
| 0:40–1:05 | Ponsel diam → status A `NORMAL`. Ketuk ringan alas beberapa kali → nilai RMS/jerk naik, status `BUMP_SUSPECTED`, event muncul di **Event timeline** | "Saat diam, getaran rendah dan status NORMAL. Saya ketuk alasnya — vibration RMS dan peak jerk naik melewati ambang, edge A menandai BUMP_SUSPECTED dan mengirim event." |
| 1:05–1:15 | Terminal edge B menampilkan baris `[SHARED EVENT] from edge A: BUMP_SUSPECTED` | "Event yang sama juga diterima oleh edge B — komunikasi lintas perangkat lewat cloud." |
| 1:15–1:35 | Putar ponsel dengan tangan (tetap di atas alas) cukup cepat hingga rotasi melewati ambang (default 0,8 rad/s) → `DEVICE_MOVEMENT` | "Kalau ponsel diputar, giroskop mendeteksi rotasi dan statusnya DEVICE_MOVEMENT. Aturan rotasi dievaluasi lebih dulu, jadi gerakan tangan tidak dihitung sebagai getaran." |
| 1:35–1:55 | Gerakkan tangan di area pandang webcam → kartu B `MOTION_OBSERVED`; tangan keluar → kembali `NORMAL` | "Edge B menghitung selisih antar-frame webcam setiap detik. Bila puncak gerakan melewati ambang, statusnya MOTION_OBSERVED. Ini hanya konteks gerak visual, bukan inspeksi kondisi jalan." |
| 1:55–2:25 | Form **Control → Edge A**: ubah ambang (mis. naikkan), klik **Send to A** → kotak ACK hijau, garis putus-putus di grafik berubah. Ulangi ketukan yang sama → perilaku berubah sesuai ambang baru | "Dari dashboard saya kirim SET_THRESHOLD ke edge A. Edge A membalas ACK dengan nilai yang benar-benar diterapkan. Dengan ambang baru, ketukan yang sama [sebutkan apa yang terlihat]." |
| 2:25–2:40 | (Opsional) **Control → Edge B** dengan nilai 0,1–150, lalu ACK B | "Hal yang sama untuk edge B. Perintah dengan target A diabaikan oleh B, dan sebaliknya." |
| 2:40–3:00 | Slide/teks keterbatasan | "Keterbatasan: hanya simulasi meja, tidak ada GPS sehingga tidak ada peringatan berbasis lokasi atau di depan rute, ambang dipilih manual, dan broker publik tanpa autentikasi. Kode ada di GitHub [sebutkan]." |

## Kalimat wajib (sampaikan di video)
- "Edge A hanya menandai **pola getaran**; ini bukan deteksi lubang jalan yang tervalidasi."
- "Webcam hanya memberi **konteks gerak visual**, bukan inspeksi jalan."
- "Tidak ada **GPS**, jadi tidak ada peringatan lokasi atau peringatan di depan rute."

## Jika ada masalah saat merekam
- Kartu **Stale**: cek terminal edge tersebut masih berjalan dan PROJECT_ID sama; tunggu reconnect.
- **No ACK within 10 s**: edge belum terhubung ke broker atau PROJECT_ID berbeda. Edge B juga tidak membalas perintah yang `command`-nya bukan `SET_THRESHOLD`.
- **ACK gagal dari B** (`out of range`): edge B hanya menerima `motion_score_threshold` 0,1–150.
- **Rejected** bertambah: buka Activity log. Alasan penolakan (misalnya `ts_ms looks like uptime`) menunjukkan field yang tidak sesuai kontrak di `SPEC.md`; perbaiki sumber pesannya, bukan validasi dashboard.
- Webcam terlalu sensitif (cahaya berkedip): naikkan `motion_score_threshold` dari dashboard — sekaligus menjadi bukti fitur control.
- B berstatus `MOTION_OBSERVED` padahal grafik di bawah garis ambang: hal ini wajar, karena B memakai nilai puncak sedangkan grafik menampilkan rata-rata.
- Jangan mengedit atau menyusun ulang video agar hasil terlihat lebih baik dari kenyataan.
