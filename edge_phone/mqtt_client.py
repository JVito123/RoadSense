import json
import logging
import ssl
import time
import uuid
from typing import Callable

import paho.mqtt.client as mqtt

from edge_phone.config import DEVICE_ID, EdgeAConfig
from edge_phone.processor import IMUProcessor

logger = logging.getLogger("edge_phone.mqtt")


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
    try:
        text = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring malformed JSON on /control: %s", exc)
        return None

    if not isinstance(data, dict):
        return None

    target = data.get("target")
    if target != DEVICE_ID:
        logger.debug("Ignoring control command for target=%s (we are A)", target)
        return None

    command = data.get("command")
    ts_ms = now_ms if now_ms is not None else int(time.time() * 1000)

    if command != "SET_THRESHOLD":
        logger.warning("Unsupported command '%s' targeted at A", command)
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


class EdgeAMQTTClient:
    """
    MQTT over TLS client for Edge A using paho-mqtt v2 CallbackAPIVersion.VERSION2.
    """

    def __init__(
        self,
        config: EdgeAConfig,
        processor: IMUProcessor,
        on_peer_event: Callable[[dict], None] | None = None,
    ) -> None:
        self.config = config
        self.processor = processor
        self.on_peer_event = on_peer_event
        self.client_id = f"roadsense-{config.project_id}-edge-A-{uuid.uuid4().hex[:8]}"

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
        )
        self._client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    def connect(self) -> None:
        logger.info(
            "Connecting to %s:%d over TLS as client_id=%s",
            self.config.broker_host,
            self.config.broker_port,
            self.client_id,
        )
        self._client.connect(
            self.config.broker_host,
            self.config.broker_port,
            keepalive=60,
        )
        self._client.loop_start()

    def disconnect(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception as exc:
            logger.debug("Disconnect cleanup warning: %s", exc)

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code == 0:
            logger.info("Connected to MQTT broker over TLS.")
            client.subscribe(self.config.control_topic, qos=1)
            client.subscribe(self.config.events_topic, qos=1)
            logger.info(
                "Subscribed to %s and %s",
                self.config.control_topic,
                self.config.events_topic,
            )
        else:
            logger.error("MQTT connection failed with reason_code=%s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            logger.warning("Unexpected MQTT disconnect (reason=%s). Auto-reconnecting...", reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        topic = msg.topic
        if topic == self.config.control_topic:
            ack = handle_control_payload(msg.payload, self.processor)
            if ack is not None:
                logger.info(
                    "Applied SET_THRESHOLD -> vib_rms=%.2f, peak_jerk=%.2f (success=%s). Sending ACK.",
                    ack["vibration_rms_threshold"],
                    ack["jerk_peak_threshold"],
                    ack["success"],
                )
                self.publish_ack(ack)
        elif topic == self.config.events_topic:
            self._handle_incoming_event(msg.payload)

    def _handle_incoming_event(self, raw_payload: bytes) -> None:
        try:
            data = json.loads(raw_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        sender = data.get("device_id")
        if sender and sender != DEVICE_ID:
            logger.info(
                "[CROSS-EDGE EVENT from %s] type=%s severity=%s detail=%s (ts_ms=%s)",
                sender,
                data.get("type"),
                data.get("severity"),
                data.get("detail"),
                data.get("ts_ms"),
            )
            if self.on_peer_event:
                self.on_peer_event(data)

    def publish_telemetry(self, payload: dict) -> None:
        encoded = json.dumps(payload, separators=(",", ":"))
        self._client.publish(self.config.telemetry_topic, encoded, qos=0)
        logger.info("PUB %s -> %s", self.config.telemetry_topic, encoded)

    def publish_event(self, payload: dict) -> None:
        encoded = json.dumps(payload, separators=(",", ":"))
        self._client.publish(self.config.events_topic, encoded, qos=1)
        logger.warning("EVENT %s -> %s", self.config.events_topic, encoded)

    def publish_ack(self, payload: dict) -> None:
        encoded = json.dumps(payload, separators=(",", ":"))
        self._client.publish(self.config.ack_topic, encoded, qos=1)
        logger.info("ACK %s -> %s", self.config.ack_topic, encoded)
