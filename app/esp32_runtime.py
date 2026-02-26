"""
ESP32 runtime shim to replace usb_runtime for network-based servo control.
Provides minimal functions used by `app_root.py` and other modules so existing calls remain safe.
"""
import os
import time
from services.servo_bus import ServoBus
from services.imu import IMUReader
from services.motion_controller import MotionController
from widgets.runtime_status import RuntimeStatusLogger


def ensure_android_usb_reconnect_watcher(app, reason=""):
    # no-op for ESP32 network mode
    return


def is_duplicate_usb_attach_event(app, signature, interval_sec=4.0):
    return False


def handle_android_usb_attach_intent(app, source="resume"):
    # no-op
    return


def try_auto_connect(app, candidate_ports=None, list_ports_module=None):
    # Try to create a ServoBus pointing to ESP32 host
    host = os.environ.get('ESP32_HOST')
    if candidate_ports:
        # allow explicit host
        host = candidate_ports[0]
    try:
        if host:
            sb = ServoBus(port=host)
            if sb and not getattr(sb, 'is_mock', True):
                try:
                    app.servo_bus = sb
                except Exception:
                    pass
                try:
                    RuntimeStatusLogger.log_info(f"Connected to ESP32 servo bridge: {host}")
                except Exception:
                    pass
                return True
    except Exception:
        pass
    return False


def init_motion_controller_after_connect(app):
    try:
        imu = IMUReader(simulate=False)
        imu.start()
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
