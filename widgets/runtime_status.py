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
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from collections import deque
import threading
import time
import logging


class RuntimeStatusPanel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', size_hint=(None, None), **kwargs)
        
        # UI 尺寸设置
        self.width = dp(280)
        self.height = dp(100)
        
        # 日志缓冲（最多保留最近的 20 条）
        self.logs = deque(maxlen=20)
        self._lock = threading.Lock()
        
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
        
        # 标题
        # title_label = Label(
        #     text='[b]运行状态[/b]',
        #     markup=True,
        #     size_hint_y=None,
        #     height=dp(24),
        #     color=(0.0, 0.9, 1.0, 1.0),
        #     font_size='11sp'
        # )
        # self.add_widget(title_label)
        
        # 日志文本区域（可滚动）
        self.scroll_view = ScrollView(size_hint=(1, 1))
        self.log_label = Label(
            text='[等待信息...]',
            markup=True,
            size_hint_y=None,
            color=(0.85, 0.9, 0.98, 1.0),
            font_size='10sp',
            halign='left',
            valign='top',
            text_size=(dp(270), None)  # \u8bbe\u7f6e\u6587\u672c\u5bbd\u5ea6\uff0c\u786e\u4fdd\u6ec6\u5de6\u6709\u6548
        )
        self.log_label.bind(texture_size=self.log_label.setter('size'))
        self.scroll_view.add_widget(self.log_label)
        self.add_widget(self.scroll_view)
        
        # 启动日志刷新定时器
        Clock.schedule_interval(self._refresh_display, 0.2)
    
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
        
        # 根据类别选择颜色
        color_map = {
            'info': '[color=00e6ff]',     # 青色
            'action': '[color=00ff88]',   # 绿色
            'servo': '[color=ffdd00]',    # 黄色
            'error': '[color=ff5555]',    # 红色
        }
        color_tag = color_map.get(category, color_map['info'])
        
        # 格式化日志
        formatted_log = f"{color_tag}{timestamp}[/color] {message}"
        
        with self._lock:
            self.logs.append(formatted_log)
    
    def _refresh_display(self, dt):
        """定时刷新显示"""
        with self._lock:
            if self.logs:
                # 将所有日志连接起来，最后 20 条
                all_logs = '\n'.join(list(self.logs))
                self.log_label.text = all_logs
            else:
                self.log_label.text = '[color=888888][等待信息...][/color]'


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
        if cls._panel:
            try:
                cls._panel.add_log(message, category)
            except Exception:
                # 如果面板添加失败，回退到 logging
                try:
                    if category == 'error':
                        logging.getLogger().error(message)
                    else:
                        logging.getLogger().info(message)
                except Exception:
                    try:
                        print(message)
                    except Exception:
                        pass
        else:
            # 面板尚未初始化：缓存到缓冲区，并同时写入 logging
            try:
                with cls._buf_lock:
                    cls._buffer.append((message, category))
            except Exception:
                pass
            try:
                if category == 'error':
                    logging.getLogger().error(message)
                else:
                    logging.getLogger().info(message)
            except Exception:
                try:
                    print(message)
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
        cls.log(f"x {error}", 'error')
    
    @classmethod
    def log_info(cls, info: str):
        """记录信息"""
        cls.log(f"-> {info}", 'info')
