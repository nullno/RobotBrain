from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.utils import platform
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.metrics import dp
from kivy.graphics import Color, Rectangle
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
from widgets.esp32_setup import Esp32SetupPopup
from widgets.esp32_indicator import Esp32Indicator
from widgets.debug_ui_components import TechButton
from app import esp32_runtime as usb_runtime
from services.control_bridge import ControlBridge
from services.esp32_link import Esp32Link
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
    def _targets_changed(self, new_targets, old_targets, threshold=3):
        try:
            if not isinstance(new_targets, dict) or not isinstance(old_targets, dict):
                return True
            if new_targets.keys() != old_targets.keys():
                return True
            th = int(max(0, threshold))
            for sid, new_pos in new_targets.items():
                old_pos = old_targets.get(sid)
                if old_pos is None:
                    return True
                try:
                    if abs(int(new_pos) - int(old_pos)) > th:
                        return True
                except Exception:
                    return True
            return False
        except Exception:
            return True

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
        Clock.schedule_once(lambda dt: self._ensure_esp32_popup(), 0.2)

    def on_resume(self):
        if platform == 'android':
            Clock.schedule_once(lambda dt: self.update_android_flags(), 0)
            Clock.schedule_once(lambda dt: self._handle_android_usb_attach_intent("resume"), 0.1)

    def on_stop(self):
        try:
            if getattr(self, "control_bridge", None):
                self.control_bridge.stop()
        except Exception:
            pass
        try:
            if getattr(self, "esp32_link", None):
                self.esp32_link.stop()
        except Exception:
            pass

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

        try:
            if getattr(self, "control_bridge", None) is None:
                self.control_bridge = ControlBridge()
                self.control_bridge.start()
        except Exception as e:
            logging.warning("ControlBridge init failed: %s", e)
            self.control_bridge = None

        # ESP32 链路状态与调试面板通信服务
        try:
            self.esp32_link = Esp32Link(self)
            self.esp32_link.start()
        except Exception as e:
            logging.warning("ESP32 link service init failed: %s", e)
            self.esp32_link = None

        # 周期刷新右上角链路指示
        try:
            Clock.schedule_interval(lambda dt: self._refresh_link_indicator(), 1.0)
        except Exception:
            pass

        # 启动 ESP32 配网门禁：未联网前遮罩主界面
        self._setup_esp32_gate()
        Clock.schedule_once(lambda dt: self._poll_esp32_gate(), 0)

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
        try:
            bridge = getattr(self, "control_bridge", None)
            if bridge:
                p, r, y = bridge.get_latest_imu()
                return p, r, y
        except Exception:
            pass
        # 优先使用已建立的 IMUReader/telemetry 数据，再回退到本机传感器
        try:
            imu = getattr(self, "imu_reader", None)
            if imu:
                return imu.get_orientation()
        except Exception:
            pass

        try:
            mc = getattr(self, "motion_controller", None)
            if mc and getattr(mc, "imu", None):
                return mc.imu.get_orientation()
        except Exception:
            pass

        try:
            sb = getattr(self, "servo_bus", None)
            if sb and not getattr(sb, "is_mock", True) and hasattr(sb, "get_latest_imu"):
                return sb.get_latest_imu()
        except Exception:
            pass

        return device_runtime.get_gyro_data(self, gyroscope)

    # ================== ESP32 引导弹窗 ==================
    def _ensure_esp32_popup(self):
        """未联网时弹出 ESP32 配网引导。"""
        try:
            connected = bool(self.servo_bus and not getattr(self.servo_bus, "is_mock", True))
        except Exception:
            connected = False
        if getattr(self, "_esp32_setup_popup", None) is None:
            try:
                self._esp32_setup_popup = Esp32SetupPopup()
            except Exception as e:
                logging.warning("创建 ESP32 弹窗失败: %s", e)
                self._esp32_setup_popup = None
        if not connected and getattr(self, "_esp32_setup_popup", None):
            try:
                self._esp32_setup_popup.open_popup()
            except Exception as e:
                logging.warning("打开 ESP32 弹窗失败: %s", e)

    def _is_esp32_ready(self):
        try:
            sb = getattr(self, "servo_bus", None)
            if sb and not getattr(sb, "is_mock", True):
                return True
        except Exception:
            pass
        try:
            link = getattr(self, "esp32_link", None)
            if link:
                state = link.get_ui_state()
                if state.get("connected"):
                    return True
        except Exception:
            pass
        return False

    def _update_gate_bg(self, overlay):
        try:
            if hasattr(overlay, "_bg_rect"):
                overlay._bg_rect.pos = overlay.pos
                overlay._bg_rect.size = overlay.size
        except Exception:
            pass

    def _setup_esp32_gate(self):
        if getattr(self, "_esp32_gate", None) or self._is_esp32_ready():
            return
        try:
            gate = FloatLayout(size_hint=(1, 1))
            with gate.canvas.before:
                Color(0, 0, 0, 0.86)
                gate._bg_rect = Rectangle(pos=gate.pos, size=gate.size)
            gate.bind(pos=lambda *_: self._update_gate_bg(gate), size=lambda *_: self._update_gate_bg(gate))

            status_lbl = Label(
                text="等待 ESP32 连接 Wi-Fi",
                font_size="18sp",
                color=(0.9, 0.95, 1, 1),
                font_name=getattr(self, "theme_font", None) or None,
                size_hint=(None, None),
                halign="center",
                valign="middle",
                width=dp(520),
                height=dp(60),
                pos_hint={"center_x": 0.5, "center_y": 0.6},
            )
            status_lbl.bind(size=status_lbl.setter("text_size"))

            tip_lbl = Label(
                text="请先完成 ESP32 配网，完成后自动进入主界面",
                font_size="14sp",
                color=(0.75, 0.82, 0.92, 1),
                font_name=getattr(self, "theme_font", None) or None,
                size_hint=(None, None),
                width=dp(520),
                height=dp(40),
                pos_hint={"center_x": 0.5, "center_y": 0.5},
                halign="center",
                valign="middle",
            )
            tip_lbl.bind(size=tip_lbl.setter("text_size"))

            action_btn = TechButton(
                text="蓝牙配网",
                size_hint=(None, None),
                width=dp(150),
                height=dp(44),
                pos_hint={"center_x": 0.5, "center_y": 0.4},
            )
            action_btn.bind(on_release=self._open_esp32_setup)

            gate.add_widget(status_lbl)
            gate.add_widget(tip_lbl)
            gate.add_widget(action_btn)

            if hasattr(self, "root_widget") and self.root_widget:
                self.root_widget.add_widget(gate)
            self._esp32_gate = gate
            self._esp32_gate_status = status_lbl
            self._esp32_gate_tip = tip_lbl

            Clock.schedule_interval(self._poll_esp32_gate, 1.0)
        except Exception:
            pass

    def _open_esp32_setup(self, *_):
        try:
            if getattr(self, "_esp32_setup_popup", None):
                self._esp32_setup_popup.open_popup()
        except Exception:
            pass

    def _poll_esp32_gate(self, dt=0):
        try:
            if self._is_esp32_ready():
                self._enter_main_ui()
                return False
            self._update_gate_status()
        except Exception:
            pass
        return True

    def _update_gate_status(self):
        try:
            status = "等待 ESP32 连接 Wi-Fi"
            link = getattr(self, "esp32_link", None)
            if link:
                st = link.get_ui_state()
                host = st.get("host") or ""
                ssid = st.get("ssid") or ""
                if host:
                    status = f"等待 ESP32 在线 ({host})"
                if ssid:
                    status += f" · {ssid}"
            if getattr(self, "_esp32_gate_status", None):
                self._esp32_gate_status.text = status
        except Exception:
            pass

    def _enter_main_ui(self):
        try:
            gate = getattr(self, "_esp32_gate", None)
            if gate and gate.parent:
                gate.parent.remove_widget(gate)
            self._esp32_gate = None
            try:
                RuntimeStatusLogger.log_info("ESP32 已在线，进入主界面")
            except Exception:
                pass
        except Exception:
            pass
        return False

    def on_esp32_provisioned(self, host=None, port=None):
        try:
            if host:
                usb_runtime.manual_bind_host(self, host, port or 5005)
        except Exception:
            pass
        Clock.schedule_once(lambda dt: self._poll_esp32_gate(), 0)

    def _refresh_link_indicator(self, dt=0):
        try:
            indicator = None
            if hasattr(self, "root_widget") and getattr(self.root_widget, "ids", None):
                indicator = self.root_widget.ids.get("esp32_indicator")
            link = getattr(self, "esp32_link", None)
            if indicator and link:
                indicator.update_state(link.get_ui_state())
        except Exception:
            pass

    # ================== 主循环 ==================
    def _update_loop(self, dt):
        try:
            p, r, y = self._get_gyro_data()
            now = time.time()
            self._latest_pitch = float(p)
            self._latest_roll = float(r)
            self._latest_yaw = float(y)

            gyro_ui_period = float(getattr(self, "_gyro_ui_period", 0.12) or 0.12)
            last_gyro_ui_t = float(getattr(self, "_last_gyro_ui_update_time", 0.0) or 0.0)
            if (now - last_gyro_ui_t) >= max(0.02, gyro_ui_period):
                if "gyro_panel" in self.root_widget.ids:
                    self.root_widget.ids.gyro_panel.update(p, r, y)
                self._last_gyro_ui_update_time = now

            # 硬件同步
            if self.servo_bus and not getattr(self.servo_bus, "is_mock", True):
                # 手机端默认关闭连续同步写，避免 USB 连接后主线程明显卡顿
                if not bool(getattr(self, "_enable_live_servo_sync", False)):
                    return

                # 调试读取/自检期间可临时暂停主循环同步写，避免读写争用导致读回 0%
                suspend_sync_until = float(getattr(self, "_suspend_servo_sync_until", 0.0) or 0.0)
                if now < suspend_sync_until:
                    return

                # USB 刚连接/重连与扫描阶段，暂缓主循环同步，避免串口争用导致主线程卡顿
                usb_busy_until = float(getattr(self, "_usb_busy_until", 0.0) or 0.0)
                if now < usb_busy_until or bool(getattr(self, "_servo_scan_in_progress", False)):
                    return

                active_period = float(getattr(self, "_sync_active_period", 0.1) or 0.1)
                idle_period = float(getattr(self, "_sync_idle_period", 0.22) or 0.22)
                pose_threshold = float(getattr(self, "_sync_pose_threshold_deg", 0.5) or 0.5)
                target_threshold = int(getattr(self, "_sync_target_threshold", 3) or 3)
                compute_pose_threshold = float(
                    getattr(self, "_sync_compute_pose_threshold_deg", 0.2) or 0.2
                )
                compute_idle_period = float(
                    getattr(self, "_sync_compute_idle_period", idle_period) or idle_period
                )

                last_compute_t = float(getattr(self, "_last_sync_compute_time", 0.0) or 0.0)
                last_compute_pitch = float(getattr(self, "_last_sync_compute_pitch", 0.0) or 0.0)
                last_compute_roll = float(getattr(self, "_last_sync_compute_roll", 0.0) or 0.0)
                last_targets = getattr(self, "_last_sync_targets", None)

                compute_due = (now - last_compute_t) >= max(0.05, compute_idle_period)
                compute_pose_changed = (
                    last_targets is None
                    or abs(float(p) - last_compute_pitch) >= compute_pose_threshold
                    or abs(float(r) - last_compute_roll) >= compute_pose_threshold
                )

                if compute_pose_changed or compute_due:
                    targets = self.balance_ctrl.compute(p, r, y)
                    self._last_sync_compute_time = now
                    self._last_sync_compute_pitch = float(p)
                    self._last_sync_compute_roll = float(r)
                else:
                    targets = last_targets
                    if not isinstance(targets, dict):
                        targets = None

                last_send_t = float(getattr(self, "_last_sync_send_time", 0.0) or 0.0)
                last_pitch = float(getattr(self, "_last_sync_pitch", 0.0) or 0.0)
                last_roll = float(getattr(self, "_last_sync_roll", 0.0) or 0.0)

                pose_changed = (
                    abs(float(p) - last_pitch) >= pose_threshold
                    or abs(float(r) - last_roll) >= pose_threshold
                )
                target_changed = self._targets_changed(targets, last_targets, threshold=target_threshold)
                elapsed = now - last_send_t

                should_send = False
                if last_targets is None:
                    should_send = True
                elif pose_changed or target_changed:
                    should_send = elapsed >= active_period
                else:
                    should_send = elapsed >= idle_period

                if should_send:
                    self.servo_bus.move_sync(targets, time_ms=100)
                    self._last_sync_send_time = now
                    self._last_sync_targets = dict(targets or {})
                    self._last_sync_pitch = float(p)
                    self._last_sync_roll = float(r)
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
            from services import usb_otg  # 惰性导入，避免网络模式下缺少模块报错
        except Exception:
            usb_otg = None

        if usb_otg:
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
