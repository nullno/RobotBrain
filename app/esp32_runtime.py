"""ESP32 WiFi runtime适配层。

目标：
- 让现有 OTG/USB 调用在 WiFi 模式下保持兼容
- 自动发现/记忆 ESP32 主机，建立 ServoBus UDP 桥接
- 在连接成功时初始化 IMUReader + MotionController，供主循环和调试面板使用
"""
import os
import json
import time
from pathlib import Path

from services.servo_bus import ServoBus
from services.imu import IMUReader
from services.motion_controller import MotionController
from services import esp32_discovery, esp32_client
from widgets.runtime_status import RuntimeStatusLogger


def _config_path(app=None):
    try:
        base = Path(getattr(app, "user_data_dir", None) or "data")
    except Exception:
        base = Path("data")
    return base / "esp32_link.json"


def _load_saved_host(app=None):
    try:
        fp = _config_path(app)
        if fp.exists():
            with open(fp, "r", encoding="utf-8") as f:
                obj = json.load(f)
            host = obj.get("host")
            port = obj.get("port")
            if host:
                return str(host), int(port or 5005)
    except Exception:
        pass
    return None, None


def _save_host(app, host, port=None):
    try:
        fp = _config_path(app)
        fp.parent.mkdir(parents=True, exist_ok=True)
        data = {"host": str(host), "port": int(port or 5005), "ts": int(time.time())}
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def ensure_android_usb_reconnect_watcher(app, reason=""):
    # no-op for ESP32 network mode
    return


def is_duplicate_usb_attach_event(app, signature, interval_sec=4.0):
    return False


def handle_android_usb_attach_intent(app, source="resume"):
    # no-op
    return


def try_auto_connect(app, candidate_ports=None, list_ports_module=None, allow_discovery=True):
    """建立与 ESP32 的 UDP 连接：优先 candidate/env/记忆 -> 发现广播。"""
    host = None
    port = None

    if candidate_ports:
        host = candidate_ports[0]
    if not host:
        host = os.environ.get('ESP32_HOST')
        port_env = os.environ.get('ESP32_PORT')
        if port_env:
            port = int(port_env)
    if not host:
        host, port = _load_saved_host(app)

    # 最后尝试局域网广播发现
    if not host and allow_discovery:
        try:
            devices = esp32_discovery.discover(timeout=1.5)
            if devices:
                host = devices[0][0]
        except Exception:
            host = None

    try:
        if host:
            host_for_bus = f"{host}:{int(port)}" if port else host
            sb = ServoBus(port=host_for_bus)
            if sb and not getattr(sb, 'is_mock', True):
                try:
                    app.servo_bus = sb
                    app._esp32_host = host
                    app._esp32_port = int(port or getattr(sb, "_port", 5005))
                except Exception:
                    pass
                try:
                    esp32_client.set_host(host, port=port)
                except Exception:
                    pass
                try:
                    RuntimeStatusLogger.log_info(f"Connected to ESP32 servo bridge: {host}")
                except Exception:
                    pass
                _save_host(app, host, port or 5005)
                return True
    except Exception:
        pass
    try:
        RuntimeStatusLogger.log_error("未找到 ESP32，ServoBus 将以 MOCK 模式运行")
    except Exception:
        pass
    return False


def init_motion_controller_after_connect(app):
    try:
        imu = IMUReader(simulate=False)
        imu.start()
        try:
            app.imu_reader = imu
        except Exception:
            pass
        app.motion_controller = MotionController(
            app.servo_bus.manager if getattr(app, 'servo_bus', None) else None,
            balance_ctrl=getattr(app, 'balance_ctrl', None),
            imu_reader=imu,
            neutral_positions={},
        )
    except Exception:
        app.motion_controller = None


def schedule_servo_scan_after_connect(app, source="连接", allow_extra_retry=True):
    # no-op for ESP32 (ESP32 管理舵机总线)
    try:
        app._servo_scan_completed = True
    except Exception:
        pass


def handle_otg_event(app, event, device_id, list_ports_module=None):
    # no-op on network-based setup
    return
