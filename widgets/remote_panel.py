"""
remote_panel.py - 手机端机器人遥控手柄弹窗

包含 GamepadLayout (手机端手柄布局) 和 RemotePanel (弹窗容器)。
PC 相关代码已移至 cockpit_panel.py。
"""

from kivy.uix.modalview import ModalView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.metrics import dp
from kivy.core.window import Window
from app.theme import FONT
from widgets.robot_actions import (
    ActionTechButton, MOTION_ACTIONS,
    send_motion as _send_motion, emergency_action,
    key_name_from_code, unfocus_text_inputs,
)
import logging

logger = logging.getLogger(__name__)


class GamepadLayout(BoxLayout):
    """手机端手柄布局 (D-Pad + 动作按钮)"""

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("spacing", dp(40))
        super().__init__(**kwargs)

        self.key_actions = {}
        self.buttons = {}
        self._keyboard = None

        # ===== 左侧：方向键 (D-Pad) =====
        dpad_container = AnchorLayout(
            anchor_x="center", anchor_y="center", size_hint_x=0.45
        )
        dpad_grid = GridLayout(cols=3, spacing=dp(12), size_hint=(None, None))
        dpad_grid.bind(
            minimum_width=dpad_grid.setter("width"),
            minimum_height=dpad_grid.setter("height"),
        )

        nav_btn_size = dp(75)

        def _add_nav_btn(text, action, key_label, keys, special_color=None):
            if not text:
                dpad_grid.add_widget(
                    Widget(size_hint=(None, None), size=(nav_btn_size, nav_btn_size))
                )
                return
            btn_kwargs = dict(
                text=text, action_name=action, key_label=key_label,
                func=self.send_motion, size=(nav_btn_size, nav_btn_size),
            )
            if special_color:
                btn_kwargs["fill_color"] = special_color
                btn_kwargs["border_color"] = (
                    special_color[0] + 0.1, special_color[1] + 0.1,
                    special_color[2] + 0.1, 0.8,
                )
            btn = ActionTechButton(**btn_kwargs)
            dpad_grid.add_widget(btn)
            for k in keys:
                self.key_actions[k.lower()] = action
            self.buttons[action] = btn

        _add_nav_btn("", "", "", [])
        _add_nav_btn("前进", "walk", "(W/↑)", ["w", "up"],
                     special_color=(0.1, 0.4, 0.2, 0.5))
        _add_nav_btn("", "", "", [])
        _add_nav_btn("左转", "turn_left", "(A/←)", ["a", "left"])
        _add_nav_btn("站立", "stand", "(Space)", ["spacebar"],
                     special_color=(0.5, 0.4, 0.1, 0.5))
        _add_nav_btn("右转", "turn_right", "(D/→)", ["d", "right"])
        _add_nav_btn("", "", "", [])
        _add_nav_btn("后退", "backward", "(S/↓)", ["s", "down"],
                     special_color=(0.1, 0.4, 0.2, 0.5))
        _add_nav_btn("", "", "", [])

        dpad_container.add_widget(dpad_grid)
        self.add_widget(dpad_container)

        # ===== 右侧：动作释放区 =====
        actions_container = ScrollView(size_hint_x=0.55)
        actions_grid = GridLayout(
            cols=3, spacing=dp(12),
            padding=[dp(5), dp(5), dp(15), dp(5)],
            size_hint_y=None,
        )
        actions_grid.bind(minimum_height=actions_grid.setter("height"))

        for label, act, key in MOTION_ACTIONS:
            btn = ActionTechButton(
                text=label, action_name=act, key_label=f"({key})",
                func=self.send_motion,
                size=(dp(30), dp(50)), size_hint=(None, None),
                fill_color=(0.3, 0.1, 0.4, 0.15),
                border_color=(0.6, 0.2, 0.8, 0.3),
                font_size="15sp",
            )
            actions_grid.add_widget(btn)
            self.key_actions[key.lower()] = act
            self.buttons[act] = btn

        actions_container.add_widget(actions_grid)
        self.add_widget(actions_container)

        self.bind(disabled=self._on_disabled_change)

    def _on_disabled_change(self, instance, value):
        if not value:
            self.bind_keyboard()
        else:
            self.unbind_keyboard()

    def bind_keyboard(self):
        from kivy.utils import platform
        if platform == "android":
            return
        if not self._keyboard:
            Window.bind(
                on_key_down=self._on_window_key_down,
                on_key_up=self._on_window_key_up,
            )
            self._keyboard = True

    def unbind_keyboard(self):
        if getattr(self, "_keyboard", None):
            Window.unbind(
                on_key_down=self._on_window_key_down,
                on_key_up=self._on_window_key_up,
            )
            self._keyboard = None

    def send_motion(self, action_name):
        _send_motion(action_name)

    def _simulate_button_down(self, btn_key):
        btn = self.buttons.get(btn_key)
        if btn and btn.state == "normal":
            btn.state = "down"
            if hasattr(btn, "_on_state"):
                btn._on_state()

    def _simulate_button_up(self, btn_key):
        btn = self.buttons.get(btn_key)
        if btn and btn.state == "down":
            btn.state = "normal"
            if hasattr(btn, "_on_state"):
                btn._on_state()
            btn.dispatch("on_release")

    def trigger_emergency(self):
        btn = self.buttons.get("emergency")
        if btn:
            btn.dispatch("on_release")

    def _on_window_key_down(self, window, key, scancode, codepoint, modifiers):
        key_name = key_name_from_code(key, scancode)
        if key_name in self.key_actions:
            unfocus_text_inputs()
            action = self.key_actions[key_name]
            self._simulate_button_down(action)
            return True
        return False

    def _on_window_key_up(self, window, key, scancode):
        key_name = key_name_from_code(key, scancode)
        handled = False
        if key_name in self.key_actions:
            action = self.key_actions[key_name]
            self._simulate_button_up(action)
            handled = True

        if key_name in ("w", "a", "s", "d", "up", "down", "left", "right"):
            opp_map = {
                "w": "s", "s": "w", "up": "down", "down": "up",
                "a": "d", "d": "a", "left": "right", "right": "left",
            }
            req_stop = True
            opp = opp_map.get(key_name)
            if opp:
                btn_key = self.key_actions.get(opp)
                if btn_key:
                    btn = self.buttons.get(btn_key)
                    if btn and btn.state == "down":
                        req_stop = False
            if req_stop:
                self.send_motion("stand")
        return handled


class RemotePanel(ModalView):
    """手机端遥控手柄弹窗"""

    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint', (0.9, 0.85))
        kwargs.setdefault('auto_dismiss', True)
        kwargs.setdefault('background_color', (0, 0, 0, 0.8))
        super().__init__(**kwargs)

        self.main_layout = BoxLayout(
            orientation='vertical', padding=dp(20), spacing=dp(20)
        )
        with self.main_layout.canvas.before:
            Color(0.08, 0.1, 0.12, 0.95)
            self.bg_rect = RoundedRectangle(
                pos=self.main_layout.pos,
                size=self.main_layout.size,
                radius=[dp(15)],
            )
            Color(0.2, 0.6, 0.9, 0.3)
            self.border_line = Line(
                rounded_rectangle=(
                    self.main_layout.x, self.main_layout.y,
                    self.main_layout.width, self.main_layout.height, dp(15),
                ),
                width=1.5,
            )
            Color(0.2, 0.6, 0.9, 0.1)
            self.glow_rect = RoundedRectangle(
                pos=(self.main_layout.x - 4, self.main_layout.y - 4),
                size=(self.main_layout.width + 8, self.main_layout.height + 8),
                radius=[dp(18)],
            )

        self.main_layout.bind(pos=self._update_bg, size=self._update_bg)

        title = Label(
            text="机 器 人 操 作 手 柄",
            font_name=FONT, font_size="22sp", bold=True,
            size_hint_y=None, height=dp(40), color=(0.2, 0.8, 1, 1),
        )
        self.main_layout.add_widget(title)

        self.gamepad = GamepadLayout()

        # 中间区域：卸力 + 关闭按钮
        mid_container = AnchorLayout(
            anchor_x='center', anchor_y='center', size_hint_x=0.15
        )
        mid_box = BoxLayout(
            orientation='vertical', spacing=dp(10), size_hint=(None, None)
        )
        mid_box.bind(
            minimum_width=mid_box.setter('width'),
            minimum_height=mid_box.setter('height'),
        )

        emergency_btn = ActionTechButton(
            text="断电\n卸力", action_name="emergency", key_label="(E)",
            size=(dp(60), dp(60)),
            fill_color=(0.8, 0.1, 0.1, 0.3),
            border_color=(1, 0.2, 0.2, 0.5),
            func=lambda *a: emergency_action(self),
        )
        close_btn = ActionTechButton(
            text="关闭\n手柄", key_label="(Esc)",
            size=(dp(60), dp(60)),
            fill_color=(0.5, 0.5, 0.6, 0.25),
            border_color=(0.6, 0.6, 0.7, 0.8),
            func=lambda *a: self.dismiss(),
        )

        mid_box.add_widget(emergency_btn)
        mid_box.add_widget(close_btn)
        mid_container.add_widget(mid_box)

        # 插入到 D-Pad 和动作按钮之间
        self.gamepad.add_widget(mid_container, index=1)
        self.gamepad.children[2].size_hint_x = 0.4
        self.gamepad.children[0].size_hint_x = 0.45

        self.gamepad.buttons["emergency"] = emergency_btn
        self.gamepad.key_actions['e'] = "emergency"

        self.main_layout.add_widget(self.gamepad)
        self.add_widget(self.main_layout)

    def _update_bg(self, instance, value):
        self.bg_rect.pos = instance.pos
        self.bg_rect.size = instance.size
        self.border_line.rounded_rectangle = (
            instance.x, instance.y,
            instance.width, instance.height, dp(15),
        )
        self.glow_rect.pos = (instance.x - dp(4), instance.y - dp(4))
        self.glow_rect.size = (instance.width + dp(8), instance.height + dp(8))

    def on_open(self):
        self.gamepad.bind_keyboard()
        from kivy.core.window import Window
        self._orig_key_down = self.gamepad._on_window_key_down
        Window.unbind(on_key_down=self.gamepad._on_window_key_down)
        Window.bind(on_key_down=self._on_kb_down_intercept)

    def on_dismiss(self):
        from kivy.core.window import Window
        Window.unbind(on_key_down=self._on_kb_down_intercept)
        self.gamepad.unbind_keyboard()

    def _on_kb_down_intercept(self, window, key, scancode, codepoint, modifiers):
        if key == 27:  # Escape
            self.dismiss()
            return True
        return self._orig_key_down(window, key, scancode, codepoint, modifiers)
