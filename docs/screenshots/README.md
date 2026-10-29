# Screenshot Bukti Pengujian

Semua file di folder ini diambil dari pengujian fisik pada 29 Oktober 2026 dengan PROJECT_ID `roadsense-v29lab`. Prosedur dan hasil lengkapnya ada di [`../test_scenarios.md`](../test_scenarios.md).

## File yang tersedia

| File | Isi | Uji |
|---|---|---|
| [`t3_dashboard_both_fresh.png`](t3_dashboard_both_fresh.png) | Dashboard *Connected*, kartu edge A (Android) dan edge B (webcam) *Fresh* dengan status `NORMAL`, grafik real-time, `Messages 80 · Rejected 0` | T2, T3 |
| [`t4_event_a_ke_b.png`](t4_event_a_ke_b.png) | Terminal edge B: baris `[B] seq=... score=... peak=... delta=...` dengan status `NORMAL`/`MOTION_OBSERVED`, serta `[SHARED EVENT] from edge A: BUMP_SUSPECTED` dan `DEVICE_MOVEMENT` | T1, T4, T6 (sebagian) |
| [`t4_event_b_ke_a.jpeg`](t4_event_b_ke_a.jpeg) | Termux edge A: `[CROSS-EDGE EVENT from B] type=MOTION_OBSERVED`, diikuti telemetri A yang dipublikasikan ke `roadsense/roadsense-v29lab/edge/A/telemetry` | T1, T2, T4 |
| [`t5_edge_a_ack.png`](t5_edge_a_ack.png) | Form kontrol edge A: `vibration_rms_threshold = 1`, `jerk_peak_threshold = 4`, round trip 1786 ms | T5 |
| [`t5_edge_b_ack.png`](t5_edge_b_ack.png) | Form kontrol edge B: `motion_score_threshold = 5`, round trip 1173 ms | T5 |

Input ambang di dashboard ditampilkan sebagai `1,0`, `4,0`, dan `5,0` karena format angka bahasa Indonesia di browser. Nilai yang diterapkan edge terlihat di kotak ACK.

## Bukti yang belum tersedia (opsional)

| Saran nama file | Isi | Uji |
|---|---|---|
| `t1_list_sensors.png` | Output `termux-sensor -l` dan `--list-sensors` di ponsel | T1 |
| `t2_monitor.png` | `tools/monitor.py` menampilkan topic A dan B | T2 |
| `t4_event_timeline.png` | Event di *Event timeline* dashboard | T4 |
| `t6_device_movement.png` | Status `DEVICE_MOVEMENT` saat ponsel diputar | T6 |

## Privasi

Sebelum mengunggah screenshot baru, pastikan tidak ada nama, wajah, alamat, kata sandi WiFi, atau notifikasi pribadi yang terlihat. File `t4_event_b_ke_a.jpeg` menyimpan metadata EXIF dari ponsel (versi software Android, ID unik gambar, dan waktu pengambilan), tetapi tidak berisi lokasi GPS.
