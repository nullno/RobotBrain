import threading
import logging
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, RoundedRectangle, Line

from services import esp32_discovery, comm_config
from app import esp32_runtime

logger = logging.getLogger(__name__)


class Esp32SetupPopup(BoxLayout):
    """启动时弹窗：引导发现并配网 ESP32-S3。

    - 未连接前弹窗不关闭；连接成功后可手动关闭。
    - 支持仅扫描以及 BLE 配网+扫描两种流程。
    """

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(8), padding=dp(10), **kwargs)
        self.popup = None
        self.status_lbl = Label(text="等待操作", size_hint_y=None, height=dp(26), color=(0.85, 0.9, 0.98, 1))
        self.log_lbl = Label(text="", size_hint_y=None, height=dp(140), color=(0.8, 0.86, 0.95, 1))
        self.ssid_inp = TextInput(hint_text="Wi-Fi SSID", multiline=False)
        self.pwd_inp = TextInput(hint_text="Wi-Fi 密码", multiline=False, password=True)
        self._load_comm_config()

        form = BoxLayout(orientation="vertical", spacing=dp(6))
        form.add_widget(self.ssid_inp)
        form.add_widget(self.pwd_inp)

        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self.scan_btn = Button(text="仅扫描")
        self.prov_btn = Button(text="BLE配网并扫描")
        btn_row.add_widget(self.scan_btn)
        btn_row.add_widget(self.prov_btn)

        self.close_btn = Button(text="关闭（已连接后可点）", size_hint_y=None, height=dp(40), disabled=True)

        self.add_widget(Label(text="ESP32 设备联网向导", size_hint_y=None, height=dp(24), color=(0.9, 0.95, 1, 1)))
        self.add_widget(form)
        self.add_widget(self.status_lbl)
        self.add_widget(self.log_lbl)
        self.add_widget(btn_row)
        self.add_widget(self.close_btn)

        with self.canvas.before:
            Color(0.12, 0.15, 0.18, 0.95)
            self._bg_rect = RoundedRectangle(radius=[12])
            Color(0.2, 0.7, 0.95, 0.08)
            self._glow_rect = RoundedRectangle(radius=[14])
            Color(0.2, 0.7, 0.95, 0.6)
            self._border_line = Line(rounded_rectangle=(0, 0, 100, 100, 12), width=2)

        def _update_rect(*_):
            self._bg_rect.pos = self.pos
            self._bg_rect.size = self.size
            self._glow_rect.pos = (self.x - 6, self.y - 6)
            self._glow_rect.size = (self.width + 12, self.height + 12)
            self._border_line.rounded_rectangle = (self.x, self.y, self.width, self.height, 12)

        self.bind(pos=_update_rect, size=_update_rect)

        self.scan_btn.bind(on_release=lambda *_: self._start_scan(ble=False))
        self.prov_btn.bind(on_release=lambda *_: self._start_scan(ble=True))
        self.close_btn.bind(on_release=lambda *_: self._try_close())

    # ------------------ 公共接口 ------------------
    def open_popup(self):
        if self.popup is None:
            self.popup = Popup(
                title="",
                content=self,
                size_hint=(None, None),
                size=(dp(640), dp(420)),
                separator_height=0,
                background="",
                auto_dismiss=False,
            )
        self._update_close_state()
        self.popup.open()
        # 启动一次自动扫描
        self._start_scan(ble=False)

    def _try_close(self):
        if self._is_connected():
            self.popup.dismiss()
        else:
            self._append_log("未连接，不能关闭弹窗")

    # ------------------ 逻辑 ------------------
    def _is_connected(self):
        try:
            app = App.get_running_app()
            sb = getattr(app, "servo_bus", None)
            return sb is not None and not getattr(sb, "is_mock", True)
        except Exception:
            return False

    def _update_close_state(self):
        self.close_btn.disabled = not self._is_connected()

    def _load_comm_config(self):
        cfg = comm_config.load_comm_config(App.get_running_app()) or {}
        self.ssid_inp.text = str(cfg.get("ssid", ""))
        self.pwd_inp.text = str(cfg.get("password", ""))

    def _save_comm_config(self):
        data = {
            "ssid": self.ssid_inp.text.strip(),
            "password": self.pwd_inp.text,
            "udp_port": 5005,
        }
        comm_config.save_comm_config(data, App.get_running_app())

    def _start_scan(self, ble=False):
        self.scan_btn.disabled = True
        self.prov_btn.disabled = True
        self._append_log("开始扫描" + (" + BLE 配网" if ble else ""))
        threading.Thread(target=self._scan_worker, args=(ble,), daemon=True).start()

    def _scan_worker(self, ble=False):
        try:
            if ble:
                self._save_comm_config()
                host, port = comm_config.auto_provision_and_discover(App.get_running_app(), preferred_port=5005)
                if host:
                    self._bind_host(host, port)
                    return
            # 普通扫描
            devices = esp32_discovery.discover(timeout=1.5)
            self._append_log(f"发现 {len(devices)} 台设备: {devices}")
            if devices:
                host = devices[0][0]
                self._bind_host(host, 5005)
            else:
                self._append_log("未发现设备，请检查设备电源与同一网段")
        finally:
            Clock.schedule_once(lambda dt: self._reset_buttons(), 0)

    def _bind_host(self, host, port=None):
        ok = esp32_runtime.manual_bind_host(App.get_running_app(), host, port)
        if ok:
            self._append_log(f"已连接 {host}:{port or 5005}")
            Clock.schedule_once(lambda dt: self._update_close_state(), 0)
        else:
            self._append_log(f"发现 {host} 但连接失败")

    def _reset_buttons(self):
        self.scan_btn.disabled = False
        self.prov_btn.disabled = False

    def _append_log(self, msg: str):
        logger.info(msg)
        def _upd(_dt):
            prev = self.log_lbl.text or ""
            lines = (prev + "\n" + msg).strip().split("\n")
            self.log_lbl.text = "\n".join(lines[-8:])
            self.status_lbl.text = msg
        Clock.schedule_once(_upd, 0)


__all__ = ["Esp32SetupPopup"]
