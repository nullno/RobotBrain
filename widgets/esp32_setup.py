import asyncio
import json
import logging
import os
import sys
import threading
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.label import Label
from kivy.graphics import Color, RoundedRectangle, Line

from services import comm_config
from app import esp32_runtime, theme
from widgets.debug_ui_components import TechButton

logger = logging.getLogger(__name__)

# Windows 需要明确后端与事件循环策略，避免 bleak 报错
if sys.platform == "win32":
    os.environ.setdefault("BLEAK_BACKEND", "winrt")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    from bleak import BleakScanner, BleakClient
except Exception:
    BleakScanner = None
    BleakClient = None


TARGET_NAME = "ROBOT-ESP32-S3-BLE"
SERVICE_UUID = "0000ffaa-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffab-0000-1000-8000-00805f9b34fb"
STATUS_CHAR_UUID = "0000ffac-0000-1000-8000-00805f9b34fb"
MAX_PACKET_SIZE = 96


class Esp32SetupPopup(BoxLayout):

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(10), padding=dp(12), **kwargs)

        self.popup = None
        self._device_address = None
        self._sending = False
        self._ble_running = False

        # 标题
        header = Label(
            text="机器人配网",
            size_hint_y=None,
            height=dp(28),
            color=(0.9, 0.95, 1, 1),
            font_name=theme.FONT,
        )

        # 状态栏
        self.status_lbl = Label(
            text="等待操作",
            size_hint_y=None,
            height=dp(24),
            color=(0.85, 0.9, 0.98, 1),
            font_name=theme.FONT,
        )

        # SSID 输入框
        self.ssid_inp = TextInput(
            hint_text="Wi-Fi SSID",
            multiline=False,
            size_hint_y=None,
            height=dp(44),
            font_name=theme.FONT,
            readonly=False,
            background_normal="",
            background_active="",
            background_color=(0.08, 0.1, 0.13, 1),
            foreground_color=(1, 1, 1, 1),
            hint_text_color=(0.7, 0.8, 0.9, 1),
            padding=(dp(12), dp(10)),
            cursor_color=(1, 1, 1, 1),
        )

        # 密码输入框
        self.pwd_inp = TextInput(
            hint_text="Wi-Fi 密码",
            multiline=False,
            password=True,
            size_hint_y=None,
            height=dp(44),
            font_name=theme.FONT,
            readonly=False,
            background_normal="",
            background_active="",
            background_color=(0.08, 0.1, 0.13, 1),
            foreground_color=(1, 1, 1, 1),
            hint_text_color=(0.7, 0.8, 0.9, 1),
            padding=(dp(12), dp(10)),
            cursor_color=(1, 1, 1, 1),
        )

        # 日志框
        self.log_lbl = TextInput(
            text="",
            readonly=True,
            size_hint_y=None,
            height=dp(140),
            font_name=theme.FONT,
            background_normal="",
            background_active="",
            background_color=(0.07, 0.08, 0.1, 1),
            foreground_color=(1, 1, 1, 1),
            padding=(dp(12), dp(10)),
            cursor_width=0,
        )

        self._load_comm_config()

        # 表单
        form = BoxLayout(orientation="vertical", spacing=dp(6))
        form.add_widget(self.ssid_inp)
        form.add_widget(self.pwd_inp)

        # 发送按钮
        self.send_btn = TechButton(
            text="发送 Wi-Fi 配置",
            size_hint_y=None,
            height=dp(42),
            disabled=False,
            font_name=theme.FONT,
        )

        # 添加组件
        self.add_widget(header)
        self.add_widget(form)
        self.add_widget(self.status_lbl)
        self.add_widget(self.send_btn)
        self.add_widget(self.log_lbl)

        # 弹窗背景
        with self.canvas.before:
            Color(0.12, 0.15, 0.18, 0.95)
            self._bg_rect = RoundedRectangle(radius=[12])

        def update_bg(*_):
            self._bg_rect.pos = self.pos
            self._bg_rect.size = self.size

        self.bind(pos=update_bg, size=update_bg)

        # 给输入框添加科技风边框
        self._add_border(self.ssid_inp)
        self._add_border(self.pwd_inp)
        self._add_border(self.log_lbl, radius=10)

        self.send_btn.bind(on_release=lambda *_: self._on_send_clicked())

    # ---------------- UI 美化 ----------------

    def _add_border(self, widget, radius=12):
        with widget.canvas.after:
            Color(0.2, 0.7, 0.95, 0.5)
            widget._border = Line(rounded_rectangle=(0, 0, 100, 100, radius), width=1.4)

        def update(*_):
            widget._border.rounded_rectangle = (
                widget.x,
                widget.y,
                widget.width,
                widget.height,
                radius,
            )

        widget.bind(pos=update, size=update)

    # ---------------- 公共接口 ----------------

    def open_popup(self):
        if self.popup is None:
            self.popup = Popup(
                title="",
                content=self,
                size_hint=(None, None),
                size=(dp(640), dp(440)),
                separator_height=0,
                background="",
                background_color=(0, 0, 0, 0),
                auto_dismiss=False,
            )
        self.popup.open()
        self._start_ble_sequence()

    # ---------------- BLE ----------------

    def _start_ble_sequence(self):
        if not BleakScanner or not BleakClient:
            self._append_log("未安装 bleak，无法蓝牙配网")
            return
        if self._ble_running:
            return

        self._ble_running = True
        self._append_log("扫描蓝牙设备...")
        threading.Thread(target=self._ble_thread, daemon=True).start()

    def _ble_thread(self):
        try:
            asyncio.run(self._ble_sequence())
        except Exception as e:
            self._append_log(f"BLE异常: {e!r}")
        finally:
            self._ble_running = False

    async def _ble_sequence(self):
        devices = await BleakScanner.discover(timeout=6)
        target = None
        for d in devices:
            if TARGET_NAME.lower() in (d.name or "").lower():
                target = d
                break

        if not target:
            self._append_log("未找到目标设备")
            return

        self._append_log("发现设备，准备连接...")
        self._device_address = target.address

    # ---------------- 配网 ----------------

    def _on_send_clicked(self):
        if self._sending:
            return

        ssid = (self.ssid_inp.text or "").strip()
        pwd = self.pwd_inp.text or ""
        if not ssid:
            self._append_log("请输入 Wi-Fi SSID")
            return

        self._sending = True
        self._set_form_enabled(False)
        self._append_log("发送 Wi-Fi 配置中...")
        threading.Thread(target=self._provision_and_discover, args=(ssid, pwd), daemon=True).start()

    def _provision_and_discover(self, ssid: str, password: str):
        try:
            comm_config.save_comm_config({"ssid": ssid, "password": password}, App.get_running_app())
        except Exception:
            pass

        host = None
        port = None
        try:
            host, port = comm_config.auto_provision_and_discover(App.get_running_app(), preferred_port=5005)
            if host:
                self._append_log(f"已发现 ESP32: {host}:{port or 5005}")
                try:
                    esp32_runtime.manual_bind_host(App.get_running_app(), host, port or 5005)
                except Exception:
                    pass
                self._notify_provision_success(host, port or 5005)
                self._append_log("配网成功")
            else:
                self._append_log("未发现设备，请重试")
        except Exception as e:
            self._append_log(f"配网失败: {e}")
        finally:
            self._sending = False
            Clock.schedule_once(lambda dt: self._set_form_enabled(True), 0)

    def _notify_provision_success(self, host: str, port: int):
        try:
            app = App.get_running_app()
            if app and hasattr(app, "on_esp32_provisioned"):
                Clock.schedule_once(lambda dt: app.on_esp32_provisioned(host, port), 0)
        except Exception:
            pass

    # ---------------- 辅助 ----------------

    def _load_comm_config(self):
        cfg = comm_config.load_comm_config(App.get_running_app()) or {}
        self.ssid_inp.text = str(cfg.get("ssid", ""))
        self.pwd_inp.text = str(cfg.get("password", ""))

    def _set_form_enabled(self, enabled):
        self.ssid_inp.readonly = not enabled
        self.pwd_inp.readonly = not enabled
        self.send_btn.disabled = not enabled

    def _append_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"

        def update(_dt):
            prev = self.log_lbl.text or ""
            lines = (prev + "\n" + line).strip().split("\n")
            self.log_lbl.text = "\n".join(lines[-10:])
            self.status_lbl.text = msg

        Clock.schedule_once(update, 0)


__all__ = ["Esp32SetupPopup"]