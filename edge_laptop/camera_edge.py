"""RoadSense Lab edge B: real webcam motion telemetry via MQTT.

Only numeric grayscale frame-difference summary is transmitted, no image/video.
Camera motion is tabletop visual context, NOT road defect classification.
"""
from __future__ import annotations

import argparse
import json
import math
import ssl
import time
import uuid

import cv2
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORT = 8883


def now_ms() -> int:
    return int(time.time() * 1000)


def make_client(project_id: str, state: dict) -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"roadsense-B-{uuid.uuid4().hex[:10]}",
        protocol=mqtt.MQTTv311,
    )
    base = f"roadsense/{project_id}"
    client.tls_set_context(ssl.create_default_context())

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"[MQTT] connect reason: {reason_code}")
        if reason_code == 0:
            client.subscribe([(f"{base}/control", 1), (f"{base}/events", 1)])

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        print(f"[MQTT] disconnected: {reason_code}; auto reconnect enabled")

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            print(f"[MQTT] ignored malformed payload on {msg.topic}: {exc}")
            return
        if msg.topic == f"{base}/events":
            if data.get("device_id") != "B":
                print(f"[SHARED EVENT] from edge {data.get('device_id')}: {data.get('type')}")
            return
        if msg.topic == f"{base}/control":
            if data.get("target") != "B" or data.get("command") != "SET_THRESHOLD":
                return
            try:
                value = float(data["motion_score_threshold"])
                if not (0.1 <= value <= 150.0) or not math.isfinite(value):
                    raise ValueError("out of range (0.1..150.0)")
                state["threshold"] = value
                result = {"device_id": "B", "command": "SET_THRESHOLD", "success": True,
                          "motion_score_threshold": value, "ts_ms": now_ms()}
                print(f"[CONTROL] B motion_score_threshold = {value}")
            except (KeyError, TypeError, ValueError) as exc:
                result = {"device_id": "B", "command": "SET_THRESHOLD", "success": False,
                          "error": str(exc), "ts_ms": now_ms()}
            client.publish(f"{base}/ack/B", json.dumps(result), qos=1)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    return client


def main():
    parser = argparse.ArgumentParser(description="Real laptop webcam IoT edge B")
    parser.add_argument("--project-id", required=True, help="Same unique ID as phone/dashboard")
    parser.add_argument("--camera", type=int, default=0, help="Webcam index, usually 0")
    parser.add_argument("--threshold", type=float, default=12.0)
    parser.add_argument("--preview", action="store_true", help="Show actual webcam image locally")
    args = parser.parse_args()
    if not args.project_id or not all(c.isalnum() or c == '-' for c in args.project_id):
        parser.error("project-id must use alphanumeric and hyphen only")
    if not (0.1 <= args.threshold <= 150):
        parser.error("threshold must be 0.1..150")
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit("Camera could not be opened. Close other camera apps; try --camera 1.")
    print("[CAM] Webcam open; only numeric statistics will be sent via MQTT")
    state = {"threshold": args.threshold}
    client = make_client(args.project_id, state)
    client.connect_async(BROKER, PORT, keepalive=45)
    client.loop_start()
    base = f"roadsense/{args.project_id}"
    prev = None
    prev_score = 0.0
    seq = 0
    window = []
    last_report = 0.0
    last_event = 0.0
    last_status = "NORMAL"
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[CAM] failed to read frame; retrying")
                time.sleep(.2)
                continue
            gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 120))
            if prev is None:
                prev = gray
                continue
            diff = cv2.absdiff(gray, prev)
            prev = gray
            score = float(diff.mean())
            delta = abs(score - prev_score)
            prev_score = score
            window.append((score, delta))
            if args.preview:
                cv2.putText(frame, f"Motion={score:.1f}, Threshold={state['threshold']:.1f}",
                            (12, 30), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 220, 255), 2)
                cv2.imshow("RoadSense Edge B: webcam context", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            now = time.monotonic()
            if now - last_report < 1.0:
                time.sleep(.06)
                continue
            last_report = now
            if not window:
                continue
            # Smooth across a window and include largest recent movement.
            mean_score = sum(x for x, _ in window) / len(window)
            peak_score = max(x for x, _ in window)
            mean_delta = sum(d for _, d in window) / len(window)
            window.clear()
            status = "MOTION_OBSERVED" if peak_score >= state["threshold"] else "NORMAL"
            seq += 1
            telemetry = {"device_id": "B", "sensor": "webcam", "seq": seq,
                         "ts_ms": now_ms(), "motion_score": round(mean_score, 3),
                         "motion_delta": round(mean_delta, 3), "status": status}
            client.publish(f"{base}/edge/B/telemetry", json.dumps(telemetry), qos=0)
            print(f"[B] seq={seq} score={mean_score:.2f} peak={peak_score:.2f} delta={mean_delta:.2f} {status}")
            if status == "MOTION_OBSERVED" and (last_status != status or now - last_event > 12):
                evt = {"device_id": "B", "ts_ms": now_ms(), "type": "MOTION_OBSERVED",
                       "severity": "INFO", "detail": "Visual motion in tabletop camera view"}
                client.publish(f"{base}/events", json.dumps(evt), qos=1)
                last_event = now
            last_status = status
    except KeyboardInterrupt:
        print("\n[STOP] stopping webcam edge")
    finally:
        cap.release()
        if args.preview:
            cv2.destroyAllWindows()
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
