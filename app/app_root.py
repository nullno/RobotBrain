from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.utils import platform
import math
import time
import json
from pathlib import Path

from widgets.camera_view import CameraView
from widgets.robot_face import RobotFace
from widgets.gyro_panel import GyroPanel
from widgets.debug_panel import DebugPanel
from widgets.servo_status import ServoStatus
from widgets.runtime_status import RuntimeStatusPanel, RuntimeStatusLogger
from services import usb_otg
from app import usb_runtime
from app import device_runtime
from app import bootstrap_runtime
from app import ai_runtime
from app import android_ui_runtime
from app import ui_runtime
from app import balance_runtime
from app import platform_runtime

try:
    # 用于枚举串口设备以便自动检测 CH340 等适配器
    from serial.tools import list_ports as _list_ports
except Exception:
    _list_ports = None
import logging
import traceback

gyroscope = platform_runtime.load_gyroscope_module()
run_on_ui_thread = platform_runtime.get_run_on_ui_thread()


class RobotDashboardApp(App):
    # ================== UI / 状态代理 ==================
    def _update_usb_state(self, **kwargs):
        ui_runtime.update_usb_state(self, **kwargs)

    def _log_usb_state_summary(self):
        ui_runtime.log_usb_state_summary(self)

    def _should_log_usb_status(self, key, status, interval_sec=3.0):
        return ui_runtime.should_log_usb_status(self, key, status, interval_sec=interval_sec)

    # ================== USB 连接状态 ==================
    def _mark_usb_connected_after_permission(self, status_text=None):
        """Android USB 串口成功连接后：清空 pending 状态，并仅提示一次授权完成。"""
        try:
            prev = str(getattr(self, "_last_usb_permission_status", "") or "")
            if prev.startswith("wait:"):
                msg = "USB 授权已完成，串口已连接"
                if status_text:
                    msg = msg + ": " + str(status_text)
                RuntimeStatusLogger.log_info(msg)
            self._last_usb_permission_status = None
            self._android_usb_connected_once = True
            self._suppress_android_otg_added_until = time.time() + 8.0
            self._update_usb_state(
                detect="device",
                auth="granted",
                connect="up",
                detail=str(status_text or ""),
            )
        except Exception:
            try:
                self._last_usb_permission_status = None
            except Exception:
                pass

    def _ensure_android_usb_reconnect_watcher(self, reason=""):
        usb_runtime.ensure_android_usb_reconnect_watcher(self, reason=reason)

    # ================== 平衡参数持久化 ==================
    def _balance_tuning_file(self):
        return balance_runtime.balance_tuning_file(self)

    def save_balance_tuning(self):
        return balance_runtime.save_balance_tuning(self)

    def load_balance_tuning(self):
        return balance_runtime.load_balance_tuning(self)

    # ================== Android USB Intent 处理 ==================
    def _is_duplicate_usb_attach_event(self, signature, interval_sec=4.0):
        return usb_runtime.is_duplicate_usb_attach_event(self, signature, interval_sec=interval_sec)

    def _handle_android_usb_attach_intent(self, source="resume"):
        usb_runtime.handle_android_usb_attach_intent(self, source=source)

    # ================== 生命周期 ==================
    def on_start(self):
        if platform == 'android':
            Clock.schedule_once(lambda dt: self.update_android_flags(), 0)
            Clock.schedule_once(lambda dt: self._handle_android_usb_attach_intent("start"), 0.1)

    def on_resume(self):
        if platform == 'android':
            Clock.schedule_once(lambda dt: self.update_android_flags(), 0)
            Clock.schedule_once(lambda dt: self._handle_android_usb_attach_intent("resume"), 0.1)

    @run_on_ui_thread
    def update_android_flags(self):
        android_ui_runtime.update_android_flags(self)

    # ================== 构建入口 ==================
    def build(self):
        bootstrap_runtime.init_android_permissions(self)

        Builder.load_file("kv/style.kv")
        self.root_widget = Builder.load_file("kv/root.kv")

        bootstrap_runtime.init_servo_bus(self)

        bootstrap_runtime.init_logging(self)

        neutral = bootstrap_runtime.init_balance_and_gyro(self)

        bootstrap_runtime.init_ai_core(self)

        bootstrap_runtime.init_motion_controller(self, neutral)
        bootstrap_runtime.init_runtime_loops(self)
        bootstrap_runtime.init_runtime_status_panel(self)
        bootstrap_runtime.start_permission_and_otg_watchers(self)

        return self.root_widget

    # ================== USB / 串口代理 ==================
    def _on_otg_event(self, event, device_id):
        usb_runtime.handle_otg_event(self, event, device_id, list_ports_module=_list_ports)

    def _try_auto_connect(self, candidate_ports=None):
        return usb_runtime.try_auto_connect(
            self,
            candidate_ports=candidate_ports,
            list_ports_module=_list_ports,
        )

    def _init_motion_controller_after_connect(self):
        usb_runtime.init_motion_controller_after_connect(self)

    def _schedule_servo_scan_after_connect(self, source="连接"):
        usb_runtime.schedule_servo_scan_after_connect(self, source=source)

    # ================== 硬件 ==================
    def _setup_gyroscope(self):
        global gyroscope
        gyroscope = device_runtime.setup_gyroscope(self)

    def _check_android_permissions(self):
        return device_runtime.check_android_permissions()

    def _start_permission_watcher(self):
        device_runtime.start_permission_watcher(self)

    def _safe_refresh_ui(self, dt=0):
        ui_runtime.safe_refresh_ui(self, dt=dt)

    def _get_gyro_data(self):
        return device_runtime.get_gyro_data(self, gyroscope)

    # ================== 主循环 ==================
    def _update_loop(self, dt):
        try:
            p, r, y = self._get_gyro_data()
            self._latest_pitch = float(p)
            self._latest_roll = float(r)
            self._latest_yaw = float(y)

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
        ai_runtime.on_ai_action(self, instance, action, emotion)

    def _on_ai_speech(self, instance, text):
        ai_runtime.on_ai_speech(self, instance, text)

    def _ai_speak_final(self, dt):
        ai_runtime.ai_speak_final(self, dt)

    def set_ai_model(self, profile_name, api_key=None):
        if not self.ai_core:
            return False
        try:
            self.ai_core.switch_profile(profile_name, api_key=api_key)
            return True
        except Exception:
            return False

    def save_ai_settings(self, profile_name, api_key):
        try:
            cfg_path = Path(getattr(self, "user_data_dir", ".")) / "ai_settings.json"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "profile_name": str(profile_name or "deepseek"),
                "api_key": str(api_key or ""),
            }
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load_ai_settings(self):
        try:
            cfg_path = Path(getattr(self, "user_data_dir", ".")) / "ai_settings.json"
            if not cfg_path.exists():
                return {}
            with open(cfg_path, "r", encoding="utf-8") as f:
                return dict(json.load(f) or {})
        except Exception:
            return {}

    def test_ai_chat(self, text):
        if not self.ai_core:
            return False
        try:
            self.ai_core.send_text(str(text or "").strip())
            return True
        except Exception:
            return False

    def set_ai_profile(self, profile_name, api_key=None):
        return self.set_ai_model(profile_name, api_key=api_key)

    def get_ai_models(self):
        if not self.ai_core:
            return []
        try:
            return self.ai_core.list_profiles()
        except Exception:
            return []

    def start_ai_voice_chat(self, language="zh-CN"):
        if not self.ai_core:
            return False
        try:
            return bool(self.ai_core.start_voice_capture(language=language))
        except Exception:
            return False

    def stop_ai_voice_chat(self):
        if not self.ai_core:
            return False
        try:
            return bool(self.ai_core.stop_voice_capture())
        except Exception:
            return False

    def get_ai_voice_error(self):
        if not self.ai_core:
            return "AI 未初始化"
        try:
            return str(self.ai_core.get_last_voice_error() or "")
        except Exception:
            return ""

    def test_ai_connection(self):
        if not self.ai_core:
            return False, "AI 未初始化"
        try:
            return self.ai_core.test_connection()
        except Exception as e:
            return False, str(e)

    def test_ai_tts(self, text="你好，我是 RobotBrain，语音播报测试成功。"):
        try:
            return bool(ai_runtime.speak_text(self, text))
        except Exception:
            return False

    def get_ai_tts_status(self):
        try:
            channel = str(getattr(self, "_tts_channel", "unknown") or "unknown")
            err = str(getattr(self, "_tts_last_error", "") or "")
            return {"channel": channel, "error": err}
        except Exception:
            return {"channel": "unknown", "error": ""}

    def get_ai_latency_status(self):
        stt_wait = 0
        stt_rec = 0
        llm_first = 0
        llm_total = 0
        try:
            if self.ai_core and hasattr(self.ai_core, "get_latency_snapshot"):
                snap = dict(self.ai_core.get_latency_snapshot() or {})
                stt_wait = int(snap.get("stt_wait_ms") or 0)
                stt_rec = int(snap.get("stt_rec_ms") or 0)
                llm_first = int(snap.get("llm_first_ms") or 0)
                llm_total = int(snap.get("llm_total_ms") or 0)
        except Exception:
            pass

        tts_ms = 0
        try:
            tts_ms = int(getattr(self, "_tts_last_ms", 0) or 0)
        except Exception:
            tts_ms = 0

        return {
            "stt_wait_ms": stt_wait,
            "stt_rec_ms": stt_rec,
            "llm_first_ms": llm_first,
            "llm_total_ms": llm_total,
            "tts_ms": tts_ms,
        }

    # ================== 退出清理 ==================
    def on_stop(self):
        """应用退出时清理 OTG 回调与 USB 重试任务，避免重复注册与残留任务。"""
        try:
            usb_otg.unregister_device_callback(self._on_otg_event)
        except Exception:
            pass
        try:
            usb_otg.stop_monitor()
        except Exception:
            pass
        try:
            ev = getattr(self, "_android_usb_reconnect_ev", None)
            if ev:
                ev.cancel()
            self._android_usb_reconnect_ev = None
        except Exception:
            pass

    # ================== 外部接口 ==================
    def set_emotion(self, emo):
        if "face" in self.root_widget.ids:
            self.root_widget.ids.face.set_emotion(emo)
