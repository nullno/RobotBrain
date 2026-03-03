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
TARGET_NAME = "ROBOT-ROBOT-ESP32-S3-BLE"

SERVICE_UUID = "0000ffaa-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffab-0000-1000-8000-00805f9b34fb"
STATUS_UUID = "0000ffac-0000-1000-8000-00805f9b34fb"

MAX_PACKET_SIZE = 180
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

    Button:
        text: "Check WiFi Status"
        size_hint_y: None
        height: 40
        on_press: root.start_check_status()

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
        devices = await BleakScanner.discover(timeout=6)

        for d in devices:
            if d.name == TARGET_NAME:
                self.device_address = d.address
                Clock.schedule_once(
                    lambda dt: self.ids.device_label.setter("text")(
                        self.ids.device_label,
                        f"Found: {TARGET_NAME} ({d.address})"
                    )
                )
                self.log("Target device found.")
                return

        self.log("Target device not found.")

    # ========= Check WiFi Status =========
    def start_check_status(self):
        threading.Thread(target=self.status_thread, daemon=True).start()

    def status_thread(self):
        asyncio.run(self.check_status())

    async def check_status(self):
        if not self.device_address:
            self.log("Scan device first.")
            return

        try:
            async with BleakClient(self.device_address) as client:
                await client.get_services()

                data = await client.read_gatt_char(STATUS_UUID)
                status = data.decode().strip()

                self.log(f"WiFi Status: {status}")

                if status == "CONNECTED":
                    self.log("Device already connected to WiFi.")
                else:
                    self.log("Device not connected.")

        except Exception as e:
            self.log(f"Status check failed: {repr(e)}")

    # ========= Provision =========
    def start_provision(self):
        threading.Thread(target=self.provision_thread, daemon=True).start()

    def provision_thread(self):
        asyncio.run(self.provision_ble())

    async def provision_ble(self):
        if not self.device_address:
            self.log("Scan device first.")
            return

        ssid = self.ids.ssid_input.text
        password = self.ids.pwd_input.text

        try:
            async with BleakClient(self.device_address) as client:
                await client.get_services()

                config = {
                    "ssid": ssid,
                    "password": password
                }

                data = json.dumps(config).encode()

                offset = 0
                while offset < len(data):
                    chunk = data[offset:offset + MAX_PACKET_SIZE]
                    await client.write_gatt_char(
                        CHAR_UUID,
                        chunk,
                        response=True
                    )
                    offset += MAX_PACKET_SIZE
                    await asyncio.sleep(0.05)

                self.log("WiFi config sent.")

        except Exception as e:
            self.log(f"Provision failed: {repr(e)}")


class BLEApp(App):
    def build(self):
        Builder.load_string(KV)
        return MainUI()


if __name__ == "__main__":
    BLEApp().run()