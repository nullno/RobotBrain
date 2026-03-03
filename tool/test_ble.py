import asyncio
import json
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout

from bleak import BleakScanner, BleakClient


# ================= CONFIG =================
TARGET_NAME = "ROBOT-ESP32-S3-BLE"

SERVICE_UUID = "0000ffaa-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffab-0000-1000-8000-00805f9b34fb"
STATUS_CHAR_UUID = "0000ffac-0000-1000-8000-00805f9b34fb"

MAX_PACKET_SIZE = 96
# ==========================================


KV = """
<MainUI>:
    orientation: "vertical"
    padding: 10
    spacing: 10

    Label:
        text: "ESP32 BLE Provision Tool"
        size_hint_y: None
        height: 40
        font_size: 20

    Button:
        text: "Scan Device"
        size_hint_y: None
        height: 40
        on_press: root.start_scan()

    Label:
        id: device_label
        text: "Device not found"
        size_hint_y: None
        height: 40

    TextInput:
        id: ssid_input
        hint_text: "WiFi SSID"
        multiline: False
        size_hint_y: None
        height: 40

    TextInput:
        id: pwd_input
        hint_text: "WiFi Password"
        password: True
        multiline: False
        size_hint_y: None
        height: 40

    Button:
        text: "Send WiFi Config"
        size_hint_y: None
        height: 40
        on_press: root.start_provision()

    TextInput:
        id: log_output
        text: root.log_text
        readonly: True
"""


class MainUI(BoxLayout):
    log_text = StringProperty("")
    device_address = None

    # ========= Thread-safe log =========
    def log(self, message):
        Clock.schedule_once(lambda dt: self._append_log(message))

    def _append_log(self, message):
        self.log_text += message + "\n"

    # ========= Scan =========
    def start_scan(self):
        self.log("Scanning...")
        threading.Thread(target=self.scan_thread, daemon=True).start()

    def scan_thread(self):
        asyncio.run(self.scan_ble())

    async def scan_ble(self):
        try:
            devices = await BleakScanner.discover(timeout=6)

            found = False
            for d in devices:
                if TARGET_NAME.lower() in (d.name or "").lower():
                    self.device_address = d.address
                    found = True

                    Clock.schedule_once(
                        lambda dt: self.ids.device_label.setter("text")(
                            self.ids.device_label,
                            f"Found: {d.address}"
                        )
                    )

                    self.log(f"Target device found: {d.name} {d.address}")
                    break

            if not found:
                self.log("Target device not found.")

        except Exception as e:
            self.log(f"Scan failed: {repr(e)}")

    # ========= Provision =========
    def start_provision(self):
        threading.Thread(target=self.provision_thread, daemon=True).start()

    def provision_thread(self):
        asyncio.run(self.provision_ble())

    async def provision_ble(self):
        if not self.device_address:
            self.log("Please scan device first.")
            return

        ssid = self.ids.ssid_input.text
        password = self.ids.pwd_input.text

        if not ssid or not password:
            self.log("Please enter WiFi credentials.")
            return

        try:
            self.log("Connecting...")

            async with BleakClient(self.device_address, timeout=15.0) as client:

                self.log("Connected.")

                # ===== 连接后等待设备准备好，再做服务发现 =====
                await asyncio.sleep(1.0)

                # ===== 服务发现重试 =====
                services_ready = False
                for attempt in range(3):
                    try:
                        await client.get_services()
                        services_ready = True
                        break
                    except Exception as e:
                        self.log(f"get_services retry {attempt+1}/3: {repr(e)}")
                        await asyncio.sleep(1.0)

                if not services_ready:
                    self.log("Service discovery failed after retries.")
                    return

                self.log("Discovering services...")

                wifi_char = None
                status_char = None

                for service in client.services:
                    if service.uuid.lower() == SERVICE_UUID.lower():
                        self.log(f"Service found: {service.uuid}")

                        for c in service.characteristics:
                            self.log(f"Char: {c.uuid} | {c.properties}")

                            if c.uuid.lower() == CHAR_UUID.lower():
                                wifi_char = c
                            if c.uuid.lower() == STATUS_CHAR_UUID.lower():
                                status_char = c

                if not wifi_char:
                    self.log("Target characteristic not found.")
                    return

                if status_char:
                    try:
                        raw = await client.read_gatt_char(status_char)
                        state = json.loads(raw.decode() or "{}") if raw else {}
                        if state.get("wifi_ok"):
                            ip = state.get("ip") or "<unknown>"
                            self.log(f"Device already online (ip={ip}), skip provisioning.")
                            return
                        self.log("Device not online, continue provisioning.")
                    except Exception as e:
                        self.log(f"Read wifi status failed: {repr(e)}")

                self.log("Characteristic ready.")

                config = {
                    "ssid": ssid,
                    "password": password
                }

                data = json.dumps(config).encode()
                self.log(f"Sending {len(data)} bytes")

                # ===== 判断写入方式 =====
                # Windows + MicroPython 可能长写超时，强制用无响应写
                use_response = False
                self.log(f"Using response mode: {use_response}")

                # ===== 分包发送 =====
                offset = 0
                while offset < len(data):
                    chunk = data[offset:offset + MAX_PACKET_SIZE]

                    await client.write_gatt_char(
                        wifi_char,
                        chunk,
                        response=use_response
                    )

                    offset += MAX_PACKET_SIZE
                    await asyncio.sleep(0.05)

                # 可选：再次读取状态
                if status_char:
                    try:
                        await asyncio.sleep(1.0)
                        raw = await client.read_gatt_char(status_char)
                        state = json.loads(raw.decode() or "{}") if raw else {}
                        self.log(f"After write wifi_ok={state.get('wifi_ok')} ip={state.get('ip')}")
                    except Exception as e:
                        self.log(f"Post-check failed: {repr(e)}")

                self.log("WiFi config sent successfully.")
                await asyncio.sleep(3)
                self.log("Provision process completed.")

        except Exception as e:
            self.log(f"Provision failed: {repr(e)}")


class BLEApp(App):
    def build(self):
        Builder.load_string(KV)
        return MainUI()


if __name__ == "__main__":
    BLEApp().run()