import math
import time
from dataclasses import dataclass

from edge_phone.config import (
    ALLOWED_STATUSES,
    DEVICE_ID,
    GRAVITY_M_S2,
    SENSOR_TYPE,
)
from edge_phone.sensors import SensorSample, SensorWindow


@dataclass
class ComputedMetrics:
    vibration_rms: float
    peak_jerk: float
    rotation_rms: float
    status: str


def compute_vibration_rms(
    accel_samples: list[SensorSample],
    gravity: float = GRAVITY_M_S2,
) -> float:
    """
    Compute RMS of acceleration magnitude deviation from standard gravity:
    d_i = sqrt(ax^2 + ay^2 + az^2) - g
    vibration_rms = sqrt(mean(d_i^2))
    """
    if not accel_samples:
        raise ValueError("accel_samples cannot be empty")

    sq_sum = 0.0
    for s in accel_samples:
        if not (math.isfinite(s.x) and math.isfinite(s.y) and math.isfinite(s.z)):
            raise ValueError("Non-finite accelerometer reading encountered")
        mag = math.sqrt(s.x * s.x + s.y * s.y + s.z * s.z)
        dev = mag - gravity
        sq_sum += dev * dev

    return math.sqrt(sq_sum / len(accel_samples))


def compute_peak_jerk(
    accel_samples: list[SensorSample],
    prev_sample: SensorSample | None = None,
    default_dt_s: float = 0.05,
) -> float:
    """
    Compute peak jerk (m/s^3) from time-differenced 3D accelerometer readings.
    Handles variations in sample rate by clamping minimum dt to 5ms.
    """
    seq: list[SensorSample] = []
    if prev_sample is not None:
        seq.append(prev_sample)
    seq.extend(accel_samples)

    if len(seq) < 2:
        return 0.0

    max_jerk = 0.0
    for i in range(1, len(seq)):
        p = seq[i - 1]
        c = seq[i]
        dt = c.ts_s - p.ts_s
        if dt <= 0.001 or dt > 2.0:
            dt = default_dt_s
        dt = max(dt, 0.005)
        da = math.sqrt((c.x - p.x) ** 2 + (c.y - p.y) ** 2 + (c.z - p.z) ** 2)
        jerk = da / dt
        if jerk > max_jerk:
            max_jerk = jerk

    return max_jerk


def compute_rotation_rms(gyro_samples: list[SensorSample]) -> float:
    """
    Compute RMS of angular velocity magnitude (rad/s) from gyroscope samples.
    Returns 0.0 if gyro is unavailable or empty in this window.
    """
    if not gyro_samples:
        return 0.0

    sq_sum = 0.0
    valid_count = 0
    for s in gyro_samples:
        if not (math.isfinite(s.x) and math.isfinite(s.y) and math.isfinite(s.z)):
            continue
        mag_sq = s.x * s.x + s.y * s.y + s.z * s.z
        sq_sum += mag_sq
        valid_count += 1

    if valid_count == 0:
        return 0.0
    return math.sqrt(sq_sum / valid_count)


def classify_imu_status(
    vibration_rms: float,
    peak_jerk: float,
    rotation_rms: float,
    vibration_rms_threshold: float,
    jerk_peak_threshold: float,
    rotation_rms_threshold: float,
    has_error: bool = False,
) -> str:
    """
    Rule-based decision for Edge A:
    1. SENSOR_ERROR if sensor read failed or produced invalid numbers.
    2. DEVICE_MOVEMENT if rotation_rms >= rotation_rms_threshold (phone tilted/rotated by hand).
    3. BUMP_SUSPECTED if vibration_rms >= vibration_rms_threshold or peak_jerk >= jerk_peak_threshold.
    4. NORMAL otherwise.
    """
    if has_error:
        return "SENSOR_ERROR"
    if not (
        math.isfinite(vibration_rms)
        and math.isfinite(peak_jerk)
        and math.isfinite(rotation_rms)
    ):
        return "SENSOR_ERROR"

    if rotation_rms >= rotation_rms_threshold:
        return "DEVICE_MOVEMENT"

    if vibration_rms >= vibration_rms_threshold or peak_jerk >= jerk_peak_threshold:
        return "BUMP_SUSPECTED"

    return "NORMAL"


class IMUProcessor:
    """
    Stateful processor tracking sequence numbers, previous sample for jerk continuity,
    live configurable thresholds, and event cooldown logic.
    """

    def __init__(
        self,
        vibration_rms_threshold: float = 0.8,
        jerk_peak_threshold: float = 3.0,
        rotation_rms_threshold: float = 0.8,
        event_cooldown_sec: float = 3.0,
        default_dt_s: float = 0.05,
    ) -> None:
        self.vibration_rms_threshold = float(vibration_rms_threshold)
        self.jerk_peak_threshold = float(jerk_peak_threshold)
        self.rotation_rms_threshold = float(rotation_rms_threshold)
        self.event_cooldown_sec = float(event_cooldown_sec)
        self.default_dt_s = float(default_dt_s)

        self._seq = 0
        self._prev_accel: SensorSample | None = None
        self._last_status: str = "NORMAL"
        self._last_event_ts_s: float = 0.0

    def update_thresholds(
        self,
        vibration_rms_threshold: float | None = None,
        jerk_peak_threshold: float | None = None,
    ) -> tuple[bool, float, float]:
        """
        Validate and apply new thresholds from SET_THRESHOLD command.
        Returns (success, applied_vibration_rms_threshold, applied_jerk_peak_threshold).
        """
        try:
            new_vib = (
                float(vibration_rms_threshold)
                if vibration_rms_threshold is not None
                else self.vibration_rms_threshold
            )
            new_jerk = (
                float(jerk_peak_threshold)
                if jerk_peak_threshold is not None
                else self.jerk_peak_threshold
            )
        except (TypeError, ValueError):
            return False, self.vibration_rms_threshold, self.jerk_peak_threshold

        if (
            not math.isfinite(new_vib)
            or not math.isfinite(new_jerk)
            or new_vib <= 0.0
            or new_jerk <= 0.0
        ):
            return False, self.vibration_rms_threshold, self.jerk_peak_threshold

        self.vibration_rms_threshold = round(new_vib, 4)
        self.jerk_peak_threshold = round(new_jerk, 4)
        return True, self.vibration_rms_threshold, self.jerk_peak_threshold

    def process_window(
        self,
        window: SensorWindow,
        now_ms: int | None = None,
    ) -> tuple[dict, dict | None]:
        """
        Process a SensorWindow and return (telemetry_payload, optional_event_payload)
        strictly conforming to SPEC.md v2 JSON schemas.
        """
        self._seq += 1
        ts_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        now_s = ts_ms / 1000.0

        if window.error_reason or not window.accel_samples:
            metrics = ComputedMetrics(
                vibration_rms=0.0,
                peak_jerk=0.0,
                rotation_rms=0.0,
                status="SENSOR_ERROR",
            )
            self._prev_accel = None
        else:
            try:
                vib_rms = compute_vibration_rms(window.accel_samples)
                pk_jerk = compute_peak_jerk(
                    window.accel_samples,
                    prev_sample=self._prev_accel,
                    default_dt_s=self.default_dt_s,
                )
                rot_rms = compute_rotation_rms(window.gyro_samples)
                self._prev_accel = window.accel_samples[-1]
                status = classify_imu_status(
                    vibration_rms=vib_rms,
                    peak_jerk=pk_jerk,
                    rotation_rms=rot_rms,
                    vibration_rms_threshold=self.vibration_rms_threshold,
                    jerk_peak_threshold=self.jerk_peak_threshold,
                    rotation_rms_threshold=self.rotation_rms_threshold,
                    has_error=False,
                )
                metrics = ComputedMetrics(
                    vibration_rms=round(vib_rms, 4),
                    peak_jerk=round(pk_jerk, 4),
                    rotation_rms=round(rot_rms, 4),
                    status=status,
                )
            except ValueError:
                self._prev_accel = None
                metrics = ComputedMetrics(
                    vibration_rms=0.0,
                    peak_jerk=0.0,
                    rotation_rms=0.0,
                    status="SENSOR_ERROR",
                )

        assert metrics.status in ALLOWED_STATUSES

        telemetry = {
            "device_id": DEVICE_ID,
            "sensor": SENSOR_TYPE,
            "seq": self._seq,
            "ts_ms": ts_ms,
            "vibration_rms": round(metrics.vibration_rms, 2),
            "peak_jerk": round(metrics.peak_jerk, 2),
            "rotation_rms": round(metrics.rotation_rms, 2),
            "status": metrics.status,
        }

        event_payload = self._maybe_build_event(metrics, ts_ms, now_s, window.error_reason)
        self._last_status = metrics.status
        return telemetry, event_payload

    def _maybe_build_event(
        self,
        metrics: ComputedMetrics,
        ts_ms: int,
        now_s: float,
        error_reason: str | None = None,
    ) -> dict | None:
        if metrics.status == "NORMAL":
            return None

        status_changed = metrics.status != self._last_status
        cooldown_elapsed = (now_s - self._last_event_ts_s) >= self.event_cooldown_sec

        if not (status_changed or cooldown_elapsed):
            return None

        self._last_event_ts_s = now_s

        if metrics.status == "BUMP_SUSPECTED":
            detail = "Abnormal vibration in tabletop demonstration"
            severity = "WARNING"
        elif metrics.status == "DEVICE_MOVEMENT":
            detail = "Large device rotation/handling artifact in tabletop demonstration"
            severity = "INFO"
        else:
            detail = error_reason or "IMU sensor read failure on Edge A"
            severity = "ERROR"

        return {
            "device_id": DEVICE_ID,
            "ts_ms": ts_ms,
            "type": metrics.status,
            "severity": severity,
            "detail": detail,
        }


def handle_control_payload(
    raw_payload: str | bytes,
    processor: IMUProcessor,
    now_ms: int | None = None,
) -> dict | None:
    """
    Parse incoming control JSON on `roadsense/{PROJECT_ID}/control`.
    If targeted at 'A' with command 'SET_THRESHOLD', update processor thresholds
    and return the exact ACK dictionary required by SPEC.md v2.
    Returns None if the message targets another device (e.g. 'B') or is invalid JSON.
    """
    import json
    try:
        text = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    target = data.get("target")
    if target != DEVICE_ID:
        return None

    command = data.get("command")
    ts_ms = now_ms if now_ms is not None else int(time.time() * 1000)

    if command != "SET_THRESHOLD":
        return {
            "device_id": DEVICE_ID,
            "command": str(command or "UNKNOWN"),
            "success": False,
            "vibration_rms_threshold": processor.vibration_rms_threshold,
            "jerk_peak_threshold": processor.jerk_peak_threshold,
            "ts_ms": ts_ms,
        }

    vib_in = data.get("vibration_rms_threshold")
    jerk_in = data.get("jerk_peak_threshold")

    if vib_in is None and jerk_in is None:
        success = False
        applied_vib = processor.vibration_rms_threshold
        applied_jerk = processor.jerk_peak_threshold
    else:
        success, applied_vib, applied_jerk = processor.update_thresholds(
            vibration_rms_threshold=vib_in,
            jerk_peak_threshold=jerk_in,
        )

    return {
        "device_id": DEVICE_ID,
        "command": "SET_THRESHOLD",
        "success": success,
        "vibration_rms_threshold": applied_vib,
        "jerk_peak_threshold": applied_jerk,
        "ts_ms": ts_ms,
    }
