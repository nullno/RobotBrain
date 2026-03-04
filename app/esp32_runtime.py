"""ESP32 WiFi runtime 适配层。

通过 wifi_servo 模块与 ESP32 通信（UDP 协议），管理连接生命周期。
"""
import os
import threading
import logging

from services.wifi_servo import (
    WiFiServoController, init_controller, get_controller,
    save_host, load_host, udp_discover,
)
from services.imu import IMUReader
from services.motion_controller import MotionController
from widgets.runtime_status import RuntimeStatusLogger

logger = logging.getLogger(__name__)


# ────────────────── 连接管理 ──────────────────

def _connect_to_host(app, host: str, port: int = 5005, *, save: bool = True) -> bool:
    """初始化 wifi_servo 控制器并绑定到 app。"""
    try:
        ctrl = init_controller(host, int(port or 5005))
        app.wifi_servo = ctrl
        app._esp32_host = host
        app._esp32_port = int(port or 5005)
        # live servo sync 默认保持当前值，不强制打开，避免在未调试时高频发送
        RuntimeStatusLogger.log_info(f"已连接 ESP32: {host}:{port}")
        init_motion_controller_after_connect(app)
        if save:
            save_host(host, port, app)
        stop_background_discovery(app)
        return True
    except Exception as e:
        logger.warning("连接 ESP32 失败: %s", e)
    return False


def try_auto_connect(app, candidate_ports=None, list_ports_module=None,
                     allow_discovery=True, allow_ble_provision=False,
                     log_on_fail=True) -> bool:
    """自动连接 ESP32：环境变量 → 已保存主机 → UDP 发现。"""
    host, port = None, 5005

    # 1. candidate / env
    if candidate_ports:
        host = candidate_ports[0]
    if not host:
        host = os.environ.get("ESP32_HOST")
        p = os.environ.get("ESP32_PORT")
        if p:
            port = int(p)

    # 2. 已保存主机
    if not host:
        host, port = load_host(app)

    # 3. UDP 广播发现
    if not host and allow_discovery:
        try:
            found = udp_discover(timeout=1.5)
            if found:
                host = found[0][0]
        except Exception:
            pass

    if host and _connect_to_host(app, host, port):
        return True

    if log_on_fail:
        RuntimeStatusLogger.log_error("未找到 ESP32")
    return False


def manual_bind_host(app, host: str, port: int = 5005) -> bool:
    """手动绑定主机（调试面板使用）。"""
    if not host:
        return False
    stop_background_discovery(app)
    return _connect_to_host(app, host, port or 5005, save=True)


# ────────────────── 后台发现 ──────────────────

def start_background_discovery(app, interval_sec: float = 5.0, max_attempts: int = 6,
                               allow_ble_provision: bool = False):
    """后台定时重试 UDP 发现。"""
    stop_ev = getattr(app, "_esp32_discovery_stop", None)
    if stop_ev is None:
        stop_ev = threading.Event()
        app._esp32_discovery_stop = stop_ev
    else:
        stop_ev.clear()

    t = getattr(app, "_esp32_discovery_thread", None)
    if t and t.is_alive():
        return

    def _loop():
        for attempt in range(max_attempts):
            if stop_ev.is_set():
                break
            ctrl = get_controller()
            if ctrl and ctrl.is_connected:
                break
            if try_auto_connect(app, allow_discovery=True, log_on_fail=False):
                RuntimeStatusLogger.log_info("后台发现 ESP32 成功")
                break
            stop_ev.wait(max(1.5, interval_sec))
        app._esp32_discovery_thread = None

    t = threading.Thread(target=_loop, daemon=True)
    app._esp32_discovery_thread = t
    t.start()


def stop_background_discovery(app):
    ev = getattr(app, "_esp32_discovery_stop", None)
    if ev:
        ev.set()


# ────────────────── 运动控制器 ──────────────────

def init_motion_controller_after_connect(app):
    """连接成功后初始化 IMU + MotionController。"""
    try:
        imu = IMUReader(simulate=False)
        imu.start()
        app.imu_reader = imu
        app.motion_controller = MotionController(
            servo_manager=None,
            balance_ctrl=getattr(app, "balance_ctrl", None),
            imu_reader=imu,
            neutral_positions={},
        )
    except Exception as e:
        logger.warning("MotionController 初始化失败: %s", e)
        app.motion_controller = None


# ────────────────── 兼容 stubs ──────────────────

def ensure_android_usb_reconnect_watcher(app, reason=""):
    pass

def is_duplicate_usb_attach_event(app, signature, interval_sec=4.0):
    return False

def handle_android_usb_attach_intent(app, source="resume"):
    pass

def schedule_servo_scan_after_connect(app, source="连接", allow_extra_retry=True):
    try:
        app._servo_scan_completed = True
    except Exception:
        pass

def handle_otg_event(app, event, device_id, list_ports_module=None):
    pass
