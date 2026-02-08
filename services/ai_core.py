import threading
import base64
import json
import time
from kivy.event import EventDispatcher
from kivy.logger import Logger
from kivy.clock import Clock

# 动态导入 DeepSeek，如果失败则使用模拟模式
try:
    from deepseek import DeepSeek
    HAS_DEEPSEEK = True
except ImportError:
    HAS_DEEPSEEK = False

class 语音(EventDispatcher):
    # 定义事件
    __events__ = ('on_action_command', 'on_speech_output')

    def __init__(self, api_key=None):
        super().__init__()
        self.is_thinking = False
        if HAS_DEEPSEEK and api_key:
            try:
                self.client = DeepSeek(api_key=api_key)
            except Exception as e:
                Logger.warning(f"AI: Failed to init DeepSeek client: {e}. Running in MOCK mode.")
                self.client = None
        else:
            self.client = None
            Logger.warning("AI: DeepSeek library not found or API key not provided. Running in MOCK mode.")
        
        # 系统提示词 (System Prompt)
        self.system_prompt = """
        你是一个活泼可爱的人形机器人。你的任务是观察眼前的画面、听懂主人的话，并做出简短的回应。
        你的所有回复都必须严格遵循纯 JSON 格式，不得包含任何额外文字。JSON结构如下:
        {
            "thought": "这里是你内心的思考过程，用于分析情况",
            "speech": "这里是你要说出口的话，必须非常简短、口语化",
            "emotion": "从'normal', 'happy', 'sad', 'angry', 'surprised', 'thinking', 'wink'中选择一个作为你当前的表情",
            "action": "从'walk', 'stop', 'nod', 'shake_head', 'none'中选择一个你要执行的动作"
        }
        """

    def on_action_command(self, action, emotion):
        pass

    def on_speech_output(self, text):
        pass

    def process_input(self, image_data=None, user_text=None):
        if self.is_thinking:
            Logger.info("AI: is already thinking, please wait.")
            return
        self.is_thinking = True
        threading.Thread(target=self._ai_thread, args=(image_data, user_text)).start()

    def _ai_thread(self, image_data, user_text):
        try:
            if not self.client:
                self._mock_response(user_text)
                return

            messages = [{"role": "system", "content": self.system_prompt}]
            
            content_list = []
            prompt = f"主人说：'{user_text}'。请结合你看到的画面回应。" if user_text else "请根据你看到的画面进行回应。"
            content_list.append({"type": "text", "text": prompt})
            
            if image_data:
                b64_img = base64.b64encode(image_data).decode('utf-8')
                content_list.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
                })

            messages.append({"role": "user", "content": content_list})

            response = self.client.chat.completions.create(
                model="deepseek-vl-chat",
                messages=messages,
                max_tokens=500
            )

            result_content = response.choices[0].message.content
            try:
                json_part = result_content[result_content.find('{'):result_content.rfind('}')+1]
                result_json = json.loads(json_part)
                self._execute_command(result_json)
            except json.JSONDecodeError:
                Logger.error(f"AI: Failed to decode JSON from response: {result_content}")
                # 逐字输出错误提示，便于 UI 显示说话字母
                self._emit_speech_stream("我的思维有点混乱。")

        except Exception as e:
            Logger.error(f"AI Error (DeepSeek): {e}")
            self._emit_speech_stream("我的 DeepSeek 大脑短路了，请检查网络和API Key。")
        finally:
            self.is_thinking = False

    def _execute_command(self, data):
        Logger.info(f"AI Decision: {data}")
        self.dispatch('on_action_command', data.get('action', 'none'), data.get('emotion', 'normal'))
        if speech := data.get('speech', ''):
            # 使用流式逐块输出，便于 UI 实时显示说话字母
            self._emit_speech_stream(speech)

    def _emit_speech_stream(self, text, chunk_size=2, interval=0.06):
        """通过 Clock 在主线程逐块派发 on_speech_output 事件。
        chunk_size: 每次派发的字符数；interval: 每块间隔（秒）。
        """
        if not text:
            return

        # 预处理文本，确保为字符串
        text = str(text)
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

        state = { 'idx': 0 }

        def _tick(dt):
            i = state['idx']
            if i >= len(chunks):
                return False
            try:
                self.dispatch('on_speech_output', chunks[i])
            except Exception as e:
                Logger.error(f"AI: Error dispatching speech chunk: {e}")
            state['idx'] += 1
            if state['idx'] >= len(chunks):
                return False
            return True

        # 使用 Clock.schedule_interval 调度并自动停止
        Clock.schedule_interval(_tick, interval)

    def _mock_response(self, text):
        time.sleep(2)
        mock_data = { "thought": "离线模拟模式", "speech": f"听到你说: {text}，但我离线了。", "emotion": "thinking", "action": "none" }
        if text:
            if "走" in text: mock_data.update({"action": "walk", "speech": "好的，出发！", "emotion": "happy"})
            elif "停" in text: mock_data.update({"action": "stop", "speech": "收到，已停止。", "emotion": "normal"})
        self._execute_command(mock_data)
