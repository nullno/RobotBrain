"""PC ↔ 手机双向语音通信服务。

架构（参考 camera_stream.py 的 P2P 模式）：
  PC 按下语音按钮 → 双端同时开始录音 + 播放对方音频
  PC 再按一次 → 双端停止录音

网络协议：
  - 双端各启动 TCP 发送服务（端口 VOICE_PORT）向对方推送音频
  - 双端各连接对方 TCP 端口接收音频
  - 音频格式：16-bit PCM, 16000 Hz, mono
  - TCP 流格式：每个音频块前 4 字节大端 uint32 表示块长度

平台适配：
  - PC (Windows/macOS/Linux)：使用 PyAudio（PortAudio）
  - Android：使用 pyjnius 调用原生 AudioRecord / AudioTrack

ESP32 设备池 → 发现对端 IP → 自动建立双向语音通道
"""
from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from collections import deque
from typing import Optional, Dict

from services.wifi_servo import get_controller
from widgets.runtime_status import RuntimeStatusLogger
from kivy.utils import platform

logger = logging.getLogger(__name__)

VOICE_PORT = 5020           # 音频 TCP 端口
SAMPLE_RATE = 16000         # 采样率
CHANNELS = 1                # 单声道
SAMPLE_WIDTH = 2            # 16-bit
CHUNK_FRAMES = 1024         # 每次采集帧数
SCAN_INTERVAL = 3.0         # 设备扫描间隔
RECONNECT_DELAY = 2.0       # 重连延迟
CONNECT_TIMEOUT = 3.0       # TCP 连接超时
# Android AudioRecord 每次读取的字节数 = CHUNK_FRAMES * CHANNELS * SAMPLE_WIDTH
ANDROID_CHUNK_BYTES = CHUNK_FRAMES * CHANNELS * SAMPLE_WIDTH


# ──────────────── 平台音频后端抽象 ────────────────

class _AudioBackend:
    """音频后端基类（录音 + 播放）。"""

    def open_mic(self):
        raise NotImplementedError

    def read_mic(self, num_frames: int) -> Optional[bytes]:
        raise NotImplementedError

    def close_mic(self):
        pass

    def open_speaker(self):
        raise NotImplementedError

    def write_speaker(self, data: bytes):
        raise NotImplementedError

    def close_speaker(self):
        pass

    def terminate(self):
        pass


class _PyAudioBackend(_AudioBackend):
    """PC 端 PyAudio 后端。"""

    def __init__(self):
        self._pa = None
        self._mic = None
        self._spk = None
        self._lock = threading.Lock()

    def _ensure_pa(self):
        if self._pa is not None:
            return
        with self._lock:
            if self._pa is not None:
                return
            import pyaudio
            self._pa = pyaudio.PyAudio()

    def open_mic(self):
        self._ensure_pa()
        import pyaudio
        with self._lock:
            self._mic = self._pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=CHUNK_FRAMES,
            )

    def read_mic(self, num_frames: int) -> Optional[bytes]:
        if not self._mic:
            return None
        with self._lock:
            return self._mic.read(num_frames, exception_on_overflow=False)

    def close_mic(self):
        if self._mic:
            try:
                with self._lock:
                    self._mic.stop_stream()
                    self._mic.close()
            except Exception:
                pass
            self._mic = None

    def open_speaker(self):
        self._ensure_pa()
        import pyaudio
        with self._lock:
            self._spk = self._pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                output=True,
                frames_per_buffer=CHUNK_FRAMES,
            )

    def write_speaker(self, data: bytes):
        if not self._spk:
            return
        with self._lock:
            self._spk.write(data)

    def close_speaker(self):
        if self._spk:
            try:
                with self._lock:
                    self._spk.stop_stream()
                    self._spk.close()
            except Exception:
                pass
            self._spk = None

    def terminate(self):
        self.close_mic()
        self.close_speaker()
        if self._pa:
            try:
                with self._lock:
                    self._pa.terminate()
            except Exception:
                pass
            self._pa = None


class _AndroidAudioBackend(_AudioBackend):
    """Android 端使用 pyjnius 调用原生 AudioRecord / AudioTrack。"""

    def __init__(self):
        self._recorder = None
        self._player = None
        self._min_rec_buf = 0
        self._min_play_buf = 0

    def open_mic(self):
        from jnius import autoclass
        AudioRecord = autoclass('android.media.AudioRecord')
        MediaRecorder_AudioSource = autoclass('android.media.MediaRecorder$AudioSource')
        AudioFormat = autoclass('android.media.AudioFormat')

        channel_in = AudioFormat.CHANNEL_IN_MONO
        encoding = AudioFormat.ENCODING_PCM_16BIT

        self._min_rec_buf = AudioRecord.getMinBufferSize(SAMPLE_RATE, channel_in, encoding)
        buf_size = max(self._min_rec_buf, ANDROID_CHUNK_BYTES * 2)

        self._recorder = AudioRecord(
            MediaRecorder_AudioSource.MIC,
            SAMPLE_RATE,
            channel_in,
            encoding,
            buf_size,
        )
        self._recorder.startRecording()

    def read_mic(self, num_frames: int) -> Optional[bytes]:
        if not self._recorder:
            return None
        byte_count = num_frames * CHANNELS * SAMPLE_WIDTH
        buf = bytearray(byte_count)
        read = self._recorder.read(buf, 0, byte_count)
        if read > 0:
            return bytes(buf[:read])
        return None

    def close_mic(self):
        if self._recorder:
            try:
                self._recorder.stop()
                self._recorder.release()
            except Exception:
                pass
            self._recorder = None

    def open_speaker(self):
        from jnius import autoclass
        AudioTrack = autoclass('android.media.AudioTrack')
        AudioManager = autoclass('android.media.AudioManager')
        AudioFormat = autoclass('android.media.AudioFormat')
        AudioAttributes = autoclass('android.media.AudioAttributes')
        AudioAttributes_Builder = autoclass('android.media.AudioAttributes$Builder')

        channel_out = AudioFormat.CHANNEL_OUT_MONO
        encoding = AudioFormat.ENCODING_PCM_16BIT

        self._min_play_buf = AudioTrack.getMinBufferSize(SAMPLE_RATE, channel_out, encoding)
        buf_size = max(self._min_play_buf, ANDROID_CHUNK_BYTES * 2)

        # 构建 AudioAttributes
        attr_builder = AudioAttributes_Builder()
        attr_builder.setUsage(AudioAttributes.USAGE_MEDIA)
        attr_builder.setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        audio_attr = attr_builder.build()

        # 构建 AudioFormat
        fmt_builder = autoclass('android.media.AudioFormat$Builder')()
        fmt_builder.setEncoding(encoding)
        fmt_builder.setSampleRate(SAMPLE_RATE)
        fmt_builder.setChannelMask(channel_out)
        audio_fmt = fmt_builder.build()

        self._player = AudioTrack(
            audio_attr,
            audio_fmt,
            buf_size,
            AudioTrack.MODE_STREAM,
            AudioManager.AUDIO_SESSION_ID_GENERATE,
        )
        self._player.play()

    def write_speaker(self, data: bytes):
        if not self._player:
            return
        self._player.write(data, 0, len(data))

    def close_speaker(self):
        if self._player:
            try:
                self._player.stop()
                self._player.release()
            except Exception:
                pass
            self._player = None

    def terminate(self):
        self.close_mic()
        self.close_speaker()


def _create_audio_backend() -> _AudioBackend:
    """根据当前平台创建音频后端。"""
    if platform == "android":
        return _AndroidAudioBackend()
    else:
        return _PyAudioBackend()


# ──────────────── 主服务类 ────────────────

class VoiceChatService:
    """双向语音通信服务（PC 和 Android 共用）。

    PC 端：
      - 麦克风采集 → TCP 推送给手机
      - TCP 服务端接收手机音频 → 扬声器播放

    手机端：
      - 麦克风采集 → TCP 推送给 PC
      - TCP 接收 PC 音频 → 扬声器播放
    """

    def __init__(self):
        self._running = False
        self._stop_event = threading.Event()

        # 平台音频后端
        self._audio: Optional[_AudioBackend] = None

        # 录音
        self._capture_thread: Optional[threading.Thread] = None

        # 播放
        self._playback_thread: Optional[threading.Thread] = None
        self._play_buffer: deque = deque(maxlen=200)
        self._play_lock = threading.Lock()

        # TCP 发送（本端录音推送给远端）
        self._send_server_sock: Optional[socket.socket] = None
        self._send_thread: Optional[threading.Thread] = None
        self._send_client: Optional[socket.socket] = None
        self._send_lock = threading.Lock()

        # TCP 接收（远端音频推送过来）
        self._recv_thread: Optional[threading.Thread] = None

        # 设备扫描
        self._scan_thread: Optional[threading.Thread] = None
        self._target_ip: Optional[str] = None

        # 状态变更回调
        self._on_state_change = None

    @property
    def is_active(self) -> bool:
        return self._running

    # ──────────────── 启动 / 停止 ────────────────

    def start(self, on_state_change=None):
        """启动语音通信服务。"""
        if self._running:
            return

        self._on_state_change = on_state_change
        self._stop_event.clear()
        self._running = True

        # PC 端检查是否已发现并连接远端手机（提示用户）
        if platform != "android":
            try:
                ctrl = get_controller()
                devices = ctrl.device_list(timeout=0.6) if (ctrl and ctrl.is_connected) else []
                my_id = getattr(ctrl, "_device_id", None)
                has_phone = any(
                    str(dev.get("ip")) and not dev.get("is_self") and dev.get("id") != my_id
                    for dev in devices
                )
                if not has_phone:
                    def _show_tip(dt):
                        try:
                            from widgets.universal_tip import UniversalTip
                            UniversalTip(
                                title="设备连接提示",
                                message="未发现手机端，请确保手机配套App已打开并连接",
                                icon="⚠️",
                                auto_close_seconds=4
                            ).open()
                        except Exception:
                            pass
                    from kivy.clock import Clock
                    Clock.schedule_once(_show_tip, 0)
            except Exception as e:
                logger.debug("检查设备列表失败: %s", e)

        # 创建平台音频后端
        try:
            self._audio = _create_audio_backend()
        except Exception as e:
            RuntimeStatusLogger.log_error(f"音频后端创建失败: {e}")
            self._running = False
            self._fire_state_change(False)
            return

        try:
            self._start_send_server()
        except Exception as e:
            logger.error("语音发送服务启动失败: %s", e)
            RuntimeStatusLogger.log_error(f"语音发送服务启动失败: {e}")

        try:
            self._capture_thread = threading.Thread(
                target=self._capture_loop, daemon=True, name="voice-capture"
            )
            self._capture_thread.start()
        except Exception as e:
            logger.error("麦克风线程启动失败: %s", e)

        try:
            self._playback_thread = threading.Thread(
                target=self._playback_loop, daemon=True, name="voice-playback"
            )
            self._playback_thread.start()
        except Exception as e:
            logger.error("播放线程启动失败: %s", e)

        try:
            self._scan_thread = threading.Thread(
                target=self._scan_loop, daemon=True, name="voice-scan"
            )
            self._scan_thread.start()
        except Exception as e:
            logger.error("设备扫描线程启动失败: %s", e)

        RuntimeStatusLogger.log_info("语音通话已开启")
        self._fire_state_change(True)

    def stop(self):
        """停止语音通信并释放所有资源。"""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()

        # 关闭 TCP
        self._close_send_server()

        # 关闭音频后端
        if self._audio:
            try:
                self._audio.terminate()
            except Exception:
                pass
            self._audio = None

        # 等待线程结束
        for t in (self._capture_thread, self._playback_thread,
                  self._recv_thread, self._scan_thread, self._send_thread):
            if t and t.is_alive():
                t.join(timeout=2.0)

        self._capture_thread = None
        self._playback_thread = None
        self._recv_thread = None
        self._scan_thread = None
        self._send_thread = None
        self._target_ip = None

        RuntimeStatusLogger.log_info("语音通话已关闭")
        self._fire_state_change(False)

    def _fire_state_change(self, active: bool):
        if self._on_state_change:
            try:
                from kivy.clock import Clock
                Clock.schedule_once(lambda dt: self._on_state_change(active), 0)
            except Exception:
                pass

    # ──────────────── 麦克风采集 ────────────────

    def _capture_loop(self):
        """后台线程：持续采集麦克风音频并推送给远端。"""
        try:
            self._audio.open_mic()
        except Exception as e:
            RuntimeStatusLogger.log_error(f"麦克风打开失败: {e}")
            return

        while not self._stop_event.is_set():
            try:
                data = self._audio.read_mic(CHUNK_FRAMES)
                if data:
                    self._send_audio_chunk(data)
            except Exception:
                if self._stop_event.is_set():
                    break
                time.sleep(0.05)

    # ──────────────── 音频播放 ────────────────

    def _playback_loop(self):
        """后台线程：持续从缓冲区读取远端音频并播放。"""
        try:
            self._audio.open_speaker()
        except Exception as e:
            RuntimeStatusLogger.log_error(f"扬声器打开失败: {e}")
            return

        while not self._stop_event.is_set():
            data = None
            with self._play_lock:
                if self._play_buffer:
                    data = self._play_buffer.popleft()
            if data:
                try:
                    self._audio.write_speaker(data)
                except Exception:
                    if self._stop_event.is_set():
                        break
            else:
                time.sleep(0.02)

    # ──────────────── TCP 音频发送（服务端） ────────────────

    def _start_send_server(self):
        """启动 TCP 服务端，远端连接后接收本端录音。"""
        try:
            self._send_server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._send_server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._send_server_sock.settimeout(1.0)
            self._send_server_sock.bind(("0.0.0.0", VOICE_PORT))
            self._send_server_sock.listen(1)
            self._send_thread = threading.Thread(
                target=self._send_server_loop, daemon=True, name="voice-send-server"
            )
            self._send_thread.start()
        except Exception as e:
            RuntimeStatusLogger.log_error(f"语音发送服务启动失败: {e}")

    def _send_server_loop(self):
        """等待远端连接，每次只接受一个客户端。"""
        while not self._stop_event.is_set():
            try:
                client, addr = self._send_server_sock.accept()
                logger.info("语音发送: 远端已连接 %s", addr)
                with self._send_lock:
                    if self._send_client:
                        try:
                            self._send_client.close()
                        except Exception:
                            pass
                    self._send_client = client
            except socket.timeout:
                continue
            except Exception:
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)

    def _send_audio_chunk(self, data: bytes):
        """将一个音频块通过 TCP 发送给远端。"""
        with self._send_lock:
            client = self._send_client
        if not client:
            return
        try:
            header = struct.pack(">I", len(data))
            client.sendall(header + data)
        except Exception:
            with self._send_lock:
                try:
                    self._send_client.close()
                except Exception:
                    pass
                self._send_client = None

    def _close_send_server(self):
        with self._send_lock:
            if self._send_client:
                try:
                    self._send_client.close()
                except Exception:
                    pass
                self._send_client = None
        if self._send_server_sock:
            try:
                self._send_server_sock.close()
            except Exception:
                pass
            self._send_server_sock = None

    # ──────────────── TCP 音频接收（客户端） ────────────────

    def _recv_loop(self, ip: str, port: int):
        """后台线程：连接远端音频推送端口，接收音频块并放入播放缓冲。"""
        while not self._stop_event.is_set():
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(CONNECT_TIMEOUT)
                sock.connect((ip, port))
                sock.settimeout(5.0)
                RuntimeStatusLogger.log_info(f"语音接收: 已连接 {ip}:{port}")

                buf = b""
                while not self._stop_event.is_set():
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    # 解析 [4字节长度][音频数据] 格式
                    while len(buf) >= 4:
                        pkt_len = struct.unpack(">I", buf[:4])[0]
                        if pkt_len > 1000000:
                            buf = b""
                            break
                        if len(buf) < 4 + pkt_len:
                            break
                        audio_data = buf[4:4 + pkt_len]
                        buf = buf[4 + pkt_len:]
                        with self._play_lock:
                            self._play_buffer.append(audio_data)

            except Exception as e:
                logger.debug("语音接收断开: %s", e)
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass

            if not self._stop_event.is_set():
                self._stop_event.wait(RECONNECT_DELAY)

    # ──────────────── 设备扫描 ────────────────

    def _scan_loop(self):
        """后台线程：通过 ESP32 设备池发现远端设备，建立音频接收连接。"""
        while not self._stop_event.is_set():
            # 心跳注册
            self._heartbeat_register()

            if self._target_ip is None:
                self._try_discover_and_connect()

            self._stop_event.wait(SCAN_INTERVAL)

    def _heartbeat_register(self):
        """向 ESP32 注册本设备（保持在线，声明有语音能力）。"""
        try:
            ctrl = get_controller()
            if ctrl and ctrl.is_connected:
                ctrl.device_register("PC", has_camera=True, stream_port=5010)
        except Exception:
            pass

    def _try_discover_and_connect(self):
        """从设备池发现手机并建立音频接收连接。"""
        try:
            ctrl = get_controller()
            if not ctrl or not ctrl.is_connected:
                return

            devices = ctrl.device_list()
            my_id = getattr(ctrl, "_device_id", None)

            for dev in devices:
                if dev.get("is_self"):
                    continue
                if dev.get("id") == my_id:
                    continue

                ip = dev.get("ip")
                if not ip:
                    continue

                # 尝试连接远端的语音端口
                if self._test_port(ip, VOICE_PORT):
                    RuntimeStatusLogger.log_info(
                        f"发现语音设备: {dev.get('name', ip)} ({ip})"
                    )
                    self._target_ip = ip
                    self._recv_thread = threading.Thread(
                        target=self._recv_loop, args=(ip, VOICE_PORT),
                        daemon=True, name="voice-recv"
                    )
                    self._recv_thread.start()
                    return
        except Exception as e:
            logger.debug("语音设备扫描失败: %s", e)

    @staticmethod
    def _test_port(ip: str, port: int) -> bool:
        """快速测试远端端口是否可达。"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.5)
            s.connect((ip, port))
            s.close()
            return True
        except Exception:
            return False


# ──────────────── 全局单例 ────────────────

_voice_service: Optional[VoiceChatService] = None


def get_voice_service() -> VoiceChatService:
    """获取全局 VoiceChatService 单例。"""
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceChatService()
    return _voice_service
