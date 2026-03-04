"""
WiFi 舵机通信模块 —— 与 ESP32 固件 UDP 协议对接。

协议对齐 a_Firmware/esp32/main.py 中 handle_command() 定义：
- servo_targets / keyframe  → 控制舵机位置
- torque                    → 使能/释放扭矩
- motion                    → 下发预设动作名
- status                    → 请求 telemetry（IMU + servos + wifi）
- discover                  → 局域网广播发现设备
- ping                      → Ping 指定舵机
- read_position             → 读取单个舵机位置
- motor_mode                → 切换电机/舵机模式
- motor_speed               → 设置电机转速与方向
- scan                      → 扫描所有在线舵机
- set_single                → 控制单个舵机（独立指令）

用法示例：
    ctrl = WiFiServoController("192.168.1.100", 5005)
    ctrl.set_targets({1: 500, 2: 300}, duration_ms=400)
    ctrl.set_torque(True)
    ctrl.send_motion("stand")
    status = ctrl.request_status(timeout=0.5)
    online = ctrl.ping_servo(1)           # Ping 舵机 1
    pos = ctrl.read_servo_position(3)     # 读取舵机 3 位置
    ctrl.set_motor_mode(5, mode="motor")  # 舵机 5 切换电机模式
    ids = ctrl.scan_servos()              # 扫描在线舵机列表
    ctrl.close()
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# UDP 调试输出开关，默认关闭，设环境变量 WIFI_SERVO_UDP_DEBUG=1 可开启
UDP_DEBUG = bool(int(os.environ.get("WIFI_SERVO_UDP_DEBUG", "0") or 0))

# ESP32 固件舵机范围（12bit，0-4095，与 a_Firmware/esp32/servo_controller.py 对齐）
SERVO_MIN = 0
SERVO_MAX = 4095
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
            # 仅在实际收发成功后才标记 connected
            self._connected = False
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
            targets: {servo_id: position} 字典，position 范围 0-4095
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

    # -------------------- 扩展指令 --------------------

    def ping_servo(self, servo_id: int, timeout: float = 0.5) -> bool:
        """Ping 指定舵机，返回是否在线。"""
        payload = {"type": "ping", "servo_id": int(servo_id)}
        resp = self._send_and_recv(payload, timeout)
        if resp and resp.get("type") == "ping_resp":
            online = bool(resp.get("online", False))
            logger.info("ping servo %d → %s", servo_id, "online" if online else "offline")
            return online
        logger.warning("ping servo %d → timeout", servo_id)
        return False

    def read_servo_position(self, servo_id: int, timeout: float = 0.5) -> Optional[int]:
        """读取指定舵机当前位置。返回 0-4096 或 None。"""
        payload = {"type": "read_position", "servo_id": int(servo_id)}
        resp = self._send_and_recv(payload, timeout)
        if resp and resp.get("type") == "read_position_resp":
            pos = resp.get("position")
            logger.info("read_position servo %d → %s", servo_id, pos)
            return int(pos) if pos is not None else None
        logger.warning("read_position servo %d → timeout", servo_id)
        return None

    def set_motor_mode(self, servo_id: int, mode: str = "motor", timeout: float = 0.5) -> bool:
        """切换舵机/电机模式。mode: 'motor' 或 'servo'。"""
        payload = {"type": "motor_mode", "servo_id": int(servo_id), "mode": str(mode)}
        resp = self._send_and_recv(payload, timeout)
        ok = bool(resp and resp.get("ok"))
        logger.info("motor_mode servo %d mode=%s → %s", servo_id, mode, "ok" if ok else "fail")
        return ok

    def set_motor_speed(self, servo_id: int, speed: int = 0, direction: int = 1, timeout: float = 0.5) -> bool:
        """设置电机转速与方向（需先切换为电机模式）。

        Args:
            servo_id: 舵机 ID
            speed: 转速 0-1000
            direction: 方向 0 或 1
        """
        payload = {
            "type": "motor_speed",
            "servo_id": int(servo_id),
            "speed": max(0, min(1000, int(speed))),
            "direction": int(direction),
        }
        resp = self._send_and_recv(payload, timeout)
        ok = bool(resp and resp.get("ok"))
        logger.info("motor_speed servo %d speed=%d dir=%d → %s", servo_id, speed, direction, "ok" if ok else "fail")
        return ok

    def scan_servos(self, timeout: float = 3.0) -> List[int]:
        """扫描所有在线舵机 ID 列表。"""
        payload = {"type": "scan"}
        resp = self._send_and_recv(payload, timeout)
        if resp and resp.get("type") == "scan_resp":
            ids = resp.get("online") or []
            logger.info("scan_servos → %d online: %s", len(ids), ids)
            return [int(i) for i in ids]
        logger.warning("scan_servos → timeout")
        return []

    def send_set_single(self, servo_id: int, position: int, duration_ms: int = 300, timeout: float = 0.5) -> bool:
        """通过独立指令控制单个舵机（与 set_targets 走不同路径）。"""
        payload = {
            "type": "set_single",
            "servo_id": int(servo_id),
            "position": int(position),
            "duration": max(30, int(duration_ms)),
        }
        resp = self._send_and_recv(payload, timeout)
        ok = bool(resp and resp.get("ok"))
        logger.info("set_single servo %d pos=%d dur=%d → %s", servo_id, position, duration_ms, "ok" if ok else "fail")
        return ok

    def read_full_status(self, servo_id: int, timeout: float = 0.8) -> Optional[Dict[str, Any]]:
        """读取指定舵机完整状态（位置、温度、电压、电流、速度等）。"""
        payload = {"type": "read_full_status", "servo_id": int(servo_id)}
        resp = self._send_and_recv(payload, timeout)
        if resp and resp.get("type") == "read_full_status_resp":
            data = resp.get("data") or {}
            logger.info("read_full_status servo %d → %s", servo_id, data)
            return data
        logger.warning("read_full_status servo %d → timeout", servo_id)
        return None

    def read_temperature(self, servo_id: int, timeout: float = 0.5) -> Optional[int]:
        """读取指定舵机温度（℃）。"""
        payload = {"type": "read_temperature", "servo_id": int(servo_id)}
        resp = self._send_and_recv(payload, timeout)
        if resp and resp.get("type") == "read_temperature_resp":
            return resp.get("temperature")
        return None

    def read_voltage(self, servo_id: int, timeout: float = 0.5) -> Optional[float]:
        """读取指定舵机供电电压（V）。"""
        payload = {"type": "read_voltage", "servo_id": int(servo_id)}
        resp = self._send_and_recv(payload, timeout)
        if resp and resp.get("type") == "read_voltage_resp":
            return resp.get("voltage")
        return None

    def set_torque_single(self, servo_id: int, enable: bool = True, timeout: float = 0.5) -> bool:
        """使能或释放单个舵机扭矩。"""
        payload = {"type": "torque_single", "servo_id": int(servo_id), "enable": bool(enable)}
        resp = self._send_and_recv(payload, timeout)
        ok = bool(resp and resp.get("ok"))
        logger.info("torque_single servo %d enable=%s → %s", servo_id, enable, "ok" if ok else "fail")
        return ok

    def change_servo_id(self, old_id: int, new_id: int, timeout: float = 0.5) -> bool:
        """修改舵机 ID（需写入 EEPROM）。"""
        payload = {"type": "set_servo_id", "old_id": int(old_id), "new_id": int(new_id)}
        resp = self._send_and_recv(payload, timeout)
        ok = bool(resp and resp.get("ok"))
        logger.info("set_servo_id %d → %d: %s", old_id, new_id, "ok" if ok else "fail")
        return ok

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
                if UDP_DEBUG:
                    logger.debug("UDP → %s:%d  %s", self._host, self._port, payload.get("type", "?"))
                return True
            except Exception as e:
                logger.debug("UDP send failed: %s", e)
                self._connected = False
                return False

    def _send_and_recv(self, payload: dict, timeout: float = 0.5) -> Optional[Dict[str, Any]]:
        """发送指令并等待回复（阻塞）。用于需要返回结果的指令。"""
        with self._lock:
            if not self._host:
                return None
            self._ensure_socket()
            if not self._sock:
                return None
            try:
                data = json.dumps(payload).encode("utf-8")
                self._sock.sendto(data, (self._host, self._port))
                if UDP_DEBUG:
                    logger.debug("UDP → %s:%d  %s", self._host, self._port, payload.get("type", "?"))
                self._sock.settimeout(float(timeout))
                resp_data, _ = self._sock.recvfrom(4096)
                obj = json.loads(resp_data.decode("utf-8"))
                if UDP_DEBUG:
                    logger.debug("UDP ← %s", obj.get("type", "?"))
                self._connected = True
                return obj
            except socket.timeout:
                if UDP_DEBUG:
                    logger.debug("UDP recv timeout for %s", payload.get("type", "?"))
                return None
            except Exception as e:
                logger.debug("UDP send_and_recv failed: %s", e)
                self._connected = False
                return None


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

if __name__ == "__main__":
    # 简单测试：发现设备 → 连接 → 查询状态
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    devices = udp_discover(timeout=3.0)
    if devices:
        ip, info = devices[0]
        print(f"发现设备: {ip} → {info}")
        ctrl = init_controller(ip)
        s = ctrl.request_status(timeout=1.0)
        print(f"状态: {s}")
        ids = ctrl.scan_servos(timeout=3.0)
        print(f"在线舵机: {ids}")
    else:
        print("未发现设备")
