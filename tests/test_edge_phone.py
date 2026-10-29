import json
import unittest
from unittest.mock import MagicMock, patch

from edge_phone.config import EdgeAConfig, GRAVITY_M_S2
from edge_phone.processor import (
    IMUProcessor,
    classify_imu_status,
    compute_peak_jerk,
    compute_rotation_rms,
    compute_vibration_rms,
    handle_control_payload,
)
from edge_phone.sensors import (
    SensorError,
    SensorSample,
    SensorWindow,
    discover_sensors,
    parse_termux_sensor_json,
    select_best_sensor,
)


class TestEdgePhone(unittest.TestCase):
    def test_select_best_sensor_prefers_calibrated(self):
        sensors = [
            "LSM6DSO Accelerometer Uncalibrated",
            "LSM6DSO Linear Acceleration",
            "LSM6DSO Accelerometer",
            "LSM6DSO Gyroscope Uncalibrated",
            "LSM6DSO Gyroscope",
        ]
        self.assertEqual(select_best_sensor(sensors, "accelerometer"), "LSM6DSO Accelerometer")
        self.assertEqual(select_best_sensor(sensors, "gyroscope"), "LSM6DSO Gyroscope")

    @patch("edge_phone.sensors.shutil.which", return_value="/data/data/com.termux/files/usr/bin/termux-sensor")
    @patch("edge_phone.sensors.subprocess.run")
    def test_discover_sensors_handles_missing_gyro(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"sensors": ["BMI160 Accelerometer", "Light Sensor"]}),
            stderr="",
        )
        accel, gyro, all_s = discover_sensors()
        self.assertEqual(accel, "BMI160 Accelerometer")
        self.assertIsNone(gyro)
        self.assertEqual(len(all_s), 2)

    @patch("edge_phone.sensors.shutil.which", return_value="/data/data/com.termux/files/usr/bin/termux-sensor")
    @patch("edge_phone.sensors.subprocess.run")
    def test_discover_sensors_raises_on_empty_output(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="   ", stderr="")
        with self.assertRaisesRegex(SensorError, "empty output"):
            discover_sensors()

    def test_parse_termux_sensor_json_extracts_3_axis_values(self):
        raw = {
            "BMI160 Accelerometer": {"values": [0.1, -0.2, 9.81]},
            "BMI160 Gyroscope": {"values": [0.01, 0.02, -0.01]},
        }
        accel, gyro = parse_termux_sensor_json(
            raw, "BMI160 Accelerometer", "BMI160 Gyroscope", ts_s=100.0
        )
        self.assertEqual(len(accel), 1)
        self.assertAlmostEqual(accel[0].z, 9.81, places=5)
        self.assertEqual(len(gyro), 1)
        self.assertAlmostEqual(gyro[0].y, 0.02, places=5)

    def test_stationary_metrics_and_normal_status(self):
        samples = [
            SensorSample(ts_s=1.00, x=0.0, y=0.0, z=GRAVITY_M_S2),
            SensorSample(ts_s=1.05, x=0.0, y=0.0, z=GRAVITY_M_S2),
            SensorSample(ts_s=1.10, x=0.0, y=0.0, z=GRAVITY_M_S2),
        ]
        gyro = [SensorSample(ts_s=1.00, x=0.01, y=0.0, z=0.01)]
        vib_rms = compute_vibration_rms(samples)
        peak_jerk = compute_peak_jerk(samples)
        rot_rms = compute_rotation_rms(gyro)

        self.assertAlmostEqual(vib_rms, 0.0, places=6)
        self.assertAlmostEqual(peak_jerk, 0.0, places=6)
        self.assertAlmostEqual(rot_rms, 0.01414, places=3)

        status = classify_imu_status(
            vibration_rms=vib_rms,
            peak_jerk=peak_jerk,
            rotation_rms=rot_rms,
            vibration_rms_threshold=0.8,
            jerk_peak_threshold=3.0,
            rotation_rms_threshold=0.8,
        )
        self.assertEqual(status, "NORMAL")

    def test_bump_suspected_classification_and_event_cooldown(self):
        proc = IMUProcessor(
            vibration_rms_threshold=0.8,
            jerk_peak_threshold=3.0,
            rotation_rms_threshold=0.8,
            event_cooldown_sec=5.0,
        )
        bump_window = SensorWindow(
            accel_samples=[
                SensorSample(ts_s=10.00, x=0.0, y=0.0, z=GRAVITY_M_S2),
                SensorSample(ts_s=10.05, x=0.0, y=0.0, z=GRAVITY_M_S2 + 2.5),
            ],
            gyro_samples=[SensorSample(ts_s=10.05, x=0.02, y=0.01, z=0.0)],
        )
        telemetry1, event1 = proc.process_window(bump_window, now_ms=1790000000000)

        self.assertEqual(telemetry1["device_id"], "A")
        self.assertEqual(telemetry1["sensor"], "imu")
        self.assertEqual(telemetry1["seq"], 1)
        self.assertEqual(telemetry1["status"], "BUMP_SUSPECTED")
        self.assertGreater(telemetry1["vibration_rms"], 0.8)
        self.assertGreater(telemetry1["peak_jerk"], 3.0)

        self.assertIsNotNone(event1)
        self.assertEqual(
            event1,
            {
                "device_id": "A",
                "ts_ms": 1790000000000,
                "type": "BUMP_SUSPECTED",
                "severity": "WARNING",
                "detail": "Abnormal vibration in tabletop demonstration",
            },
        )

        telemetry2, event2 = proc.process_window(bump_window, now_ms=1790000001000)
        self.assertEqual(telemetry2["status"], "BUMP_SUSPECTED")
        self.assertIsNone(event2)

    def test_device_movement_overrides_bump_when_rotated(self):
        proc = IMUProcessor(
            vibration_rms_threshold=0.8,
            jerk_peak_threshold=3.0,
            rotation_rms_threshold=0.8,
        )
        rotated_window = SensorWindow(
            accel_samples=[
                SensorSample(ts_s=1.00, x=2.0, y=2.0, z=11.5),
                SensorSample(ts_s=1.05, x=-2.0, y=3.0, z=8.0),
            ],
            gyro_samples=[
                SensorSample(ts_s=1.00, x=1.5, y=1.2, z=0.9),
            ],
        )
        telemetry, event = proc.process_window(rotated_window, now_ms=1790000005000)
        self.assertEqual(telemetry["status"], "DEVICE_MOVEMENT")
        self.assertIsNotNone(event)
        self.assertEqual(event["type"], "DEVICE_MOVEMENT")

    def test_sensor_error_on_empty_window(self):
        proc = IMUProcessor()
        err_window = SensorWindow(accel_samples=[], gyro_samples=[], error_reason="Timeout")
        telemetry, event = proc.process_window(err_window, now_ms=1790000009000)
        self.assertEqual(telemetry["status"], "SENSOR_ERROR")
        self.assertIsNotNone(event)
        self.assertEqual(event["type"], "SENSOR_ERROR")

    def test_control_set_threshold_for_a_and_ignore_b(self):
        proc = IMUProcessor(vibration_rms_threshold=0.8, jerk_peak_threshold=3.0)

        cmd_b = json.dumps({
            "command": "SET_THRESHOLD",
            "target": "B",
            "motion_score_threshold": 12.0,
        })
        self.assertIsNone(handle_control_payload(cmd_b, proc, now_ms=1790000000000))

        cmd_a = json.dumps({
            "command": "SET_THRESHOLD",
            "target": "A",
            "vibration_rms_threshold": 1.25,
            "jerk_peak_threshold": 4.5,
        })
        ack = handle_control_payload(cmd_a, proc, now_ms=1790000000000)
        self.assertEqual(
            ack,
            {
                "device_id": "A",
                "command": "SET_THRESHOLD",
                "success": True,
                "vibration_rms_threshold": 1.25,
                "jerk_peak_threshold": 4.5,
                "ts_ms": 1790000000000,
            },
        )
        self.assertEqual(proc.vibration_rms_threshold, 1.25)
        self.assertEqual(proc.jerk_peak_threshold, 4.5)

    def test_topic_contract_names(self):
        cfg = EdgeAConfig(project_id="roadsense-abc123")
        self.assertEqual(cfg.telemetry_topic, "roadsense/roadsense-abc123/edge/A/telemetry")
        self.assertEqual(cfg.events_topic, "roadsense/roadsense-abc123/events")
        self.assertEqual(cfg.control_topic, "roadsense/roadsense-abc123/control")
        self.assertEqual(cfg.ack_topic, "roadsense/roadsense-abc123/ack/A")


if __name__ == "__main__":
    unittest.main()
