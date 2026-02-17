import importlib
import random

from kivy.clock import Clock
from kivy.utils import platform

from widgets.runtime_status import RuntimeStatusLogger
from widgets.startup_tip import StartupTip


def setup_gyroscope(app):
    """初始化陀螺仪并返回 gyroscope 模块对象（失败返回 None）。"""
    if platform != "android":
        return None
    try:
        try:
            from plyer import gyroscope as _gyro
        except Exception:
            try:
                _gyro = importlib.import_module("plyer.gyroscope")
            except Exception:
                _gyro = None

        if not _gyro:
            try:
                RuntimeStatusLogger.log_error("未检测到 plyer.gyroscope；无法启用陀螺仪")
            except Exception:
                pass
            return None

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
        return _gyro
    except Exception:
        return None


def check_android_permissions():
    """返回缺失的权限列表（Android）。"""
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


def start_permission_watcher(app):
    """在启动时（以及授权未完成时）持续提醒并在授权完成后触发重试初始化。"""
    missing = check_android_permissions()
    if missing:
        RuntimeStatusLogger.log_info("检测到缺失权限，等待用户授权")
        try:
            app._startup_tip = StartupTip()
            app._startup_tip.open()
        except Exception:
            pass

        def _watch(dt):
            missing_now = check_android_permissions()
            if not missing_now:
                RuntimeStatusLogger.log_info("权限已授予，正在重新初始化授权依赖模块")
                try:
                    cam = app.root_widget.ids.get("camera_view")
                    if cam and hasattr(cam, "_start_android"):
                        cam._start_android()
                except Exception:
                    pass
                try:
                    app._setup_gyroscope()
                except Exception:
                    pass
                return False
            return True

        Clock.schedule_interval(_watch, 1.0)
    else:
        RuntimeStatusLogger.log_info("权限检查通过")


def get_gyro_data(app, gyroscope_module):
    """读取并转换陀螺仪数据；无可用传感器时回退模拟数据。"""
    p, r, y = 0.0, 0.0, 0.0
    if platform == "android" and gyroscope_module:
        try:
            val = gyroscope_module.rotation
            if val[0] is not None:
                dx, dy, dz = val[0], val[1], val[2]

                mode = getattr(app, "_gyro_axis_mode", "normal")
                if mode == "auto":
                    try:
                        ax, ay = abs(dx), abs(dy)
                        if max(ax, ay) > 0.8:
                            if ay > ax * 1.8:
                                app._gyro_axis_mode = "swapped"
                            elif ax > ay * 1.8:
                                app._gyro_axis_mode = "normal"
                        app._gyro_axis_samples = getattr(app, "_gyro_axis_samples", 0) + 1
                        if getattr(app, "_gyro_axis_mode", "auto") == "auto" and app._gyro_axis_samples > 120:
                            app._gyro_axis_mode = "normal"
                        mode = getattr(app, "_gyro_axis_mode", "normal")
                        if mode != "auto":
                            try:
                                if getattr(app, "_gyro_axis_mode_logged", None) != mode:
                                    RuntimeStatusLogger.log_info(f"陀螺仪轴映射已设置: {mode}")
                                    app._gyro_axis_mode_logged = mode
                            except Exception:
                                pass
                    except Exception:
                        mode = "normal"

                if mode == "swapped":
                    p = -dx
                    r = dy
                else:
                    p = dy
                    r = -dx
                y = dz
        except Exception:
            pass
    else:
        p = random.uniform(-5, 5)
        r = random.uniform(-5, 5)
        y = random.uniform(0, 360)
    return p, r, y
