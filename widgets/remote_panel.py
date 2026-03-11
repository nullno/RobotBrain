from kivy.uix.modalview import ModalView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.label import Label
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.metrics import dp
from app.theme import FONT
from widgets.gamepad_layout import GamepadLayout, ActionTechButton
import logging

logger = logging.getLogger(__name__)

class RemotePanel(ModalView):
    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint', (0.9, 0.85))
        kwargs.setdefault('auto_dismiss', True)
        kwargs.setdefault('background_color', (0, 0, 0, 0.8))
        super().__init__(**kwargs)
        
        self.main_layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        with self.main_layout.canvas.before:
            Color(0.08, 0.1, 0.12, 0.95)
            self.bg_rect = RoundedRectangle(pos=self.main_layout.pos, size=self.main_layout.size, radius=[dp(15)])
            Color(0.2, 0.6, 0.9, 0.3)
            self.border_line = Line(rounded_rectangle=(self.main_layout.x, self.main_layout.y, self.main_layout.width, self.main_layout.height, dp(15)), width=1.5)
            Color(0.2, 0.6, 0.9, 0.1)
            self.glow_rect = RoundedRectangle(pos=(self.main_layout.x - 4, self.main_layout.y - 4), size=(self.main_layout.width + 8, self.main_layout.height + 8), radius=[dp(18)])

        self.main_layout.bind(pos=self._update_bg, size=self._update_bg)

        title = Label(
            text="机 器 人 操 作 手 柄",
            font_name=FONT,
            font_size="22sp",
            bold=True,
            size_hint_y=None,
            height=dp(40),
            color=(0.2, 0.8, 1, 1)
        )
        self.main_layout.add_widget(title)

        self.gamepad = GamepadLayout()

        # 中间区域：卸力 + 关闭按钮（与PC布局一致，置于方向键和动作按钮之间）
        mid_container = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_x=0.15)
        mid_box = BoxLayout(orientation='vertical', spacing=dp(10), size_hint=(None, None))
        mid_box.bind(minimum_width=mid_box.setter('width'), minimum_height=mid_box.setter('height'))

        emergency_btn = ActionTechButton(
            text="断电\n卸力",
            action_name="emergency",
            key_label="(E)",
            size=(dp(60), dp(60)),
            fill_color=(0.8, 0.1, 0.1, 0.3),
            border_color=(1, 0.2, 0.2, 0.5),
            func=self._emergency
        )
        close_btn = ActionTechButton(
            text="关闭\n手柄",
            key_label="(Esc)",
            size=(dp(60), dp(60)),
            fill_color=(0.5, 0.5, 0.6, 0.25),
            border_color=(0.6, 0.6, 0.7, 0.8),
            func=lambda *a: self.dismiss()
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

    def _emergency(self, *args):
        from app.debug_panel_runtime import emergency_torque_release
        emergency_torque_release(self)

    def _update_bg(self, instance, value):
        self.bg_rect.pos = instance.pos
        self.bg_rect.size = instance.size
        self.border_line.rounded_rectangle = (
            instance.x, instance.y, instance.width, instance.height, dp(15)
        )
        self.glow_rect.pos = (instance.x - dp(4), instance.y - dp(4))
        self.glow_rect.size = (instance.width + dp(8), instance.height + dp(8))

    def on_open(self):
        # Bind keyboard through the inner gamepad layout when modal opens
        self.gamepad.bind_keyboard()
        # Intercept Escape key via Window binding
        from kivy.core.window import Window
        self._orig_key_down = self.gamepad._on_window_key_down
        Window.unbind(on_key_down=self.gamepad._on_window_key_down)
        Window.bind(on_key_down=self._on_kb_down_intercept)

    def on_dismiss(self):
        from kivy.core.window import Window
        Window.unbind(on_key_down=self._on_kb_down_intercept)
        self.gamepad.unbind_keyboard()

    def _on_kb_down_intercept(self, window, key, scancode, codepoint, modifiers):
        if key == 27:  # Escape keycode
            self.dismiss()
            return True
        return self._orig_key_down(window, key, scancode, codepoint, modifiers)
