"""ESP32 配网引导弹窗。

流程：
1. 打开弹窗 → 先尝试已保存主机直连
2. 若已保存主机在线 → 直接进入主界面
3. 否则用户点击 "扫描蓝牙" → BLE 扫描到设备 → 连接 → 读 WiFi 状态
4. 若 ESP32 已联网 → 记住 IP → 进入主界面
5. 若未联网 → 用户填写 SSID/密码 → BLE 写入 → 等待加入 WiFi → UDP 发现 → 保存 → 进入主界面
"""
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

from app import theme
from widgets.debug_ui_components import TechButton
from services.wifi_servo import save_host, load_host, udp_discover, init_controller

logger = logging.getLogger(__name__)

# Windows BLE 后端
if sys.platform == "win32":
    os.environ.setdefault("BLEAK_BACKEND", "winrt")
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

try:
    from bleak import BleakScanner, BleakClient
except Exception:
    BleakScanner = None
    BleakClient = None

TARGET_NAME = "ROBOT-ESP32-S3-BLE"
SERVICE_UUID = "0000ffaa-0000-1000-8000-00805f9b34fb"
WIFI_CHAR_UUID = "0000ffab-0000-1000-8000-00805f9b34fb"
STATUS_CHAR_UUID = "0000ffac-0000-1000-8000-00805f9b34fb"


class Esp32SetupPopup(BoxLayout):

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(10), padding=dp(12), **kwargs)

        self.popup = None
        self._device_address = None
        self._sending = False
        self._ble_running = False

        # 标题
        header = Label(
            text="--机器人配网--",
            size_hint_y=None, height=dp(28),
            color=(0.9, 0.95, 1, 1), font_name=theme.FONT,
        )

        # 状态栏
        self.status_lbl = Label(
            text="等待操作",
            size_hint_y=None, height=dp(24),
            color=(0.85, 0.9, 0.98, 1), font_name=theme.FONT,
        )

        # SSID / 密码
        self.ssid_inp = TextInput(
            hint_text="Wi-Fi SSID", multiline=False,
            size_hint_y=None, height=dp(44), font_name=theme.FONT,
            readonly=False, background_normal="", background_active="",
            background_color=(0.08, 0.1, 0.13, 1),
            foreground_color=(1, 1, 1, 1), hint_text_color=(0.7, 0.8, 0.9, 1),
            padding=(dp(12), dp(10)), cursor_color=(1, 1, 1, 1),
        )
        self.pwd_inp = TextInput(
            hint_text="Wi-Fi 密码", multiline=False, password=True,
            size_hint_y=None, height=dp(44), font_name=theme.FONT,
            readonly=False, background_normal="", background_active="",
            background_color=(0.08, 0.1, 0.13, 1),
            foreground_color=(1, 1, 1, 1), hint_text_color=(0.7, 0.8, 0.9, 1),
            padding=(dp(12), dp(10)), cursor_color=(1, 1, 1, 1),
        )

        # 日志框
        self.log_lbl = TextInput(
            text="", readonly=True, size_hint_y=None, height=dp(220),
            font_name=theme.FONT, background_normal="", background_active="",
            background_color=(0.07, 0.08, 0.1, 1),
            foreground_color=(1, 1, 1, 1), padding=(dp(12), dp(10)), cursor_width=0,
        )

        # 加载上次保存的 SSID/密码
        self._load_wifi_config()

        form = BoxLayout(orientation="vertical", spacing=dp(6))
        form.add_widget(self.ssid_inp)
        form.add_widget(self.pwd_inp)

        # 按钮行
        btn_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        self.scan_btn = TechButton(text="扫描蓝牙", font_name=theme.FONT)
        self.send_btn = TechButton(text="发送 Wi-Fi 配置", font_name=theme.FONT, disabled=True)
        btn_row.add_widget(self.scan_btn)
        btn_row.add_widget(self.send_btn)

        self.add_widget(header)
        self.add_widget(form)
        # self.add_widget(self.status_lbl)
        self.add_widget(btn_row)
        self.add_widget(self.log_lbl)

        # 背景
        with self.canvas.before:
            Color(0.12, 0.15, 0.18, 0.95)
            self._bg_rect = RoundedRectangle(radius=[12])

        def _upd_bg(*_):
            self._bg_rect.pos = self.pos
            self._bg_rect.size = self.size
        self.bind(pos=_upd_bg, size=_upd_bg)

        self._add_border(self.ssid_inp)
        self._add_border(self.pwd_inp)
        self._add_border(self.log_lbl, radius=10)

        self.scan_btn.bind(on_release=lambda *_: self._on_scan_clicked())
        self.send_btn.bind(on_release=lambda *_: self._on_send_clicked())

    # -------------------- UI 辅助 --------------------

    def _add_border(self, widget, radius=12):
        with widget.canvas.after:
            Color(0.2, 0.7, 0.95, 0.5)
            widget._border = Line(rounded_rectangle=(0, 0, 100, 100, radius), width=1.4)

        def update(*_):
            widget._border.rounded_rectangle = (
                widget.x, widget.y, widget.width, widget.height, radius,
            )
        widget.bind(pos=update, size=update)

    # -------------------- 弹窗 --------------------

    def open_popup(self):
        if self.popup is None:
            self.popup = Popup(
                title="", content=self,
                size_hint=(None, None), size=(dp(640), dp(480)),
                separator_height=0, background="", background_color=(0, 0, 0, 0),
                auto_dismiss=False,
            )
        self.popup.open()
        # 先尝试已保存主机
        self._try_saved_host_first()

    def dismiss(self):
        try:
            if self.popup:
                self.popup.dismiss()
        except Exception:
            pass

    # -------------------- 启动检测 --------------------

    def _try_saved_host_first(self):
        """尝试用已保存的主机信息直连，成功则跳过 BLE。"""
        def _try():
            host, port = load_host(App.get_running_app())
            if host:
                self._append_log(f"尝试已保存主机 {host}:{port}")
                devices = udp_discover(timeout=1.5, port=port)
                for ip, resp in devices:
                    if ip == host or resp.get("type") == "discover_resp":
                        self._append_log(f"已保存主机在线: {ip}")
                        self._on_esp32_found(ip, port)
                        return
                self._append_log("已保存主机离线，请扫描蓝牙配网")
            else:
                self._append_log("未检测到已保存主机，请扫描蓝牙配网")
        threading.Thread(target=_try, daemon=True).start()

    # -------------------- BLE 扫描 --------------------

    def _on_scan_clicked(self):
        if self._ble_running:
            return
        if not BleakScanner or not BleakClient:
            self._append_log("未安装 bleak，无法蓝牙配网")
            return
        self._ble_running = True
        self.scan_btn.disabled = True
        self._append_log("扫描蓝牙设备...")
        threading.Thread(target=self._ble_scan_thread, daemon=True).start()

    def _ble_scan_thread(self):
        try:
            asyncio.run(self._ble_scan_and_check())
        except Exception as e:
            self._append_log(f"BLE 异常: {e!r}")
        finally:
            self._ble_running = False
            Clock.schedule_once(lambda dt: setattr(self.scan_btn, "disabled", False), 0)

    async def _ble_scan_and_check(self):
        """BLE 扫描 → 连接 → 读 WiFi 状态 → 已联网直接进入 / 未联网等待用户配置。"""
        devices = await BleakScanner.discover(timeout=6)
        target = None
        for d in devices:
            if TARGET_NAME.lower() in (d.name or "").lower():
                target = d
                break

        if not target:
            self._append_log("未找到 ESP32 蓝牙设备")
            return

        self._append_log(f"发现 {target.name}，连接中...")
        try:
            async with BleakClient(target) as client:
                # 读取 WiFi 状态特征
                try:
                    raw = await client.read_gatt_char(STATUS_CHAR_UUID)
                    status = json.loads(raw.decode("utf-8"))
                    wifi_ok = bool(status.get("wifi_ok"))
                    ip = status.get("ip")
                    self._append_log(f"设备 WiFi: {'已连接' if wifi_ok else '未连接'} ip={ip}")

                    if wifi_ok and ip:
                        self._append_log("ESP32 已联网，无需配网")
                        self._on_esp32_found(ip, 5005)
                        return
                except Exception:
                    self._append_log("无法读取 WiFi 状态，需要配网")

                # 未联网 → 启用发送按钮
                self._device_address = target.address
                Clock.schedule_once(lambda dt: setattr(self.send_btn, "disabled", False), 0)
                self._append_log("请输入 Wi-Fi 信息并点击发送")
        except Exception as e:
            self._append_log(f"BLE 连接失败: {e!r}")

    # -------------------- 配网发送 --------------------

    def _on_send_clicked(self):
        if self._sending:
            return
        ssid = (self.ssid_inp.text or "").strip()
        pwd = self.pwd_inp.text or ""
        if not ssid:
            self._append_log("请输入 Wi-Fi SSID")
            return
        self._sending = True
        self.send_btn.disabled = True
        self._append_log("发送 Wi-Fi 配置中...")
        threading.Thread(target=self._provision_thread, args=(ssid, pwd), daemon=True).start()

    def _provision_thread(self, ssid: str, pwd: str):
        try:
            asyncio.run(self._provision_async(ssid, pwd))
        except Exception as e:
            self._append_log(f"配网失败: {e!r}")
        finally:
            self._sending = False
            Clock.schedule_once(lambda dt: setattr(self.send_btn, "disabled", False), 0)

    async def _provision_async(self, ssid: str, pwd: str):
        """BLE 写入 WiFi 凭据 → 等待 ESP32 连接 → UDP 发现。"""
        addr = self._device_address
        if not addr:
            self._append_log("重新扫描蓝牙...")
            devices = await BleakScanner.discover(timeout=6)
            target = None
            for d in devices:
                if TARGET_NAME.lower() in (d.name or "").lower():
                    target = d
                    break
            if not target:
                self._append_log("未找到 ESP32 蓝牙")
                return
            addr = target.address

        payload = f"{ssid}\n{pwd}".encode("utf-8")
        self._append_log(f"连接 {addr}，写入 WiFi 配置...")
        async with BleakClient(addr) as client:
            await client.write_gatt_char(WIFI_CHAR_UUID, payload, response=True)
        self._append_log("已发送，等待 ESP32 连接 WiFi (~5秒)...")

        # 保存 WiFi 配置供下次回填
        self._save_wifi_config(ssid, pwd)

        import time
        time.sleep(5.0)

        # UDP 广播发现
        self._append_log("搜索 ESP32...")
        found = udp_discover(timeout=3.0)
        if found:
            ip = found[0][0]
            self._append_log(f"发现 ESP32: {ip}")
            self._on_esp32_found(ip, 5005)
        else:
            self._append_log("未发现设备，请检查 WiFi 后重试")

    # -------------------- 成功回调 --------------------

    def _on_esp32_found(self, host: str, port: int):
        """ESP32 在线：保存主机信息、初始化控制器、通知 app。"""
        app = App.get_running_app()
        save_host(host, port, app)
        ctrl = init_controller(host, port)
        try:
            app.wifi_servo = ctrl
            app._esp32_host = host
            app._esp32_port = port
        except Exception:
            pass
        self._append_log(f"配网成功-->{host}:{port}")

        def _notify(dt):
            try:
                if hasattr(app, "on_esp32_connected"):
                    app.on_esp32_connected(host, port)
            except Exception:
                pass
            self.dismiss()
        Clock.schedule_once(_notify, 0.3)

    # -------------------- WiFi 配置记忆 --------------------

    def _wifi_config_path(self):
        try:
            from pathlib import Path
            app = App.get_running_app()
            base = Path(getattr(app, "user_data_dir", None) or "data")
            return str(base / "wifi_config.json")
        except Exception:
            return "data/wifi_config.json"

    def _load_wifi_config(self):
        try:
            fp = self._wifi_config_path()
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.ssid_inp.text = str(cfg.get("ssid", ""))
                self.pwd_inp.text = str(cfg.get("password", ""))
        except Exception:
            pass

    def _save_wifi_config(self, ssid: str, pwd: str):
        try:
            fp = self._wifi_config_path()
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                json.dump({"ssid": ssid, "password": pwd}, f)
        except Exception:
            pass

    # -------------------- 日志 --------------------

    def _append_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"

        def update(_dt):
            prev = self.log_lbl.text or ""
            lines = (prev + "\n" + line).strip().split("\n")
            self.log_lbl.text = "\n".join(lines[-12:])
            # self.status_lbl.text = msg
        Clock.schedule_once(update, 0)


__all__ = ["Esp32SetupPopup"]