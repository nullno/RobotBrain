"""ESP32 WiFi runtime适配层。

目标：
- 让现有 OTG/USB 调用在 WiFi 模式下保持兼容
- 自动发现/记忆 ESP32 主机，建立 ServoBus UDP 桥接
- 在连接成功时初始化 IMUReader + MotionController，供主循环和调试面板使用
"""
import os
import json
import time
import threading
from pathlib import Path

from services.servo_bus import ServoBus
from services.imu import IMUReader
from services.motion_controller import MotionController
from services.control_bridge import ControlBridge
from services import esp32_discovery, esp32_client, comm_config
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


def _update_control_bridge(app, host, port=None):
    """Align ControlBridge targets with the discovered ESP32."""
    try:
        ws_url = f"ws://{host}:8080/ws"
        bridge = getattr(app, "control_bridge", None)
        if bridge:
            bridge.set_udp_target(host, port)
            bridge.set_ws_url(ws_url)
            bridge.request_status()
            return True
        bridge = ControlBridge(udp_host=host, udp_port=int(port or 5005), ws_url=ws_url)
        bridge.start()
        try:
            app.control_bridge = bridge
        except Exception:
            pass
        return True
    except Exception:
        return False


def _connect_to_host(app, host, port=None, *, save=True, update_control_bridge=True):
    """Attempt to wire ServoBus/clients to a discovered host."""
    try:
        # Replace any existing ServoBus to avoid stale sockets
        old_sb = getattr(app, "servo_bus", None)
    except Exception:
        old_sb = None

    try:
        host_for_bus = f"{host}:{int(port)}" if port else host
        sb = ServoBus(port=host_for_bus)
        if sb and not getattr(sb, "is_mock", True):
            if old_sb and old_sb is not sb:
                try:
                    old_sb.close()
                except Exception:
                    pass
            try:
                app.servo_bus = sb
                app._esp32_host = host
                app._esp32_port = int(port or getattr(sb, "_port", 5005))
            except Exception:
                pass
            try:
                link = getattr(app, "esp32_link", None)
                if link:
                    link.set_host(host, port or getattr(sb, "_port", 5005))
            except Exception:
                pass
            try:
                esp32_client.set_host(host, port=port)
            except Exception:
                pass
            if update_control_bridge:
                _update_control_bridge(app, host, port or getattr(sb, "_port", 5005))
            try:
                RuntimeStatusLogger.log_info(f"Connected to ESP32 servo bridge: {host}")
            except Exception:
                pass
            try:
                app._enable_live_servo_sync = True
            except Exception:
                pass
            try:
                init_motion_controller_after_connect(app)
            except Exception:
                pass
            if save:
                _save_host(app, host, port or 5005)
            try:
                # Stop any pending background discovery since we are connected now
                stop_background_discovery(app)
            except Exception:
                pass
            return True
    except Exception:
        pass
    return False


def ensure_android_usb_reconnect_watcher(app, reason=""):
    # no-op for ESP32 network mode
    return


def is_duplicate_usb_attach_event(app, signature, interval_sec=4.0):
    return False


def handle_android_usb_attach_intent(app, source="resume"):
    # no-op
    return


def try_auto_connect(app, candidate_ports=None, list_ports_module=None, allow_discovery=True, allow_ble_provision=True, log_on_fail=True):
    """建立与 ESP32 的 UDP 连接：优先 candidate/env/记忆 -> 发现广播/蓝牙配网。"""
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

    if host and _connect_to_host(app, host, port):
        return True

    # 尝试蓝牙配网 + 再发现
    if allow_discovery and allow_ble_provision:
        try:
            host2, port2 = comm_config.auto_provision_and_discover(app, preferred_port=port or 5005)
            if host2 and _connect_to_host(app, host2, port2):
                return True
        except Exception:
            pass
    if log_on_fail:
        try:
            RuntimeStatusLogger.log_error("未找到 ESP32，ServoBus 将以 MOCK 模式运行")
        except Exception:
            pass
    return False


def manual_bind_host(app, host, port=None):
    """Bind to a host selected from UI (debug panel)."""
    if not host:
        return False
    # stop background discovery to avoid race while user is configuring
    try:
        stop_background_discovery(app)
    except Exception:
        pass
    return _connect_to_host(app, host, port or 5005, save=True, update_control_bridge=True)


def start_background_discovery(app, interval_sec: float = 5.0, max_attempts: int = 6, allow_ble_provision: bool = True):
    """Retry discovery/provisioning in the background until connected or attempts exhausted."""
    try:
        stop_ev = getattr(app, "_esp32_discovery_stop", None)
        if stop_ev is None:
            stop_ev = threading.Event()
            app._esp32_discovery_stop = stop_ev
        else:
            try:
                stop_ev.clear()
            except Exception:
                pass

        t = getattr(app, "_esp32_discovery_thread", None)
        if t and getattr(t, "is_alive", lambda: False)():
            return

        def _loop():
            attempts = 0
            while not stop_ev.is_set():
                if getattr(app, "servo_bus", None) and not getattr(app.servo_bus, "is_mock", True):
                    break
                if max_attempts and attempts >= max_attempts:
                    break
                ok = try_auto_connect(app, allow_discovery=True, allow_ble_provision=allow_ble_provision, log_on_fail=False)
                attempts += 1
                if ok and getattr(app, "servo_bus", None) and not getattr(app.servo_bus, "is_mock", True):
                    try:
                        RuntimeStatusLogger.log_info("后台自动发现 ESP32 成功")
                    except Exception:
                        pass
                    break
                stop_ev.wait(max(1.5, float(interval_sec or 5.0)))
            try:
                app._esp32_discovery_thread = None
            except Exception:
                pass

        t = threading.Thread(target=_loop, daemon=True)
        app._esp32_discovery_thread = t
        t.start()
    except Exception:
        try:
            RuntimeStatusLogger.log_error("后台发现任务启动失败")
        except Exception:
            pass


def stop_background_discovery(app):
    try:
        ev = getattr(app, "_esp32_discovery_stop", None)
        if ev:
            ev.set()
    except Exception:
        pass


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
