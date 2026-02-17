from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.textinput import TextInput

from app.theme import FONT


class FontSpinnerOption(SpinnerOption):
    def __init__(self, **kwargs):
        kwargs.setdefault("font_name", FONT)
        super().__init__(**kwargs)


class AIModelPanel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(6), padding=dp(8), **kwargs)
        self.size_hint_y = None
        self.bind(minimum_height=self.setter("height"))

        self.app = App.get_running_app()
        self._voice_recording = False
        self._record_blink_event = None
        self._record_blink_on = False

        model_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        self.model_spinner = Spinner(
            text="deepseek",
            values=self._read_models(),
            font_name=FONT,
            option_cls=FontSpinnerOption,
        )
        btn_refresh = Button(text="刷新", font_name=FONT, size_hint_x=None, width=dp(72))
        model_row.add_widget(self.model_spinner)
        model_row.add_widget(btn_refresh)
        self.add_widget(model_row)

        self.key_input = TextInput(
            hint_text="API Key",
            font_name=FONT,
            password=False,
            multiline=False,
            size_hint_y=None,
            height=dp(38),
        )
        self.add_widget(self.key_input)

        model_actions = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        btn_apply = Button(text="应用模型", font_name=FONT)
        btn_save = Button(text="保存配置", font_name=FONT)
        btn_test_conn = Button(text="连接测试", font_name=FONT)
        model_actions.add_widget(btn_apply)
        model_actions.add_widget(btn_save)
        model_actions.add_widget(btn_test_conn)
        self.add_widget(model_actions)

        voice_actions = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        btn_voice_start = Button(text="开始对话", font_name=FONT)
        btn_voice_stop = Button(text="结束对话", font_name=FONT)
        btn_tts_test = Button(text="语音自检", font_name=FONT)
        voice_actions.add_widget(btn_voice_start)
        voice_actions.add_widget(btn_voice_stop)
        voice_actions.add_widget(btn_tts_test)
        self.add_widget(voice_actions)

        self.status = Label(
            text="状态：待机",
            font_name=FONT,
            size_hint_y=None,
            height=dp(22),
            color=(0.74, 0.84, 0.95, 1),
            halign="left",
            valign="middle",
        )
        self.status.bind(size=self.status.setter("text_size"))
        self.add_widget(self.status)

        self.tts_status = Label(
            text="TTS：unknown",
            font_name=FONT,
            size_hint_y=None,
            height=dp(22),
            color=(0.67, 0.78, 0.9, 1),
            halign="left",
            valign="middle",
        )
        self.tts_status.bind(size=self.tts_status.setter("text_size"))
        self.add_widget(self.tts_status)

        self.latency_status = Label(
            text="延迟：STT 0+0ms | LLM 0/0ms | TTS 0ms",
            font_name=FONT,
            size_hint_y=None,
            height=dp(22),
            color=(0.64, 0.76, 0.88, 1),
            halign="left",
            valign="middle",
        )
        self.latency_status.bind(size=self.latency_status.setter("text_size"))
        self.add_widget(self.latency_status)

        self.recording_indicator = Label(
            text="● 未对话",
            font_name=FONT,
            size_hint_y=None,
            height=dp(22),
            color=(0.65, 0.65, 0.68, 1),
            halign="left",
            valign="middle",
        )
        self.recording_indicator.bind(size=self.recording_indicator.setter("text_size"))
        self.add_widget(self.recording_indicator)

        btn_apply.bind(on_release=self._apply_model)
        btn_refresh.bind(on_release=self._refresh_models)
        btn_save.bind(on_release=self._save_settings)
        btn_test_conn.bind(on_release=self._test_connection)
        btn_voice_start.bind(on_release=self._start_voice_chat)
        btn_voice_stop.bind(on_release=self._stop_voice_chat)
        btn_tts_test.bind(on_release=self._test_tts)

        Clock.schedule_once(lambda dt: self._init_from_saved_settings(), 0)
        Clock.schedule_interval(self._sync_runtime_state, 0.8)

    def _read_models(self):
        try:
            models = list(self.app.get_ai_models() or [])
            return tuple(models) if models else ("deepseek",)
        except Exception:
            return ("deepseek",)

    def _refresh_models(self, *_args):
        vals = self._read_models()
        self.model_spinner.values = vals
        if self.model_spinner.text not in vals:
            self.model_spinner.text = vals[0]
        self._refresh_current()

    def _init_from_saved_settings(self):
        try:
            data = dict(self.app.load_ai_settings() or {})
            saved_profile = str(data.get("profile_name") or "").strip()
            saved_key = str(data.get("api_key") or "")
            if saved_profile and saved_profile in (self.model_spinner.values or []):
                self.model_spinner.text = saved_profile
            if saved_key:
                self.key_input.text = saved_key
        except Exception:
            pass
        self._refresh_current()

    def _refresh_current(self):
        try:
            ai_core = getattr(self.app, "ai_core", None)
            if not ai_core:
                self.status.text = "状态：AI 未初始化"
                self.tts_status.text = "TTS：unknown"
                return
            cur = str(getattr(ai_core, "profile_name", "deepseek"))
            self.model_spinner.text = cur
            online = bool(getattr(ai_core, "enabled", False))
            self.status.text = f"状态：{cur} | {'在线' if online else '离线'}"
            self._sync_runtime_state(0)
        except Exception:
            self.status.text = "状态：读取失败"
            self.tts_status.text = "TTS：unknown"

    def _apply_model(self, *_args):
        model = str(self.model_spinner.text or "deepseek").strip()
        api_key = str(self.key_input.text or "").strip() or None
        try:
            ok = bool(self.app.set_ai_model(model, api_key=api_key))
            if ok:
                self._refresh_current()
            else:
                self.status.text = f"状态：切换失败 ({model})"
        except Exception as e:
            self.status.text = f"状态：切换异常 {e}"

    def _save_settings(self, *_args):
        profile = str(self.model_spinner.text or "deepseek").strip()
        api_key = str(self.key_input.text or "").strip()
        try:
            ok = bool(self.app.save_ai_settings(profile, api_key))
            self.status.text = "状态：配置已持久化保存" if ok else "状态：配置保存失败"
        except Exception as e:
            self.status.text = f"状态：配置保存异常 {e}"

    def _test_connection(self, *_args):
        model = str(self.model_spinner.text or "deepseek").strip()
        api_key = str(self.key_input.text or "").strip() or None
        try:
            self.app.set_ai_model(model, api_key=api_key)
        except Exception:
            pass

        try:
            ok, msg = self.app.test_ai_connection()
            self.status.text = f"状态：{'连接成功' if ok else '连接失败'}（{msg}）"
        except Exception as e:
            self.status.text = f"状态：连接测试异常 {e}"

    def _test_tts(self, *_args):
        try:
            ok = bool(self.app.test_ai_tts())
            self.status.text = "状态：语音自检已触发" if ok else "状态：语音自检失败"
            Clock.schedule_once(self._sync_runtime_state, 0.2)
        except Exception as e:
            self.status.text = f"状态：语音自检异常 {e}"

    def _start_voice_chat(self, *_args):
        try:
            ok = bool(self.app.start_ai_voice_chat(language="zh-CN"))
            if ok:
                self._set_recording_state(True)
                self.status.text = "状态：对话中（实时语音对话已启动）"
            else:
                self._set_recording_state(False)
                reason = ""
                try:
                    reason = str(self.app.get_ai_voice_error() or "").strip()
                except Exception:
                    reason = ""
                self.status.text = f"状态：对话启动失败（{reason or '请检查麦克风权限/依赖'}）"
        except Exception as e:
            self._set_recording_state(False)
            self.status.text = f"状态：对话启动异常 {e}"

    def _stop_voice_chat(self, *_args):
        try:
            ok = bool(self.app.stop_ai_voice_chat())
            if ok:
                self._set_recording_state(False)
                self._refresh_current()
                self.status.text = self.status.text + " | 对话已结束"
            else:
                self.status.text = "状态：对话结束失败"
        except Exception as e:
            self.status.text = f"状态：对话结束异常 {e}"

    def _set_recording_state(self, is_recording):
        self._voice_recording = bool(is_recording)
        if not self._voice_recording:
            if self._record_blink_event:
                try:
                    self._record_blink_event.cancel()
                except Exception:
                    pass
                self._record_blink_event = None
            self._record_blink_on = False
            self.recording_indicator.text = "● 未对话"
            self.recording_indicator.color = (0.65, 0.65, 0.68, 1)
            return

        self.recording_indicator.text = "● 对话中"
        self.recording_indicator.color = (1.0, 0.25, 0.25, 1)

        if self._record_blink_event:
            try:
                self._record_blink_event.cancel()
            except Exception:
                pass
            self._record_blink_event = None

        def _blink(_dt):
            if not self._voice_recording:
                return False
            self._record_blink_on = not self._record_blink_on
            self.recording_indicator.color = (
                (1.0, 0.25, 0.25, 1) if self._record_blink_on else (1.0, 0.25, 0.25, 0.32)
            )
            return True

        self._record_blink_event = Clock.schedule_interval(_blink, 0.5)

    def _sync_runtime_state(self, _dt):
        try:
            st = dict(self.app.get_ai_tts_status() or {})
            ch = str(st.get("channel") or "unknown")
            err = str(st.get("error") or "").strip()
            if err:
                if len(err) > 36:
                    err = err[:36] + "..."
                self.tts_status.text = f"TTS：{ch} | {err}"
            else:
                self.tts_status.text = f"TTS：{ch}"
        except Exception:
            self.tts_status.text = "TTS：unknown"

        try:
            p = dict(self.app.get_ai_latency_status() or {})
            stt_wait = int(p.get("stt_wait_ms") or 0)
            stt_rec = int(p.get("stt_rec_ms") or 0)
            llm_first = int(p.get("llm_first_ms") or 0)
            llm_total = int(p.get("llm_total_ms") or 0)
            tts_ms = int(p.get("tts_ms") or 0)
            self.latency_status.text = (
                f"延迟：STT {stt_wait}+{stt_rec}ms | LLM {llm_first}/{llm_total}ms | TTS {tts_ms}ms"
            )
        except Exception:
            self.latency_status.text = "延迟：--"
