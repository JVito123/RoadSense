import json
import logging
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("edge_phone.sensors")


class SensorError(RuntimeError):
    """Raised when Termux sensor API fails, times out, or lacks accelerometer."""


@dataclass
class SensorSample:
    ts_s: float
    x: float
    y: float
    z: float


@dataclass
class SensorWindow:
    accel_samples: list[SensorSample] = field(default_factory=list)
    gyro_samples: list[SensorSample] = field(default_factory=list)
    gyro_available: bool = True
    error_reason: str | None = None


def select_best_sensor(sensor_list: list[str], keyword: str) -> str | None:
    """
    Pick the best calibrated sensor matching `keyword` (e.g. 'accelerometer' or 'gyroscope').
    Avoids 'uncalibrated', 'linear', 'significant motion', or 'wakeup' variants if a base sensor exists.
    """
    kw = keyword.lower()
    candidates = [s for s in sensor_list if kw in s.lower()]
    if not candidates:
        return None

    def score(name: str) -> tuple[int, int]:
        low = name.lower()
        penalty = 0
        for bad in ("uncalibrated", "linear", "gravity", "wakeup", "wake-up", " tilt", "step"):
            if bad in low:
                penalty += 10
        return (penalty, len(name))

    candidates.sort(key=score)
    return candidates[0]


def discover_sensors(
    timeout_sec: float = 5.0,
    accel_override: str = "",
    gyro_override: str = "",
) -> tuple[str, str | None, list[str]]:
    """
    Run `termux-sensor -l` to dynamically discover accelerometer and gyroscope names.
    Returns (accel_name, gyro_name_or_none, all_sensors).
    Raises SensorError if `termux-sensor` is missing, times out, or no accelerometer exists.
    """
    if shutil.which("termux-sensor") is None:
        raise SensorError(
            "Binary 'termux-sensor' not found. Install Termux:API app and `pkg install termux-api`."
        )

    try:
        proc = subprocess.run(
            ["termux-sensor", "-l"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SensorError(
            f"`termux-sensor -l` timed out after {timeout_sec}s. Check Termux:API permissions."
        ) from exc
    except OSError as exc:
        raise SensorError(f"Failed to execute `termux-sensor -l`: {exc}") from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise SensorError(f"`termux-sensor -l` exited with code {proc.returncode}: {stderr}")

    raw_out = (proc.stdout or "").strip()
    if not raw_out:
        raise SensorError("`termux-sensor -l` returned empty output. Check Termux:API permission.")

    try:
        parsed = json.loads(raw_out)
    except json.JSONDecodeError as exc:
        raise SensorError(f"Invalid JSON from `termux-sensor -l`: {exc}") from exc

    sensors = parsed.get("sensors")
    if not isinstance(sensors, list) or not sensors:
        raise SensorError("No sensors reported by `termux-sensor -l`.")

    sensor_names = [str(s) for s in sensors]
    accel_name = accel_override.strip() or select_best_sensor(sensor_names, "accelerometer")
    gyro_name = gyro_override.strip() or select_best_sensor(sensor_names, "gyroscope")

    if not accel_name:
        raise SensorError(f"No accelerometer found in device sensor list: {sensor_names}")

    if not gyro_name:
        logger.warning(
            "No gyroscope found in sensor list. Edge A will operate with rotation_rms=0.0."
        )

    return accel_name, gyro_name, sensor_names


def parse_termux_sensor_json(
    payload: dict,
    accel_name: str,
    gyro_name: str | None,
    ts_s: float | None = None,
) -> tuple[list[SensorSample], list[SensorSample]]:
    """
    Parse a single JSON object emitted by `termux-sensor`.
    Handles both single reading `{"values": [x, y, z]}` and nested readings.
    """
    now_s = ts_s if ts_s is not None else time.time()
    accel_out: list[SensorSample] = []
    gyro_out: list[SensorSample] = []

    if not isinstance(payload, dict):
        return accel_out, gyro_out

    for key, val in payload.items():
        if not isinstance(val, dict):
            continue
        values = val.get("values")
        if not isinstance(values, list) or len(values) < 3:
            continue
        try:
            sample = SensorSample(
                ts_s=now_s,
                x=float(values[0]),
                y=float(values[1]),
                z=float(values[2]),
            )
        except (TypeError, ValueError):
            continue

        key_low = key.lower()
        if key == accel_name or "accelerometer" in key_low:
            accel_out.append(sample)
        elif gyro_name and (key == gyro_name or "gyroscope" in key_low):
            gyro_out.append(sample)

    return accel_out, gyro_out


class TermuxSensorStream:
    """
    Persistent background reader for `termux-sensor -s <sensors> -d <delay_ms>`.
    Avoids per-window JVM/IPC startup latency of Termux:API while also supporting
    automatic fallback/restart on timeout.
    """

    def __init__(
        self,
        accel_name: str,
        gyro_name: str | None,
        delay_ms: int = 50,
        max_buffer: int = 64,
        timeout_sec: float = 4.0,
    ) -> None:
        self.accel_name = accel_name
        self.gyro_name = gyro_name
        self.delay_ms = max(20, int(delay_ms))
        self.timeout_sec = timeout_sec
        self._accel_buf: deque[SensorSample] = deque(maxlen=max_buffer)
        self._gyro_buf: deque[SensorSample] = deque(maxlen=max_buffer)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._last_sample_ts: float = 0.0
        self._last_error: str | None = None

    @property
    def sensor_arg(self) -> str:
        if self.gyro_name:
            return f"{self.accel_name},{self.gyro_name}"
        return self.accel_name

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._terminate_proc()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        try:
            subprocess.run(
                ["termux-sensor", "-c"],
                capture_output=True,
                timeout=2.0,
                check=False,
            )
        except Exception:
            pass

    def _terminate_proc(self) -> None:
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            finally:
                self._proc = None

    def _reader_loop(self) -> None:
        cmd = ["termux-sensor", "-s", self.sensor_arg, "-d", str(self.delay_ms)]
        logger.info("Starting Termux sensor stream: %s", " ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            with self._lock:
                self._last_error = f"Failed to start termux-sensor stream: {exc}"
            return

        brace_depth = 0
        chunk_lines: list[str] = []

        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._stop_event.is_set():
                break
            stripped = line.strip()
            if not stripped and brace_depth == 0:
                continue

            brace_depth += stripped.count("{") - stripped.count("}")
            chunk_lines.append(line)

            if brace_depth <= 0 and chunk_lines:
                raw_json = "".join(chunk_lines).strip()
                chunk_lines.clear()
                brace_depth = 0
                try:
                    data = json.loads(raw_json)
                except json.JSONDecodeError:
                    continue

                now_s = time.time()
                a_samples, g_samples = parse_termux_sensor_json(
                    data, self.accel_name, self.gyro_name, ts_s=now_s
                )
                with self._lock:
                    if a_samples:
                        self._accel_buf.extend(a_samples)
                        self._last_sample_ts = now_s
                        self._last_error = None
                    if g_samples:
                        self._gyro_buf.extend(g_samples)

        if not self._stop_event.is_set():
            with self._lock:
                self._last_error = "termux-sensor stream ended unexpectedly"

    def read_window(self, min_samples: int = 4) -> SensorWindow:
        """
        Collect buffered samples for the current window, waiting up to `timeout_sec`
        if the buffer does not yet have enough fresh accelerometer samples.
        Falls back to one-shot `termux-sensor -n` if stream is stalled.
        """
        deadline = time.time() + self.timeout_sec
        while time.time() < deadline:
            with self._lock:
                if len(self._accel_buf) >= min_samples:
                    accel = list(self._accel_buf)
                    gyro = list(self._gyro_buf)
                    self._accel_buf.clear()
                    self._gyro_buf.clear()
                    return SensorWindow(
                        accel_samples=accel,
                        gyro_samples=gyro,
                        gyro_available=self.gyro_name is not None,
                    )
            time.sleep(0.04)

        with self._lock:
            if self._accel_buf and (time.time() - self._last_sample_ts) <= self.timeout_sec:
                accel = list(self._accel_buf)
                gyro = list(self._gyro_buf)
                self._accel_buf.clear()
                self._gyro_buf.clear()
                return SensorWindow(
                    accel_samples=accel,
                    gyro_samples=gyro,
                    gyro_available=self.gyro_name is not None,
                )
            err = self._last_error

        return self._oneshot_fallback(count=max(2, min_samples), prior_error=err)

    def _oneshot_fallback(self, count: int, prior_error: str | None = None) -> SensorWindow:
        cmd = [
            "termux-sensor",
            "-s",
            self.sensor_arg,
            "-d",
            str(self.delay_ms),
            "-n",
            str(count),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SensorWindow(
                gyro_available=self.gyro_name is not None,
                error_reason=prior_error or f"Sensor read timed out after {self.timeout_sec}s",
            )
        except OSError as exc:
            return SensorWindow(
                gyro_available=self.gyro_name is not None,
                error_reason=f"OS error running termux-sensor: {exc}",
            )

        raw = (proc.stdout or "").strip()
        if not raw:
            return SensorWindow(
                gyro_available=self.gyro_name is not None,
                error_reason=prior_error or "Empty output from termux-sensor",
            )

        accel_all: list[SensorSample] = []
        gyro_all: list[SensorSample] = []
        decoder = json.JSONDecoder()
        idx = 0
        n = len(raw)
        step_s = self.delay_ms / 1000.0
        base_ts = time.time() - (count * step_s)
        sample_idx = 0

        while idx < n:
            while idx < n and raw[idx].isspace():
                idx += 1
            if idx >= n:
                break
            try:
                obj, next_idx = decoder.raw_decode(raw, idx)
                idx = next_idx
            except json.JSONDecodeError:
                break
            ts_s = base_ts + sample_idx * step_s
            sample_idx += 1
            a_s, g_s = parse_termux_sensor_json(obj, self.accel_name, self.gyro_name, ts_s=ts_s)
            accel_all.extend(a_s)
            gyro_all.extend(g_s)

        if not accel_all:
            return SensorWindow(
                gyro_available=self.gyro_name is not None,
                error_reason="No valid accelerometer values parsed from termux-sensor",
            )

        return SensorWindow(
            accel_samples=accel_all,
            gyro_samples=gyro_all,
            gyro_available=self.gyro_name is not None,
        )
