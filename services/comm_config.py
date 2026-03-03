"""Communication configuration utilities.

Responsibilities
- Load/save Wi-Fi + BLE provisioning config from data/comm_config.json (or app user_data_dir).
- Optionally push Wi-Fi credentials to ESP32 over BLE.
- Discover ESP32 on LAN after provisioning.
- Keep logic small and synchronous for use during startup.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from services import esp32_discovery
from services.ble_provisioner import DEFAULT_NAME as DEFAULT_BLE_NAME
from services.ble_provisioner import send_wifi_credentials

logger = logging.getLogger(__name__)


def _config_path(app=None) -> Path:
    try:
        base = Path(getattr(app, "user_data_dir", None) or "data")
    except Exception:
        base = Path("data")
    return base / "comm_config.json"


def ensure_template(app=None) -> Path:
    """Create a template config if missing for users to fill in Wi-Fi info."""
    path = _config_path(app)
    if path.exists():
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "ssid": "",
                    "password": "",
                    "ble_name": DEFAULT_BLE_NAME,
                    "udp_port": 5005,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info("Created comm_config template at %s", path)
    except Exception as exc:
        logger.debug("Failed to create comm_config template: %s", exc)
    return path


def load_comm_config(app=None) -> Dict[str, object]:
    path = _config_path(app)
    if not path.exists():
        ensure_template(app)
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data or {}
    except Exception as exc:
        logger.warning("Failed to load comm_config.json: %s", exc)
        return {}


def _local_lan_ip() -> Optional[str]:
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return None


def _ensure_lan_ready() -> bool:
    ip = _local_lan_ip()
    if not ip:
        logger.warning("No LAN IP detected; ensure PC/phone is connected to Wi-Fi")
        return False
    logger.info("Detected LAN IP %s", ip)
    return True


def auto_provision_and_discover(app=None, preferred_port: int = 5005) -> Tuple[Optional[str], Optional[int]]:
    """Send Wi-Fi credentials via BLE then try LAN discovery.

    Returns (host, port) if a device is discovered, otherwise (None, None).
    """
    cfg = load_comm_config(app)
    ssid = os.environ.get("ROBOT_WIFI_SSID") or str(cfg.get("ssid", "")).strip()
    password = os.environ.get("ROBOT_WIFI_PASSWORD") or str(cfg.get("password", ""))
    ble_name = os.environ.get("ESP32_BLE_NAME") or cfg.get("ble_name") or DEFAULT_BLE_NAME
    udp_port = int(cfg.get("udp_port") or preferred_port or 5005)

    if not ssid:
        logger.info("Wi-Fi SSID not configured; fill in comm_config.json to enable BLE provisioning")
        return None, None

    logger.info("开始 BLE 配网流程，目标名称=%s，SSID=%s", ble_name, ssid)

    _ensure_lan_ready()

    ok, msg = send_wifi_credentials(ssid, password, target_name=str(ble_name))
    if ok:
        logger.info("BLE 配网成功: %s", msg)
    else:
        logger.warning("BLE 配网失败: %s", msg)
        return None, None

    # Give ESP32 a moment to join Wi-Fi before discovery
    time.sleep(1.5)

    try:
        devices = esp32_discovery.discover(timeout=2.0)
        logger.info("发现结果 %d 条: %s", len(devices), devices)
        if devices:
            host = devices[0][0]
            logger.info("BLE 配网后发现 ESP32: %s:%s", host, udp_port)
            return host, udp_port
    except Exception as exc:
        logger.warning("BLE 配网后局域网发现失败: %s", exc)
    return None, None


__all__ = [
    "auto_provision_and_discover",
    "load_comm_config",
    "ensure_template",
    "save_comm_config",
]


def save_comm_config(data: Dict[str, object], app=None) -> bool:
    """Persist communication config to disk.

    Returns True on success. Creates parent directories if needed.
    """
    try:
        path = _config_path(app)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data or {}, f, ensure_ascii=False, indent=2)
        logger.info("Saved comm_config to %s", path)
        return True
    except Exception as exc:
        logger.warning("Failed to save comm_config.json: %s", exc)
        return False
