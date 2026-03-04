import logging
import pathlib
import threading
import os
import json

# 注意：ServoBus/串口初始化逻辑已迁移到运行时初始化函数（例如 app.esp32_runtime 或 app_root 中），
# 早期文件顶部的直接执行代码已删除以避免导入时副作用或语法错误。

from kivy.utils import platform
from kivy.clock import Clock

# 导入运行时适配模块与服务
from app import esp32_runtime as esp32_runtime
from widgets.runtime_status import RuntimeStatusLogger
from services.ai_core import AICore
from services.wifi_servo import get_controller as get_wifi_servo, load_host, init_controller
from services.neutral import load_neutral


def init_android_permissions(app):
    """兼容接口（已弃用本地权限监控）。"""
    return []


def init_servo_bus(app):
    """初始化 wifi_servo 控制器。

    优先 esp32_runtime.try_auto_connect → 若失败则启动后台发现。
    """
    try:
        ok = esp32_runtime.try_auto_connect(app)
        if ok:
            return True
    except Exception:
        pass
    # 主机未知，启动后台 UDP 发现（不自动触发 BLE 配网）
    try:
        esp32_runtime.start_background_discovery(
            app, interval_sec=8.0, max_attempts=4, allow_ble_provision=False,
        )
    except Exception:
        pass
    RuntimeStatusLogger.log_info("wifi_servo 等待连接")
    return False



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


def init_neutral_positions(app):
    """加载中位值（平衡算法已迁移至固件，此处仅保留中位数据供 UI 使用）。"""
    neutral_raw = load_neutral() or {}
    try:
        neutral = {int(k): int(v) for k, v in neutral_raw.items()}
    except Exception:
        neutral = {i: 2048 for i in range(1, 26)}
    app.neutral_positions = neutral

    # 不再创建本地 BalanceController
    app.balance_ctrl = None
    app.motion_controller = None
    app.imu_reader = None

    return neutral


def init_balance_and_gyro(app):
    """兼容接口 —— 重定向到 init_neutral_positions。"""
    return init_neutral_positions(app)


def init_motion_controller(app, neutral=None):
    """兼容占位 —— 平衡/运动由固件处理，主程序不再初始化本地 MotionController。"""
    app.motion_controller = None


def init_runtime_loops(app):
    app._demo_step = 0

    # 运行时性能档位：mobile(默认安卓) / desktop
    runtime_profile = str(getattr(app, "_runtime_profile", "")).strip().lower()
    if not runtime_profile:
        runtime_profile = "mobile" if platform == "android" else "desktop"
    app._runtime_profile = runtime_profile

    update_interval = 0.12 if runtime_profile == "mobile" else 0.1
    Clock.schedule_interval(app._update_loop, update_interval)

    # 连续硬件同步默认随 wifi_servo 连接状态自动开启
    default_live_sync = False
    try:
        ctrl = getattr(app, "wifi_servo", None) or get_wifi_servo()
        default_live_sync = bool(ctrl and ctrl.is_connected)
    except Exception:
        default_live_sync = False
    app._enable_live_servo_sync = bool(getattr(app, "_enable_live_servo_sync", default_live_sync))

    if runtime_profile == "mobile":
        app._gyro_ui_period = float(getattr(app, "_gyro_ui_period", 0.22) or 0.22)
        app._sync_compute_pose_threshold_deg = float(
            getattr(app, "_sync_compute_pose_threshold_deg", 0.22) or 0.22
        )
        app._sync_compute_idle_period = float(
            getattr(app, "_sync_compute_idle_period", 0.35) or 0.35
        )
    else:
        app._gyro_ui_period = float(getattr(app, "_gyro_ui_period", 0.12) or 0.12)
        app._sync_compute_pose_threshold_deg = float(
            getattr(app, "_sync_compute_pose_threshold_deg", 0.16) or 0.16
        )
        app._sync_compute_idle_period = float(
            getattr(app, "_sync_compute_idle_period", 0.22) or 0.22
        )

    # 发布/移动端默认关闭演示表情循环，减少主线程和 GPU 抢占
    enable_demo_face_loop = bool(
        getattr(app, "_enable_demo_face_loop", runtime_profile != "mobile")
    )
    if enable_demo_face_loop:
        Clock.schedule_interval(app._demo_emotion_loop, 4.0)

    eye_move_interval = 0.14 if runtime_profile == "mobile" else 0.08
    Clock.schedule_interval(app._demo_eye_move, eye_move_interval)

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


def init_ai_core(app):
    """初始化 AI 核心（支持模型切换，默认 DeepSeek）。"""
    app.ai_core = None
    app._ai_speech_buf = ""
    app._ai_speech_clear_ev = None

    try:
        profile_name = os.environ.get("ROBOTBRAIN_LLM_PROFILE") or "deepseek"
        api_key = os.environ.get("ROBOTBRAIN_LLM_API_KEY")

        try:
            cfg_path = pathlib.Path(getattr(app, "user_data_dir", ".")) / "ai_settings.json"
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                profile_name = str(saved.get("profile_name") or profile_name)
                api_key = str(saved.get("api_key") or api_key or "").strip() or api_key
        except Exception as e:
            RuntimeStatusLogger.log_info(f"AI 配置读取失败，使用环境变量: {e}")

        app.ai_core = AICore(api_key=api_key, profile_name=profile_name)
        app.ai_core.bind(
            on_action_command=app._on_ai_action,
            on_speech_output=app._on_ai_speech,
        )
        RuntimeStatusLogger.log_info(
            f"AI 已初始化: profile={app.ai_core.profile_name}, online={app.ai_core.enabled}"
        )
    except Exception as e:
        app.ai_core = None
        try:
            RuntimeStatusLogger.log_error(f"AI 初始化失败: {e}")
        except Exception:
            print(f"AI 初始化失败: {e}")


def start_permission_and_otg_watchers(app):
    # 已弃用本地 OTG/串口监测
    try:
        RuntimeStatusLogger.log_info("已弃用本地 OTG/串口监测")
    except Exception:
        pass
