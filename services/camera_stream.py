"""PC 端远程摄像头视频流服务。

通过 ESP32 设备池发现手机摄像头，自动建立 MJPEG 视频流连接，
实现 PC 端流畅观看手机摄像头画面。

架构:
  手机 → MJPEG HTTP Server (:5010/stream) → PC 读取流 → 解码显示
  ESP32 设备池 → PC 定时扫描 → 发现手机 → 自动连接
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Optional, Dict

from services.wifi_servo import get_controller
from widgets.runtime_status import RuntimeStatusLogger

logger = logging.getLogger(__name__)

STREAM_PORT = 5010
SCAN_INTERVAL = 4.0       # 设备扫描间隔（秒）
RECONNECT_DELAY = 2.0     # 断线重连延迟（秒）
CONNECT_TIMEOUT = 3.0     # TCP 连接超时（秒）
READ_TIMEOUT = 5.0        # 流读取超时（秒）


class CameraStreamService:
    """PC 端远程摄像头 MJPEG 视频流服务。

    功能:
    - 定时扫描 ESP32 设备池，发现有摄像头的手机
    - 自动连接手机的 MJPEG 视频流
    - 解码帧并推送给 CameraView 显示
    - 断线自动重连 + 定时重新扫描
    """

    def __init__(self):
        self._camera_view = None
        self._stop_event = threading.Event()
        self._scan_thread: Optional[threading.Thread] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._stream_stop = threading.Event()
        self._connected_target: Optional[Dict[str, object]] = None
        self._latest_frame: Optional[bytes] = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._display_event = None    # Kivy Clock event

    def start(self, camera_view):
        """启动服务，绑定 CameraView 用于显示。"""
        if self._running:
            return
        self._camera_view = camera_view
        self._stop_event.clear()
        self._running = True
        self._scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._scan_thread.start()
        RuntimeStatusLogger.log_info("远程摄像头服务已启动，等待发现手机...")

    def stop(self):
        """停止服务并清理资源。"""
        self._running = False
        self._stop_event.set()
        self._disconnect_stream()

    @property
    def is_connected(self) -> bool:
        return (self._connected_target is not None
                and self._stream_thread is not None
                and self._stream_thread.is_alive())

    @property
    def connected_device_name(self) -> Optional[str]:
        if self._connected_target:
            return self._connected_target.get("name")
        return None

    # ──────────────── 设备扫描 ────────────────

    def _scan_loop(self):
        """后台线程：定时扫描 ESP32 设备池。"""
        while not self._stop_event.is_set():
            if not self.is_connected:
                self._try_discover_and_connect()
            self._stop_event.wait(SCAN_INTERVAL)

    def _try_discover_and_connect(self):
        """尝试从设备池发现手机摄像头并连接。"""
        try:
            ctrl = get_controller()
            if not ctrl or not ctrl.is_connected:
                return

            # 先确保 PC 已注册到设备池
            if not getattr(ctrl, "_device_id", None):
                try:
                    ctrl.device_register("PC", has_camera=True, stream_port=STREAM_PORT)
                except Exception:
                    pass

            devices = ctrl.device_list()
            my_id = getattr(ctrl, "_device_id", None)

            for dev in devices:
                if dev.get("id") == my_id:
                    continue
                if not dev.get("has_camera"):
                    continue

                ip = dev.get("ip")
                port = dev.get("stream_port", STREAM_PORT)
                name = dev.get("name", ip)

                if not ip:
                    continue

                # 快速连通测试
                if self._test_stream_endpoint(ip, port):
                    RuntimeStatusLogger.log_info(
                        f"发现手机摄像头: {name} ({ip}:{port})，正在连接..."
                    )
                    self._connect_stream(ip, port, name)
                    return
        except Exception as e:
            logger.debug("扫描设备池失败: %s", e)

    @staticmethod
    def _test_stream_endpoint(ip: str, port: int) -> bool:
        """快速测试目标 MJPEG 端口是否可达。"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((ip, port))
            s.close()
            return True
        except Exception:
            return False

    # ──────────────── MJPEG 流连接 ────────────────

    def _connect_stream(self, ip: str, port: int, name: str):
        """建立 MJPEG 视频流连接。"""
        self._disconnect_stream()

        self._stream_stop.clear()
        self._connected_target = {"ip": ip, "port": port, "name": name}

        self._stream_thread = threading.Thread(
            target=self._mjpeg_stream_loop, args=(ip, port), daemon=True
        )
        self._stream_thread.start()

        # 在主线程启动定时帧刷新
        from kivy.clock import Clock
        if self._camera_view:
            self._camera_view._remote_stream_active = True
            self._display_event = Clock.schedule_interval(self._push_frame_to_view, 1 / 30)

    def _disconnect_stream(self):
        """断开当前流连接。"""
        self._stream_stop.set()
        self._connected_target = None

        if self._display_event:
            try:
                self._display_event.cancel()
            except Exception:
                pass
            self._display_event = None

        if self._camera_view:
            self._camera_view._remote_stream_active = False

    def _mjpeg_stream_loop(self, ip: str, port: int):
        """后台线程：持续读取 MJPEG multipart 流。"""
        while not self._stream_stop.is_set():
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(CONNECT_TIMEOUT)
                sock.connect((ip, port))

                # 发送 HTTP 请求
                request = (
                    f"GET /stream HTTP/1.1\r\n"
                    f"Host: {ip}:{port}\r\n"
                    f"Connection: close\r\n"
                    f"\r\n"
                )
                sock.sendall(request.encode())

                # 读取响应头
                sock.settimeout(READ_TIMEOUT)
                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = sock.recv(4096)
                    if not chunk:
                        raise ConnectionError("连接关闭")
                    buf += chunk
                    if len(buf) > 16384:
                        raise ConnectionError("响应头过大")

                header_end = buf.index(b"\r\n\r\n") + 4
                remaining = buf[header_end:]

                RuntimeStatusLogger.log_info(
                    f"MJPEG 流已连接: {ip}:{port}"
                )

                # 持续解析 MJPEG 帧
                self._read_mjpeg_frames(sock, remaining)

            except Exception as e:
                logger.debug("MJPEG 流断开: %s", e)
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass

            # 断线后等待重连
            if not self._stream_stop.is_set():
                RuntimeStatusLogger.log_info("远程摄像头断开，等待重连...")
                self._connected_target = None
                if self._camera_view:
                    self._camera_view._remote_stream_active = False
                self._stream_stop.wait(RECONNECT_DELAY)

        # 线程退出时清理
        self._connected_target = None
        if self._camera_view:
            self._camera_view._remote_stream_active = False

    def _read_mjpeg_frames(self, sock: socket.socket, initial_buf: bytes):
        """从 socket 解析 MJPEG multipart 帧。

        协议格式:
          --frame\\r\\n
          Content-Type: image/jpeg\\r\\n
          Content-Length: NNN\\r\\n
          \\r\\n
          <JPEG bytes>\\r\\n
        """
        buf = initial_buf
        boundary = b"--frame"

        while not self._stream_stop.is_set():
            # 读取更多数据
            try:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
            except socket.timeout:
                continue
            except Exception:
                break

            # 解析所有完整帧
            while True:
                idx = buf.find(boundary)
                if idx < 0:
                    # 防止 buffer 无限增长
                    if len(buf) > 500000:
                        buf = buf[-200000:]
                    break

                next_idx = buf.find(boundary, idx + len(boundary))
                if next_idx < 0:
                    break

                # 提取本帧数据
                frame_section = buf[idx + len(boundary):next_idx]
                buf = buf[next_idx:]

                # 找到 header 和 body 的分隔
                header_end = frame_section.find(b"\r\n\r\n")
                if header_end < 0:
                    continue

                jpeg_data = frame_section[header_end + 4:].rstrip(b"\r\n")

                # 验证 JPEG 魔数
                if jpeg_data and len(jpeg_data) > 2 and jpeg_data[:2] == b"\xff\xd8":
                    with self._frame_lock:
                        self._latest_frame = jpeg_data

    def _push_frame_to_view(self, dt):
        """主线程回调：将最新帧推送给 CameraView 显示。"""
        with self._frame_lock:
            jpeg_data = self._latest_frame
            self._latest_frame = None

        if jpeg_data and self._camera_view:
            self._camera_view._display_remote_jpeg(jpeg_data)


# ──────────────── 全局单例 ────────────────

_service: Optional[CameraStreamService] = None


def get_camera_stream_service() -> CameraStreamService:
    """获取全局 CameraStreamService 单例。"""
    global _service
    if _service is None:
        _service = CameraStreamService()
    return _service
