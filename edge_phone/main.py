import argparse
import json
import logging
import signal
import sys
import time

from edge_phone.config import EdgeAConfig
from edge_phone.mqtt_client import EdgeAMQTTClient
from edge_phone.processor import IMUProcessor
from edge_phone.sensors import SensorError, TermuxSensorStream, discover_sensors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RoadSense Lab v2 — Edge A (Android Termux IMU Publisher)"
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="Unique lowercase alphanumeric/hyphen PROJECT_ID (overrides env PROJECT_ID)",
    )
    parser.add_argument(
        "--list-sensors",
        action="store_true",
        help="Discover and print real Android accelerometer/gyroscope via termux-sensor -l and exit",
    )
    parser.add_argument(
        "--check-once",
        action="store_true",
        help="Capture one real sensor window, print computed telemetry JSON, and exit without MQTT",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("edge_phone.main")

    try:
        config = EdgeAConfig.from_env(project_id_override=args.project_id)
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        return 2

    try:
        accel_name, gyro_name, all_sensors = discover_sensors(
            timeout_sec=config.sensor_timeout_sec,
            accel_override=config.accel_sensor_override,
            gyro_override=config.gyro_sensor_override,
        )
    except SensorError as exc:
        logger.error("Sensor discovery failed: %s", exc)
        return 1

    logger.info(
        "Discovered IMU sensors -> Accelerometer='%s', Gyroscope='%s'",
        accel_name,
        gyro_name or "MISSING (fallback rotation_rms=0.0)",
    )

    if args.list_sensors:
        print(
            json.dumps(
                {
                    "selected_accelerometer": accel_name,
                    "selected_gyroscope": gyro_name,
                    "all_sensors": all_sensors,
                },
                indent=2,
            )
        )
        return 0

    processor = IMUProcessor(
        vibration_rms_threshold=config.vibration_rms_threshold,
        jerk_peak_threshold=config.jerk_peak_threshold,
        rotation_rms_threshold=config.rotation_rms_threshold,
        event_cooldown_sec=config.event_cooldown_sec,
        default_dt_s=config.sensor_delay_ms / 1000.0,
    )

    stream = TermuxSensorStream(
        accel_name=accel_name,
        gyro_name=gyro_name,
        delay_ms=config.sensor_delay_ms,
        timeout_sec=config.sensor_timeout_sec,
    )
    stream.start()

    if args.check_once:
        try:
            window = stream.read_window(min_samples=config.samples_per_window)
            telemetry, event = processor.process_window(window)
            print("TELEMETRY:", json.dumps(telemetry))
            if event:
                print("EVENT:", json.dumps(event))
            return 0 if telemetry["status"] != "SENSOR_ERROR" else 1
        finally:
            stream.stop()

    mqtt_client = EdgeAMQTTClient(config=config, processor=processor)
    running = True

    def _handle_sig(signum, frame) -> None:
        nonlocal running
        logger.info("Signal %s received, stopping Edge A...", signum)
        running = False

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    try:
        mqtt_client.connect()
        logger.info(
            "Edge A running for PROJECT_ID='%s'. Disclaimer: Tabletop vibration monitor ONLY, NOT a validated pothole detector.",
            config.project_id,
        )
        while running:
            loop_start = time.time()
            window = stream.read_window(min_samples=config.samples_per_window)
            telemetry, event = processor.process_window(window)
            mqtt_client.publish_telemetry(telemetry)
            if event is not None:
                mqtt_client.publish_event(event)

            elapsed = time.time() - loop_start
            sleep_for = max(0.05, config.publish_interval_sec - elapsed)
            time.sleep(sleep_for)
    finally:
        stream.stop()
        mqtt_client.disconnect()
        logger.info("Edge A shutdown complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
