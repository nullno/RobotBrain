"""
Bluetooth (BLE) Wi-Fi provisioning helper.
- Scans for an ESP32 advertising a given name or service UUID.
- Writes SSID/password to a characteristic for provisioning.

This module is safe to import even when `bleak` is unavailable; callers should
check the return status and message for feedback.
"""
import asyncio
import os
from typing import Optional, Tuple

try:
    from bleak import BleakClient, BleakScanner
except Exception:  # pragma: no cover - optional dependency
    BleakClient = None
    BleakScanner = None

DEFAULT_NAME = os.environ.get("ESP32_BLE_NAME", "ESP32-PROV")
WIFI_SERVICE_UUID = os.environ.get("ESP32_WIFI_SERVICE_UUID", "0000ffaa-0000-1000-8000-00805f9b34fb")
WIFI_CHAR_UUID = os.environ.get("ESP32_WIFI_CHAR_UUID", "0000ffab-0000-1000-8000-00805f9b34fb")


async def _provision_async(ssid: str, password: str, target_name: str = DEFAULT_NAME) -> Tuple[bool, str]:
    if BleakScanner is None or BleakClient is None:
        return False, "bleak not installed; skip BLE provisioning"
    devices = await BleakScanner.discover(timeout=5.0)
    target = None
    for dev in devices:
        if target_name.lower() in (dev.name or "").lower():
            target = dev
            break
    if target is None:
        return False, f"device named {target_name} not found"

    payload = f"{ssid}\n{password}".encode("utf-8")
    async with BleakClient(target) as client:
        await client.write_gatt_char(WIFI_CHAR_UUID, payload, response=True)
    return True, f"sent Wi-Fi creds to {target.address}"


def send_wifi_credentials(ssid: str, password: str, target_name: str = DEFAULT_NAME) -> Tuple[bool, str]:
    ssid = (ssid or "").strip()
    password = password or ""
    if not ssid:
        return False, "SSID is required"
    try:
        return asyncio.run(_provision_async(ssid, password, target_name=target_name))
    except RuntimeError:
        # Already inside an event loop (e.g., on Android); create a new loop in thread
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ok, msg = loop.run_until_complete(_provision_async(ssid, password, target_name=target_name))
            loop.close()
            return ok, msg
        except Exception as exc:  # pragma: no cover - defensive
            return False, f"BLE provision failed: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"BLE provision failed: {exc}"


__all__ = ["send_wifi_credentials"]
