import os
import re
from dataclasses import dataclass

GRAVITY_M_S2 = 9.80665
DEVICE_ID = "A"
SENSOR_TYPE = "imu"

ALLOWED_STATUSES = frozenset({
    "NORMAL",
    "BUMP_SUSPECTED",
    "DEVICE_MOVEMENT",
    "SENSOR_ERROR",
})

PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9-]+$")


def validate_project_id(project_id: str) -> str:
    cleaned = project_id.strip()
    if not cleaned or not PROJECT_ID_PATTERN.match(cleaned):
        raise ValueError(
            f"Invalid PROJECT_ID '{project_id}'. "
            "Must be lowercase alphanumeric/hyphen (e.g. 'roadsense-abc123')."
        )
    return cleaned


@dataclass
class EdgeAConfig:
    project_id: str
    broker_host: str = "broker.hivemq.com"
    broker_port: int = 8883
    vibration_rms_threshold: float = 0.8
    jerk_peak_threshold: float = 3.0
    rotation_rms_threshold: float = 0.8
    event_cooldown_sec: float = 3.0
    publish_interval_sec: float = 1.0
    sensor_delay_ms: int = 50
    samples_per_window: int = 8
    sensor_timeout_sec: float = 4.0
    accel_sensor_override: str = ""
    gyro_sensor_override: str = ""

    def __post_init__(self) -> None:
        self.project_id = validate_project_id(self.project_id)

    @property
    def base_topic(self) -> str:
        return f"roadsense/{self.project_id}"

    @property
    def telemetry_topic(self) -> str:
        return f"{self.base_topic}/edge/A/telemetry"

    @property
    def events_topic(self) -> str:
        return f"{self.base_topic}/events"

    @property
    def control_topic(self) -> str:
        return f"{self.base_topic}/control"

    @property
    def ack_topic(self) -> str:
        return f"{self.base_topic}/ack/A"

    @classmethod
    def from_env(cls, project_id_override: str | None = None) -> "EdgeAConfig":
        project_id = project_id_override or os.getenv("PROJECT_ID", "roadsense-demo01")
        return cls(
            project_id=project_id,
            broker_host=os.getenv("MQTT_BROKER_HOST", "broker.hivemq.com"),
            broker_port=int(os.getenv("MQTT_BROKER_PORT", "8883")),
            vibration_rms_threshold=float(os.getenv("VIBRATION_RMS_THRESHOLD", "0.8")),
            jerk_peak_threshold=float(os.getenv("JERK_PEAK_THRESHOLD", "3.0")),
            rotation_rms_threshold=float(os.getenv("ROTATION_RMS_THRESHOLD", "0.8")),
            event_cooldown_sec=float(os.getenv("EVENT_COOLDOWN_SEC", "3.0")),
            publish_interval_sec=float(os.getenv("PUBLISH_INTERVAL_SEC", "1.0")),
            sensor_delay_ms=int(os.getenv("SENSOR_DELAY_MS", "50")),
            samples_per_window=int(os.getenv("SAMPLES_PER_WINDOW", "8")),
            sensor_timeout_sec=float(os.getenv("SENSOR_TIMEOUT_SEC", "4.0")),
            accel_sensor_override=os.getenv("ACCEL_SENSOR_NAME", ""),
            gyro_sensor_override=os.getenv("GYRO_SENSOR_NAME", ""),
        )
