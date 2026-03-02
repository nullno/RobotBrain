"""
Control bridge for PC/mobile GUI <-> ESP32 <-> CH340 servo board.
- Supports UDP and WebSocket command/telemetry channels.
- Provides safety-checked servo writes and remote motion commands.
- Exposes IMU readings (prefers telemetry; falls back to local I2C IMU).

This module is designed to be resilient: it tolerates missing network links and
falls back to simulation when hardware is absent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from services.ble_provisioner import send_wifi_credentials
from services.imu_service import IMUService

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    websockets = None

logger = logging.getLogger(__name__)


@dataclass
class ServoStatus:
    position: Optional[int] = None
    temperature: Optional[float] = None
    voltage: Optional[float] = None
    torque_enabled: Optional[bool] = None
    online: bool = False


class ControlBridge:
    def __init__(
        self,
        udp_host: str = "192.168.4.1",
        udp_port: int = 5005,
        ws_url: str = "ws://192.168.4.1:8080/ws",
        max_servo_id: int = 25,
        min_angle: int = 0,
        max_angle: int = 4095,
    ) -> None:
        self.udp_host = udp_host
        self.udp_port = int(udp_port)
        self.ws_url = ws_url
        self.max_servo_id = int(max_servo_id)
        self.min_angle = int(min_angle)
        self.max_angle = int(max_angle)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ws: Optional[object] = None
        self._imu = IMUService(simulate=True)
        self._last_imu: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._servo_status: Dict[int, ServoStatus] = {i: ServoStatus() for i in range(1, max_servo_id + 1)}
        self._last_ws_rx = 0.0
        self._last_udp_rx = 0.0

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._imu.start()

    def stop(self) -> None:
        self._stop.set()
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        self._thread = None
        self._imu.stop()

    # ------------------------------------------------------------------
    def set_udp_target(self, host: str, port: Optional[int] = None) -> None:
        if host:
            self.udp_host = host
        if port:
            self.udp_port = int(port)

    def set_ws_url(self, ws_url: str) -> None:
        if ws_url:
            self.ws_url = ws_url

    # ------------------------------------------------------------------
    def send_servo_targets(self, targets: Dict[int, int], duration_ms: int = 120) -> None:
        safe_targets = {}
        for sid, pos in (targets or {}).items():
            try:
                sid_i = int(sid)
                if sid_i < 1 or sid_i > self.max_servo_id:
                    continue
                pos_i = int(pos)
                pos_i = max(self.min_angle, min(self.max_angle, pos_i))
                safe_targets[sid_i] = pos_i
            except Exception:
                continue
        if not safe_targets:
            return
        payload = {
            "type": "targets",
            "duration": int(max(30, duration_ms)),
            "targets": safe_targets,
        }
        self._fire_and_forget_udp(payload)
        self._submit_ws(payload)

    def send_motion(self, name: str, speed: float = 1.0) -> None:
        payload = {
            "type": "motion",
            "name": str(name or "").lower(),
            "speed": float(max(0.1, min(2.0, speed))),
        }
        self._submit_ws(payload)
        self._fire_and_forget_udp(payload)

    def request_status(self) -> None:
        payload = {"type": "status"}
        self._submit_ws(payload)
        self._fire_and_forget_udp(payload)

    def provision_wifi_via_ble(self, ssid: str, password: str) -> Tuple[bool, str]:
        return send_wifi_credentials(ssid, password)

    # ------------------------------------------------------------------
    def get_latest_imu(self) -> Tuple[float, float, float]:
        if (time.time() - self._last_ws_rx) < 2.0 or (time.time() - self._last_udp_rx) < 2.0:
            return self._last_imu
        return self._imu.get_orientation()

    def get_servo_cards(self):
        cards = []
        for sid, st in self._servo_status.items():
            data = None
            if st.position is not None:
                data = {
                    "pos": st.position,
                    "temp": st.temperature,
                    "volt": st.voltage,
                    "torque": st.torque_enabled,
                }
            cards.append((sid, data, bool(st.online)))
        return cards

    # ------------------------------------------------------------------
    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        tasks = []
        tasks.append(loop.create_task(self._udp_server()))
        if websockets is not None:
            tasks.append(loop.create_task(self._ws_client()))
        try:
            loop.run_forever()
        except KeyboardInterrupt:  # pragma: no cover - manual stop
            pass
        finally:
            for t in tasks:
                t.cancel()
            try:
                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            except Exception:
                pass
            loop.stop()
            loop.close()
            self._loop = None

    # ------------------------------------------------------------------
    async def _ws_client(self) -> None:
        while not self._stop.is_set():
            if websockets is None:
                await asyncio.sleep(2.0)
                continue
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    logger.info("WebSocket connected to %s", self.ws_url)
                    await ws.send(json.dumps({"type": "hello", "ts": time.time()}))
                    async for msg in ws:
                        self._handle_incoming(msg)
                        self._last_ws_rx = time.time()
            except Exception as exc:
                logger.debug("ws reconnect due to %s", exc)
                await asyncio.sleep(2.0)
            finally:
                self._ws = None

    async def _udp_server(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self._handle_incoming), local_addr=("0.0.0.0", self.udp_port)
        )
        try:
            while not self._stop.is_set():
                await asyncio.sleep(0.25)
        finally:
            transport.close()

    def _handle_incoming(self, msg: str) -> None:
        try:
            if isinstance(msg, (bytes, bytearray)):
                msg = msg.decode("utf-8", errors="ignore")
            obj = json.loads(msg)
        except Exception:
            return
        typ = obj.get("type")
        if typ == "imu":
            try:
                p, r, y = obj.get("pitch", 0), obj.get("roll", 0), obj.get("yaw", 0)
                self._last_imu = (float(p), float(r), float(y))
            except Exception:
                pass
        elif typ == "servo_status":
            try:
                items = obj.get("items", {})
                now = time.time()
                for sid_str, data in items.items():
                    sid = int(sid_str)
                    if sid not in self._servo_status:
                        continue
                    st = self._servo_status[sid]
                    st.position = data.get("pos")
                    st.temperature = data.get("temp")
                    st.voltage = data.get("volt")
                    st.torque_enabled = data.get("torque")
                    st.online = True
                self._last_udp_rx = now
            except Exception:
                pass
        elif typ == "status":
            try:
                imu = obj.get("imu") or {}
                self._last_imu = (
                    float(imu.get("pitch", 0.0)),
                    float(imu.get("roll", 0.0)),
                    float(imu.get("yaw", 0.0)),
                )
                items = obj.get("servos", {})
                now = time.time()
                for sid_str, data in items.items():
                    sid = int(sid_str)
                    if sid not in self._servo_status:
                        continue
                    st = self._servo_status[sid]
                    st.position = data.get("pos")
                    st.temperature = data.get("temp")
                    st.voltage = data.get("volt")
                    st.torque_enabled = data.get("torque")
                    st.online = True
                self._last_udp_rx = now
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _submit_ws(self, payload: dict) -> None:
        if self._loop is None or websockets is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._ws_send(payload), self._loop)
        except Exception:
            pass

    async def _ws_send(self, payload: dict) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(payload))
        except Exception:
            pass

    def _fire_and_forget_udp(self, payload: dict) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.2)
            sock.sendto(json.dumps(payload).encode("utf-8"), (self.udp_host, self.udp_port))
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass


class _UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_message):
        self.on_message = on_message

    def datagram_received(self, data, addr):
        try:
            self.on_message(data)
        except Exception:
            pass


__all__ = ["ControlBridge", "ServoStatus"]
