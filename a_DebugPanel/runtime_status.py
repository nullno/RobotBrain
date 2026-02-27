"""
RuntimeStatusPanel - 运行状态面板（简化版，来自 widgets/runtime_status.py）
"""
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.utils import platform as _kivy_platform
from collections import deque
import threading
import time
import logging
import os


def _pick_emoji_font():
    candidates = [
        'assets/fonts/NotoColorEmoji.ttf',
        'assets/fonts/NotoEmoji-Regular.ttf',
        'assets/fonts/simhei.ttf',
        r'C:\Windows\Fonts\seguiemj.ttf',
        '/system/fonts/NotoColorEmoji.ttf',
        '/system/fonts/NotoColorEmoji-Regular.ttf',
        '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf',
        '/System/Library/Fonts/Apple Color Emoji.ttc',
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                return p
        except Exception:
            pass
    return None


class RuntimeStatusPanel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', size_hint=(None, None), **kwargs)

        self._expanded_width = dp(280)
        self._expanded_height = dp(100)
        self._collapsed_width = dp(220)
        self._collapsed_height = dp(32)
        self._expanded = True
        self.width = self._expanded_width
        self.height = self._expanded_height

        self.logs = deque(maxlen=80)
        self._lock = threading.Lock()
        self._dirty = True
        self._last_render_text = None

        with self.canvas.before:
            Color(0, 0, 0, 0)
            self._bg_rect = RoundedRectangle(radius=[8], pos=self.pos, size=self.size)

        def _update_bg(*_):
            try:
                self._bg_rect.pos = self.pos
                self._bg_rect.size = self.size
            except Exception:
                pass

        self.bind(pos=_update_bg, size=_update_bg)

        self.scroll_view = ScrollView(size_hint=(1, 1))
        emoji_font = _pick_emoji_font()
        label_kwargs = {}
        if emoji_font:
            label_kwargs['font_name'] = emoji_font
        self.log_label = Label(
            text='[等待信息...]',
            markup=True,
            size_hint_y=None,
            color=(0.85, 0.9, 0.98, 1.0),
            font_size='10sp',
            halign='left',
            valign='top',
            text_size=(dp(270), None),
            **label_kwargs,
        )
        self.log_label.bind(texture_size=self.log_label.setter('size'))
        self.scroll_view.add_widget(self.log_label)
        self.add_widget(self.scroll_view)

        refresh_interval = 0.45 if _kivy_platform == 'android' else 0.25
        Clock.schedule_interval(self._refresh_display, refresh_interval)

    def toggle_visible(self):
        self._expanded = not self._expanded
        if self._expanded:
            self.width = self._expanded_width
            self.height = self._expanded_height
            self.log_label.text_size = (dp(270), None)
            self.scroll_view.opacity = 1.0
            self.scroll_view.disabled = False
            self._dirty = True
        else:
            self.width = self._collapsed_width
            self.height = self._collapsed_height
            self.scroll_view.opacity = 0.0
            self.scroll_view.disabled = True

    def add_log(self, message: str, category: str = 'info'):
        timestamp = time.strftime('%H:%M:%S')
        color_map = {
            'info': '[color=00e6ff]',
            'action': '[color=00ff88]',
            'servo': '[color=ffdd00]',
            'error': '[color=ff5555]',
        }
        color_tag = color_map.get(category, color_map['info'])
        try:
            message = str(message).replace("\ufe0f", "")
        except Exception:
            pass
        formatted_log = f"{color_tag}{timestamp}[/color] {message}"
        with self._lock:
            self.logs.append(formatted_log)
            self._dirty = True

    def _refresh_display(self, dt):
        if not self._expanded:
            return
        with self._lock:
            if not self._dirty:
                return
            if self.logs:
                all_logs = '\n'.join(list(self.logs)[-30:])
            else:
                all_logs = '[color=888888][等待信息...][/color]'
            if all_logs != self._last_render_text:
                self.log_label.text = all_logs
                self._last_render_text = all_logs
            self._dirty = False


class RuntimeStatusLogger:
    _panel = None
    _buffer = deque(maxlen=400)
    _buf_lock = threading.Lock()
    _last_msg_key = None
    _last_msg_time = 0.0
    _repeat_drop_count = 0

    @classmethod
    def set_panel(cls, panel: RuntimeStatusPanel):
        cls._panel = panel
        try:
            with cls._buf_lock:
                while cls._buffer:
                    msg, cat = cls._buffer.popleft()
                    try:
                        cls._panel.add_log(msg, cat)
                    except Exception:
                        pass
        except Exception:
            pass

    @classmethod
    def log(cls, message: str, category: str = 'info'):
        try:
            msg_text = str(message)
        except Exception:
            msg_text = ""
        cat = str(category or 'info')
        now = time.time()
        key = (cat, msg_text)
        if key == cls._last_msg_key and (now - cls._last_msg_time) < 0.8:
            cls._repeat_drop_count += 1
            return
        if cls._repeat_drop_count > 0:
            repeat_note = f"(重复 {cls._repeat_drop_count} 条已折叠)"
            try:
                if cls._panel:
                    cls._panel.add_log(repeat_note, 'info')
                else:
                    with cls._buf_lock:
                        cls._buffer.append((repeat_note, 'info'))
            except Exception:
                pass
            cls._repeat_drop_count = 0
        cls._last_msg_key = key
        cls._last_msg_time = now
        if cls._panel:
            try:
                cls._panel.add_log(msg_text, cat)
            except Exception:
                try:
                    if cat == 'error':
                        logging.getLogger().error(msg_text)
                    else:
                        logging.getLogger().info(msg_text)
                except Exception:
                    try:
                        print(msg_text)
                    except Exception:
                        pass
        else:
            try:
                with cls._buf_lock:
                    cls._buffer.append((msg_text, cat))
            except Exception:
                pass
            try:
                if cat == 'error':
                    logging.getLogger().error(msg_text)
                else:
                    logging.getLogger().info(msg_text)
            except Exception:
                try:
                    print(msg_text)
                except Exception:
                    pass

    @classmethod
    def log_action(cls, action: str, details: str = ''):
        msg = f"-> {action}"
        if details:
            msg += f" - {details}"
        cls.log(msg, 'action')

    @classmethod
    def log_servo(cls, servo_id: int, position: int, angle: float = None):
        msg = f"舵机 {servo_id}: 位置={position}"
        if angle is not None:
            msg += f" (角度={angle:.1f}°)"
        cls.log(msg, 'servo')

    @classmethod
    def log_error(cls, error: str):
        try:
            text = str(error)
        except Exception:
            text = ""
        if text.lstrip().startswith("x "):
            msg = text
        else:
            msg = f"x {text}"
        cls.log(msg, 'error')

    @classmethod
    def log_info(cls, info: str):
        try:
            text = str(info)
        except Exception:
            text = ""
        if text.lstrip().startswith("->"):
            msg = text
        else:
            msg = f"-> {text}"
        cls.log(msg, 'info')
