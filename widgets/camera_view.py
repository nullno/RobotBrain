from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.utils import platform
from kivy.app import App
from kivy.graphics import PushMatrix, PopMatrix, Rotate, Scale
from widgets.runtime_status import RuntimeStatusLogger
import os
import base64
import threading
import socket
import time


# P2P视频流服务端口
STREAM_SERVER_PORT = 5010


class CameraView(Image):
    DEFAULT_ANDROID_FIX_MODE = "rotate180"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fit_mode = "contain"
        
        # 核心修复：Image为空texture时会默认渲染一个白色方块
        # 通过修改颜色滤镜为黑色，可防止无摄像头画面时显示白屏
        self.color = (0, 0, 0, 1)
        self.bind(texture=self._on_texture_change)

        # 确保无摄像头时背景为黑色（不依赖 kv 规则加载顺序）
        from kivy.graphics import Color, Rectangle as _Rect
        with self.canvas.before:
            Color(0, 0, 0, 1)
            self._bg_rect = _Rect(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_bg, size=self._sync_bg)

        self.capture = None
        # 可注册回调以获取原始 OpenCV 帧：callback(frame: numpy.ndarray)
        self.frame_callback = None
        self._event = None
        self._camera_index = None  # 记录使用的摄像头索引
        self._camera_init_phase = True  # 权限等待阶段标志
        self._desktop_frame_logged = False
        self._android_last_texture_id = None
        self._android_texture_ready_logged = False
        self._android_front_indices = set()
        self._android_camera_started = False
        self._display_rotate = None
        self._display_scale = None
        self._android_fix_mode = self.DEFAULT_ANDROID_FIX_MODE
        self._last_display_mode = None

        # P2P远程摄像头：ESP32只负责设备发现，视频流直连
        self._camera_source = "local"  # "local" 或 {"ip": str, "port": int, "name": str}
        self._remote_event = None
        self._remote_target = None  # {"ip": str, "port": int}
        self._stream_server = None
        self._stream_server_thread = None
        self._latest_jpeg_frame = None
        self._frame_lock = threading.Lock()
        self._registered_device_id = None
        self._stream_sharing_enabled = False
        self._remote_fetch_thread = None
        self._remote_fetch_stop = threading.Event()
        self._remote_latest_frame = None  # 后台线程写入，主线程读取
        self._remote_frame_lock = threading.Lock()
        self._auto_discover_event = None
        self._remote_stream_active = False   # 远程流服务正在推送画面时为 True
        self._camera_stream_service = None   # PC 端远程摄像头服务引用
        self._android_share_clock = None     # Android 独立帧捕获定时器
        self._esp32_heartbeat_clock = None   # ESP32 心跳注册定时器

        try:
            self._load_saved_android_fix_mode()
        except Exception:
            pass

        try:
            self._setup_display_transform()
            self.bind(pos=lambda *_: self._update_display_transform_origin())
            self.bind(size=lambda *_: self._update_display_transform_origin())
            self._update_display_transform_origin()
            self._apply_android_display_transform()
        except Exception:
            pass
        
        if platform in ("win", "linux", "macosx"):
            self._start_desktop()
        else:
            self._start_android()

    def _sync_bg(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _on_texture_change(self, instance, value):
        # 一旦有真正的画面纹理，就把颜色滤镜改回正常（白色滤镜即原色）
        # 如果纹理消失，重新变回黑色
        if value:
            self.color = (1, 1, 1, 1)
        else:
            self.color = (0, 0, 0, 1)

    def _get_android_camera_candidates(self):
        """返回 Android 摄像头候选索引：优先前置，再补充常见索引。"""
        candidates = []
        try:
            from jnius import autoclass

            CameraJava = autoclass("android.hardware.Camera")
            CameraInfo = autoclass("android.hardware.Camera$CameraInfo")
            count = int(CameraJava.getNumberOfCameras())
            for idx in range(count):
                try:
                    info = CameraInfo()
                    CameraJava.getCameraInfo(idx, info)
                    facing = int(getattr(info, "facing", -1))
                    if facing == int(CameraInfo.CAMERA_FACING_FRONT):
                        self._android_front_indices.add(int(idx))
                        if idx not in candidates:
                            candidates.append(int(idx))
                except Exception:
                    pass
            for idx in range(count):
                if idx not in candidates:
                    candidates.append(int(idx))
        except Exception:
            pass

        for idx in [1, 0, 2, -1]:
            if idx not in candidates:
                candidates.append(idx)
        return candidates

    def _apply_android_texture_transform(self, texture, camera_idx):
        """对 Android 摄像头纹理应用稳定的 uv 变换。"""
        try:
            mode = self.get_android_front_fix_mode()
            is_front = int(camera_idx) in self._android_front_indices if camera_idx != -1 else False

            # Android 相机纹理普遍存在 Y 轴反向，默认先做垂直翻转
            uvpos = (0.0, 1.0)
            uvsize = (1.0, -1.0)

            # 用户在视觉设置中选择的模式应始终生效（不依赖前置识别结果）
            if mode in ("rotate180", "180", "default"):
                uvpos = (1.0, 1.0)
                uvsize = (-1.0, -1.0)
            elif mode in ("vflip", "vertical"):
                uvpos = (0.0, 1.0)
                uvsize = (1.0, -1.0)
            elif mode in ("hflip", "horizontal"):
                uvpos = (1.0, 0.0)
                uvsize = (-1.0, 1.0)
            elif mode in ("none", "off"):
                uvpos = (0.0, 0.0)
                uvsize = (1.0, 1.0)

            texture.uvpos = uvpos
            texture.uvsize = uvsize
            return is_front, mode
        except Exception:
            return False, "unknown"

    def _setup_display_transform(self):
        """显示层变换兜底：解决部分 Android 设备 uv 变换不生效问题。"""
        try:
            if self._display_rotate is not None and self._display_scale is not None:
                return
            with self.canvas.before:
                PushMatrix()
                self._display_rotate = Rotate(angle=0, origin=self.center)
                self._display_scale = Scale(x=1.0, y=1.0, z=1.0, origin=self.center)
            with self.canvas.after:
                PopMatrix()
        except Exception:
            pass

    def _update_display_transform_origin(self):
        try:
            c = self.center
            if self._display_rotate is not None:
                self._display_rotate.origin = c
            if self._display_scale is not None:
                self._display_scale.origin = c
        except Exception:
            pass

    def _apply_android_display_transform(self):
        """根据当前模式应用显示层旋转/翻转，作为纹理 uv 的兜底。"""
        try:
            if platform != "android":
                return
            self._setup_display_transform()
            mode = self.get_android_front_fix_mode()

            angle = 0.0
            sx = 1.0
            sy = 1.0
            if mode in ("rotate180", "180", "default"):
                angle = 180.0
            elif mode in ("vflip", "vertical"):
                sy = -1.0
            elif mode in ("hflip", "horizontal"):
                sx = -1.0
            elif mode in ("none", "off"):
                pass

            if self._display_rotate is not None:
                self._display_rotate.angle = angle
            if self._display_scale is not None:
                self._display_scale.x = sx
                self._display_scale.y = sy
            self._update_display_transform_origin()
            self._last_display_mode = mode
        except Exception:
            pass

    def _apply_mode_to_current_android_texture(self):
        """将当前模式立即应用到当前纹理，避免依赖 texture 事件回调。"""
        try:
            if platform != "android":
                return
            tex = getattr(self, "texture", None)
            if not tex:
                return
            idx = int(getattr(self, "_camera_index", -1) or -1)
            self._apply_android_texture_transform(tex, idx)
        except Exception:
            pass

    def _apply_fix_mode_to_desktop_frame(self, frame):
        """将与 Android 一致的翻转模式应用到桌面 OpenCV 帧。"""
        try:
            mode = self.get_android_front_fix_mode()
            if mode in ("rotate180", "180", "default"):
                return self.cv2.rotate(frame, self.cv2.ROTATE_180)
            if mode in ("vflip", "vertical"):
                return self.cv2.flip(frame, 0)
            if mode in ("hflip", "horizontal"):
                return self.cv2.flip(frame, 1)
            return frame
        except Exception:
            return frame

    def _get_android_fix_mode_file(self):
        try:
            app = App.get_running_app()
            if app and getattr(app, "user_data_dir", None):
                base = str(app.user_data_dir)
            else:
                base = "data"
            return os.path.join(base, "camera_fix_mode.txt")
        except Exception:
            return os.path.join("data", "camera_fix_mode.txt")

    def _normalize_fix_mode(self, mode):
        try:
            m = str(mode or "").strip().lower()
            alias = {
                "180": "rotate180",
                "default": "rotate180",
                "vertical": "vflip",
                "horizontal": "hflip",
                "off": "none",
            }
            m = alias.get(m, m)
            if m not in ("rotate180", "vflip", "hflip", "none"):
                m = self.DEFAULT_ANDROID_FIX_MODE
            return m
        except Exception:
            return self.DEFAULT_ANDROID_FIX_MODE

    def _load_saved_android_fix_mode(self):
        mode = self.DEFAULT_ANDROID_FIX_MODE
        try:
            path = self._get_android_fix_mode_file()
            if os.path.exists(path):
                with open(path, "r", encoding="utf8") as f:
                    mode = f.read().strip() or mode
        except Exception:
            pass
        mode = self._normalize_fix_mode(mode)
        self._android_fix_mode = mode
        os.environ["RB_ANDROID_FRONT_FIX"] = mode
        return mode

    def _save_android_fix_mode(self, mode):
        try:
            path = self._get_android_fix_mode_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf8") as f:
                f.write(str(mode))
        except Exception:
            pass

    # ---------- Desktop (OpenCV) ----------
    def _start_desktop(self):
        try:
            import cv2

            self.cv2 = cv2
            RuntimeStatusLogger.log_info('OpenCV 导入成功，准备打开桌面摄像头')
        except ImportError:
            RuntimeStatusLogger.log_error('OpenCV 未安装，桌面摄像头不可用')
            print("❌ OpenCV not installed")
            return

        self.capture = self.cv2.VideoCapture(0)
        if not self.capture.isOpened():
            RuntimeStatusLogger.log_error('桌面摄像头打开失败')
            print("❌ Camera open failed")
            return

        self._event = Clock.schedule_interval(self._update_desktop, 1 / 30)
        RuntimeStatusLogger.log_info('桌面摄像头已启动，开始读取帧')
        # --mode phone 桌面模拟手机时也自动开启画面共享并注册设备
        if getattr(App.get_running_app(), 'run_mode', 'pc') == 'phone':
            Clock.schedule_once(lambda dt: self._auto_enable_sharing_and_register(), 2.0)
        # PC模式：启动远程摄像头视频流服务（自动扫描设备池、连接手机画面）
        if getattr(App.get_running_app(), 'run_mode', 'pc') == 'pc':
            Clock.schedule_once(lambda dt: self._start_camera_stream_service(), 3.0)

    def _update_desktop(self, dt):
        ret, frame = self.capture.read()
        if not ret:
            return

        # 在调用转换为 Kivy 纹理之前，先把原始帧传给回调（若有）
        try:
            if self.frame_callback is not None:
                self.frame_callback(frame)
            if not self._desktop_frame_logged:
                try:
                    h, w, _ = frame.shape
                    RuntimeStatusLogger.log_info(f'桌面摄像头接收到首帧: {w}x{h}')
                except Exception:
                    RuntimeStatusLogger.log_info('桌面摄像头接收到首帧')
                self._desktop_frame_logged = True
        except Exception:
            pass

        # 为MJPEG共享准备JPEG帧（应用方向修正后再编码，保证PC看到正确方向）
        if self._stream_sharing_enabled:
            try:
                share_frame = self._apply_fix_mode_to_desktop_frame(frame.copy())
                h, w = share_frame.shape[:2]
                if w > 640:
                    scale = 640 / w
                    share_frame = self.cv2.resize(share_frame, (640, int(h * scale)))
                _, buffer = self.cv2.imencode('.jpg', share_frame, [self.cv2.IMWRITE_JPEG_QUALITY, 75])
                with self._frame_lock:
                    self._latest_jpeg_frame = buffer.tobytes()
            except Exception:
                pass

        try:
            frame = self._apply_fix_mode_to_desktop_frame(frame)
        except Exception:
            pass

        # 如果远程流服务正在推送画面，跳过本地纹理更新
        if self._remote_stream_active:
            return

        # OpenCV -> Kivy Texture
        frame = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        h, w, _ = frame.shape
        texture = Texture.create(size=(w, h), colorfmt="rgb")
        texture.blit_buffer(frame.tobytes(), colorfmt="rgb", bufferfmt="ubyte")
        texture.flip_vertical()
        self.texture = texture

    # ---------- Android (Kivy Camera) ----------
    def _start_android(self):
        from kivy.uix.camera import Camera
        from kivy.clock import Clock

        def start_camera():
            try:
                if self._android_camera_started and getattr(self, "camera", None):
                    return
                self.camera = None
                camera_started = False
                candidates = self._get_android_camera_candidates()

                # 尝试多个摄像头索引：优先前置，再回退
                for idx in candidates:
                    try:
                        if idx == -1:
                            self.camera = Camera(play=True, resolution=(640, 480))
                        else:
                            self.camera = Camera(index=idx, play=True, resolution=(640, 480))

                        # 绑定 texture 回调 —— 回调只负责替换 texture，不进行 canvas 操作
                        def _on_text(inst, val, camera_idx=idx):
                            try:
                                if val:
                                    # 直接复用相机纹理，避免每帧复制 get_region 带来的 CPU 开销
                                    tex = val
                                    is_front, mode = self._apply_android_texture_transform(tex, camera_idx)
                                    self.texture = tex
                                    if mode != self._last_display_mode:
                                        self._apply_android_display_transform()
                                    # 为P2P共享准备JPEG帧（Android端默认开启）
                                    if self._stream_sharing_enabled:
                                        self._capture_android_texture_for_sharing(tex)
                                    if not self._android_texture_ready_logged:
                                        RuntimeStatusLogger.log_info(
                                            f'Android 摄像头 texture 就绪 (index={camera_idx}, front={is_front}, mode={mode})'
                                        )
                                        self._android_texture_ready_logged = True
                            except Exception:
                                pass

                        self.camera.bind(texture=_on_text)
                        self._camera_index = idx
                        camera_started = True
                        self._android_camera_started = True
                        RuntimeStatusLogger.log_info(f"摄像头已启动 (index={idx})")
                        print(f"✅ 摄像头已启动 (index={idx})")
                        if getattr(App.get_running_app(), 'run_mode', 'phone') == 'phone':
                            self._auto_enable_sharing_and_register()
                        break
                    except Exception as e:
                        print(f"⚠ 尝试摄像头 index={idx} 失败: {e}")
                        self.camera = None
                        continue

                if not camera_started:
                    RuntimeStatusLogger.log_error("无法启动任何摄像头")
                    print("❌ 无法启动任何摄像头")
            except Exception as e:
                RuntimeStatusLogger.log_error(f"摄像头启动异常: {e}")
                print(f"❌ 摄像头启动异常: {e}")

        # 在 Android 上先检查权限；若未授权则请求授权，授权后再启动摄像头
        try:
            from android.permissions import request_permissions, Permission, check_permission

            try:
                has = check_permission(Permission.CAMERA)
            except Exception:
                # 某些环境没有 check_permission，退回为请求权限流程
                has = False

            if has:
                start_camera()
            else:
                def _cb(permissions, results):
                    if all(results):
                        RuntimeStatusLogger.log_info('摄像头权限已授予，开始启动摄像头')
                        start_camera()
                    else:
                        RuntimeStatusLogger.log_error('摄像头权限未授予，无法显示摄像头画面')
                        print("⚠ 摄像头权限未授予，无法显示摄像头画面")

                # 请求权限并在回调里处理；同时如用户延迟允许，定期检测并重试
                request_permissions([Permission.CAMERA], _cb)

                def _perm_retry(dt):
                    try:
                        if check_permission(Permission.CAMERA):
                            RuntimeStatusLogger.log_info('检测到摄像头权限已被允许，正在启动')
                            start_camera()
                            return False
                    except Exception:
                        pass
                    return True

                Clock.schedule_interval(_perm_retry, 1.0)
        except Exception:
            # 非 android.permissions 环境：直接尝试启动摄像头
            start_camera()

    def set_android_front_fix_mode(self, mode):
        """设置摄像头方向修正模式（Android/桌面统一）。"""
        try:
            m = self._normalize_fix_mode(mode)
            self._android_fix_mode = m
            os.environ["RB_ANDROID_FRONT_FIX"] = m
            self._save_android_fix_mode(m)
            self._apply_mode_to_current_android_texture()
            self._apply_android_display_transform()
            try:
                RuntimeStatusLogger.log_info(f"视觉设置: 前置修正模式 -> {m}")
            except Exception:
                pass
            return m
        except Exception:
            return self.DEFAULT_ANDROID_FIX_MODE

    def get_android_front_fix_mode(self):
        """读取当前视觉修正模式（以实例状态为准）。"""
        try:
            m = self._normalize_fix_mode(getattr(self, "_android_fix_mode", self.DEFAULT_ANDROID_FIX_MODE))
            self._android_fix_mode = m
            return m
        except Exception:
            return self.DEFAULT_ANDROID_FIX_MODE

    def get_effective_tex_coords(self, texture=None):
        """返回与当前视觉模式一致的 tex_coords（供外部绘制链路复用）。"""
        try:
            mode = self.get_android_front_fix_mode()
            if mode in ("rotate180", "180", "default"):
                u0, v0, us, vs = 1.0, 1.0, -1.0, -1.0
            elif mode in ("vflip", "vertical"):
                u0, v0, us, vs = 0.0, 1.0, 1.0, -1.0
            elif mode in ("hflip", "horizontal"):
                u0, v0, us, vs = 1.0, 0.0, -1.0, 1.0
            else:
                u0, v0, us, vs = 0.0, 0.0, 1.0, 1.0
            return [u0, v0, u0 + us, v0, u0 + us, v0 + vs, u0, v0 + vs]
        except Exception:
            return None

    def restart_camera(self):
        """重启相机以重新探测设备与索引。"""
        try:
            if platform in ("win", "linux", "macosx"):
                try:
                    if self.capture:
                        self.capture.release()
                except Exception:
                    pass
                self.capture = None
                if self._event:
                    try:
                        self._event.cancel()
                    except Exception:
                        pass
                self._event = None
                self._desktop_frame_logged = False
                self._start_desktop()
                return True

            try:
                if hasattr(self, "camera") and self.camera:
                    self.camera.play = False
                    self.camera = None
            except Exception:
                pass
            self._android_camera_started = False
            self._android_texture_ready_logged = False
            self._android_front_indices = set()
            self._last_display_mode = None
            self._start_android()
            return True
        except Exception:
            return False

    def on_parent(self, instance, parent):
        """清理资源：当widget从父级移除时"""
        if not parent:
            if self.capture:
                self.capture.release()
                self.capture = None
            if self._event:
                self._event.cancel()
                self._event = None
            self._stop_remote_fetch()
            # 停止流媒体服务器
            self._stop_stream_server()
            self._stop_android_share_clock()
            # 停止心跳注册
            if self._esp32_heartbeat_clock:
                self._esp32_heartbeat_clock.cancel()
                self._esp32_heartbeat_clock = None
            # 停止 PC 端远程摄像头服务
            if self._camera_stream_service:
                try:
                    self._camera_stream_service.stop()
                except Exception:
                    pass
            # Android摄像头清理
            try:
                if hasattr(self, 'camera') and self.camera:
                    self.camera.play = False
                    self.camera = None
                self._android_camera_started = False
            except Exception:
                pass

    # ==================== P2P远程摄像头（设备直连，不经过ESP32）====================

    def get_camera_source(self) -> str:
        """获取当前摄像头源："local" 或远程设备名称。"""
        if self._camera_source == "local":
            return "local"
        if isinstance(self._remote_target, dict):
            return self._remote_target.get("name", "remote")
        return "local"

    def set_camera_source(self, source) -> bool:
        """切换摄像头源。
        
        Args:
            source: "local" 使用本地摄像头，或 {"ip": str, "port": int, "name": str} 远程设备
        Returns:
            是否切换成功
        """
        try:
            if source == "local" or source is None:
                return self._switch_to_local()
            elif isinstance(source, dict) and source.get("ip"):
                return self._switch_to_remote_p2p(source)
            else:
                RuntimeStatusLogger.log_error(f"无效摄像头源: {source}")
                return False
        except Exception as e:
            RuntimeStatusLogger.log_error(f"切换摄像头源失败: {e}")
            return False

    def _switch_to_local(self) -> bool:
        """切换回本地摄像头。"""
        try:
            # 停止远程帧拉取
            self._stop_remote_fetch()
            
            self._camera_source = "local"
            self._remote_target = None
            
            # 重启本地摄像头
            if platform in ("win", "linux", "macosx"):
                if not self.capture or not self.capture.isOpened():
                    self._start_desktop()
                elif not self._event:
                    self._event = Clock.schedule_interval(self._update_desktop, 1 / 30)
            else:
                if not self._android_camera_started:
                    self._start_android()
            
            RuntimeStatusLogger.log_info("已切换到本地摄像头")
            return True
        except Exception as e:
            RuntimeStatusLogger.log_error(f"切换本地摄像头失败: {e}")
            return False

    def _switch_to_remote_p2p(self, target: dict) -> bool:
        """P2P直连切换到远程摄像头。"""
        try:
            ip = target.get("ip")
            port = target.get("stream_port", STREAM_SERVER_PORT)
            name = target.get("name", ip)
            
            if not ip:
                RuntimeStatusLogger.log_error("远程设备IP无效")
                return False
            
            # 暂停本地摄像头采集
            if self._event:
                self._event.cancel()
                self._event = None
            
            # 停止旧的远程帧拉取
            self._stop_remote_fetch()
            
            self._camera_source = "remote"
            self._remote_target = {"ip": ip, "port": port, "name": name}
            
            # 启动后台线程拉取远程帧 + 主线程定时更新纹理
            self._remote_fetch_stop.clear()
            self._remote_fetch_thread = threading.Thread(
                target=self._remote_fetch_loop, args=(ip, port), daemon=True
            )
            self._remote_fetch_thread.start()
            self._remote_event = Clock.schedule_interval(self._apply_remote_frame, 1 / 25)
            
            RuntimeStatusLogger.log_info(f"P2P连接远程摄像头: {name} ({ip}:{port})")
            return True
        except Exception as e:
            RuntimeStatusLogger.log_error(f"P2P连接失败: {e}")
            return False

    def _stop_remote_fetch(self):
        """停止后台远程帧拉取线程。"""
        self._remote_fetch_stop.set()
        if self._remote_event:
            self._remote_event.cancel()
            self._remote_event = None
        try:
            conn = getattr(self, '_remote_http_conn', None)
            if conn:
                conn.close()
            self._remote_http_conn = None
        except Exception:
            pass

    def _remote_fetch_loop(self, ip, port):
        """后台线程：持续从远程设备拉取JPEG帧。"""
        import http.client
        conn = None
        while not self._remote_fetch_stop.is_set():
            try:
                if conn is None:
                    conn = http.client.HTTPConnection(ip, port, timeout=2.0)
                conn.request("GET", "/frame")
                resp = conn.getresponse()
                if resp.status == 200:
                    jpeg_bytes = resp.read()
                    if jpeg_bytes:
                        with self._remote_frame_lock:
                            self._remote_latest_frame = jpeg_bytes
                elif resp.status == 204:
                    time.sleep(0.03)
                else:
                    time.sleep(0.1)
            except Exception:
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
                conn = None
                if not self._remote_fetch_stop.is_set():
                    time.sleep(0.3)
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    def _apply_remote_frame(self, dt):
        """主线程：将后台拉取的最新帧应用到纹理。"""
        with self._remote_frame_lock:
            jpeg_bytes = self._remote_latest_frame
            self._remote_latest_frame = None
        if jpeg_bytes:
            self._display_jpeg_frame(jpeg_bytes)

    def _display_jpeg_frame(self, jpeg_bytes: bytes):
        """将JPEG字节解码并显示（应用本地视觉修正）。"""
        try:
            import numpy as np
            import cv2
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                return
            
            # 应用视觉修正模式
            frame = self._apply_fix_mode_to_desktop_frame(frame)
            
            # 转换为Kivy纹理
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, _ = frame.shape
            texture = Texture.create(size=(w, h), colorfmt="rgb")
            texture.blit_buffer(frame.tobytes(), colorfmt="rgb", bufferfmt="ubyte")
            texture.flip_vertical()
            self.texture = texture
        except ImportError:
            RuntimeStatusLogger.log_error("远程摄像头需要cv2和numpy")
        except Exception as e:
            RuntimeStatusLogger.log_error(f"解码远程帧失败: {e}")

    def _display_remote_jpeg(self, jpeg_bytes: bytes):
        """将远程MJPEG帧解码并显示（不应用本地修正，因为发送端已修正）。"""
        try:
            import numpy as np
            import cv2
            nparr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                return
            # 远程帧已经由发送端应用了方向修正，此处直接显示
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, _ = frame.shape
            texture = Texture.create(size=(w, h), colorfmt="rgb")
            texture.blit_buffer(frame.tobytes(), colorfmt="rgb", bufferfmt="ubyte")
            texture.flip_vertical()
            self.texture = texture
        except ImportError:
            RuntimeStatusLogger.log_error("远程摄像头需要cv2和numpy")
        except Exception as e:
            RuntimeStatusLogger.log_error(f"解码远程帧失败: {e}")

    def _get_wifi_servo(self):
        """获取WiFi舵机控制器（ESP32连接）。"""
        try:
            from services.wifi_servo import get_controller
            return get_controller()
        except Exception:
            return None

    # ──────── Android 独立帧捕获定时器 ────────

    def _start_android_share_clock(self):
        """启动 Android 独立帧捕获定时器（~15fps）。"""
        if self._android_share_clock:
            return
        self._android_share_clock = Clock.schedule_interval(self._android_share_tick, 1 / 15)

    def _stop_android_share_clock(self):
        """停止 Android 独立帧捕获定时器。"""
        if self._android_share_clock:
            self._android_share_clock.cancel()
            self._android_share_clock = None

    def _android_share_tick(self, dt):
        """定时从当前纹理捕获帧用于 MJPEG 共享（不依赖 texture 属性回调）。"""
        if not self._stream_sharing_enabled:
            return
        tex = self.texture
        if tex:
            self._capture_android_texture_for_sharing(tex)

    def _capture_android_texture_for_sharing(self, tex):
        """从Android摄像头纹理中提取像素并编码为JPEG，供MJPEG共享。"""
        try:
            if not tex or not self._stream_sharing_enabled:
                return
            pixels = tex.pixels
            if not pixels:
                return
            w, h = tex.size
            if w <= 0 or h <= 0:
                return
            import numpy as np
            import cv2
            arr = np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 4)
            # RGBA -> BGR
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            # 应用与显示一致的方向修正，确保PC看到的画面和手机一致
            mode = self.get_android_front_fix_mode()
            if mode in ("rotate180", "180", "default"):
                bgr = cv2.rotate(bgr, cv2.ROTATE_180)
            elif mode in ("vflip", "vertical"):
                bgr = cv2.flip(bgr, 0)
            elif mode in ("hflip", "horizontal"):
                bgr = cv2.flip(bgr, 1)
            # 缩小分辨率
            oh, ow = bgr.shape[:2]
            if ow > 640:
                scale = 640 / ow
                bgr = cv2.resize(bgr, (640, int(oh * scale)))
            _, buffer = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
            with self._frame_lock:
                self._latest_jpeg_frame = buffer.tobytes()
        except Exception:
            pass

    def register_with_esp32(self, name: str = None) -> bool:
        """向ESP32注册本设备（仅用于设备发现）。"""
        try:
            ctrl = self._get_wifi_servo()
            if not ctrl or not ctrl.is_connected:
                return False
            
            if name is None:
                name = "PC" if platform in ("win", "linux", "macosx") else "Android"
            
            has_camera = bool(self.capture) if platform in ("win", "linux", "macosx") else self._android_camera_started
            
            result = ctrl.device_register(name, has_camera=has_camera, stream_port=STREAM_SERVER_PORT)
            if result:
                self._registered_device_id = result.get("client_id")
                RuntimeStatusLogger.log_info(f"ESP32设备注册成功: {self._registered_device_id}")
                return True
            return False
        except Exception as e:
            RuntimeStatusLogger.log_error(f"ESP32注册失败: {e}")
            return False

    def get_available_sources(self) -> list:
        """获取可用的摄像头源列表（从ESP32获取已注册设备）。"""
        sources = [{"id": "local", "name": "本地摄像头", "is_self": True}]
        try:
            ctrl = self._get_wifi_servo()
            if ctrl and ctrl.is_connected:
                devices = ctrl.device_list()
                my_id = getattr(ctrl, "_device_id", None)
                for dev in devices:
                    if dev.get("id") != my_id and dev.get("has_camera"):
                        sources.append({
                            "id": dev["id"],
                            "name": dev.get("name", "未知设备"),
                            "ip": dev.get("ip"),
                            "stream_port": dev.get("stream_port", STREAM_SERVER_PORT),
                            "is_self": False,
                        })
        except Exception:
            pass
        return sources

    # ==================== P2P视频流服务器（供其他设备连接）====================

    def enable_stream_sharing(self, enabled: bool = True):
        """启用/禁用视频流共享（启动HTTP服务供其他设备连接）。"""
        if enabled:
            if not self._registered_device_id:
                self.register_with_esp32()
            self._start_stream_server()
            self._stream_sharing_enabled = True
            # Android: 启动独立的帧捕获定时器
            # texture 属性回调在某些设备上不每帧触发，需要独立 Clock 保证持续捕获
            if platform not in ("win", "linux", "macosx"):
                self._start_android_share_clock()
            RuntimeStatusLogger.log_info(f"视频流共享已启用 (端口 {STREAM_SERVER_PORT})")
        else:
            self._stop_stream_server()
            self._stream_sharing_enabled = False
            self._stop_android_share_clock()
            RuntimeStatusLogger.log_info("视频流共享已停止")

    def _start_stream_server(self):
        """启动HTTP视频流服务器。"""
        if self._stream_server_thread and self._stream_server_thread.is_alive():
            return
        
        self._stream_server_stop = threading.Event()
        self._stream_server_thread = threading.Thread(target=self._stream_server_loop, daemon=True)
        self._stream_server_thread.start()

    def _stop_stream_server(self):
        """停止HTTP视频流服务器。"""
        if hasattr(self, '_stream_server_stop'):
            self._stream_server_stop.set()
        if self._stream_server:
            try:
                self._stream_server.close()
            except Exception:
                pass
            self._stream_server = None

    def _stream_server_loop(self):
        """HTTP视频流服务器主循环。"""
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", STREAM_SERVER_PORT))
            server.listen(5)
            server.settimeout(1.0)
            self._stream_server = server
            
            RuntimeStatusLogger.log_info(f"视频流服务器启动: 0.0.0.0:{STREAM_SERVER_PORT}")
            
            while not self._stream_server_stop.is_set():
                try:
                    client, addr = server.accept()
                    threading.Thread(target=self._handle_stream_client, args=(client,), daemon=True).start()
                except socket.timeout:
                    continue
                except Exception:
                    break
        except Exception as e:
            RuntimeStatusLogger.log_error(f"视频流服务器错误: {e}")
        finally:
            if server:
                try:
                    server.close()
                except Exception:
                    pass

    def _handle_stream_client(self, client: socket.socket):
        """处理MJPEG视频流客户端请求。"""
        try:
            client.settimeout(5.0)
            try:
                request = client.recv(1024).decode('utf-8', errors='ignore')
            except socket.timeout:
                return
            if not request:
                return

            if "GET /stream" in request:
                # MJPEG multipart 持续推流
                header = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
                    "Cache-Control: no-cache, no-store\r\n"
                    "Pragma: no-cache\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                client.sendall(header.encode())

                last_frame_id = None
                while not self._stream_server_stop.is_set():
                    with self._frame_lock:
                        jpeg_data = self._latest_jpeg_frame

                    if jpeg_data and jpeg_data is not last_frame_id:
                        last_frame_id = jpeg_data
                        frame_part = (
                            "--frame\r\n"
                            "Content-Type: image/jpeg\r\n"
                            f"Content-Length: {len(jpeg_data)}\r\n"
                            "\r\n"
                        )
                        try:
                            client.sendall(frame_part.encode() + jpeg_data + b"\r\n")
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break
                    else:
                        time.sleep(0.03)

            elif "GET /frame" in request:
                # 兼容旧协议：单帧请求
                with self._frame_lock:
                    jpeg_data = self._latest_jpeg_frame
                if jpeg_data:
                    response = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg_data)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    client.sendall(response.encode() + jpeg_data)
                else:
                    response = "HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n"
                    client.sendall(response.encode())
            else:
                response = "HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n"
                client.sendall(response.encode())
        except socket.timeout:
            pass
        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass

    @property
    def is_remote_source(self) -> bool:
        """是否正在使用远程摄像头源。"""
        return self._camera_source != "local"

    @property
    def current_source_name(self) -> str:
        """当前摄像头源名称。"""
        if self._camera_source == "local":
            return "本地摄像头"
        if self._remote_target:
            return f"远程: {self._remote_target.get('name', 'unknown')}"
        return "本地摄像头"

    # ==================== PC 端远程摄像头视频流服务 ====================

    def _start_camera_stream_service(self):
        """PC 端启动远程摄像头 MJPEG 视频流服务（自动扫描设备池 + 连接手机画面）。"""
        try:
            from services.camera_stream import get_camera_stream_service
            self._camera_stream_service = get_camera_stream_service()
            self._camera_stream_service.start(self)
        except Exception as e:
            RuntimeStatusLogger.log_error(f"启动远程摄像头服务失败: {e}")

    # ==================== 手机端自动注册 + 启用共享 ====================

    def _auto_enable_sharing_and_register(self):
        """手机端/桌面模拟手机：启用 MJPEG 共享并向 ESP32 持续心跳注册。"""
        self.enable_stream_sharing(True)
        # 持续心跳注册（每 10 秒），ESP32 设备池 30 秒过期，不能注册一次就停
        def _heartbeat(dt):
            try:
                self.register_with_esp32()
            except Exception:
                pass
        if self._esp32_heartbeat_clock:
            self._esp32_heartbeat_clock.cancel()
        self._esp32_heartbeat_clock = Clock.schedule_interval(_heartbeat, 15.0)
        # 首次立即尝试
        Clock.schedule_once(lambda dt: _heartbeat(0), 1.0)
