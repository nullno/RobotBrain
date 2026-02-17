import base64
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests
from kivy.clock import Clock
from kivy.event import EventDispatcher
from kivy.logger import Logger
from kivy.utils import platform


@dataclass
class ModelProfile:
    name: str
    base_url: str
    text_model: str
    vision_model: str
    api_key_env: str = "ROBOTBRAIN_LLM_API_KEY"
    timeout_sec: int = 60


class VoiceAI(EventDispatcher):
    __events__ = ("on_action_command", "on_speech_output")

    def __init__(self, api_key=None, profile_name=None, config_path=None, history_turns=8):
        super().__init__()
        self.is_thinking = False
        self._lock = threading.Lock()
        self._history_turns = max(2, int(history_turns))
        self._history: List[Dict[str, str]] = []
        self._streamed_chars = 0
        self._realtime_text_buf = ""
        self._realtime_flush_event = None
        self._pending_inputs: List[Dict[str, Optional[bytes]]] = []

        self._voice_sr = None
        self._voice_mic = None
        self._voice_stop_listener = None
        self._voice_thread = None
        self._voice_running = False
        self._stt_ignore_until = 0.0
        self._perf = {
            "stt_wait_ms": 0,
            "stt_rec_ms": 0,
            "llm_first_ms": 0,
            "llm_total_ms": 0,
            "updated_at": 0.0,
        }
        self.last_voice_error = ""
        self.last_chat_error = ""

        self._profiles, cfg_default_profile = self._load_profiles(config_path)
        self.profile_name = profile_name or os.environ.get("ROBOTBRAIN_LLM_PROFILE") or cfg_default_profile or "deepseek"
        if self.profile_name not in self._profiles:
            self.profile_name = "deepseek"
        self.profile = self._profiles[self.profile_name]

        self.api_key = self._normalize_api_key(
            api_key or os.environ.get(self.profile.api_key_env) or os.environ.get("ROBOTBRAIN_LLM_API_KEY")
        )
        self.enabled = bool(self.api_key)

        if self.enabled:
            Logger.info(f"AI: online mode. profile={self.profile_name}, model={self.profile.text_model}")
        else:
            Logger.warning("AI: API key missing. Running in MOCK mode.")

        self.system_prompt = """
你是一个活泼可爱的人形机器人。你要结合视觉和对话做决策。
必须只输出 JSON，不能包含任何 JSON 外文字。格式如下：
{
  "thought": "内部思考，简短",
  "speech": "对主人说的话，必须短句口语化",
  "emotion": "normal|happy|sad|angry|surprised|thinking|wink",
  "action": "walk|stop|nod|shake_head|wave|sit|stand|twist|none"
}
规则：
1) 默认 action=none，只有主人明确要求动作时才输出动作。
2) 安全优先：动作不确定时输出 stop。
3) speech 尽量 8~24 字，适合实时播报。
""".strip()

    def on_action_command(self, action, emotion):
        pass

    def on_speech_output(self, text):
        pass

    def list_profiles(self):
        return list(self._profiles.keys())

    def get_profiles(self):
        return self.list_profiles()

    def switch_profile(self, profile_name, api_key=None):
        if profile_name not in self._profiles:
            raise ValueError(f"Unknown profile: {profile_name}")
        self.profile_name = profile_name
        self.profile = self._profiles[profile_name]
        self.api_key = self._normalize_api_key(
            api_key or os.environ.get(self.profile.api_key_env) or os.environ.get("ROBOTBRAIN_LLM_API_KEY")
        )
        self.enabled = bool(self.api_key)
        Logger.info(f"AI: switched profile={self.profile_name}, online={self.enabled}")

    def set_profile(self, profile_name, api_key=None):
        self.switch_profile(profile_name, api_key=api_key)

    def process_input(self, image_data=None, user_text=None):
        text = str(user_text or "").strip()
        with self._lock:
            if self.is_thinking:
                self._pending_inputs.append({"image_data": image_data, "user_text": text})
                Logger.info(f"AI: busy, queued input. queue_size={len(self._pending_inputs)}")
                return
            self.is_thinking = True
        threading.Thread(target=self._ai_thread, args=(image_data, text), daemon=True).start()

    def send_text(self, text, image_data=None):
        self.process_input(image_data=image_data, user_text=text)

    def send_realtime_text(self, partial_text, image_data=None, is_final=False, debounce_sec=0.45):
        """实时文本输入入口：
        - partial_text: 语音识别中间文本（可多次调用）
        - is_final: True 时立即触发一次 AI 推理
        - debounce_sec: 中间文本静默触发间隔
        """
        partial_text = str(partial_text or "").strip()
        if not partial_text:
            return

        self._realtime_text_buf = partial_text
        if self._realtime_flush_event:
            try:
                self._realtime_flush_event.cancel()
            except Exception:
                pass
            self._realtime_flush_event = None

        def _flush(_dt):
            txt = str(self._realtime_text_buf or "").strip()
            self._realtime_flush_event = None
            if txt:
                self.send_text(txt, image_data=image_data)

        if is_final:
            Clock.schedule_once(_flush, 0)
        else:
            self._realtime_flush_event = Clock.schedule_once(_flush, max(0.1, float(debounce_sec)))

    def stream_text(self, partial_text, image_data=None, is_final=False, debounce_sec=0.45):
        self.send_realtime_text(
            partial_text=partial_text,
            image_data=image_data,
            is_final=is_final,
            debounce_sec=debounce_sec,
        )

    def start_voice_capture(self, language="zh-CN", phrase_time_limit=4):
        """启动麦克风录音并转文字（可选依赖 SpeechRecognition）。"""
        self.last_voice_error = ""

        if self._voice_running:
            Logger.info("AI: voice capture already running.")
            return True

        if platform == "android":
            try:
                perms = __import__("android.permissions", fromlist=["check_permission", "Permission"])
                check_permission = getattr(perms, "check_permission", None)
                permission_cls = getattr(perms, "Permission", None)
                record_audio = getattr(permission_cls, "RECORD_AUDIO", None) if permission_cls else None
                if check_permission and record_audio and (not check_permission(record_audio)):
                    self.last_voice_error = "Android 麦克风权限未授予（RECORD_AUDIO）"
                    Logger.warning(f"AI: {self.last_voice_error}")
                    return False
            except Exception:
                pass

        try:
            import speech_recognition as sr
        except Exception:
            self.last_voice_error = "缺少依赖 SpeechRecognition"
            Logger.warning("AI: speech_recognition not installed. voice capture unavailable.")
            self._emit_speech_stream("录音功能未安装，请先安装语音识别依赖。")
            return False

        try:
            self._voice_sr = sr.Recognizer()
            self._voice_mic = sr.Microphone()

            try:
                self._voice_sr.dynamic_energy_threshold = True
                self._voice_sr.energy_threshold = 120
                self._voice_sr.pause_threshold = 0.6
                self._voice_sr.non_speaking_duration = 0.3
                self._voice_sr.phrase_threshold = 0.2
            except Exception:
                pass

            self._voice_running = True
            self._dispatch_speech_on_main("[系统] 对话已开始，请直接说话。")

            def _loop():
                try:
                    with self._voice_mic as source:
                        try:
                            self._voice_sr.adjust_for_ambient_noise(source, duration=0.5)
                        except Exception:
                            pass

                        while self._voice_running:
                            if time.time() < float(getattr(self, "_stt_ignore_until", 0.0) or 0.0):
                                time.sleep(0.08)
                                continue
                            listen_start = time.time()
                            try:
                                audio = self._voice_sr.listen(
                                    source,
                                    timeout=1,
                                    phrase_time_limit=max(2, int(phrase_time_limit)),
                                )
                                listen_ms = int((time.time() - listen_start) * 1000)
                            except sr.WaitTimeoutError:
                                continue
                            except Exception as e:
                                self.last_voice_error = f"语音监听异常: {e}"
                                self._dispatch_speech_on_main("[系统] 语音监听异常，请重试。")
                                continue

                            if not self._voice_running:
                                break

                            try:
                                rec_start = time.time()
                                text = self._voice_sr.recognize_google(audio, language=language)
                                rec_ms = int((time.time() - rec_start) * 1000)
                                text = str(text or "").strip()
                                if text:
                                    if time.time() < float(getattr(self, "_stt_ignore_until", 0.0) or 0.0):
                                        continue
                                    self._perf["stt_wait_ms"] = max(0, int(listen_ms))
                                    self._perf["stt_rec_ms"] = max(0, int(rec_ms))
                                    self._perf["updated_at"] = time.time()
                                    try:
                                        Logger.info(
                                            f"AI PERF STT: wait={self._perf['stt_wait_ms']}ms rec={self._perf['stt_rec_ms']}ms"
                                        )
                                    except Exception:
                                        pass
                                    try:
                                        Logger.info(f"AI STT: {text}")
                                    except Exception:
                                        pass
                                    try:
                                        print(f"[STT] {text}")
                                    except Exception:
                                        pass
                                    self._dispatch_speech_on_main(f"[我] {text}")
                                    self.send_realtime_text(text, is_final=True)
                            except sr.UnknownValueError:
                                continue
                            except sr.RequestError as e:
                                self.last_voice_error = f"语音识别服务不可用: {e}"
                                self._dispatch_speech_on_main("[系统] 语音识别服务不可用，请检查网络。")
                            except Exception as e:
                                self.last_voice_error = f"语音识别异常: {e}"
                                self._dispatch_speech_on_main("[系统] 语音识别异常，请重试。")
                finally:
                    self._voice_running = False

            self._voice_thread = threading.Thread(target=_loop, daemon=True)
            self._voice_thread.start()
            Logger.info("AI: voice capture started.")
            return True
        except Exception as e:
            Logger.error(f"AI: failed to start voice capture: {e}")
            self.last_voice_error = str(e)
            self._voice_sr = None
            self._voice_mic = None
            self._voice_stop_listener = None
            self._voice_thread = None
            self._voice_running = False
            return False

    def stop_voice_capture(self):
        try:
            self._voice_running = False
            if self._voice_stop_listener:
                self._voice_stop_listener(wait_for_stop=False)
            self._voice_stop_listener = None
            self._voice_sr = None
            self._voice_mic = None
            self._voice_thread = None
            self._dispatch_speech_on_main("[系统] 对话已结束。")
            Logger.info("AI: voice capture stopped.")
            return True
        except Exception as e:
            self.last_voice_error = str(e)
            return False

    def get_last_voice_error(self):
        return str(self.last_voice_error or "")

    def test_connection(self):
        """测试当前模型与 API Key 是否可用（不触发语音对话流程）。"""
        if not self.enabled:
            self.last_chat_error = "AI API Key 为空"
            return False, self.last_chat_error

        model = self.profile.text_model
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0,
            "max_tokens": 8,
            "stream": False,
        }

        key = self._normalize_api_key(self.api_key)
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

        last_error = None
        for url in self._candidate_chat_urls(self.profile.base_url):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.profile.timeout_sec,
                )
                if resp.status_code == 401:
                    raise RuntimeError(f"401 Unauthorized: Key 无效或未开通。url={url}")
                if resp.status_code == 402:
                    raise RuntimeError(
                        f"402 Payment Required: 账户余额不足或未开通计费/模型权限。url={url}"
                    )
                if resp.status_code == 404:
                    raise RuntimeError(f"404 Not Found: endpoint 不存在。url={url}")
                resp.raise_for_status()
                return True, f"连接成功: profile={self.profile_name}, model={model}"
            except Exception as e:
                last_error = e
                msg = str(e)
                if "401" in msg or "Unauthorized" in msg or "402" in msg:
                    break
                continue

        self.last_chat_error = str(last_error or "AI 连接测试失败")
        return False, self.last_chat_error

    def _ai_thread(self, image_data, user_text):
        try:
            if not self.enabled:
                self._mock_response(user_text)
                return

            self._streamed_chars = 0
            messages = self._build_messages(image_data=image_data, user_text=user_text)
            raw_text, first_ms, total_ms = self._chat_stream(messages, use_vision=bool(image_data))
            self._perf["llm_first_ms"] = max(0, int(first_ms))
            self._perf["llm_total_ms"] = max(0, int(total_ms))
            self._perf["updated_at"] = time.time()
            Logger.info(f"AI PERF LLM: first={self._perf['llm_first_ms']}ms total={self._perf['llm_total_ms']}ms")
            result_json = self._parse_json_result(raw_text)
            if not result_json:
                Logger.error(f"AI: invalid JSON result: {raw_text}")
                self._emit_speech_stream("我刚刚没组织好语言，再说一次好吗？")
                return

            self._append_history("user", str(user_text or ""))
            self._append_history("assistant", str(result_json.get("speech", "")))
            self._execute_command(result_json)
        except Exception as e:
            self.last_chat_error = str(e)
            Logger.error(f"AI Error: {e}")
            err = str(e)
            if "401" in err or "Unauthorized" in err or "认证失败" in err:
                self._emit_speech_stream("AI 鉴权失败，请检查模型和 API Key。")
            elif "402" in err or "Payment Required" in err:
                self._emit_speech_stream("AI 服务余额不足或未开通计费，请先充值或开通权限。")
            else:
                self._emit_speech_stream("网络有点卡，我的大脑短路了一下。")
        finally:
            next_item = None
            with self._lock:
                if self._pending_inputs:
                    next_item = self._pending_inputs.pop(0)
                    self.is_thinking = True
                else:
                    self.is_thinking = False

            if next_item is not None:
                threading.Thread(
                    target=self._ai_thread,
                    args=(next_item.get("image_data"), next_item.get("user_text")),
                    daemon=True,
                ).start()

    def _build_messages(self, image_data=None, user_text=None):
        messages = [{"role": "system", "content": self.system_prompt}]
        for item in self._history[-self._history_turns * 2 :]:
            messages.append({"role": item["role"], "content": item["content"]})

        prompt = f"主人刚刚说：{user_text}。请像连续对话一样自然回应。" if user_text else "请根据当前画面进行一句自然回应。"
        if image_data:
            b64_img = base64.b64encode(image_data).decode("utf-8")
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
                        },
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": prompt})
        return messages

    def _chat_stream(self, messages, use_vision=False):
        model = self.profile.vision_model if use_vision else self.profile.text_model
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 500,
            "stream": True,
        }
        key = self._normalize_api_key(self.api_key)
        if not key:
            raise RuntimeError("AI API Key 为空")
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

        output = ""
        request_start = time.time()
        first_piece_at = None
        last_error = None
        for url in self._candidate_chat_urls(self.profile.base_url):
            try:
                with requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=self.profile.timeout_sec,
                ) as resp:
                    if resp.status_code == 401:
                        raise RuntimeError(
                            f"401 Unauthorized: AI API 认证失败，请检查 Key/模型/服务商。url={url}"
                        )
                    if resp.status_code == 402:
                        raise RuntimeError(
                            f"402 Payment Required: 账户余额不足或未开通计费/模型权限。url={url}"
                        )
                    if resp.status_code == 404:
                        raise RuntimeError(f"404 Not Found: endpoint 不存在。url={url}")
                    resp.raise_for_status()
                    for line in resp.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        if not str(line).startswith("data:"):
                            continue
                        data = str(line)[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            packet = json.loads(data)
                        except Exception:
                            continue
                        delta = ((packet.get("choices") or [{}])[0]).get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            if first_piece_at is None:
                                first_piece_at = time.time()
                            output += str(piece)
                            self._emit_streaming_speech_from_json(output)
                    total_ms = int((time.time() - request_start) * 1000)
                    first_ms = int((first_piece_at - request_start) * 1000) if first_piece_at else total_ms
                    return output, first_ms, total_ms
            except Exception as e:
                last_error = e
                msg = str(e)
                if "401" in msg or "Unauthorized" in msg or "402" in msg:
                    break
                continue

        raise RuntimeError(str(last_error or "AI 请求失败"))

    def get_latency_snapshot(self):
        try:
            return dict(self._perf)
        except Exception:
            return {
                "stt_wait_ms": 0,
                "stt_rec_ms": 0,
                "llm_first_ms": 0,
                "llm_total_ms": 0,
                "updated_at": 0.0,
            }

    def _candidate_chat_urls(self, base_url):
        base = str(base_url or "").rstrip("/")
        if not base:
            return []
        urls = [base + "/chat/completions"]
        if not base.endswith("/v1") and not base.endswith("v1"):
            urls.append(base + "/v1/chat/completions")
        return urls

    def _normalize_api_key(self, key):
        if key is None:
            return ""
        s = str(key).strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()
        return s

    def _emit_streaming_speech_from_json(self, text):
        speech = self._extract_speech_partial(text)
        if not speech:
            return
        if len(speech) <= self._streamed_chars:
            return
        chunk = speech[self._streamed_chars :]
        self._streamed_chars = len(speech)
        self._dispatch_speech_on_main(chunk)

    def _parse_json_result(self, text):
        json_text = self._extract_json_object(text)
        if not json_text:
            return None
        try:
            return json.loads(json_text)
        except Exception:
            return None

    def _extract_json_object(self, text):
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return ""
        return text[start : end + 1]

    def _extract_speech_partial(self, text):
        m = re.search(r'"speech"\s*:\s*"((?:\\.|[^"\\])*)', text)
        if not m:
            return ""
        raw = m.group(1)
        try:
            return json.loads(f'"{raw}"')
        except Exception:
            return raw.replace("\\n", "\n").replace('\\"', '"')

    def _execute_command(self, data):
        action = str(data.get("action", "none") or "none")
        emotion = str(data.get("emotion", "normal") or "normal")
        speech = str(data.get("speech", "") or "")

        Logger.info(f"AI Decision: action={action}, emotion={emotion}, speech={speech}")
        self._dispatch_action_on_main(action, emotion)

        if speech:
            if self._streamed_chars < len(speech):
                self._dispatch_speech_on_main(speech[self._streamed_chars :])
            self._streamed_chars = 0

    def _dispatch_action_on_main(self, action, emotion):
        def _do(_dt):
            try:
                self.dispatch("on_action_command", action, emotion)
            except Exception as e:
                Logger.error(f"AI: action dispatch failed: {e}")

        Clock.schedule_once(_do, 0)

    def _dispatch_speech_on_main(self, text):
        if not text:
            return

        def _do(_dt):
            try:
                self.dispatch("on_speech_output", text)
            except Exception as e:
                Logger.error(f"AI: speech dispatch failed: {e}")

        Clock.schedule_once(_do, 0)

    def _append_history(self, role, content):
        item = {"role": str(role), "content": str(content)}
        self._history.append(item)
        max_items = self._history_turns * 2
        if len(self._history) > max_items:
            self._history = self._history[-max_items:]

    def _emit_speech_stream(self, text, chunk_size=2, interval=0.06):
        if not text:
            return
        text = str(text)
        chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
        state = {"idx": 0}

        def _tick(_dt):
            i = state["idx"]
            if i >= len(chunks):
                return False
            self._dispatch_speech_on_main(chunks[i])
            state["idx"] += 1
            return state["idx"] < len(chunks)

        Clock.schedule_interval(_tick, interval)

    def _mock_response(self, text):
        time.sleep(0.8)
        mock_data = {
            "thought": "离线模拟模式",
            "speech": f"听到你说：{text}，我现在离线。",
            "emotion": "thinking",
            "action": "none",
        }
        if text:
            if "走" in text:
                mock_data.update({"action": "walk", "speech": "好的，开始行走。", "emotion": "happy"})
            elif "停" in text:
                mock_data.update({"action": "stop", "speech": "收到，我先停下。", "emotion": "normal"})
            elif "点头" in text:
                mock_data.update({"action": "nod", "speech": "明白，我点点头。", "emotion": "wink"})
        self._execute_command(mock_data)

    def _load_profiles(self, config_path=None):
        defaults = {
            "deepseek": ModelProfile(
                name="deepseek",
                base_url="https://api.deepseek.com",
                text_model="deepseek-chat",
                vision_model="deepseek-vl2",
                api_key_env="ROBOTBRAIN_LLM_API_KEY",
                timeout_sec=60,
            ),
            "openai": ModelProfile(
                name="openai",
                base_url="https://api.openai.com/v1",
                text_model="gpt-4o-mini",
                vision_model="gpt-4o-mini",
                api_key_env="ROBOTBRAIN_OPENAI_API_KEY",
                timeout_sec=60,
            ),
            "qwen": ModelProfile(
                name="qwen",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                text_model="qwen-plus",
                vision_model="qwen-vl-plus",
                api_key_env="ROBOTBRAIN_QWEN_API_KEY",
                timeout_sec=60,
            ),
            "glm": ModelProfile(
                name="glm",
                base_url="https://open.bigmodel.cn/api/paas/v4",
                text_model="glm-4-plus",
                vision_model="glm-4v-plus",
                api_key_env="ROBOTBRAIN_GLM_API_KEY",
                timeout_sec=60,
            ),
        }
        cfg_path = config_path or os.environ.get("ROBOTBRAIN_AI_CONFIG") or os.path.join("data", "ai_models.json")
        if not os.path.exists(cfg_path):
            return defaults, "deepseek"

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            profiles_data = data.get("profiles") or {}
            out = dict(defaults)
            for key, value in profiles_data.items():
                out[key] = ModelProfile(
                    name=key,
                    base_url=str(value.get("base_url") or defaults.get(key, defaults["deepseek"]).base_url),
                    text_model=str(value.get("text_model") or defaults.get(key, defaults["deepseek"]).text_model),
                    vision_model=str(value.get("vision_model") or defaults.get(key, defaults["deepseek"]).vision_model),
                    api_key_env=str(value.get("api_key_env") or defaults.get(key, defaults["deepseek"]).api_key_env),
                    timeout_sec=int(value.get("timeout_sec") or defaults.get(key, defaults["deepseek"]).timeout_sec),
                )
            default_profile = str(data.get("default_profile") or "deepseek")
            return out, default_profile
        except Exception as e:
            Logger.warning(f"AI: load ai_models.json failed: {e}. use built-in defaults.")
            return defaults, "deepseek"

class 语音(VoiceAI):
    pass


AICore = VoiceAI
