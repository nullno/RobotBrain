import logging
import pathlib
import threading

from kivy.clock import Clock
from kivy.utils import platform

from widgets.runtime_status import RuntimeStatusLogger
from services.servo_bus import ServoBus
from services.balance_ctrl import BalanceController
from services.motion_controller import MotionController
from services.imu import IMUReader
from services.neutral import load_neutral
from services import usb_otg


def init_android_permissions(app):
    if platform != "android":
        return
    try:
        from android.permissions import request_permissions, Permission, check_permission

        Clock.schedule_once(lambda dt: app.update_android_flags(), 0)

        required_perms = [
            Permission.CAMERA,
            Permission.WRITE_EXTERNAL_STORAGE,
            Permission.READ_EXTERNAL_STORAGE,
        ]

        missing_perms = []
        for perm in required_perms:
            try:
                if not check_permission(perm):
                    missing_perms.append(perm)
            except Exception:
                missing_perms.append(perm)

        if missing_perms:
            def _perm_callback(permissions, results):
                if all(results):
                    print("✅ 所有权限申请成功")
                else:
                    missing = [p for p, r in zip(permissions, results) if not r]
                    print(f"⚠ 未授予权限: {missing}，部分功能可能受限")

            request_permissions(missing_perms, _perm_callback)
        else:
            print("✅ 所有权限已获得")
    except Exception as e:
        print(f"⚠ Android platform init failed: {e}")


def init_servo_bus(app):
    app.servo_bus = None
    if platform == "android":
        try:
            from services.android_serial import (
                open_first_usb_serial,
                get_last_usb_serial_status,
            )
            usb_wrapper = open_first_usb_serial(baud=115200)
            if usb_wrapper:
                app.servo_bus = ServoBus(port=usb_wrapper)
                app._mark_usb_connected_after_permission(
                    get_last_usb_serial_status()
                )
                RuntimeStatusLogger.log_info("启动时 USB 串口已连接，开始扫描舵机")
                app._schedule_servo_scan_after_connect("启动")
            else:
                _s = str(get_last_usb_serial_status())
                if _s.startswith("wait:"):
                    app._last_usb_permission_status = _s
                    app._update_usb_state(
                        detect="device",
                        auth="wait",
                        connect="down",
                        detail=_s,
                    )
                    RuntimeStatusLogger.log_info(
                        f"启动时检测到 USB 设备，正在等待授权: {_s}"
                    )
                    app._ensure_android_usb_reconnect_watcher("启动等待授权")
                else:
                    app._update_usb_state(
                        detect="nodevice",
                        auth="idle",
                        connect="down",
                        detail=_s,
                    )
                    RuntimeStatusLogger.log_info(
                        f"启动时 Android USB Serial 未连接: {_s}"
                    )
        except Exception as e:
            print(f"Android USB Serial init failed: {e}")

    if not app.servo_bus:
        try:
            dev_port = "/dev/ttyUSB0" if platform == "android" else "COM8"
            app._dev_port = dev_port
            app.servo_bus = ServoBus(port=dev_port)
            if app.servo_bus and not getattr(app.servo_bus, "is_mock", True):
                RuntimeStatusLogger.log_info(f"启动时串口已连接: {dev_port}，开始扫描舵机")
                app._schedule_servo_scan_after_connect("启动")
        except Exception as e:
            print(f"❌ 串口初始化失败: {e}")
            app.servo_bus = None

    try:
        if not app.servo_bus or getattr(app.servo_bus, "is_mock", True):
            app._try_auto_connect()
    except Exception:
        pass


def init_logging(app):
    try:
        if platform == "android":
            log_dir = pathlib.Path(app.user_data_dir) / "logs"
        else:
            log_dir = pathlib.Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            filename=str(log_dir / "robot_dashboard.log"),
            filemode="a",
            format="%(asctime)s %(levelname)s: %(message)s",
        )
        logging.info("App starting")
        try:
            class _ForwardHandler(logging.Handler):
                _local = threading.local()

                def emit(self, record):
                    if getattr(self._local, "busy", False):
                        return
                    try:
                        self._local.busy = True
                        msg = self.format(record)
                        if RuntimeStatusLogger:
                            if record.levelno >= logging.ERROR:
                                RuntimeStatusLogger.log(msg, "error")
                            else:
                                RuntimeStatusLogger.log(msg, "info")
                    except Exception:
                        pass
                    finally:
                        try:
                            self._local.busy = False
                        except Exception:
                            pass

            fh = _ForwardHandler()
            fh.setLevel(logging.INFO)
            logging.getLogger().addHandler(fh)
        except Exception:
            pass

        try:
            import sys

            class _StdForward:
                def __init__(self, level="info"):
                    self._level = level

                def write(self, s):
                    try:
                        s = s.strip()
                        if not s:
                            return
                        if self._level == "error":
                            logging.getLogger().error(s)
                        else:
                            logging.getLogger().info(s)
                    except Exception:
                        pass

                def flush(self):
                    pass

            sys.stdout = _StdForward("info")
            sys.stderr = _StdForward("error")
        except Exception:
            pass
    except Exception:
        pass


def init_balance_and_gyro(app):
    neutral_raw = load_neutral() or {}
    try:
        neutral = {int(k): int(v) for k, v in neutral_raw.items()}
    except Exception:
        neutral = {i: 2048 for i in range(1, 26)}

    app.balance_ctrl = BalanceController(neutral, is_landscape=True)
    try:
        app.load_balance_tuning()
    except Exception:
        pass

    try:
        app._setup_gyroscope()
    except Exception:
        pass

    return neutral


def init_motion_controller(app, neutral):
    try:
        if app.servo_bus and not getattr(app.servo_bus, "is_mock", True):
            imu = IMUReader(simulate=False)
            imu.start()
            app.motion_controller = MotionController(
                app.servo_bus.manager,
                balance_ctrl=app.balance_ctrl,
                imu_reader=imu,
                neutral_positions=neutral,
            )
        else:
            app.motion_controller = None
    except Exception:
        logging.exception("MotionController init failed")
        app.motion_controller = None


def init_runtime_loops(app):
    app._demo_step = 0
    Clock.schedule_interval(app._update_loop, 0.1)
    Clock.schedule_interval(app._demo_emotion_loop, 4.0)
    Clock.schedule_interval(app._demo_eye_move, 0.05)

    app._last_loop_error = None
    app._last_loop_error_time = 0
    app._latest_pitch = 0.0
    app._latest_roll = 0.0
    app._latest_yaw = 0.0


def init_runtime_status_panel(app):
    try:
        runtime_status_panel = app.root_widget.ids.runtime_status
        RuntimeStatusLogger.set_panel(runtime_status_panel)
        RuntimeStatusLogger.log_info("应用启动成功")
    except Exception as e:
        print(f"⚠ 运行状态面板初始化失败: {e}")


def start_permission_and_otg_watchers(app):
    Clock.schedule_once(lambda dt: app._start_permission_watcher(), 0.6)

    try:
        usb_otg.start_monitor()
        RuntimeStatusLogger.log_info("串口/OTG 监测已启动")
        try:
            usb_otg.register_device_callback(app._on_otg_event)
        except Exception:
            pass
    except Exception as e:
        try:
            RuntimeStatusLogger.log_error(f"OTG 监测启动失败: {e}")
        except Exception:
            print(f"OTG 监测启动失败: {e}")
