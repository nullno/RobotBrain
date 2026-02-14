from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.utils import platform
from widgets.runtime_status import RuntimeStatusLogger
from widgets.runtime_status import RuntimeStatusLogger


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
        
        if platform in ("win", "linux", "macosx"):
            self._start_desktop()
        else:
            self._start_android()

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
                self.camera = None
                camera_started = False

                # 尝试多个摄像头索引：优先尝试 1/2/不指定索引作为最后手段
                for idx in [1, 2, -1]:
                    try:
                        if idx == -1:
                            self.camera = Camera(play=True, resolution=(640, 480))
                        else:
                            self.camera = Camera(index=idx, play=True, resolution=(640, 480))

                        # 仅在首次确定需要翻转时，设置一次 canvas 转换指令，避免每帧清理画布导致闪烁
                        if idx == 1:
                            try:
                                from kivy.graphics import PushMatrix, PopMatrix, Scale
                                # 在 canvas.before/after 中添加变换指令
                                if not getattr(self, '_camera_flip_installed', False):
                                    with self.canvas.before:
                                        PushMatrix()
                                        Scale(-1, 1, 1)
                                    with self.canvas.after:
                                        PopMatrix()
                                    self._camera_flip_installed = True
                            except Exception:
                                pass

                        # 绑定 texture 回调 —— 回调只负责替换 texture，不进行 canvas 操作
                        def _on_text(inst, val, camera_idx=idx):
                            try:
                                if val:
                                    # 修复: Android 前置摄像头(idx=1)画面上下颠倒的问题
                                    # 配合 canvas 的 Scale(-1, 1, 1) 实现正确的镜像与正立显示
                                    if camera_idx == 1 and not getattr(val, '__flipped__', False):
                                        val.flip_vertical()
                                        val.__flipped__ = True
                                        
                                    self.texture = val
                                    RuntimeStatusLogger.log_info(
                                        f'Android 摄像头 texture 就绪 (index={camera_idx})'
                                    )
                            except Exception:
                                pass

                        self.camera.bind(texture=_on_text)
                        self._camera_index = idx
                        camera_started = True
                        RuntimeStatusLogger.log_info(f"摄像头已启动 (index={idx})")
                        print(f"✅ 摄像头已启动 (index={idx})")
                        break
                    except Exception as e:
                        print(f"⚠️ 尝试摄像头 index={idx} 失败: {e}")
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
                        print("⚠️ 摄像头权限未授予，无法显示摄像头画面")

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
            except Exception:
                pass
