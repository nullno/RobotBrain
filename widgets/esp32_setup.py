import asyncio
import json
import logging
import os
import sys
import threading

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


# Windows 需要明确后端与事件循环策略，避免 bleak 报错
if sys.platform == "win32":
    os.environ.setdefault("BLEAK_BACKEND", "winrt")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

try:
    from bleak import BleakScanner, BleakClient
except Exception:  # bleak 可能未安装，延迟导入失败时只允许 LAN 扫描
    BleakScanner = None
    BleakClient = None


TARGET_NAME = "ROBOT-ESP32-S3-BLE"
SERVICE_UUID = "0000ffaa-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffab-0000-1000-8000-00805f9b34fb"
STATUS_CHAR_UUID = "0000ffac-0000-1000-8000-00805f9b34fb"
MAX_PACKET_SIZE = 96


class Esp32SetupPopup(BoxLayout):
    """配网弹窗：蓝牙优先检查 Wi-Fi，已联网则自动关闭，否则下发配网。"""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(10), padding=dp(12), **kwargs)
        self.popup = None
        self.status_lbl = Label(text="等待操作", size_hint_y=None, height=dp(24), color=(0.85, 0.9, 0.98, 1))
        self.log_lbl = TextInput(
            text="",
            size_hint_y=None,
            height=dp(160),
            readonly=True,
            background_color=(0.09, 0.1, 0.12, 0.9),
            foreground_color=(0.8, 0.86, 0.95, 1),
            cursor_width=0,
        )
        self.ssid_inp = TextInput(hint_text="Wi-Fi SSID", multiline=False)
        self.pwd_inp = TextInput(hint_text="Wi-Fi 密码", multiline=False, password=True)
        self._load_comm_config()

        form = BoxLayout(orientation="vertical", spacing=dp(6))
        form.add_widget(self.ssid_inp)
        form.add_widget(self.pwd_inp)

        btn_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        self.ble_btn = Button(text="蓝牙扫描+配网")
        self.scan_btn = Button(text="仅局域网扫描")
        btn_row.add_widget(self.ble_btn)
        btn_row.add_widget(self.scan_btn)

        self.close_btn = Button(text="关闭（已连接自动）", size_hint_y=None, height=dp(42), disabled=True)

        header = Label(text="ESP32 联网向导", size_hint_y=None, height=dp(26), color=(0.9, 0.95, 1, 1))
        sub = Label(text="先蓝牙检测联网状态，已联网直接关闭", size_hint_y=None, height=dp(20), color=(0.7, 0.8, 0.9, 1))

        self.add_widget(header)
        self.add_widget(sub)
        self.add_widget(form)
        self.add_widget(self.status_lbl)
        self.add_widget(self.log_lbl)
        self.add_widget(btn_row)
        self.add_widget(self.close_btn)

        with self.canvas.before:
            Color(0.12, 0.15, 0.18, 0.95)
            self._bg_rect = RoundedRectangle(radius=[12])
        with self.canvas.after:
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

        self.scan_btn.bind(on_release=lambda *_: self._start_lan_scan())
        self.ble_btn.bind(on_release=lambda *_: self._start_ble_flow())
        self.close_btn.bind(on_release=lambda *_: self._try_close())

    # ------------------ 公共接口 ------------------
    def open_popup(self):
        if self.popup is None:
            self.popup = Popup(
                title="",
                content=self,
                size_hint=(None, None),
                size=(dp(640), dp(440)),
                separator_height=0,
                background="",
                auto_dismiss=False,
            )
        self._update_close_state()
        self.popup.open()
        # 默认先跑一次蓝牙流程；如未安装 bleak 则退化为 LAN 扫描
        if BleakScanner and BleakClient:
            self._start_ble_flow()
        else:
            self._append_log("未检测到 bleak，执行局域网扫描。")
            self._start_lan_scan()

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

    # ------------------ LAN 扫描 ------------------
    def _start_lan_scan(self):
        self._set_buttons_disabled(True)
        self._append_log("开始局域网扫描...")
        threading.Thread(target=self._lan_scan_worker, daemon=True).start()

    def _lan_scan_worker(self):
        try:
            devices = esp32_discovery.discover(timeout=1.5)
            self._append_log(f"发现 {len(devices)} 台设备: {devices}")
            if devices:
                host = devices[0][0]
                self._bind_host(host, 5005)
            else:
                self._append_log("未发现设备，请确认设备通电且同网段")
        finally:
            Clock.schedule_once(lambda dt: self._set_buttons_disabled(False), 0)

    # ------------------ BLE 配网流程 ------------------
    def _start_ble_flow(self):
        if not BleakScanner or not BleakClient:
            self._append_log("未安装 bleak，无法执行蓝牙配网")
            return
        self._save_comm_config()
        self._set_buttons_disabled(True)
        self._append_log("蓝牙扫描中...")
        threading.Thread(target=self._ble_flow_thread, daemon=True).start()

    def _ble_flow_thread(self):
        try:
            asyncio.run(self._ble_flow())
        except Exception as e:
            self._append_log(f"BLE 流程异常: {e!r}")
        finally:
            Clock.schedule_once(lambda dt: self._set_buttons_disabled(False), 0)

    async def _ble_flow(self):
        device = await self._discover_ble_target()
        if not device:
            self._append_log("未找到目标蓝牙设备")
            return

        self._append_log(f"发现设备 {device.address}，尝试连接")

        async with BleakClient(device.address, timeout=20.0) as client:
            self._append_log("蓝牙已连接，检查联网状态...")

            state = await self._read_status(client)
            if state.get("wifi_ok"):
                ip = state.get("ip") or state.get("addr")
                self._append_log(f"设备已联网 ip={ip or '<unknown>'}，直接绑定")
                if ip:
                    self._bind_host(ip, 5005)
                    Clock.schedule_once(lambda dt: self._auto_close_if_connected(), 0.2)
                return

            self._append_log("设备未联网，开始发送 Wi-Fi 配置")
            ok = await self._send_wifi_config(client)
            if not ok:
                self._append_log("配网写入失败")
                return

            await asyncio.sleep(1.0)
            state = await self._read_status(client)
            ip = state.get("ip") if state else None
            wifi_ok = state.get("wifi_ok") if state else False
            self._append_log(f"配网完成 wifi_ok={wifi_ok} ip={ip}")
            if wifi_ok and ip:
                self._bind_host(ip, 5005)
                Clock.schedule_once(lambda dt: self._auto_close_if_connected(), 0.4)
            else:
                self._append_log("未拿到 IP，请稍后在局域网扫描重试")

    async def _discover_ble_target(self):
        try:
            devices = await BleakScanner.discover(timeout=6)
            for d in devices:
                if TARGET_NAME.lower() in (d.name or "").lower():
                    return d
        except Exception as e:
            self._append_log(f"扫描失败: {e!r}")
        return None

    async def _read_status(self, client):
        try:
            services = await self._ensure_services(client)
            status_char = None
            for svc in services:
                if svc.uuid.lower() == SERVICE_UUID.lower():
                    for c in svc.characteristics:
                        if c.uuid.lower() == STATUS_CHAR_UUID.lower():
                            status_char = c
                            break
                if status_char:
                    break
            if status_char:
                raw = await client.read_gatt_char(status_char)
                return json.loads(raw.decode() or "{}") if raw else {}
        except Exception as e:
            self._append_log(f"读取状态失败: {e!r}")
        return {}

    async def _send_wifi_config(self, client):
        ssid = self.ssid_inp.text.strip()
        pwd = self.pwd_inp.text
        if not ssid or not pwd:
            self._append_log("请输入 Wi-Fi SSID 与密码")
            return False

        services = await self._ensure_services(client)
        wifi_char = None
        status_char = None
        for svc in services:
            if svc.uuid.lower() == SERVICE_UUID.lower():
                for c in svc.characteristics:
                    if c.uuid.lower() == CHAR_UUID.lower():
                        wifi_char = c
                    if c.uuid.lower() == STATUS_CHAR_UUID.lower():
                        status_char = c

        if not wifi_char:
            self._append_log("未找到配网特征值")
            return False

        data = json.dumps({"ssid": ssid, "password": pwd}).encode()
        self._append_log(f"发送配网数据 {len(data)} 字节")

        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + MAX_PACKET_SIZE]
            await client.write_gatt_char(wifi_char, chunk, response=False)
            offset += MAX_PACKET_SIZE
            await asyncio.sleep(0.05)

        if status_char:
            try:
                await asyncio.sleep(1.0)
                raw = await client.read_gatt_char(status_char)
                state = json.loads(raw.decode() or "{}") if raw else {}
                self._append_log(f"写入后状态 wifi_ok={state.get('wifi_ok')} ip={state.get('ip')}")
            except Exception as e:
                self._append_log(f"写后状态读取失败: {e!r}")
        return True

    async def _ensure_services(self, client):
        if hasattr(client, "get_services"):
            for attempt in range(3):
                try:
                    maybe_coro = client.get_services()
                    if asyncio.iscoroutine(maybe_coro):
                        await maybe_coro
                    return list(client.services or [])
                except Exception as e:
                    self._append_log(f"服务发现重试 {attempt+1}/3: {e!r}")
                    await asyncio.sleep(1.0)
        return list(client.services or [])

    # ------------------ 辅助 ------------------
    def _bind_host(self, host, port=None):
        ok = esp32_runtime.manual_bind_host(App.get_running_app(), host, port)
        if ok:
            self._append_log(f"已连接 {host}:{port or 5005}")
            Clock.schedule_once(lambda dt: self._update_close_state(), 0)
        else:
            self._append_log(f"发现 {host} 但连接失败")

    def _set_buttons_disabled(self, disabled):
        self.scan_btn.disabled = disabled
        self.ble_btn.disabled = disabled

    def _auto_close_if_connected(self):
        self._update_close_state()
        if self.popup and self._is_connected():
            self._append_log("检测到已连接，自动关闭弹窗")
            try:
                self.popup.dismiss()
            except Exception:
                pass

    def _append_log(self, msg: str):
        logger.info(msg)

        def _upd(_dt):
            prev = self.log_lbl.text or ""
            lines = (prev + "\n" + msg).strip().split("\n")
            self.log_lbl.text = "\n".join(lines[-10:])
            self.status_lbl.text = msg

        Clock.schedule_once(_upd, 0)


__all__ = ["Esp32SetupPopup"]
