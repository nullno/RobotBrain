"""
BLE 配网助手。
- 扫描指定名称的 ESP32-S3 设备；
- 写入 Wi-Fi SSID/密码到特定特征值。

即使缺少 bleak 依赖也能安全导入，返回值包含失败原因。
"""
import asyncio
import logging
import os
from typing import Optional, Tuple

try:
    from bleak import BleakClient, BleakScanner
except Exception:  # pragma: no cover - 可选依赖
    BleakClient = None
    BleakScanner = None

DEFAULT_NAME = os.environ.get("ESP32_BLE_NAME", "ROBOT-ROBOT-ESP32-S3-BLE")
WIFI_SERVICE_UUID = os.environ.get("ESP32_WIFI_SERVICE_UUID", "0000ffaa-0000-1000-8000-00805f9b34fb")
WIFI_CHAR_UUID = os.environ.get("ESP32_WIFI_CHAR_UUID", "0000ffab-0000-1000-8000-00805f9b34fb")

logger = logging.getLogger(__name__)


def _mask_password(pwd: str) -> str:
    """仅显示长度，避免日志暴露明文。"""
    if not pwd:
        return "(空)"
    return f"*** 共{len(pwd)}位"


async def _provision_async(ssid: str, password: str, target_name: str = DEFAULT_NAME) -> Tuple[bool, str]:
    if BleakScanner is None or BleakClient is None:
        msg = "未安装 bleak，无法执行 BLE 配网"
        logger.warning(msg)
        return False, msg

    logger.info("BLE 配网开始，目标名称=%s，SSID=%s，密码=%s", target_name, ssid, _mask_password(password))
    devices = await BleakScanner.discover(timeout=5.0)
    logger.info("BLE 扫描结果 %d 个设备", len(devices))

    target = None
    for dev in devices:
        logger.info("发现设备 name=%s addr=%s", dev.name, dev.address)
        if target_name.lower() in (dev.name or "").lower():
            target = dev
            break

    if target is None:
        msg = f"未找到名称包含 {target_name} 的设备"
        logger.warning(msg)
        return False, msg

    payload = f"{ssid}\n{password}".encode("utf-8")
    logger.info("连接设备 %s，写入 Wi-Fi 信息", target.address)
    async with BleakClient(target) as client:
        await client.write_gatt_char(WIFI_CHAR_UUID, payload, response=True)
    msg = f"已发送 Wi-Fi 信息到 {target.address}"
    logger.info(msg)
    return True, msg


def send_wifi_credentials(ssid: str, password: str, target_name: str = DEFAULT_NAME) -> Tuple[bool, str]:
    ssid = (ssid or "").strip()
    password = password or ""
    if not ssid:
        msg = "SSID 不能为空"
        logger.warning(msg)
        return False, msg
    logger.info("准备向 BLE 设备写入 Wi-Fi，目标=%s，SSID=%s，密码=%s", target_name, ssid, _mask_password(password))
    try:
        return asyncio.run(_provision_async(ssid, password, target_name=target_name))
    except RuntimeError:
        # 已在事件循环内（如 Android），新建 loop 在当前线程执行
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ok, msg = loop.run_until_complete(_provision_async(ssid, password, target_name=target_name))
            loop.close()
            return ok, msg
        except Exception as exc:  # pragma: no cover - 防御
            logger.error("BLE 配网失败: %s", exc)
            return False, f"BLE 配网失败: {exc}"
    except Exception as exc:  # pragma: no cover - 防御
        logger.error("BLE 配网失败: %s", exc)
        return False, f"BLE 配网失败: {exc}"


__all__ = ["send_wifi_credentials"]
