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


class ServoBus:
    def __init__(self, port=None, baudrate=115200):
        """port: 可为 ESP32 主机地址字符串（如 '192.168.4.1'），否则尝试读取环境变量 ESP32_HOST。"""
        self.is_mock = True
        self._host = None
        self._port = 5005
        self.manager = self  # 兼容旧代码习惯使用 servo_bus.manager

        try:
            host = None
            if isinstance(port, str) and ('.' in port or ':' in port):
                host = port
            if not host:
                host = os.environ.get('ESP32_HOST')
            if not host:
                # 无可用主机，进入 mock 模式
                self.is_mock = True
                return

            self._host = str(host)
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.is_mock = False
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
