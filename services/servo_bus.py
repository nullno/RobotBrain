"""
ServoBus 网络桥接（ESP32 UDP 客户端）

此模块替代原先的基于串口的 `ServoBus` 实现，向 ESP32 固件发送关键帧指令。
保持与原接口兼容的常用方法：`move`, `move_sync`, `set_torque`, `get_status`, `close`。

连接逻辑：
- 优先使用传入的 `port` 参数作为 ESP32 主机地址（如果看起来像 IP 地址或域名）；
- 若未提供，从环境变量 `ESP32_HOST` 读取；若仍未提供，进入 mock 模式（`is_mock=True`）。

通信：通过 UDP 将 JSON 包发送到 ESP32 (默认端口 5005)。
JSON 格式示例： {"targets": {"1": 2048, "2":1024}, "duration": 500}
"""

import os
import socket
import json
import time
import threading


class ServoBus:
    """UDP 桥接到 ESP32 的 ServoBus。

    - `port` 代表 ESP32 主机地址（IP/域名）；若缺省则读取环境变量 `ESP32_HOST`
    - 维持与原串口版接口兼容：`move`/`move_sync`/`sync_set_position`/`read_data_by_name`
    - 增强：后台监听 telemetry，缓存 IMU 与舵机状态供 UI 与平衡算法读取
    """

    def __init__(self, port=None, baudrate=115200):
        """port: ESP32 主机地址字符串（如 '192.168.4.1'）；无则读取 ESP32_HOST。"""
        self.is_mock = True
        self._host = None
        self._port = 5005
        self._telemetry_port = int(os.environ.get("ESP32_TELEMETRY_PORT", 5006))
        self._telemetry_sock = None
        self._telemetry_thread = None
        self._telemetry_running = False
        self._telemetry_cache = {
            "imu": (0.0, 0.0, 0.0),
            "servos": {},  # sid -> {pos, temp, volt, torque, ts}
        }
        # 提供最小的 servo_info_dict 供 UI 展示与 ping() 使用
        self.servo_info_dict = {
            sid: type("ServoInfo", (), {"id": sid, "is_online": True})()
            for sid in range(1, 26)
        }
        self.manager = self  # 兼容旧代码习惯使用 servo_bus.manager

        try:
            host = None
            if isinstance(port, str) and ('.' in port or ':' in port):
                host = port
            if isinstance(port, int):
                # 当传入纯端口时，仍然依赖环境变量/记忆的主机
                self._port = int(port)
            if not host:
                host = os.environ.get('ESP32_HOST')
            env_port = os.environ.get('ESP32_PORT')
            if env_port:
                self._port = int(env_port)
            if not host:
                # 无可用主机，进入 mock 模式
                self.is_mock = True
                return

            # 支持 "ip:port" 写法
            if ':' in str(host):
                try:
                    h, p = str(host).rsplit(':', 1)
                    self._host = h
                    self._port = int(p)
                except Exception:
                    self._host = str(host)
            else:
                self._host = str(host)
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(0.4)
            self.is_mock = False
            # 启动 telemetry 监听，尽早获取 IMU/舵机反馈
            self._start_telemetry_listener()
            # 主动告知 ESP32 我们的 telemetry 端口（固件可选实现）
            self._send_udp({"hello": True, "telemetry_port": self._telemetry_port})
            self._send_udp({"type": "telemetry_subscribe", "port": self._telemetry_port})
        except Exception:
            self.is_mock = True

    def _send_udp(self, payload: dict):
        if self.is_mock:
            return False
        try:
            data = json.dumps(payload).encode('utf-8')
            self._sock.sendto(data, (self._host, self._port))
            return True
        except Exception:
            return False

    def close(self):
        self._stop_telemetry_listener()
        try:
            if not self.is_mock and hasattr(self, '_sock'):
                try:
                    self._sock.close()
                except Exception:
                    pass
        finally:
            self.is_mock = True

    def move(self, sid, position, time_ms=300):
        if self.is_mock:
            return
        try:
            payload = {'targets': {str(int(sid)): int(position)}, 'duration': int(time_ms)}
            self._send_udp(payload)
            info = self.servo_info_dict.get(int(sid))
            if info is not None:
                try:
                    info.is_online = True
                except Exception:
                    pass
        except Exception:
            pass

    def move_sync(self, targets: dict, time_ms=300):
        if self.is_mock or not targets:
            return
        try:
            # normalize keys to strings
            t = {str(int(k)): int(v) for k, v in targets.items()}
            payload = {'targets': t, 'duration': int(time_ms)}
            self._send_udp(payload)
            for k in targets:
                info = self.servo_info_dict.get(int(k))
                if info is not None:
                    try:
                        info.is_online = True
                    except Exception:
                        pass
        except Exception:
            pass

    # 兼容旧 API
    def sync_set_position(self, servo_id_list, position_list, runtime_ms_list):
        try:
            pairs = {str(int(servo_id_list[i])): int(position_list[i]) for i in range(min(len(servo_id_list), len(position_list)))}
            dur = int(runtime_ms_list[0]) if runtime_ms_list else 300
            self.move_sync(pairs, time_ms=dur)
        except Exception:
            pass

    def set_position_time(self, servo_id, position, runtime_ms=None, time_ms=None):
        if runtime_ms is None and time_ms is not None:
            runtime_ms = time_ms
        if runtime_ms is None:
            runtime_ms = 300
        self.move(int(servo_id), int(position), int(runtime_ms))

    def set_torque(self, enable=True):
        # ESP32 固件若需支持扭矩控制，可扩展协议；当前为无操作
        try:
            payload = {'torque': bool(enable)}
            self._send_udp(payload)
        except Exception:
            pass

    def get_status(self, sid):
        # 无状态读取机制，返回 None
        return None

    # ---------------- Telemetry 支持 ----------------
    def _start_telemetry_listener(self):
        if self.is_mock or self._telemetry_running:
            return
        self._telemetry_running = True

        def _loop():
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("", int(self._telemetry_port)))
                sock.settimeout(1.0)
                self._telemetry_sock = sock
                while self._telemetry_running:
                    try:
                        data, addr = sock.recvfrom(4096)
                        if not data:
                            continue
                        try:
                            obj = json.loads(data.decode("utf-8"))
                        except Exception:
                            continue
                        if isinstance(obj, dict):
                            self._handle_telemetry(obj, addr)
                    except socket.timeout:
                        continue
                    except Exception:
                        time.sleep(0.02)
            finally:
                try:
                    if sock:
                        sock.close()
                finally:
                    self._telemetry_sock = None

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        self._telemetry_thread = t

    def _stop_telemetry_listener(self):
        self._telemetry_running = False
        try:
            if self._telemetry_sock:
                self._telemetry_sock.close()
        except Exception:
            pass
        try:
            if self._telemetry_thread:
                self._telemetry_thread.join(timeout=0.4)
        except Exception:
            pass

    def _handle_telemetry(self, obj, addr=None):
        try:
            imu_obj = obj.get("imu") or obj.get("imu_deg")
            if imu_obj and isinstance(imu_obj, dict):
                p = float(imu_obj.get("pitch", 0.0))
                r = float(imu_obj.get("roll", 0.0))
                y = float(imu_obj.get("yaw", 0.0))
                self._telemetry_cache["imu"] = (p, r, y)
        except Exception:
            pass

        try:
            servos = obj.get("servos") or obj.get("servo")
            if isinstance(servos, dict):
                now = time.time()
                cache = self._telemetry_cache.get("servos", {})
                for sid_str, item in servos.items():
                    try:
                        sid = int(sid_str)
                    except Exception:
                        continue
                    if not isinstance(item, dict):
                        continue
                    pos = item.get("pos") if item.get("pos") is not None else item.get("position")
                    temp = item.get("temp") or item.get("temperature")
                    volt = item.get("volt") or item.get("voltage")
                    torque_flag = item.get("torque") or item.get("torque_enable")
                    cache[sid] = {
                        "pos": pos,
                        "temp": temp,
                        "volt": volt,
                        "torque": torque_flag,
                        "ts": now,
                    }
                    info = self.servo_info_dict.get(sid)
                    if info is not None:
                        try:
                            info.is_online = True
                        except Exception:
                            pass
                self._telemetry_cache["servos"] = cache
        except Exception:
            pass

    def get_latest_imu(self):
        """返回最近一次 telemetry 中的 (pitch, roll, yaw) 元组。"""
        try:
            return tuple(self._telemetry_cache.get("imu", (0.0, 0.0, 0.0)))
        except Exception:
            return (0.0, 0.0, 0.0)

    def ping(self, sid):
        """网络模式下无法逐 ID 探测，若已连接则认为在线。"""
        return not self.is_mock

    def read_data_by_name(self, sid, name):
        """从 telemetry 缓存读取数据，兼容调试面板的字段名。"""
        try:
            sid = int(sid)
            name = str(name or "").upper()
            cache = self._telemetry_cache.get("servos", {})
            data = cache.get(sid, {})
            if name == "CURRENT_POSITION":
                return data.get("pos")
            if name == "CURRENT_TEMPERATURE":
                return data.get("temp")
            if name == "CURRENT_VOLTAGE":
                return data.get("volt")
            if name == "TORQUE_ENABLE":
                return data.get("torque")
        except Exception:
            pass
        return None
