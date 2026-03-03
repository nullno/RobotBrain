"""ESP32 链路状态与数据交换服务。

职责：
- 聚合 ESP32 UDP/WebSocket 状态（连接、信号强度、主机信息）。
- 为调试面板提供统一的舵机状态读取与指令发送入口。
- 将现有 `servo_bus` 与 `control_bridge` 的数据封装为线程安全的快照。
"""
from __future__ import annotations

import threading
import time
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services import esp32_client

logger = logging.getLogger(__name__)


class Esp32Link:
    def __init__(self, app, poll_interval: float = 1.5):
        self.app = app
        self.poll_interval = float(max(0.6, poll_interval))
        self._host: Optional[str] = None
        self._port: int = 5005
        self._last_rssi: Optional[float] = None
        self._last_status: Dict[str, Any] = {}
        self._last_seen: float = 0.0
        self._connected: bool = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------------------- lifecycle ----------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if self._thread:
                self._thread.join(timeout=0.6)
        except Exception:
            pass
        self._thread = None

    # ---------------------- host binding ----------------------
    def set_host(self, host: Optional[str], port: Optional[int] = None):
        if not host:
            return
        try:
            esp32_client.set_host(host, port=port)
        except Exception:
            pass
        with self._lock:
            self._host = str(host)
            if port is not None:
                try:
                    self._port = int(port)
                except Exception:
                    pass

    # ---------------------- public API ----------------------
    def send_targets(self, targets: Dict[int, int], duration_ms: int = 120) -> bool:
        bridge = getattr(self.app, "control_bridge", None)
        try:
            if bridge:
                bridge.send_servo_targets(targets, duration_ms=duration_ms)
                return True
        except Exception:
            logger.debug("control_bridge send_targets failed", exc_info=True)
        sb = getattr(self.app, "servo_bus", None)
        try:
            if sb and not getattr(sb, "is_mock", True):
                sb.move_sync(targets, time_ms=duration_ms)
                return True
        except Exception:
            logger.debug("servo_bus send_targets failed", exc_info=True)
        return False

    def set_torque(self, enable: bool) -> bool:
        bridge = getattr(self.app, "control_bridge", None)
        try:
            if bridge:
                # control_bridge 暂无专用扭矩命令，保留占位以便固件扩展
                payload = {"type": "torque", "enable": bool(enable)}
                bridge._fire_and_forget_udp(payload)  # pylint: disable=protected-access
                bridge._submit_ws(payload)  # pylint: disable=protected-access
                return True
        except Exception:
            logger.debug("control_bridge torque fallback failed", exc_info=True)
        sb = getattr(self.app, "servo_bus", None)
        try:
            if sb and not getattr(sb, "is_mock", True):
                sb.set_torque(bool(enable))
                return True
        except Exception:
            logger.debug("servo_bus set_torque failed", exc_info=True)
        return False

    def get_servo_cards(self) -> List[Tuple[int, Optional[Dict[str, Any]], bool]]:
        bridge = getattr(self.app, "control_bridge", None)
        try:
            if bridge:
                cards = list(bridge.get_servo_cards() or [])
                if cards:
                    return cards
        except Exception:
            logger.debug("control_bridge get_servo_cards failed", exc_info=True)

        sb = getattr(self.app, "servo_bus", None)
        try:
            if sb and not getattr(sb, "is_mock", True):
                cache = getattr(sb, "_telemetry_cache", {}).get("servos", {})
                now = time.time()
                cards = []
                max_sid = max(cache.keys()) if cache else 25
                for sid in range(1, max_sid + 1):
                    entry = cache.get(sid) or {}
                    ts = float(entry.get("ts", 0.0) or 0.0)
                    online = (now - ts) < 3.0 if entry else False
                    data = None
                    if entry:
                        data = {
                            "pos": entry.get("pos"),
                            "temp": entry.get("temp"),
                            "volt": entry.get("volt"),
                            "torque": entry.get("torque"),
                        }
                    cards.append((sid, data, online))
                return cards
        except Exception:
            logger.debug("servo_bus cards fallback failed", exc_info=True)

        # fallback placeholders
        return [(sid, None, False) for sid in range(1, 26)]

    def get_ui_state(self) -> Dict[str, Any]:
        cards = self.get_servo_cards()
        online_cnt = sum(1 for _sid, _data, online in cards if online)
        total = len(cards)
        with self._lock:
            host = self._host or getattr(self.app, "_esp32_host", None)
            port = self._port or getattr(self.app, "_esp32_port", 5005)
            rssi = self._last_rssi
            connected = self._connected or self._is_bus_connected()
            last_seen = self._last_seen
            ssid = self._last_status.get("ssid")
        quality, bars = _rssi_to_quality_and_bars(rssi)
        return {
            "connected": bool(connected),
            "host": host,
            "port": port,
            "rssi": rssi,
            "quality": quality,
            "bars": bars,
            "last_seen": last_seen,
            "online_servos": online_cnt,
            "total_servos": total,
            "ssid": ssid,
        }

    # ---------------------- internal ----------------------
    def _loop(self):
        while not self._stop.is_set():
            try:
                self._poll_status()
            except Exception:
                logger.debug("esp32 link poll failed", exc_info=True)
            self._stop.wait(self.poll_interval)

    def _poll_status(self):
        host = self._host or getattr(self.app, "_esp32_host", None)
        if not host:
            self._mark_disconnected()
            return
        try:
            esp32_client.set_host(host, port=self._port)
        except Exception:
            pass
        res = esp32_client.status()
        now = time.time()
        connected = False
        rssi = None
        ssid = None
        try:
            if isinstance(res, dict):
                connected = True
                wifi_obj = res.get("wifi") if isinstance(res.get("wifi"), dict) else res
                if isinstance(wifi_obj, dict):
                    rssi = wifi_obj.get("rssi")
                    ssid = wifi_obj.get("ssid")
        except Exception:
            connected = False
        with self._lock:
            self._last_rssi = rssi
            if connected:
                self._last_seen = now
            self._connected = bool(connected or self._is_bus_connected())
            self._last_status = {
                "host": host,
                "port": self._port,
                "rssi": rssi,
                "ssid": ssid,
                "ts": now,
            }

    def _mark_disconnected(self):
        with self._lock:
            self._connected = self._is_bus_connected()
            self._last_rssi = None

    def _is_bus_connected(self) -> bool:
        try:
            sb = getattr(self.app, "servo_bus", None)
            return bool(sb and not getattr(sb, "is_mock", True))
        except Exception:
            return False


def _rssi_to_quality_and_bars(rssi: Optional[float]) -> Tuple[Optional[int], Optional[int]]:
    if rssi is None:
        return None, None
    try:
        rssi_f = float(rssi)
    except Exception:
        return None, None
    if rssi_f >= -50:
        quality = 100
    elif rssi_f >= -60:
        quality = 90
    elif rssi_f >= -67:
        quality = 75
    elif rssi_f >= -75:
        quality = 55
    elif rssi_f >= -82:
        quality = 35
    else:
        quality = 15
    bars = max(0, min(4, int((quality + 4) // 25)))
    return int(quality), int(bars)


__all__ = ["Esp32Link"]
