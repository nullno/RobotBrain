from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.utils import platform
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from widgets.startup_tip import StartupTip
import random
import math
import os
import sys
import subprocess
import json
import threading
import time

from widgets.camera_view import CameraView
from widgets.robot_face import RobotFace
from widgets.gyro_panel import GyroPanel
from widgets.debug_panel import DebugPanel
from widgets.servo_status import ServoStatus
from widgets.runtime_status import RuntimeStatusPanel, RuntimeStatusLogger
from services.servo_bus import ServoBus
from services.balance_ctrl import BalanceController
from services.motion_controller import MotionController
from services.imu import IMUReader
from services.neutral import load_neutral
from services import usb_otg

try:
    # 用于枚举串口设备以便自动检测 CH340 等适配器
    from serial.tools import list_ports as _list_ports
except Exception:
    _list_ports = None
# AICore 暂时禁用，注释掉导入
# from services.ai_core import AICore
import logging
import pathlib
import traceback

try:
    # 仅在 Android 平台尝试延迟导入 plyer.gyroscope，避免在 Windows/macOS 上触发
    # 因为 plyer 在某些平台上会尝试导入不存在的子模块（如 plyer.platforms.win.gyroscope）
    if platform == "android":
        try:
            import importlib

            gyroscope = importlib.import_module("plyer.gyroscope")
        except ModuleNotFoundError:
            gyroscope = None
        except Exception:
            gyroscope = None
    else:
        gyroscope = None
except Exception:
    gyroscope = None


if platform == 'android':
    try:
        from android.runnable import run_on_ui_thread
    except ImportError:
        def run_on_ui_thread(f):
            return f
else:
    def run_on_ui_thread(f):
        return f


class RobotDashboardApp(App):
    def on_start(self):
        if platform == 'android':
            Clock.schedule_once(lambda dt: self.update_android_flags(), 0)

    def on_resume(self):
        if platform == 'android':
            Clock.schedule_once(lambda dt: self.update_android_flags(), 0)

    @run_on_ui_thread
    def update_android_flags(self):
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            View = autoclass("android.view.View")
            window = activity.getWindow()
            decor_view = window.getDecorView()

            # 组合标志位: 全屏 + 隐藏导航栏 + 沉浸模式 + 内容延伸且稳定
            flags = (
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE |
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION |
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN |
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                View.SYSTEM_UI_FLAG_FULLSCREEN |
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            )
            decor_view.setSystemUiVisibility(flags)

            # 适配刘海屏/挖孔屏 (Android 9.0+, API 28+)
            # Build.VERSION 可能无法直接访问，需使用 $VERSION 内部类
            VERSION = autoclass("android.os.Build$VERSION")
            if VERSION.SDK_INT >= 28:
                LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
                # LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES = 1
                # 显式获取常量，确保兼容性
                try:
                    layout_mode = LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
                except Exception:
                    layout_mode = 1                
                
                params = window.getAttributes()
                params.layoutInDisplayCutoutMode = layout_mode
                window.setAttributes(params)
        except Exception as e:
            print(f"⚠️ Android UI Flags 设置失败: {e}")

    def build(self):
        # Android权限申请
        if platform == "android":
            try:
                from jnius import autoclass
                from android.permissions import (
                    request_permissions,
                    Permission,
                    check_permission,
                )

                # 初始化 UI 状态 (全屏、沉浸式、挖孔屏适配)
                Clock.schedule_once(lambda dt: self.update_android_flags(), 0)

                # 检查并请求权限
                required_perms = [
                    Permission.CAMERA,
                    Permission.WRITE_EXTERNAL_STORAGE,
                    Permission.READ_EXTERNAL_STORAGE,
                ]

                # 检查缺失的权限
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
                            print(f"⚠️ 未授予权限: {missing}，部分功能可能受限")

                    request_permissions(missing_perms, _perm_callback)
                else:
                    print("✅ 所有权限已获得")
            except Exception as e:
                print(f"⚠️ Android platform init failed: {e}")
                # Log to RuntimeStatusLogger if available later, but for now just print
                pass

        Builder.load_file("kv/style.kv")
        self.root_widget = Builder.load_file("kv/root.kv")

        # ---------- 硬件 ----------
        # 优先尝试连接硬件，Android 平台特殊处理
        self.servo_bus = None
        if platform == "android":
            try:
                # 尝试通过 USB Serial 库连接
                from services.android_serial import open_first_usb_serial
                usb_wrapper = open_first_usb_serial(baud=115200)
                if usb_wrapper:
                     self.servo_bus = ServoBus(port=usb_wrapper)
                     RuntimeStatusLogger.log_info("启动时已通过 USB 串口连接硬件")
            except Exception as e:
                print(f"Android USB Serial init failed: {e}")
        
        # PC 或 Android 失败回退连接
        if not self.servo_bus:
            try:
                dev_port = "/dev/ttyUSB0" if platform == "android" else "COM6"
                self._dev_port = dev_port
                # 这里如果不成功，ServoBus 内部会自动切换到 mock 模式
                self.servo_bus = ServoBus(port=dev_port)
            except Exception as e:
                print(f"❌ 串口初始化失败: {e}")
                self.servo_bus = None

        # 如果未能通过默认端口连接（即处于 mock 状态），尝试自动扫描系统串口
        try:
            if not self.servo_bus or getattr(self.servo_bus, "is_mock", True):
                self._try_auto_connect()
        except Exception:
            pass

        # 初始化日志
        try:
            if platform == "android":
                log_dir = pathlib.Path(self.user_data_dir) / "logs"
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
            # 将 Python logging 同步到 RuntimeStatusLogger，便于在界面查看日志
            try:

                class _ForwardHandler(logging.Handler):
                    def emit(self, record):
                        try:
                            msg = self.format(record)
                            if RuntimeStatusLogger:
                                if record.levelno >= logging.ERROR:
                                    RuntimeStatusLogger.log_error(msg)
                                else:
                                    RuntimeStatusLogger.log_info(msg)
                        except Exception:
                            pass

                fh = _ForwardHandler()
                fh.setLevel(logging.INFO)
                logging.getLogger().addHandler(fh)
            except Exception:
                pass
            # 将 stdout/stderr 重定向到 logging，以便 print() 也能显示在 runtime_status 中
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

        # 加载中位配置（若存在）
        neutral_raw = load_neutral() or {}
        # normalize keys to ints
        try:
            neutral = {int(k): int(v) for k, v in neutral_raw.items()}
        except Exception:
            neutral = {i: 2048 for i in range(1, 26)}

        self.balance_ctrl = BalanceController(neutral, is_landscape=True)
        # 尝试初始化陀螺仪（延迟导入并兼容多种 plyer 导入失败场景）
        try:
            self._setup_gyroscope()
        except Exception:
            # 忽略初始化失败，后续权限通过时会重试
            pass

        # AI 核心暂时禁用（不初始化 AICore）
        self.ai_core = None
        self._ai_speech_buf = ""
        self._ai_speech_clear_ev = None

        # MotionController 集成（若有 ServoBus）
        try:
            if self.servo_bus and not getattr(self.servo_bus, "is_mock", True):
                imu = IMUReader(simulate=False)
                imu.start()
                self.motion_controller = MotionController(
                    self.servo_bus.manager,
                    balance_ctrl=self.balance_ctrl,
                    imu_reader=imu,
                    neutral_positions=neutral,
                )
            else:
                self.motion_controller = None
        except Exception as e:
            logging.exception("MotionController init failed")
            self.motion_controller = None

        # ---------- Demo 动画 ----------
        self._demo_step = 0
        Clock.schedule_interval(self._update_loop, 0.1)
        Clock.schedule_interval(self._demo_emotion_loop, 4.0)
        Clock.schedule_interval(self._demo_eye_move, 0.05)

        # 用于循环错误节流，避免界面被频繁相同错误刷屏
        self._last_loop_error = None
        self._last_loop_error_time = 0

        # 初始化运行状态日志记录器
        try:
            runtime_status_panel = self.root_widget.ids.runtime_status
            RuntimeStatusLogger.set_panel(runtime_status_panel)
            RuntimeStatusLogger.log_info("应用启动成功")
        except Exception as e:
            print(f"⚠️ 运行状态面板初始化失败: {e}")

        # 启动时展示权限和连接提示（会在未授权时持续提示并监听授权变化）
        Clock.schedule_once(lambda dt: self._start_permission_watcher(), 0.6)

        # 启动 OTG / 串口监测（跨平台：Android / PC / macOS / Linux）
        try:
            usb_otg.start_monitor()
            RuntimeStatusLogger.log_info("串口/OTG 监测已启动")
            try:
                # 注册 OTG 设备事件回调，热插拔时尝试重建 ServoBus 并刷新 UI
                usb_otg.register_device_callback(self._on_otg_event)
            except Exception:
                pass
        except Exception as e:
            try:
                RuntimeStatusLogger.log_error(f"OTG 监测启动失败: {e}")
            except Exception:
                print(f"OTG 监测启动失败: {e}")

        return self.root_widget

    def _on_otg_event(self, event, device_id):
        """处理 OTG 插拔事件：在设备插入时尝试重建 ServoBus 并刷新界面；拔出时清理状态。"""
        try:
            # 在后台执行 I/O/初始化以避免阻塞主线程
            def _handle():
                try:
                    if event == "added":
                        # 解析 device_id 中的实际串口端口名（如 COM6 或 /dev/ttyUSB0）
                        # Android 特殊处理：尝试通过 usb-serial-for-android 打开设备（Pyjnius）
                        try:
                            if platform == "android":
                                try:
                                    from services.android_serial import (
                                        open_first_usb_serial,
                                    )

                                    usb_wrapper = open_first_usb_serial(baud=115200)
                                except Exception:
                                    usb_wrapper = None
                                if usb_wrapper:
                                    try:
                                        sb = ServoBus(port=usb_wrapper)
                                        if sb and not getattr(sb, "is_mock", True):
                                            # 成功连接，替换旧实例并刷新 UI
                                            try:
                                                if getattr(
                                                    self, "servo_bus", None
                                                ) and hasattr(self.servo_bus, "close"):
                                                    try:
                                                        self.servo_bus.close()
                                                    except Exception:
                                                        pass
                                            except Exception:
                                                pass
                                            self.servo_bus = sb
                                            try:
                                                if getattr(
                                                    self.servo_bus, "manager", None
                                                ):
                                                    try:
                                                        self.servo_bus.manager.servo_scan(
                                                            list(range(1, 26))
                                                        )
                                                    except Exception:
                                                        pass
                                            except Exception:
                                                pass
                                            try:
                                                Clock.schedule_once(
                                                    self._safe_refresh_ui, 0
                                                )
                                            except Exception:
                                                pass
                                            return
                                    except Exception:
                                        pass
                        except Exception:
                            pass

                    def _parse_port(dev_id):
                        try:
                            if not dev_id:
                                return None
                            if "::" in dev_id:
                                return dev_id.split("::", 1)[0]
                            import re

                            m = re.search(r"(COM\d+)", dev_id, re.I)
                            if m:
                                return m.group(1)
                            m = re.search(r"(/dev/tty[^,;\s]+)", dev_id)
                            if m:
                                return m.group(1)
                            return dev_id
                        except Exception:
                            return None

                    # 首先尝试解析 device_id 提供的端口
                    port = (
                        _parse_port(device_id)
                        or getattr(self, "_dev_port", None)
                        or ("/dev/ttyUSB0" if platform == "android" else "COM6")
                    )
                    # 若当前为 mock，则尝试使用可用端口列表连接（优先使用解析到的 port）
                    if not getattr(self, "servo_bus", None) or getattr(
                        self.servo_bus, "is_mock", True
                    ):
                        try:
                            # 保存首选端口
                            self._dev_port = port
                            # 优先尝试解析到的端口，然后回退到系统枚举的端口
                            tried = [port]
                            connected = False
                            # 先尝试首选端口
                            try_ports = list(tried)
                            # 如果可用，使用 pyserial 列出更多候选端口（包含描述信息），优先匹配 CH340/USB-SERIAL
                            if _list_ports:
                                try:
                                    for p in _list_ports.comports():
                                        dev = p.device
                                        desc = p.description or ""
                                        if dev not in try_ports:
                                            # 优先选取包含 CH340/USB-SERIAL 的设备
                                            if (
                                                "ch340" in desc.lower()
                                                or "usb-serial" in desc.lower()
                                                or "usb serial" in desc.lower()
                                            ):
                                                try_ports.insert(0, dev)
                                            else:
                                                try_ports.append(dev)
                                except Exception:
                                    pass

                            # 等待系统稳固枚举设备再尝试（短延迟），并重试一次以提高热插拔稳定性
                            import time as _time

                            _time.sleep(0.2)
                            # 额外重试一次枚举以捕获延迟出现的 COM 端口
                            if _list_ports:
                                try:
                                    for p in _list_ports.comports():
                                        dev = p.device
                                        if dev not in try_ports:
                                            try_ports.append(dev)
                                except Exception:
                                    pass

                            for cand in try_ports:
                                try:
                                    sb = ServoBus(port=cand)
                                    if sb and not getattr(sb, "is_mock", True):
                                        # 关闭旧实例
                                        try:
                                            if getattr(
                                                self, "servo_bus", None
                                            ) and hasattr(self.servo_bus, "close"):
                                                try:
                                                    self.servo_bus.close()
                                                except Exception:
                                                    pass
                                        except Exception:
                                            pass
                                        self.servo_bus = sb
                                        # 强制扫描已连接的舵机以确保 manager 有最新的 servo_info_dict
                                        try:
                                            if getattr(self.servo_bus, "manager", None):
                                                try:
                                                    self.servo_bus.manager.servo_scan(
                                                        list(range(1, 26))
                                                    )
                                                except Exception:
                                                    pass
                                        except Exception:
                                            pass
                                        connected = True
                                        try:
                                            imu = IMUReader(simulate=False)
                                            imu.start()
                                            self.motion_controller = MotionController(
                                                self.servo_bus.manager,
                                                balance_ctrl=self.balance_ctrl,
                                                imu_reader=imu,
                                                neutral_positions={},
                                            )
                                        except Exception:
                                            self.motion_controller = None
                                        try:
                                            RuntimeStatusLogger.log_info(
                                                f"检测到 OTG 设备，已连接串口: {cand}"
                                            )
                                        except Exception:
                                            pass
                                        break
                                except Exception:
                                    pass

                            # 如果连接成功则刷新 UI；若未成功且为 Android，则提示用户在手机端用我们的应用连接
                            if connected:
                                try:
                                    Clock.schedule_once(self._safe_refresh_ui, 0)
                                except Exception:
                                    pass
                            else:
                                try:
                                    if platform == "android":

                                        def _show_connect_tip(dt):
                                            try:
                                                content = BoxLayout(
                                                    orientation="vertical",
                                                    spacing=8,
                                                    padding=8,
                                                )
                                                content.add_widget(
                                                    Label(
                                                        text="检测到手机连接但未找到 USB 串口。请在手机上打开本应用并启用 USB/OTG 串口模式进行连接。"
                                                    )
                                                )
                                                btn = Button(
                                                    text="我知道了",
                                                    size_hint_y=None,
                                                    height=40,
                                                )
                                                popup = Popup(
                                                    title="请在手机上启用串口连接",
                                                    content=content,
                                                    size_hint=(0.9, None),
                                                    height=200,
                                                )

                                                def _close(instance):
                                                    try:
                                                        popup.dismiss()
                                                    except Exception:
                                                        pass

                                                btn.bind(on_release=_close)
                                                content.add_widget(btn)
                                                popup.open()
                                            except Exception:
                                                pass

                                        Clock.schedule_once(_show_connect_tip, 0)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    elif event == "removed":
                        # 简单清理：优雅关闭 servo_bus 与 motion_controller，并刷新 UI
                        try:
                            if getattr(self, "servo_bus", None) and hasattr(
                                self.servo_bus, "close"
                            ):
                                try:
                                    self.servo_bus.close()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        try:
                            self.servo_bus = None
                        except Exception:
                            pass
                        try:
                            self.motion_controller = None
                        except Exception:
                            pass
                        try:
                            RuntimeStatusLogger.log_info(f"串口设备已拔出: {device_id}")
                        except Exception:
                            pass
                        try:
                            Clock.schedule_once(self._safe_refresh_ui, 0)
                        except Exception:
                            pass
                except Exception:
                    pass

            threading.Thread(target=_handle, daemon=True).start()
        except Exception:
            pass

    def _try_auto_connect(self, candidate_ports=None):
        """尝试通过候选端口列表自动连接 ServoBus。
        若 candidate_ports 为空，则枚举系统串口并优先匹配 CH340/USB-SERIAL 描述。
        Android 平台会尝试使用 usb-serial-for-android 库连接。
        """
        try:
            # Android 专属自动连接逻辑
            if platform == "android" and not candidate_ports:
                try:
                    from services.android_serial import open_first_usb_serial
                    # 尝试连接
                    usb_wrapper = open_first_usb_serial(baud=115200)
                    if usb_wrapper:
                        # 如果已有连接，先关闭
                        if getattr(self, "servo_bus", None) and hasattr(self.servo_bus, "close"):
                            try:
                                self.servo_bus.close()
                            except Exception:
                                pass
                        
                        sb = ServoBus(port=usb_wrapper)
                        if sb and not getattr(sb, "is_mock", True):
                            self.servo_bus = sb
                            self._init_motion_controller_after_connect()
                            RuntimeStatusLogger.log_info(f"自动连接 Android USB 串口成功")
                            Clock.schedule_once(self._safe_refresh_ui, 0)
                            return True
                except Exception as e:
                    print(f"Android auto-connect failed: {e}")
            
            # PC / 通用逻辑
            candidates = []
            if candidate_ports:
                candidates = list(candidate_ports)
            else:
                # 枚举系统串口
                if _list_ports:
                    try:
                        for p in _list_ports.comports():
                            dev = p.device
                            desc = p.description or ""
                            # 优先把带 CH340/USB-SERIAL 的放前面
                            if (
                                "ch340" in desc.lower()
                                or "usb-serial" in desc.lower()
                                or "usb serial" in desc.lower()
                            ):
                                candidates.insert(0, dev)
                            else:
                                candidates.append(dev)
                    except Exception:
                        pass
                # 最后加入默认端口作为兜底
                default = getattr(self, "_dev_port", None) or (
                    "/dev/ttyUSB0" if platform == "android" else "COM6"
                )
                if default and default not in candidates:
                    candidates.append(default)

            for cand in candidates:
                try:
                    sb = ServoBus(port=cand)
                    if sb and not getattr(sb, "is_mock", True):
                        try:
                            if getattr(self, "servo_bus", None) and hasattr(
                                self.servo_bus, "close"
                            ):
                                try:
                                    self.servo_bus.close()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        self._dev_port = cand
                        self.servo_bus = sb
                        self._init_motion_controller_after_connect()
                        try:
                            RuntimeStatusLogger.log_info(f"自动连接串口成功: {cand}")
                        except Exception:
                            pass
                        try:
                            Clock.schedule_once(self._safe_refresh_ui, 0)
                        except Exception:
                            pass
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    def _init_motion_controller_after_connect(self):
        """连接成功后初始化 MotionController"""
        try:
            imu = IMUReader(simulate=False)
            imu.start()
            self.motion_controller = MotionController(
                self.servo_bus.manager,
                balance_ctrl=self.balance_ctrl,
                imu_reader=imu,
                neutral_positions={},
            )
        except Exception:
            self.motion_controller = None

    # ================== 硬件 ==================
    def _setup_gyroscope(self):
        # 延迟导入 plyer.gyroscope，兼容 importlib 与直接 from-import 两种情形
        global gyroscope
        if platform == "android":
            try:
                # 优先使用直接导入
                try:
                    from plyer import gyroscope as _gyro
                except Exception:
                    try:
                        import importlib

                        _gyro = importlib.import_module("plyer.gyroscope")
                    except Exception:
                        _gyro = None

                if not _gyro:
                    try:
                        RuntimeStatusLogger.log_error(
                            "未检测到 plyer.gyroscope；无法启用陀螺仪"
                        )
                    except Exception:
                        pass
                    return

                # 将成功导入的模块保存在全局变量，供 _get_gyro_data 使用
                try:
                    gyroscope = _gyro

                except Exception:
                    pass

                try:
                    _gyro.enable()
                    try:
                        RuntimeStatusLogger.log_info("Android 陀螺仪已激活")
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        RuntimeStatusLogger.log_error(f"无法激活陀螺仪: {e}")
                    except Exception:
                        pass
            except Exception:
                pass

    def _check_android_permissions(self):
        """返回缺失的权限列表（Android）"""
        if platform != "android":
            return []
        try:
            from android.permissions import check_permission, Permission

            required_perms = [
                Permission.CAMERA,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
            ]
            missing = []
            for p in required_perms:
                try:
                    if not check_permission(p):
                        missing.append(p)
                except Exception:
                    missing.append(p)
            return missing
        except Exception:
            return []

    def _start_permission_watcher(self):
        """在启动时（以及授权未完成时）持续提醒用户并在授权完成后触发重试初始化。"""
        missing = self._check_android_permissions()
        # 如果有权限缺失，展示 StartupTip 并每秒重试检查
        if missing:
            RuntimeStatusLogger.log_info("检测到缺失权限，等待用户授权")
            # 打开提示（如果用户延迟授权，可多次打开）
            try:
                self._startup_tip = StartupTip()
                self._startup_tip.open()
            except Exception:
                pass

            def _watch(dt):
                missing_now = self._check_android_permissions()
                if not missing_now:
                    # 权限已授予，关闭提示并重新初始化必要组件
                    # try:
                    #     if hasattr(self, '_startup_tip') and self._startup_tip._popup:
                    #         self._startup_tip._popup.dismiss()
                    # except Exception:
                    #     pass
                    RuntimeStatusLogger.log_info(
                        "权限已授予，正在重新初始化授权依赖模块"
                    )
                    # 触发 CameraView 重试（如果存在）
                    try:
                        cam = self.root_widget.ids.get("camera_view")
                        if cam and hasattr(cam, "_start_android"):
                            cam._start_android()
                    except Exception:
                        pass
                    # 权限通过后，重试初始化陀螺仪
                    try:
                        self._setup_gyroscope()
                    except Exception:
                        pass
                    return False
                return True

            Clock.schedule_interval(_watch, 1.0)
        else:
            # 没有缺失权限，仍记录日志
            RuntimeStatusLogger.log_info("权限检查通过")

    def _safe_refresh_ui(self, dt=0):
        """在主线程安全刷新调试面板与运行面板的辅助方法。"""
        try:
            try:
                dp = None
                if hasattr(self, "root_widget") and getattr(
                    self.root_widget, "ids", None
                ):
                    dp = self.root_widget.ids.get("debug_panel")
                if dp and hasattr(dp, "refresh_servo_status"):
                    dp.refresh_servo_status()
            except Exception:
                pass
            try:
                rs = None
                if hasattr(self, "root_widget") and getattr(
                    self.root_widget, "ids", None
                ):
                    rs = self.root_widget.ids.get("runtime_status")
                if rs and hasattr(rs, "refresh"):
                    rs.refresh()
            except Exception:
                pass
        except Exception:
            pass

    def _get_gyro_data(self):
        p, r, y = 0, 0, 0
        if platform == "android" and gyroscope:
            try:
                val = gyroscope.rotation
                if val[0] is not None:
                    # 原始数据通常基于竖屏坐标系：0=Pitch(X), 1=Roll(Y), 2=Yaw(Z)
                    dx, dy, dz = val[0], val[1], val[2]
                    
                    # 针对横屏模式进行坐标系转换
                    # 假设是标准横屏（Home键在右，顶部在左），此时：
                    # 屏幕的前后倾斜（Pitch）对应设备的左右翻转（Roll, Y轴）
                    # 屏幕的左右倾斜（Roll）对应设备的前后翻转（-Pitch, -X轴）
                    p = dy
                    r = -dx
                    y = dz
            except:
                pass
        else:
            p = random.uniform(-5, 5)
            r = random.uniform(-5, 5)
            y = random.uniform(0, 360)
        return p, r, y

    # ================== 主循环 ==================
    def _update_loop(self, dt):
        try:
            p, r, y = self._get_gyro_data()

            if "gyro_panel" in self.root_widget.ids:
                self.root_widget.ids.gyro_panel.update(p, r, y)

            # 硬件同步
            if self.servo_bus and not getattr(self.servo_bus, "is_mock", True):
                targets = self.balance_ctrl.compute(p, r, y)
                self.servo_bus.move_sync(targets, time_ms=100)
        except Exception as e:
            try:
                now = time.time()
                tb = traceback.format_exc()
                # 使用简短的首行作为对比（通常包含异常类型与消息）
                first_line = tb.splitlines()[-1] if tb else str(e)
                # 仅当错误信息变化或距离上次记录超过5秒时，才输出到运行面板，避免刷屏
                if (
                    first_line != getattr(self, "_last_loop_error", None)
                    or (now - getattr(self, "_last_loop_error_time", 0)) > 5
                ):
                    try:
                        RuntimeStatusLogger.log_error(f"Loop Error: {first_line}")
                    except Exception:
                        pass
                    try:
                        logging.exception(f"Loop Error: {first_line}")
                    except Exception:
                        print(f"Loop Error: {first_line}")
                    self._last_loop_error = first_line
                    self._last_loop_error_time = now
                # 可选：在首次出现时打印完整堆栈以便调试
                # print(tb)
            except Exception:
                pass

    # ================== 表情 Demo ==================
    def _demo_emotion_loop(self, dt):
        faces = [
            "normal",
            "happy",
            "sad",
            "angry",
            "surprised",
            "sleepy",
            "thinking",
            "wink",
        ]
        emo = faces[self._demo_step % len(faces)]
        self._demo_step += 1

        self.set_emotion(emo)

        face = self.root_widget.ids.get("face")
        if face:
            if emo in ("happy", "angry", "surprised"):
                face.start_talking()
            else:
                face.stop_talking()

    def _demo_eye_move(self, dt):
        face = self.root_widget.ids.get("face")
        if not face:
            return
        t = Clock.get_time()
        face.look_at(math.sin(t), math.cos(t * 0.7) * 0.5)

    # ============== AI 事件处理 ==============
    def _on_ai_action(self, instance, action, emotion):
        # 更新表情并处理动作指令（动作交给上层或硬件）
        if "face" in self.root_widget.ids:
            try:
                self.root_widget.ids.face.set_emotion(emotion)
            except Exception:
                pass
        # 简单打印或延后处理动作
        print(f"AI action received: {action}, emotion: {emotion}")

    def _on_ai_speech(self, instance, text):
        # 接收逐块/逐字的 speech 输出，传递给 RobotFace 做显示
        face = self.root_widget.ids.get("face")
        if face:
            try:
                face.show_speaking_text(text)
            except Exception:
                pass
        # 聚合分片，短时间无新分片则触发 TTS 播放完整句子
        try:
            self._ai_speech_buf += str(text)
            if self._ai_speech_clear_ev:
                self._ai_speech_clear_ev.cancel()
            self._ai_speech_clear_ev = Clock.schedule_once(self._ai_speak_final, 0.6)
        except Exception:
            pass

    def _ai_speak_final(self, dt):
        txt = self._ai_speech_buf.strip()
        self._ai_speech_buf = ""
        self._ai_speech_clear_ev = None
        if not txt:
            return
        # 尝试使用 plyer tts（优先，支持 Android/iOS），失败则回退到桌面 TTS（pyttsx3）
        try:
            from plyer import tts

            try:
                tts.speak(txt)
                return
            except Exception as e:
                print(f"TTS (plyer) play failed: {e}")
        except Exception as e:
            print(f"plyer.tts not available: {e}")

        # 回退到 pyttsx3（桌面环境），若不可用则打印文本
        try:
            # 确保 comtypes 有一个可写的缓存目录，避免权限错误
            try:
                cache_dir = os.environ.get("COMTYPES_CACHE_DIR") or os.path.join(
                    os.path.expanduser("~"), ".comtypes_cache"
                )
                os.makedirs(cache_dir, exist_ok=True)
                os.environ["COMTYPES_CACHE_DIR"] = cache_dir
            except Exception as _e:
                print(f"Warning: cannot create comtypes cache dir: {_e}")

            import pyttsx3

            try:
                engine = pyttsx3.init()
                # 调整语速与音量为适中
                try:
                    engine.setProperty("rate", 150)
                except Exception:
                    pass
                engine.say(txt)
                engine.runAndWait()
                return
            except Exception as e:
                print(f"TTS (pyttsx3) play failed: {e}")
                # Windows 特殊回退到 SAPI（win32com）尝试
                try:
                    import platform as _plat

                    if _plat.system().lower().startswith("win"):
                        try:
                            import win32com.client

                            sapi = win32com.client.Dispatch("SAPI.SpVoice")
                            sapi.Speak(txt)
                            return
                        except Exception as e2:
                            print(f"TTS (win32com SAPI) play failed: {e2}")
                            # PowerShell SAPI 直接调用回退（避开 comtypes 生成），可在多数 Windows 上工作
                            try:
                                if sys.platform.startswith("win"):
                                    ps_cmd = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak({json.dumps(txt)})"
                                    subprocess.run(
                                        [
                                            "powershell",
                                            "-NoProfile",
                                            "-Command",
                                            ps_cmd,
                                        ],
                                        check=True,
                                    )
                                    return
                            except Exception as e3:
                                print(f"TTS (PowerShell) play failed: {e3}")
                except Exception:
                    pass
        except Exception as e:
            print(f"pyttsx3 not available: {e}")

        # 最后的回退：在控制台输出文本
        print(f"AI says: {txt}")

    # ================== 外部接口 ==================
    def set_emotion(self, emo):
        if "face" in self.root_widget.ids:
            self.root_widget.ids.face.set_emotion(emo)
