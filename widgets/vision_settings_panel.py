from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.metrics import dp
from kivy.app import App
from kivy.clock import Clock
from widgets.runtime_status import RuntimeStatusLogger
from widgets.camera_view import CameraView


class VisionSettingsPanel(BoxLayout):
    """视觉设置面板：用于调整摄像头方向修正模式（Android/桌面）。"""

    def __init__(self, show_message=None, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", dp(8))
        kwargs.setdefault("padding", (dp(10), dp(10), dp(10), dp(10)))
        super().__init__(**kwargs)

        self._show_message = show_message
        self._status = Label(
            text="视觉设置: 未检测到 CameraView",
            size_hint_y=None,
            height=dp(28),
            color=(0.8, 0.9, 1, 1),
            halign="left",
            valign="middle",
        )
        self._status.bind(size=self._status.setter("text_size"))
        self.add_widget(self._status)

        hint = Label(
            text="摄像头方向修正（跨平台）：若画面颠倒可切换模式",
            size_hint_y=None,
            height=dp(24),
            color=(0.7, 0.8, 0.9, 1),
            halign="left",
            valign="middle",
        )
        hint.bind(size=hint.setter("text_size"))
        self.add_widget(hint)

        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._btn_rotate180 = Button(text="旋转180°")
        self._btn_vflip = Button(text="上下翻转")
        self._btn_hflip = Button(text="左右翻转")
        self._btn_none = Button(text="不修正")
        row.add_widget(self._btn_rotate180)
        row.add_widget(self._btn_vflip)
        row.add_widget(self._btn_hflip)
        row.add_widget(self._btn_none)
        self.add_widget(row)

        row2 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._btn_refresh = Button(text="读取当前")
        self._btn_restart = Button(text="重启摄像头")
        row2.add_widget(self._btn_refresh)
        row2.add_widget(self._btn_restart)
        self.add_widget(row2)

        self._btn_rotate180.bind(on_release=lambda *_: self._set_mode("rotate180"))
        self._btn_vflip.bind(on_release=lambda *_: self._set_mode("vflip"))
        self._btn_hflip.bind(on_release=lambda *_: self._set_mode("hflip"))
        self._btn_none.bind(on_release=lambda *_: self._set_mode("none"))
        self._btn_refresh.bind(on_release=lambda *_: self.refresh_status())
        self._btn_restart.bind(on_release=lambda *_: self._restart_camera())

        Clock.schedule_once(lambda dt: self.refresh_status(), 0)

    def _get_camera_view(self):
        try:
            app = App.get_running_app()
            root = getattr(app, "root_widget", None)
            if root and getattr(root, "ids", None):
                cam = root.ids.get("camera_view")
                if cam is not None:
                    return cam

            def _walk(widget):
                if isinstance(widget, CameraView):
                    return widget
                for child in getattr(widget, "children", []):
                    found = _walk(child)
                    if found is not None:
                        return found
                return None

            if root is not None:
                found = _walk(root)
                if found is not None:
                    return found
        except Exception:
            pass
        return None

    def _notify(self, text):
        try:
            if callable(self._show_message):
                self._show_message(text)
        except Exception:
            pass
        try:
            RuntimeStatusLogger.log_info(str(text))
        except Exception:
            pass

    def _set_mode(self, mode):
        cam = self._get_camera_view()
        if not cam or not hasattr(cam, "set_android_front_fix_mode"):
            self._notify("未找到 CameraView，无法设置视觉模式")
            return
        try:
            actual = cam.set_android_front_fix_mode(mode)
            self._notify(f"视觉设置已应用: {actual}")
            self.refresh_status()
        except Exception as e:
            self._notify(f"视觉设置失败: {e}")

    def _restart_camera(self):
        cam = self._get_camera_view()
        if not cam or not hasattr(cam, "restart_camera"):
            self._notify("未找到 CameraView，无法重启相机")
            return
        try:
            ok = bool(cam.restart_camera())
            if ok:
                self._notify("相机已重启")
            else:
                self._notify("相机重启失败")
            Clock.schedule_once(lambda dt: self.refresh_status(), 0.2)
        except Exception as e:
            self._notify(f"相机重启异常: {e}")

    def refresh_status(self):
        cam = self._get_camera_view()
        if not cam:
            self._status.text = "视觉设置: 未检测到 CameraView"
            return
        try:
            mode = "rotate180"
            if hasattr(cam, "get_android_front_fix_mode"):
                mode = str(cam.get_android_front_fix_mode())
            idx = getattr(cam, "_camera_index", None)
            self._status.text = f"视觉设置: index={idx}, 模式={mode}"
        except Exception:
            self._status.text = "视觉设置: 状态读取失败"
