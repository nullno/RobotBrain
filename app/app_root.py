from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.utils import platform
import math
import time
import json
from pathlib import Path

from widgets.runtime_status import RuntimeStatusLogger
from widgets.connection_status import (
    is_esp32_ready, setup_connection_gate,
    poll_connection, refresh_link_indicator,
)
from app import esp32_runtime as e_runtime
from services.wifi_servo import get_controller as get_wifi_servo
from app import bootstrap_runtime
from app import ai_runtime
from app import android_ui_runtime
from app import ui_runtime
from app import platform_runtime
import logging
from kivy.properties import StringProperty
from app import theme
import traceback

run_on_ui_thread = platform_runtime.get_run_on_ui_thread() or (lambda f: f)


class RobotDashboardApp(App):
    theme_font = StringProperty(theme.FONT)

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

    # ================== 平衡参数（已迁移至固件） ==================
    def _balance_tuning_file(self):
        return None

    def save_balance_tuning(self):
        return False

    def load_balance_tuning(self):
        return False

    # ================== 生命周期 ==================
    def on_start(self):
        Clock.schedule_once(lambda dt: self._ensure_esp32_popup(), 0.2)

    @run_on_ui_thread
    def update_android_flags(self):
        android_ui_runtime.update_android_flags(self)

    # ================== 构建入口 ==================
    def build(self):
        from kivy.uix.floatlayout import FloatLayout
        self.root_container = FloatLayout()
        
        self.ai_core = None
        bootstrap_runtime.init_android_permissions(self)

        # 挂载配网门禁层，确保 Kivy 第一帧即可将其直接渲染，避免黑屏
        self.root_widget = None
        self._esp32_gate = setup_connection_gate(self)
        if self._esp32_gate:
            self.root_container.add_widget(self._esp32_gate)
        else:
            from kivy.uix.label import Label
            self._loading_lbl = Label(text="加载中...", font_name=self.theme_font)
            self.root_container.add_widget(self._loading_lbl)

        # 延迟执行所有后端设备的加载和初始化，释放主线程渲染第一帧
        Clock.schedule_once(self._load_heavy_ui, 0.1)

        return self.root_container

    def _load_heavy_ui(self, dt):
        from widgets.camera_view import CameraView
        from widgets.robot_face import RobotFace
        from widgets.gyro_panel import GyroPanel
        from widgets.debug_panel import DebugPanel
        from widgets.servo_status import ServoStatus
        from widgets.runtime_status import RuntimeStatusPanel
        from widgets.esp32_setup import Esp32SetupPopup
        from widgets.esp32_indicator import Esp32Indicator

        Builder.load_file('kv/style.kv')
        self.root_widget = Builder.load_file('kv/root.kv')
        
        # 将主界面插入到底层 (后面)
        self.root_container.add_widget(self.root_widget, index=len(self.root_container.children))
        
        if hasattr(self, "_loading_lbl"):
            self.root_container.remove_widget(self._loading_lbl)
            
        Clock.schedule_once(self._delayed_init, 0.1)

    def _delayed_init(self, dt):
        bootstrap_runtime.init_servo_bus(self)
        bootstrap_runtime.init_logging(self)
        bootstrap_runtime.init_neutral_positions(self)
        bootstrap_runtime.init_runtime_loops(self)

        Clock.schedule_interval(lambda dt: refresh_link_indicator(self), 2.0)

        if self._esp32_gate:
            Clock.schedule_interval(lambda dt: poll_connection(self, self._esp32_gate, dt), 1.0)
        elif is_esp32_ready(self):
            self._show_main_content()

    def _show_main_content(self):
        try:
            main = self.root_widget.ids.get('main_content')
            if main:
                if not getattr(self, '_main_content_loaded', False):
                    from kivy.lang import Builder
                    from kivy.factory import Factory
                    Builder.load_file('kv/main_content.kv')
                    main_ui = Factory.MainContentContainer()
                    main.add_widget(main_ui)
                    # 将动态加载的主界面的 ids 挂载到 root_widget 以保证兼容性
                    self.root_widget.ids.update(main_ui.ids)
                    self._main_content_loaded = True
                    
                    # 在表情加载完成后再初始化核心组件
                    import app.bootstrap_runtime as bootstrap_runtime
                    bootstrap_runtime.init_runtime_status_panel(self)
                    bootstrap_runtime.init_ai_core(self)
                
                main.opacity = 1
                main.disabled = False
        except Exception as e:
            import logging
            logging.error(f"Failed to load main ui: {e}")

    # ================== 硬件 ==================
    def _safe_refresh_ui(self, dt=0):
        ui_runtime.safe_refresh_ui(self, dt=dt)

    def _get_gyro_data(self):
        """从 ESP32 WiFi telemetry 获取 IMU 数据。"""
        try:
            ctrl = getattr(self, 'wifi_servo', None) or get_wifi_servo()
            if ctrl and ctrl.is_connected:
                imu_data = ctrl.get_imu()
                if imu_data and isinstance(imu_data, tuple):
                    return imu_data
                if imu_data and isinstance(imu_data, dict):
                    return (
                        float(imu_data.get('pitch', 0)),
                        float(imu_data.get('roll', 0)),
                        float(imu_data.get('yaw', 0)),
                    )
        except Exception:
            pass
        # 无连接时返回零姿态
        return (0.0, 0.0, 0.0)

    # ================== ESP32 引导弹窗 ==================
    def _ensure_esp32_popup(self):
        if getattr(self, '_esp32_setup_popup', None) is None:
            try:
                from widgets.esp32_setup import Esp32SetupPopup
                self._esp32_setup_popup = Esp32SetupPopup()
            except Exception as e:
                logging.warning('ESP32 popup create failed: %s', e)
                self._esp32_setup_popup = None
        if not is_esp32_ready(self) and self._esp32_setup_popup:
            try:
                self._esp32_setup_popup.open_popup()
            except Exception as e:
                logging.warning('ESP32 popup open failed: %s', e)

    def on_esp32_provisioned(self, host=None, port=None):
        self.on_esp32_connected(host, port)

    def on_esp32_connected(self, host=None, port=None):
        try:
            if host:
                e_runtime.manual_bind_host(self, host, port or 5005)
        except Exception:
            pass
        # 触发门禁轮询
        gate = getattr(self, '_esp32_gate', None)
        if gate:
            Clock.schedule_once(lambda dt: poll_connection(self, gate), 0)
        else:
            self._show_main_content()

    # ================== 主循环 ==================
    def _update_loop(self, dt):
        """主循环：仅更新 UI 显示（IMU 姿态面板），平衡算法已迁移至固件。"""
        try:
            p, r, y = self._get_gyro_data()
            now = time.time()
            self._latest_pitch = float(p)
            self._latest_roll = float(r)
            self._latest_yaw = float(y)

            gyro_ui_period = float(getattr(self, '_gyro_ui_period', 0.12) or 0.12)
            last_gyro_ui_t = float(getattr(self, '_last_gyro_ui_update_time', 0.0) or 0.0)
            if (now - last_gyro_ui_t) >= max(0.02, gyro_ui_period):
                if 'gyro_panel' in self.root_widget.ids:
                    self.root_widget.ids.gyro_panel.update(p, r, y)
                self._last_gyro_ui_update_time = now
        except Exception as e:
            try:
                now = time.time()
                tb = traceback.format_exc()
                first_line = tb.splitlines()[-1] if tb else str(e)
                if (
                    first_line != getattr(self, '_last_loop_error', None)
                    or (now - getattr(self, '_last_loop_error_time', 0)) > 5
                ):
                    try:
                        RuntimeStatusLogger.log_error(f'Loop Error: {first_line}')
                    except Exception:
                        pass
                    try:
                        logging.exception(f'Loop Error: {first_line}')
                    except Exception:
                        print(f'Loop Error: {first_line}')
                    self._last_loop_error = first_line
                    self._last_loop_error_time = now
            except Exception:
                pass

    # ================== 表情 Demo ==================
    def _demo_emotion_loop(self, dt):
        faces = ['normal', 'happy', 'sad', 'angry', 'surprised', 'sleepy', 'thinking', 'wink']
        emo = faces[self._demo_step % len(faces)]
        self._demo_step += 1
        self.set_emotion(emo)
        face = self.root_widget.ids.get('face')
        if face:
            if emo in ('happy', 'angry', 'surprised'):
                face.start_talking()
            else:
                face.stop_talking()

    def _demo_eye_move(self, dt):
        face = self.root_widget.ids.get('face')
        if not face:
            return
        t = Clock.get_time()
        face.look_at(math.sin(t), math.cos(t * 0.7) * 0.5)

    # ============== AI ==============
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
            cfg_path = Path(getattr(self, 'user_data_dir', '.')) / 'ai_settings.json'
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            data = {'profile_name': str(profile_name or 'deepseek'), 'api_key': str(api_key or '')}
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load_ai_settings(self):
        try:
            cfg_path = Path(getattr(self, 'user_data_dir', '.')) / 'ai_settings.json'
            if not cfg_path.exists():
                return {}
            with open(cfg_path, 'r', encoding='utf-8') as f:
                return dict(json.load(f) or {})
        except Exception:
            return {}

    def test_ai_chat(self, text):
        if not self.ai_core:
            return False
        try:
            self.ai_core.send_text(str(text or '').strip())
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

    def start_ai_voice_chat(self, language='zh-CN'):
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
            return 'AI not initialized'
        try:
            return str(self.ai_core.get_last_voice_error() or '')
        except Exception:
            return ''

    def test_ai_connection(self):
        if not self.ai_core:
            return False, 'AI not initialized'
        try:
            return self.ai_core.test_connection()
        except Exception as e:
            return False, str(e)

    def test_ai_tts(self, text='你好，我是 RobotBrain，语音播报测试成功。'):
        try:
            return bool(ai_runtime.speak_text(self, text))
        except Exception:
            return False

    def get_ai_tts_status(self):
        try:
            channel = str(getattr(self, '_tts_channel', 'unknown') or 'unknown')
            err = str(getattr(self, '_tts_last_error', '') or '')
            return {'channel': channel, 'error': err}
        except Exception:
            return {'channel': 'unknown', 'error': ''}

    def get_ai_latency_status(self):
        stt_wait = stt_rec = llm_first = llm_total = 0
        try:
            if self.ai_core and hasattr(self.ai_core, 'get_latency_snapshot'):
                snap = dict(self.ai_core.get_latency_snapshot() or {})
                stt_wait = int(snap.get('stt_wait_ms') or 0)
                stt_rec = int(snap.get('stt_rec_ms') or 0)
                llm_first = int(snap.get('llm_first_ms') or 0)
                llm_total = int(snap.get('llm_total_ms') or 0)
        except Exception:
            pass
        tts_ms = 0
        try:
            tts_ms = int(getattr(self, '_tts_last_ms', 0) or 0)
        except Exception:
            pass
        return {
            'stt_wait_ms': stt_wait, 'stt_rec_ms': stt_rec,
            'llm_first_ms': llm_first, 'llm_total_ms': llm_total, 'tts_ms': tts_ms,
        }

    # ================== 退出清理 ==================
    def on_stop(self):
        try:
            ctrl = getattr(self, 'wifi_servo', None) or get_wifi_servo()
            if ctrl:
                ctrl.close()
        except Exception:
            pass
        try:
            e_runtime.stop_background_discovery(self)
        except Exception:
            pass

    # ================== 外部接口 ==================
    def set_emotion(self, emo):
        if 'face' in self.root_widget.ids:
            self.root_widget.ids.face.set_emotion(emo)