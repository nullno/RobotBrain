from __future__ import annotations

import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

from services import comm_config, esp32_client, esp32_discovery


class CommConfigPanel(BoxLayout):
    """通信配置面板：用于 Wi-Fi 与 BLE 配网、发现与主机绑定。"""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=8, padding=8, **kwargs)
        # Allow ScrollView to size correctly
        self.size_hint_y = None

        font_path = "assets/fonts/simhei.ttf"
        font_args = {"font_name": font_path}

        self.container = BoxLayout(orientation="vertical", spacing=8, size_hint_y=None, padding=(0, dp(6), 0, dp(12)))
        self.container.bind(minimum_height=self.container.setter("height"))

        form = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None, height=dp(190))
        self.ssid_inp = TextInput(hint_text="Wi-Fi SSID", multiline=False, **font_args)
        self.pwd_inp = TextInput(hint_text="Wi-Fi 密码", multiline=False, password=True, **font_args)
        self.ble_inp = TextInput(hint_text="BLE 名称 (可选)", multiline=False, **font_args)
        self.port_inp = TextInput(hint_text="UDP端口 (默认5005)", multiline=False, **font_args)
        form.add_widget(self.ssid_inp)
        form.add_widget(self.pwd_inp)
        form.add_widget(self.ble_inp)
        form.add_widget(self.port_inp)
        self.container.add_widget(form)

        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=6)
        self.load_btn = Button(text="加载配置", **font_args)
        self.save_btn = Button(text="保存配置", **font_args)
        btn_row.add_widget(self.load_btn)
        btn_row.add_widget(self.save_btn)
        self.container.add_widget(btn_row)

        action_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=6)
        self.prov_btn = Button(text="蓝牙配网并发现", **font_args)
        self.discover_btn = Button(text="仅发现设备", **font_args)
        action_row.add_widget(self.prov_btn)
        action_row.add_widget(self.discover_btn)
        self.container.add_widget(action_row)

        test_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=6)
        self.ping_btn = Button(text="连通性测试", **font_args)
        test_row.add_widget(self.ping_btn)
        self.container.add_widget(test_row)

        self.status_lbl = Label(text="状态: 空", size_hint_y=None, height=dp(24), **font_args)
        self.container.add_widget(self.status_lbl)

        # bottom spacer to avoid clipping inside ScrollView
        spacer = Label(size_hint_y=None, height=dp(8))
        self.container.add_widget(spacer)

        # Bind container height to self to enable scrolling
        self.container.bind(height=lambda inst, val: setattr(self, "height", val))
        self.add_widget(self.container)

        self.load_btn.bind(on_release=lambda *_: self._load())
        self.save_btn.bind(on_release=lambda *_: self._save())
        self.prov_btn.bind(on_release=lambda *_: threading.Thread(target=self._provision_and_discover, daemon=True).start())
        self.discover_btn.bind(on_release=lambda *_: threading.Thread(target=self._discover_only, daemon=True).start())
        self.ping_btn.bind(on_release=lambda *_: threading.Thread(target=self._ping_status, daemon=True).start())

        # Initialize fields from config if present
        Clock.schedule_once(lambda dt: self._load(), 0)

    # -----------------------------------------------------
    def _load(self):
        cfg = comm_config.load_comm_config(App.get_running_app()) or {}
        self.ssid_inp.text = str(cfg.get("ssid", ""))
        self.pwd_inp.text = str(cfg.get("password", ""))
        self.ble_inp.text = str(cfg.get("ble_name", ""))
        port_val = cfg.get("udp_port")
        self.port_inp.text = str(port_val) if port_val else ""
        self._set_status("已加载配置")

    def _save(self):
        data = {
            "ssid": self.ssid_inp.text.strip(),
            "password": self.pwd_inp.text,
            "ble_name": self.ble_inp.text.strip() or None,
            "udp_port": int(self.port_inp.text) if self.port_inp.text.strip().isdigit() else 5005,
        }
        ok = comm_config.save_comm_config(data, App.get_running_app())
        self._set_status("保存成功" if ok else "保存失败")

    def _discover_only(self):
        self._set_status("扫描中...")
        try:
            devices = esp32_discovery.discover(timeout=1.5)
        except Exception:
            devices = []
        if devices:
            host = devices[0][0]
            port = self._port_or_default()
            self._bind_host(host, port)
            self._set_status(f"发现设备: {host}:{port}")
        else:
            self._set_status("未发现设备")

    def _provision_and_discover(self):
        self._set_status("蓝牙配网中...")
        host, port = comm_config.auto_provision_and_discover(App.get_running_app(), preferred_port=self._port_or_default())
        if host:
            self._bind_host(host, port)
            self._set_status(f"已配网并发现: {host}:{port}")
        else:
            self._set_status("配网或发现失败")

    def _ping_status(self):
        self._set_status("连通性测试中...")
        try:
            res = esp32_client.status() or {}
            self._set_status(f"状态: {res}")
        except Exception as exc:
            self._set_status(f"测试失败: {exc}")

    # -----------------------------------------------------
    def _bind_host(self, host, port=None):
        try:
            esp32_client.set_host(host, port=port)
        except Exception:
            pass
        try:
            app = App.get_running_app()
            app._esp32_host = host
            if port:
                app._esp32_port = int(port)
        except Exception:
            pass

    def _port_or_default(self) -> int:
        try:
            return int(self.port_inp.text.strip()) if self.port_inp.text.strip() else 5005
        except Exception:
            return 5005

    def _set_status(self, msg: str):
        Clock.schedule_once(lambda dt: setattr(self.status_lbl, "text", f"状态: {msg}"), 0)


__all__ = ["CommConfigPanel"]
