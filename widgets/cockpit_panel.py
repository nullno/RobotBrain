from kivy.uix.floatlayout import FloatLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle, Canvas, Ellipse
from kivy.animation import Animation
from kivy.app import App
from kivy.metrics import dp
from kivy.core.window import Window
from app.theme import FONT
from widgets.robot_actions import (
    KEY_MAP, send_motion as _send_motion, emergency_action,
    key_name_from_code, unfocus_text_inputs,
)
import logging
import random
import math

logger = logging.getLogger(__name__)


# 方向键集合（按住走、松手停）
_NAV_KEYS = frozenset(("w", "a", "s", "d", "up", "down", "left", "right"))


# ==================== HUD 长条按钮 ====================
class HudButton(Button):
    """赛博朋克风格的细长条按钮"""
    def __init__(self, action_name="", key_hint="", on_action=None,
                 accent_color=(0, 0.85, 1, 0.7), **kwargs):
        self.action_name = action_name
        self.on_action = on_action
        self.accent_color = accent_color

        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("color", accent_color[:3] + (1,))
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", "11sp")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(28))
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        kwargs.setdefault("markup", True)

        display = kwargs.pop("text", "")
        if key_hint:
            display = f"{display}  [size=9sp][color=#88aacc]{key_hint}[/color][/size]"
        kwargs["text"] = display

        super().__init__(**kwargs)
        self.bind(size=lambda *_: setattr(self, 'text_size', self.size))

        with self.canvas.before:
            self._bg_c = Color(accent_color[0], accent_color[1], accent_color[2], 0.08)
            self._bg_r = RoundedRectangle(radius=[3])
        with self.canvas.after:
            self._bd_c = Color(accent_color[0], accent_color[1], accent_color[2], 0.35)
            self._bd_l = Line(rounded_rectangle=(0, 0, 10, 10, 3), width=1.0)

        self.bind(pos=self._upd, size=self._upd, state=self._on_state)
        self.bind(on_release=self._fire)

    def _upd(self, *_):
        self._bg_r.pos = self.pos
        self._bg_r.size = self.size
        self._bd_l.rounded_rectangle = (self.x, self.y, self.width, self.height, 3)

    def _on_state(self, *_):
        if self.state == "down":
            self._bg_c.rgba = (self.accent_color[0], self.accent_color[1],
                               self.accent_color[2], 0.3)
            self._bd_c.rgba = (min(self.accent_color[0] + 0.3, 1),
                               min(self.accent_color[1] + 0.3, 1),
                               min(self.accent_color[2] + 0.3, 1), 0.9)
        else:
            self._bg_c.rgba = (self.accent_color[0], self.accent_color[1],
                               self.accent_color[2], 0.08)
            self._bd_c.rgba = (self.accent_color[0], self.accent_color[1],
                               self.accent_color[2], 0.35)

    def _fire(self, *_):
        if self.on_action:
            self.on_action(self.action_name)


# ==================== 十字准星 + 动画 ====================
class HudCrosshair(Widget):
    """带展开动画的赛博朋克十字准星"""
    def __init__(self, **kwargs):
        super().__init__(size_hint=(None, None), size=(dp(80), dp(80)), **kwargs)
        self.opacity = 0
        self._anim_progress = 0.0  # 0→1
        self._ring_alpha = 0.8
        self._line_extend = 0.0
        self.bind(pos=self._redraw, size=self._redraw)

    def appear_at(self, x, y):
        """在指定位置播放展开动画"""
        self.center = (x, y)
        self.opacity = 1
        self._anim_progress = 0.0
        self._ring_alpha = 0.8
        self._line_extend = 0.0
        # 展开动画
        anim = Animation(_anim_progress=1.0, _ring_alpha=0.6, _line_extend=1.0,
                         duration=0.35, t='out_back')
        anim.bind(on_progress=lambda *_: self._redraw())
        # 保持片刻 → 淡出
        anim += Animation(opacity=0.3, _ring_alpha=0.25, duration=2.0, t='linear')
        anim.start(self)
        self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        cx, cy = self.center
        prog = max(0, min(1, self._anim_progress))
        ra = self._ring_alpha
        ext = self._line_extend

        with self.canvas:
            # 外圈
            radius_outer = dp(20) * prog
            Color(0, 1, 0.7, ra * 0.3)
            Line(circle=(cx, cy, radius_outer + dp(8) * prog), width=0.8)
            # 内圈
            Color(0, 1, 0.7, ra)
            Line(circle=(cx, cy, dp(3)), width=1.5)
            # 十字线
            arm = dp(6) + dp(28) * ext
            gap = dp(5) * prog
            Color(0, 1, 0.7, ra)
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                Line(points=[cx + dx * gap, cy + dy * gap,
                             cx + dx * arm, cy + dy * arm], width=1.2)
            # 对角小刻度
            Color(0, 1, 0.7, ra * 0.4)
            tick = dp(8) * prog
            off = dp(14) * prog
            for sx, sy in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
                Line(points=[cx + sx * off, cy + sy * off,
                             cx + sx * (off + tick), cy + sy * (off + tick)], width=0.8)


# ==================== HUD 装饰层 ====================
class HudOverlay(Widget):
    """赛博朋克 HUD 装饰：四角边框 + 扫描线 + 随机数据闪烁"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._scan_y = 0.0
        self._data_segments = []
        self._tick = 0
        self.bind(pos=self._redraw, size=self._redraw)
        Clock.schedule_interval(self._animate, 1 / 20)

    def _animate(self, dt):
        self._scan_y += dt * 40
        if self._scan_y > (self.height or 500):
            self._scan_y = 0
        self._tick += 1
        if self._tick % 6 == 0:
            self._gen_data_segments()
        self._redraw()

    def _gen_data_segments(self):
        """生成随机装饰数据段"""
        segs = []
        w = self.width or 800
        h = self.height or 500
        for _ in range(random.randint(2, 5)):
            side = random.choice(['left', 'right'])
            y = random.uniform(h * 0.15, h * 0.85)
            length = random.uniform(dp(20), dp(60))
            segs.append((side, y, length, random.uniform(0.15, 0.4)))
        self._data_segments = segs

    def _redraw(self, *_):
        self.canvas.clear()
        x, y = self.pos
        w, h = self.size
        if w < 10 or h < 10:
            return

        corner_len = dp(40)
        with self.canvas:
            # ---- 四角 HUD 边框 ----
            Color(0, 0.9, 1, 0.5)
            # 左上
            Line(points=[x, y + h - corner_len, x, y + h, x + corner_len, y + h], width=1.2)
            # 右上
            Line(points=[x + w - corner_len, y + h, x + w, y + h, x + w, y + h - corner_len], width=1.2)
            # 左下
            Line(points=[x, y + corner_len, x, y, x + corner_len, y], width=1.2)
            # 右下
            Line(points=[x + w - corner_len, y, x + w, y, x + w, y + corner_len], width=1.2)

            # ---- 顶部/底部细线 ----
            Color(0, 0.9, 1, 0.15)
            Line(points=[x + corner_len + dp(10), y + h,
                         x + w - corner_len - dp(10), y + h], width=0.6)
            Line(points=[x + corner_len + dp(10), y,
                         x + w - corner_len - dp(10), y], width=0.6)

            # ---- 扫描线 ----
            scan_abs = y + self._scan_y
            if y < scan_abs < y + h:
                Color(0, 1, 0.8, 0.06)
                Rectangle(pos=(x, scan_abs - dp(1)), size=(w, dp(2)))

            # ---- 侧边随机数据线 ----
            for side, sy, length, alpha in self._data_segments:
                Color(0, 0.9, 1, alpha)
                if side == 'left':
                    Line(points=[x + dp(2), y + sy, x + dp(2) + length, y + sy], width=0.7)
                else:
                    Line(points=[x + w - dp(2) - length, y + sy, x + w - dp(2), y + sy], width=0.7)

            # ---- 左侧/右侧竖向刻度 ----
            Color(0, 0.9, 1, 0.12)
            for i in range(5):
                ty = y + h * 0.2 + (h * 0.6) * i / 4
                Line(points=[x + dp(1), ty, x + dp(8), ty], width=0.6)
                Line(points=[x + w - dp(8), ty, x + w - dp(1), ty], width=0.6)


# ==================== PC 驾驶舱主面板 ====================
class CockpitPanel(FloatLayout):
    def on_touch_down(self, touch):
        if self.disabled or self.opacity == 0:
            return False
            
        # 触发准星动画 (如果在不拦截区域)：即使子控件吃掉该事件也先播放动画
        if touch.y >= dp(85):
            self._crosshair.appear_at(touch.x, touch.y)

        # 传递给底部按钮等子控件
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.disabled or self.opacity == 0:
            return False
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.disabled or self.opacity == 0:
            return False
        return super().on_touch_up(touch)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._keyboard_bound = False
        self._kb = None
        self.key_actions = {}
        self.buttons = {}

        # --- HUD 装饰层 ---
        self._hud_overlay = HudOverlay()
        self.add_widget(self._hud_overlay)
        self._hud_overlay.size_hint = (1, 1)
        self._hud_overlay.pos_hint = {"x": 0, "y": 0}

        # --- 十字准星层（全屏点击捕获） ---
        self._crosshair_layer = FloatLayout()
        self.add_widget(self._crosshair_layer)
        self._crosshair = HudCrosshair()
        self._crosshair_layer.add_widget(self._crosshair)

        # --- 底部操作按钮（两排长条按钮） ---
        self._build_hud_buttons()

        self.bind(disabled=self._on_disabled_change)
        Clock.schedule_once(lambda dt: self._on_disabled_change(self, self.disabled), 0)

    def _build_hud_buttons(self):
        """构建底部两排 HUD 操作按钮"""
        bottom = AnchorLayout(anchor_x='center', anchor_y='bottom',
                              size_hint=(1, None), height=dp(80),
                              pos_hint={"x": 0, "y": 0})
        container = BoxLayout(orientation='vertical', spacing=dp(3),
                              size_hint=(0.92, None), height=dp(72),
                              padding=[dp(4), dp(4), dp(4), dp(4)])

        # 第一排：方向控制 + 核心
        row1 = GridLayout(cols=12, spacing=dp(3), size_hint_y=None, height=dp(30))
        # 第二排：动作指令
        row2 = GridLayout(cols=12, spacing=dp(3), size_hint_y=None, height=dp(30))

        # === 第一排按钮 ===
        nav_color = (0.1, 0.85, 0.5, 0.7)
        core_color = (0.9, 0.7, 0.1, 0.7)
        danger_color = (1, 0.25, 0.2, 0.7)

        row1_actions = [
            ("前进", "walk", "W/↑", nav_color),
            ("后退", "backward", "S/↓", nav_color),
            ("左转", "turn_left", "A/←", nav_color),
            ("右转", "turn_right", "D/→", nav_color),
            ("站立", "stand", "Space", core_color),
            ("蹲下", "crouch", "sh+Z", (0, 0.85, 1, 0.7)),
            ("小跑", "trot", "sh+Y", (0, 0.85, 1, 0.7)),
            ("爬行", "crawl", "sh+F", (0, 0.85, 1, 0.7)),
            ("上楼", "climb_stairs", "sh+T", (0, 0.85, 1, 0.7)),
            ("坐下", "sit", "sh+G", (0, 0.85, 1, 0.7)),
            ("弯腰", "bend_over", "sh+N", (0, 0.85, 1, 0.7)),
            ("卸力", "emergency", "E", danger_color),
        ]

        row2_actions = [
            ("晃动", "swagger", "sh+X", (0.6, 0.3, 0.9, 0.7)),
            ("叉腰", "akimbo", "sh+C", (0.6, 0.3, 0.9, 0.7)),
            ("点头", "nod", "sh+V", (0.6, 0.3, 0.9, 0.7)),
            ("摇头", "shake_head", "sh+B", (0.6, 0.3, 0.9, 0.7)),
            ("扎马步", "horse_stance", "sh+M", (0.6, 0.3, 0.9, 0.7)),
            ("独立", "golden_rooster", "sh+J", (0.6, 0.3, 0.9, 0.7)),
            ("手倒立", "handstand", "sh+K", (0.6, 0.3, 0.9, 0.7)),
            ("单手", "one_hand_handstand", "sh+L", (0.6, 0.3, 0.9, 0.7)),
            ("思考", "think", "sh+U", (0.6, 0.3, 0.9, 0.7)),
            ("比心", "make_heart", "sh+I", (0.6, 0.3, 0.9, 0.7)),
            ("挥手", "wave", "sh+O", (0.6, 0.3, 0.9, 0.7)),
            ("坐凳", "sit_chair", "sh+H", (0.6, 0.3, 0.9, 0.7)),
        ]

        for text, action, key, color in row1_actions:
            btn = HudButton(text=text, action_name=action, key_hint=key,
                            on_action=self._send_action, accent_color=color)
            row1.add_widget(btn)
            self.buttons[action] = btn

        for text, action, key, color in row2_actions:
            btn = HudButton(text=text, action_name=action, key_hint=key,
                            on_action=self._send_action, accent_color=color)
            row2.add_widget(btn)
            self.buttons[action] = btn

        # 加一个"拒绝"（第13个，放row1的空位或单独处理）
        refuse_btn = HudButton(text="拒绝", action_name="refuse", key_hint="sh+P",
                               on_action=self._send_action,
                               accent_color=(0.6, 0.3, 0.9, 0.7))
        self.buttons["refuse"] = refuse_btn
        # 不加到网格避免超出12列，但注册键盘映射

        container.add_widget(row1)
        container.add_widget(row2)

        # 半透明底板
        with container.canvas.before:
            Color(0, 0, 0, 0.45)
            container._bg = RoundedRectangle(radius=[4])
        with container.canvas.after:
            Color(0, 0.9, 1, 0.2)
            container._bd = Line(rounded_rectangle=(0, 0, 10, 10, 4), width=0.8)

        def _upd_bg(*_):
            container._bg.pos = container.pos
            container._bg.size = container.size
            container._bd.rounded_rectangle = (container.x, container.y,
                                                container.width, container.height, 4)
        container.bind(pos=_upd_bg, size=_upd_bg)

        bottom.add_widget(container)
        self.add_widget(bottom)

        # === 键盘映射 (来自共享 robot_actions) ===
        self.key_actions = dict(KEY_MAP)

    def _send_action(self, action_name):
        """发送动作到 ESP32"""
        if action_name == "emergency":
            emergency_action(self)
            return
        _send_motion(action_name)

    # ==================== 键盘 ====================
    def _on_disabled_change(self, instance, value):
        if not value:
            self.bind_keyboard()
        else:
            self.unbind_keyboard()

    def bind_keyboard(self):
        if not self._keyboard_bound:
            self._kb = Window.request_keyboard(self._kb_closed, self, 'text')
            if self._kb:
                self._kb.bind(on_key_down=self._on_kb_down,
                              on_key_up=self._on_kb_up)
                self._keyboard_bound = True

    def unbind_keyboard(self):
        if self._keyboard_bound and self._kb:
            self._kb.unbind(on_key_down=self._on_kb_down,
                            on_key_up=self._on_kb_up)
            self._kb.release()
        self._kb = None
        self._keyboard_bound = False

    def _kb_closed(self):
        """键盘被其他控件抢占时自动重新请求"""
        self._keyboard_bound = False
        self._kb = None
        if not self.disabled:
            Clock.schedule_once(lambda dt: self.bind_keyboard(), 0.15)

    def _simulate_btn_down(self, action):
        btn = self.buttons.get(action)
        if btn and btn.state == "normal":
            btn.state = "down"
            if hasattr(btn, '_on_state'):
                btn._on_state()

    def _simulate_btn_up_visual(self, action):
        """恢复按钮视觉状态"""
        btn = self.buttons.get(action)
        if btn and btn.state == "down":
            btn.state = "normal"
            if hasattr(btn, '_on_state'):
                btn._on_state()

    def _on_kb_down(self, keyboard, keycode, text, modifiers):
        """键盘按下：导航键直接触发，动作键需 Shift"""
        _, key_name = keycode
        if not key_name:
            return False
        key_name = key_name.lower()
        if key_name == ' ':
            key_name = 'spacebar'

        # codepoint 兜底（适配不同平台 / 输入法）
        if key_name not in self.key_actions and text:
            t = text.lower()
            if t == ' ':
                t = 'spacebar'
            if t in self.key_actions:
                key_name = t

        if key_name not in self.key_actions:
            return False

        action = self.key_actions[key_name]

        # 动作键需要 Shift
        if key_name not in _NAV_KEYS and key_name not in ('spacebar', 'e'):
            if 'shift' not in modifiers:
                return False

        unfocus_text_inputs()
        btn = self.buttons.get(action)
        if btn and btn.state == "down":
            return True
        self._simulate_btn_down(action)
        self._send_action(action)
        return True

    def _on_kb_up(self, keyboard, keycode):
        """键盘松开：恢复按钮视觉，方向键松开发 stand"""
        _, key_name = keycode
        if not key_name:
            return False
        key_name = key_name.lower()
        if key_name == ' ':
            key_name = 'spacebar'

        if key_name not in self.key_actions:
            return False

        action = self.key_actions[key_name]
        self._simulate_btn_up_visual(action)

        # 方向键松开 → stand
        if key_name in _NAV_KEYS:
            opp = {"w": "s", "s": "w", "up": "down", "down": "up",
                    "a": "d", "d": "a", "left": "right", "right": "left"}
            req_stop = True
            opp_key = opp.get(key_name)
            if opp_key:
                opp_action = self.key_actions.get(opp_key)
                if opp_action:
                    opp_btn = self.buttons.get(opp_action)
                    if opp_btn and opp_btn.state == "down":
                        req_stop = False
            if req_stop:
                self._send_action("stand")
        return True
