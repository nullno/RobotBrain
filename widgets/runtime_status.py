"""
RuntimeStatusPanel - 左下角运行状态透明浮层
用于实时显示：
- 打印信息
- 动作执行状态
- 舵机指令和旋转角度
- 其他调试信息
"""

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.utils import platform as _kivy_platform
from collections import deque
import threading
import time
import logging
import os
import re


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

        # UI 尺寸设置
        self._expanded_width = dp(280)
        self._expanded_height = dp(100)
        self._collapsed_width = dp(220)
        self._collapsed_height = dp(32)
        self._expanded = True
        self.width = self._expanded_width
        self.height = self._expanded_height
        
        # 日志缓冲（最多保留最近的 80 条）
        self.logs = deque(maxlen=80)
        self._lock = threading.Lock()
        self._dirty = True
        self._last_render_text = None
        # 用户交互标记：选中文本时暂停自动滚动
        self._user_interacting = False
        self._interaction_timer = None
        
        # 绘制背景
        with self.canvas.before:
            Color(0, 0, 0, 0)  # 半透明黑色背景
            self._bg_rect = RoundedRectangle(radius=[8], pos=self.pos, size=self.size)
            # Color(0.0, 0.9, 1.0, 0.6)  # 霓虹青边框
            # self._border_line = RoundedRectangle(radius=[8], pos=self.pos, size=self.size)
        
        def _update_bg(*_):
            try:
                self._bg_rect.pos = self.pos
                self._bg_rect.size = self.size
                self._border_line.pos = self.pos
                self._border_line.size = self.size
            except Exception:
                pass
        
        self.bind(pos=_update_bg, size=_update_bg)
        
        # 日志文本区域（自由选择复制 + 支持滚动）
        _is_android = _kivy_platform == 'android'

        emoji_font = _pick_emoji_font()
        font_kw = {}
        if emoji_font:
            font_kw['font_name'] = emoji_font

        self.log_label = TextInput(
            text='[等待信息...]',
            readonly=True,
            foreground_color=(0.85, 0.9, 0.98, 1.0),
            background_color=(0, 0, 0, 0),
            font_size='10sp',
            use_bubble=True,
            use_handles=_is_android,
            allow_copy=True,
            padding=(dp(4), dp(2)),
            background_normal='',
            background_active='',
            **font_kw,
        )

        # 手机端：使用 ScrollView 包裹实现触摸滚动
        if _is_android:
            self.log_label.size_hint_y = None
            self.log_label.bind(minimum_height=self.log_label.setter('height'))
            
            self._scroll_view = ScrollView(
                size_hint=(1, 1),
                do_scroll_x=False,
                do_scroll_y=True,
                bar_width=dp(2),
                bar_color=(0, 0.9, 1, 0.3),
                bar_inactive_color=(0, 0.9, 1, 0.1),
                scroll_type=['bars', 'content'],
            )
            self._scroll_view.add_widget(self.log_label)
            self.add_widget(self._scroll_view)
        else:
            # PC端：完全不使用 ScrollView，TextInput直接原生完全支持滚轮和完美的随动选中高亮
            self.log_label.size_hint_y = 1
            self._scroll_view = None
            self.add_widget(self.log_label)
        
        # 启动日志刷新定时器（仅在内容变化时刷新）
        refresh_interval = 0.45 if _is_android else 0.25
        Clock.schedule_interval(self._refresh_display, refresh_interval)

    def on_touch_down(self, touch):
        try:
            if self.collide_point(*touch.pos) and bool(getattr(touch, 'is_double_tap', False)):
                self.toggle_visible()
                return True
        except Exception:
            pass
        # 点击日志区域外时清除选中状态和焦点
        try:
            if not self.collide_point(*touch.pos):
                self.log_label.cancel_selection()
                self.log_label.focus = False
                self._user_interacting = False
        except Exception:
            pass
        # 点击在日志区域内时标记用户交互（暂停自动滚动）
        try:
            if self.log_label.collide_point(*touch.pos):
                self._user_interacting = True
                # 暂停自动滚动和UI文本更新，延长交互时间以方便复制
                if self._interaction_timer:
                    self._interaction_timer.cancel()
                self._interaction_timer = Clock.schedule_once(
                    self._reset_interaction, 5.0
                )
        except Exception:
            pass
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        # 拖拽选中文本时持续续期
        try:
            if self.log_label.collide_point(*touch.pos):
                self._user_interacting = True
                if self._interaction_timer:
                    self._interaction_timer.cancel()
                self._interaction_timer = Clock.schedule_once(
                    self._reset_interaction, 5.0
                )
        except Exception:
            pass
        return super().on_touch_move(touch)

    def _reset_interaction(self, dt=None):
        """恢复自动滚动"""
        self._user_interacting = False
        # 如果没有选中文本，取消焦点
        try:
            sel_from = getattr(self.log_label, 'selection_from', None)
            sel_to = getattr(self.log_label, 'selection_to', None)
            if sel_from is not None and sel_to is not None and sel_from == sel_to:
                self.log_label.focus = False
        except Exception:
            pass

    def toggle_visible(self):
        self._expanded = not self._expanded
        if self._expanded:
            self.width = self._expanded_width
            self.height = self._expanded_height
            if getattr(self, '_scroll_view', None):
                self._scroll_view.opacity = 1.0
                self._scroll_view.disabled = False
            else:
                self.log_label.opacity = 1.0
                self.log_label.disabled = False
            self._dirty = True
            RuntimeStatusLogger.log_info('日志面板已展开（双击可隐藏）')
        else:
            self.width = self._collapsed_width
            self.height = self._collapsed_height
            if getattr(self, '_scroll_view', None):
                self._scroll_view.opacity = 0.0
                self._scroll_view.disabled = True
            else:
                self.log_label.opacity = 0.0
                self.log_label.disabled = True
    
    def add_log(self, message: str, category: str = 'info'):
        """
        添加日志消息
        
        参数:
            message: 日志内容
            category: 日志类别
                - 'info': 普通信息，青色
                - 'action': 动作状态，绿色
                - 'servo': 舵机指令，黄色
                - 'error': 错误信息，红色
        """
        timestamp = time.strftime('%H:%M:%S')
        
        # 类别前缀
        prefix_map = {
            'info': '▶',
            'action': '►',
            'servo': '⚙',
            'error': 'x',
        }
        prefix = prefix_map.get(category, '▶')

        try:
            message = str(message).replace('\ufe0f', '')
        except Exception:
            pass

        # 纯文本格式（TextInput 不支持 markup）
        formatted_log = f'{timestamp} {message}'
        
        with self._lock:
            self.logs.append(formatted_log)
            self._dirty = True
    
    def _refresh_display(self, dt):
        """定时刷新显示"""
        if not self._expanded:
            return

        with self._lock:
            if not self._dirty:
                return

            if self.logs:
                all_logs = '\n'.join(list(self.logs)[-30:])
            else:
                all_logs = '[等待信息...]'

            if all_logs != self._last_render_text:
                if self._user_interacting:
                    return  # 暂停UI文本更新，保留当前的选中高亮态
                self.log_label.text = all_logs
                self._last_render_text = all_logs
                # 用户未交互时自动滚动到底部
                Clock.schedule_once(self._scroll_to_bottom, 0.05)
            self._dirty = False

    def _scroll_to_bottom(self, dt=None):
        """滚动到底部"""
        try:
            if getattr(self, '_scroll_view', None):
                self._scroll_view.scroll_y = 0
            else:
                self.log_label.cursor = (0, max(0, len(self.log_label._lines) - 1))
        except Exception:
            pass


class RuntimeStatusLogger:
    """
    全局日志记录器
    用于在应用各处添加状态信息
    """
    _instance = None
    _panel = None
    # 启动期缓冲：当面板尚未创建时，将日志缓存起来，set_panel 时刷新到面板
    _buffer = deque(maxlen=400)
    _buf_lock = threading.Lock()
    _last_msg_key = None
    _last_msg_time = 0.0
    _repeat_drop_count = 0
    
    @classmethod
    def set_panel(cls, panel: RuntimeStatusPanel):
        """设置关联的 RuntimeStatusPanel"""
        cls._panel = panel
        # 将缓冲区中的日志刷新到面板（保持时间顺序）
        try:
            with cls._buf_lock:
                while cls._buffer:
                    msg, cat = cls._buffer.popleft()
                    try:
                        cls._panel.add_log(msg, cat)
                    except Exception:
                        # 若添加失败，继续下一条
                        pass
        except Exception:
            pass
    
    @classmethod
    def log(cls, message: str, category: str = 'info'):
        """添加日志"""
        try:
            msg_text = str(message)
        except Exception:
            msg_text = ""
        cat = str(category or 'info')

        # 高频重复日志去重（窗口内相同内容直接丢弃），并在下一条变化时补充摘要
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
                # 如果面板添加失败，回退到 logging
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
            # 面板尚未初始化：缓存到缓冲区，并同时写入 logging
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
        """记录动作执行"""
        msg = f"-> {action}"
        if details:
            msg += f" - {details}"
        cls.log(msg, 'action')
    
    @classmethod
    def log_servo(cls, servo_id: int, position: int, angle: float = None):
        """记录舵机指令"""
        msg = f"舵机 {servo_id}: 位置={position}"
        if angle is not None:
            msg += f" (角度={angle:.1f}°)"
        cls.log(msg, 'servo')
    
    @classmethod
    def log_error(cls, error: str):
        """记录错误"""
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
        """记录信息"""
        try:
            text = str(info)
        except Exception:
            text = ""
        if text.lstrip().startswith("->"):
            msg = text
        else:
            msg = f"-> {text}"
        cls.log(msg, 'info')
