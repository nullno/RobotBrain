"""
IMU Reader

功能：
- 优先尝试在 Android 环境使用本机传感器（如 plyer/android）读取陀螺仪/姿态
- 如果不可用，作为后备可通过 UDP 接收来自手机的 JSON 姿态数据，例如：
  {"pitch": 1.2, "roll": -0.5, "yaw": 12.3}
- 在桌面环境还会提供模拟模式（始终返回 0,0,0 或周期性测试信号）

使用：
    imu = IMUReader(udp_port=5005)
    imu.start()
    pitch, roll, yaw = imu.get_orientation()
    imu.stop()

说明：手机端可用任意小程序把传感器姿态通过 UDP 发到运行此程序的主机。
"""

import threading
import time
import json
import socket
import math
import sys

try:
    from kivy.utils import platform as _kivy_platform
except Exception:
    _kivy_platform = sys.platform

class IMUReader:
    def __init__(self, udp_port=5005, simulate=False):
        self.udp_port = udp_port
        self.simulate = simulate

        self._running = False
        self._lock = threading.Lock()
        self._pitch = 0.0
        self._roll = 0.0
        self._yaw = 0.0

        self._thread = None
        self._sock = None

    def start(self):
        # Try platform-specific sensor first (best-effort)
        self._running = True

        # If simulate explicitly requested, don't start network
        if self.simulate:
            self._thread = threading.Thread(target=self._sim_loop, daemon=True)
            self._thread.start()
            return

        # Try plyer/Android sensors (best-effort, may not exist)
        started = False
        try:
            if _kivy_platform == 'android':
                try:
                    # 延迟加载以避免在桌面平台触发 plyer 平台子模块导入错误
                    import importlib
                    gyroscope = importlib.import_module('plyer.gyroscope')
                    try:
                        gyroscope.enable()
                        self._gyroscope = gyroscope
                        self._thread = threading.Thread(target=self._plyer_loop, daemon=True)
                        self._thread.start()
                        started = True
                    except Exception:
                        started = False
                except ModuleNotFoundError:
                    # 在非 Android 环境或缺少实现时安静回退
                    started = False
                except Exception:
                    started = False
            else:
                started = False
        except Exception:
            started = False

        if started:
            return

        # 否则启用 UDP 接收器（手机可以将姿态通过 UDP 发到此端口）
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("", self.udp_port))
            self._thread = threading.Thread(target=self._udp_loop, daemon=True)
            self._thread.start()
            started = True
        except Exception:
            # 最终回退到模拟器
            self._thread = threading.Thread(target=self._sim_loop, daemon=True)
            self._thread.start()
            started = True

    def stop(self):
        self._running = False
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=0.5)

    def get_orientation(self):
        with self._lock:
            return (float(self._pitch), float(self._roll), float(self._yaw))

    # -------------------- loops --------------------
    def _udp_loop(self):
        # 接收 JSON 文本或简单 CSV
        while self._running:
            try:
                data, addr = self._sock.recvfrom(2048)
                if not data:
                    continue
                s = data.decode(errors='ignore').strip()
                try:
                    obj = json.loads(s)
                    pitch = float(obj.get('pitch', 0.0))
                    roll = float(obj.get('roll', 0.0))
                    yaw = float(obj.get('yaw', 0.0))
                except Exception:
                    # 解析失败时尝试 CSV: pitch,roll,yaw
                    try:
                        parts = s.replace('\n','').split(',')
                        pitch = float(parts[0]) if len(parts) > 0 else 0.0
                        roll = float(parts[1]) if len(parts) > 1 else 0.0
                        yaw = float(parts[2]) if len(parts) > 2 else 0.0
                    except Exception:
                        continue

                with self._lock:
                    self._pitch = pitch
                    self._roll = roll
                    self._yaw = yaw
            except Exception:
                time.sleep(0.02)

    def _sim_loop(self):
        t0 = time.time()
        while self._running:
            t = time.time() - t0
            # 产生小幅摆动便于在没有真机时观察算法反应
            pitch = math.sin(t * 0.8) * 4.0
            roll = math.sin(t * 0.6) * 3.0
            yaw = (t * 10.0) % 360.0
            with self._lock:
                self._pitch = pitch
                self._roll = roll
                self._yaw = yaw
            time.sleep(0.02)

    def _plyer_loop(self):
        # plyer.gyroscope 返回 (x,y,z) 角速度，某些设备可能有 orientation 接口
        # 这里做最小封装：尝试读取 gyroscope 值并数值积分 (仅作示例，不是精确姿态融合)
        last = None
        while self._running:
            try:
                vals = self._gyroscope.rotation
                # plyer 的接口不统一，尝试不同属性
                if vals is None:
                    try:
                        vals = self._gyroscope.orientation
                    except Exception:
                        vals = None
                if vals:
                    # 假设 vals 为 (x,y,z) 角度或角速度
                    with self._lock:
                        self._pitch = vals[0]
                        self._roll = vals[1]
                        self._yaw = vals[2] if len(vals) > 2 else self._yaw
            except Exception:
                pass
            time.sleep(0.02)


if __name__ == '__main__':
    # 简单本地调试：运行此模块并用 netcat 或手机 UDP 发数据
    imu = IMUReader(udp_port=5005)
    imu.start()
    try:
        while True:
            print(imu.get_orientation())
            time.sleep(0.2)
    except KeyboardInterrupt:
        imu.stop()
