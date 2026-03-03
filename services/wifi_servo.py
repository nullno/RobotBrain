"""
WiFi 舵机通信模块 —— 与 ESP32 固件 UDP 协议对接。

协议对齐 a_Firmware/esp32/main.py 中 handle_command() 定义：
- servo_targets / keyframe  → 控制舵机位置
- torque                    → 使能/释放扭矩
- motion                    → 下发预设动作名
- status                    → 请求 telemetry（IMU + servos + wifi）
- discover                  → 局域网广播发现设备

用法示例：
    ctrl = WiFiServoController("192.168.1.100", 5005)
    ctrl.set_targets({1: 500, 2: 300}, duration_ms=400)
    ctrl.set_torque(True)
    ctrl.send_motion("stand")
    status = ctrl.request_status(timeout=0.5)
    ctrl.close()
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ESP32 固件伺服范围（与 a_Firmware/esp32/main.py 中 SERVO_MIN/MAX 一致）
SERVO_MIN = 0
SERVO_MAX = 1000
DEFAULT_UDP_PORT = 5005
MAX_SERVO_ID = 25


class WiFiServoController:
    """通过 UDP 与 ESP32 固件通信的舵机控制器。

    线程安全：所有公开方法可从任意线程调用。
    """

    def __init__(self, host: str = "", port: int = DEFAULT_UDP_PORT):
        self._host = host
        self._port = int(port or DEFAULT_UDP_PORT)
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._connected = False
        # 最新 telemetry 缓存
        self._last_status: Dict[str, Any] = {}
        self._last_status_ts: float = 0.0
        if host:
            self._ensure_socket()

    # -------------------- 连接管理 --------------------

    def set_host(self, host: str, port: Optional[int] = None):
        """切换目标 ESP32 主机地址。"""
        with self._lock:
            self._host = str(host or "")
            if port is not None:
                self._port = int(port)
            self._connected = bool(self._host)
            self._ensure_socket()

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def is_connected(self) -> bool:
        return self._connected and bool(self._host)

    def close(self):
        with self._lock:
            self._connected = False
            try:
                if self._sock:
                    self._sock.close()
            except Exception:
                pass
            self._sock = None

    # -------------------- 舵机控制 --------------------

    def set_targets(self, targets: Dict[int, int], duration_ms: int = 300) -> bool:
        """发送舵机目标位置。

        Args:
            targets: {servo_id: position} 字典，position 范围 0-1000
            duration_ms: 运动时间（毫秒）
        Returns:
            是否发送成功
        """
        safe = {}
        for sid, pos in (targets or {}).items():
            try:
                sid_i = int(sid)
                if sid_i < 1 or sid_i > MAX_SERVO_ID:
                    continue
                safe[str(sid_i)] = max(SERVO_MIN, min(SERVO_MAX, int(pos)))
            except (ValueError, TypeError):
                continue
        if not safe:
            return False
        payload = {
            "type": "servo_targets",
            "targets": safe,
            "duration": max(30, int(duration_ms)),
        }
        return self._send(payload)

    def set_single(self, servo_id: int, position: int, duration_ms: int = 300) -> bool:
        """控制单个舵机。"""
        return self.set_targets({int(servo_id): int(position)}, duration_ms)

    def set_torque(self, enable: bool = True) -> bool:
        """使能或释放所有舵机扭矩。"""
        return self._send({"type": "torque", "enable": bool(enable)})

    def send_motion(self, name: str, speed: float = 1.0) -> bool:
        """发送预设动作名称（如 stand / sit / walk 等）。"""
        payload = {
            "type": "motion",
            "name": str(name or "").lower().strip(),
            "speed": float(max(0.1, min(2.0, speed))),
        }
        return self._send(payload)

    # -------------------- 状态查询 --------------------

    def request_status(self, timeout: float = 0.5) -> Optional[Dict[str, Any]]:
        """向 ESP32 请求当前 telemetry（阻塞等待回复）。

        Returns:
            包含 imu / servos / wifi 等字段的 dict，超时返回 None。
        """
        payload = {"type": "status"}
        with self._lock:
            if not self._host or not self._sock:
                return None
            try:
                data = json.dumps(payload).encode("utf-8")
                self._sock.sendto(data, (self._host, self._port))
                self._sock.settimeout(float(timeout))
                resp_data, _ = self._sock.recvfrom(4096)
                obj = json.loads(resp_data.decode("utf-8"))
                self._last_status = obj
                self._last_status_ts = time.time()
                self._connected = True
                return obj
            except Exception:
                return self._last_status if self._last_status else None

    def get_cached_status(self) -> Dict[str, Any]:
        """返回最近一次缓存的 telemetry。"""
        return dict(self._last_status)

    def get_servo_positions(self) -> Dict[int, int]:
        """从缓存 status 中提取舵机位置。"""
        servos = self._last_status.get("servos") or {}
        result = {}
        for sid_str, val in servos.items():
            try:
                sid = int(sid_str)
                if isinstance(val, dict):
                    pos = val.get("pos") or val.get("position")
                else:
                    pos = int(val)
                if pos is not None:
                    result[sid] = int(pos)
            except (ValueError, TypeError):
                continue
        return result

    def get_imu(self) -> Tuple[float, float, float]:
        """从缓存 status 中提取 IMU 数据 (pitch, roll, yaw)。"""
        imu = self._last_status.get("imu") or {}
        if isinstance(imu, dict):
            return (
                float(imu.get("pitch", 0.0)),
                float(imu.get("roll", 0.0)),
                float(imu.get("yaw", 0.0)),
            )
        return (0.0, 0.0, 0.0)

    # -------------------- 发现 --------------------

    @staticmethod
    def discover(timeout: float = 2.0, port: int = DEFAULT_UDP_PORT) -> List[Tuple[str, Dict[str, Any]]]:
        """局域网 UDP 广播发现 ESP32 设备。

        Returns:
            [(ip, response_dict), ...]
        """
        return udp_discover(timeout=timeout, port=port)

    # -------------------- 内部 --------------------

    def _ensure_socket(self):
        if self._sock is None:
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._sock.settimeout(0.4)
            except Exception:
                self._sock = None

    def _send(self, payload: dict) -> bool:
        with self._lock:
            if not self._host:
                return False
            self._ensure_socket()
            if not self._sock:
                return False
            try:
                data = json.dumps(payload).encode("utf-8")
                self._sock.sendto(data, (self._host, self._port))
                self._connected = True
                return True
            except Exception as e:
                logger.debug("UDP send failed: %s", e)
                self._connected = False
                return False


# --------------- 便捷全局实例 ---------------
_global_ctrl: Optional[WiFiServoController] = None
_global_lock = threading.Lock()


def get_controller() -> WiFiServoController:
    """获取全局单例 WiFiServoController（懒初始化）。"""
    global _global_ctrl
    with _global_lock:
        if _global_ctrl is None:
            _global_ctrl = WiFiServoController()
        return _global_ctrl


def init_controller(host: str, port: int = DEFAULT_UDP_PORT) -> WiFiServoController:
    """初始化全局控制器并设置目标主机。"""
    ctrl = get_controller()
    ctrl.set_host(host, port)
    return ctrl


# --------------- UDP 发现 ---------------

def udp_discover(timeout: float = 2.0, port: int = DEFAULT_UDP_PORT) -> List[Tuple[str, Dict[str, Any]]]:
    """局域网 UDP 广播发现 ESP32 设备。

    向 255.255.255.255:port 发送 ``{"type":"discover"}``，收集回复。
    Returns:
        [(ip, response_dict), ...]
    """
    results: Dict[str, Dict[str, Any]] = {}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.4)
        msg = json.dumps({"type": "discover"}).encode("utf-8")
        end = time.time() + float(timeout or 2.0)
        logger.info("UDP 广播发现 ESP32 (%.1fs)", float(timeout or 2.0))
        while time.time() < end:
            try:
                sock.sendto(msg, ("<broadcast>", int(port)))
            except Exception:
                pass
            deadline = time.time() + 0.4
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(2048)
                    ip = addr[0]
                    try:
                        obj = json.loads(data.decode("utf-8"))
                    except Exception:
                        obj = {"raw": data.hex()}
                    results[ip] = obj
                    logger.info("发现 ESP32: %s", ip)
                except Exception:
                    break
        sock.close()
    except Exception:
        pass
    logger.info("发现结束: %d 个设备", len(results))
    return list(results.items())


# --------------- 主机记忆 ---------------

def _host_config_path(app=None) -> str:
    """返回保存 ESP32 主机信息的文件路径。"""
    try:
        from pathlib import Path
        base = Path(getattr(app, "user_data_dir", None) or "data")
        return str(base / "esp32_host.json")
    except Exception:
        return "data/esp32_host.json"


def save_host(host: str, port: int = DEFAULT_UDP_PORT, app=None):
    """将 ESP32 主机信息持久化。"""
    try:
        import os
        fp = _host_config_path(app)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump({"host": host, "port": int(port), "ts": int(time.time())}, f)
    except Exception:
        pass


def load_host(app=None) -> Tuple[Optional[str], int]:
    """加载已保存的 ESP32 主机信息。"""
    try:
        fp = _host_config_path(app)
        import os
        if not os.path.exists(fp):
            return None, DEFAULT_UDP_PORT
        with open(fp, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return str(obj.get("host", "")), int(obj.get("port", DEFAULT_UDP_PORT))
    except Exception:
        return None, DEFAULT_UDP_PORT


__all__ = [
    "WiFiServoController",
    "get_controller",
    "init_controller",
    "udp_discover",
    "save_host",
    "load_host",
    "SERVO_MIN",
    "SERVO_MAX",
    "MAX_SERVO_ID",
    "DEFAULT_UDP_PORT",
]
