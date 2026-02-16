from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.utils import platform
from widgets.runtime_status import RuntimeStatusLogger
import os


class CameraView(Image):
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
            mode = str(os.environ.get("RB_ANDROID_FRONT_FIX", "rotate180")).strip().lower()
            is_front = int(camera_idx) in self._android_front_indices if camera_idx != -1 else False

            # Android 相机纹理普遍存在 Y 轴反向，默认先做垂直翻转
            uvpos = (0.0, 1.0)
            uvsize = (1.0, -1.0)

            # 前置默认做 180°（等价于上下+左右），可通过环境变量覆盖
            if is_front:
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
        """设置 Android 前置摄像头方向修正模式。"""
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
                m = "rotate180"
            os.environ["RB_ANDROID_FRONT_FIX"] = m
            try:
                RuntimeStatusLogger.log_info(f"视觉设置: 前置修正模式 -> {m}")
            except Exception:
                pass
            return m
        except Exception:
            return "rotate180"

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
