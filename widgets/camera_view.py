from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.utils import platform
from kivy.app import App
from kivy.graphics import PushMatrix, PopMatrix, Rotate, Scale
from widgets.runtime_status import RuntimeStatusLogger
import os


class CameraView(Image):
    DEFAULT_ANDROID_FIX_MODE = "rotate180"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.allow_stretch = True
        self.keep_ratio = True

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
            mode = str(
                os.environ.get("RB_ANDROID_FRONT_FIX", self.DEFAULT_ANDROID_FIX_MODE)
            ).strip().lower()
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
            mode = str(
                os.environ.get("RB_ANDROID_FRONT_FIX", self.DEFAULT_ANDROID_FIX_MODE)
            ).strip().lower()

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
            mode = str(
                os.environ.get("RB_ANDROID_FRONT_FIX", self.DEFAULT_ANDROID_FIX_MODE)
            ).strip().lower()
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

        try:
            frame = self._apply_fix_mode_to_desktop_frame(frame)
        except Exception:
            pass

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
                                    # 复制一个子纹理并通过 uv 变换修正方向（比 flip_* 更稳定）
                                    tex = val.get_region(0, 0, val.width, val.height)
                                    is_front, mode = self._apply_android_texture_transform(tex, camera_idx)
                                    self.texture = tex
                                    self._apply_android_display_transform()
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
            # Android摄像头清理
            try:
                if hasattr(self, 'camera') and self.camera:
                    self.camera.play = False
                    self.camera = None
                self._android_camera_started = False
            except Exception:
                pass
