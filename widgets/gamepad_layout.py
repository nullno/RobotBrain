import logging
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.metrics import dp
from kivy.core.window import Window
from app.theme import FONT
from services.wifi_servo import get_controller
from widgets.debug_ui_components import SquareTechButton

logger = logging.getLogger(__name__)


class ActionTechButton(SquareTechButton):
    def __init__(self, action_name="", key_label="", func=None, **kwargs):
        self.action_name = action_name
        self.func = func

        display_text = kwargs.pop("text", "")
        if key_label:
            display_text = f"{display_text}\n{key_label}"

        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        kwargs["text"] = display_text

        super().__init__(**kwargs)
        self.bind(on_release=self._trigger)

    def _trigger(self, *args):
        if self.func:
            self.func(self.action_name)

    def _on_state(self, *args):
        if self.state == "down":
            self._bg_color.rgba = (
                min(self.fill_color[0] + 0.4, 1.0),
                min(self.fill_color[1] + 0.4, 1.0),
                min(self.fill_color[2] + 0.4, 1.0),
                max(self.fill_color[3], 0.7),
            )
            self._border_color.rgba = (1, 1, 1, 1)
            self.color = (1, 1, 1, 1)
        else:
            self._bg_color.rgba = self.fill_color
            self._border_color.rgba = self.border_color
            self.color = self.text_color


class GamepadLayout(BoxLayout):
    _KEYCODE_TO_NAME = None
    _SCANCODE_TO_NAME = {
        4: 'a', 5: 'b', 6: 'c', 7: 'd', 8: 'e', 9: 'f', 10: 'g', 11: 'h', 12: 'i',
        13: 'j', 14: 'k', 15: 'l', 16: 'm', 17: 'n', 18: 'o', 19: 'p', 20: 'q',
        21: 'r', 22: 's', 23: 't', 24: 'u', 25: 'v', 26: 'w', 27: 'x', 28: 'y', 29: 'z',
        44: 'spacebar', 79: 'right', 80: 'left', 81: 'down', 82: 'up', 41: 'escape'
    }

    @staticmethod
    def _build_keycode_map():
        from kivy.core.window import Keyboard

        GamepadLayout._KEYCODE_TO_NAME = {v: k for k, v in Keyboard.keycodes.items()}
        return GamepadLayout._KEYCODE_TO_NAME

    def __init__(self, scale=1.0, action_cols=3, is_pc=False, **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("spacing", dp(40 * scale))
        super().__init__(**kwargs)

        self.key_actions = {}
        self.buttons = {}
        btn_fs = str(int(14 * scale)) + "sp"

        # ================= 左侧：方向键 (D-Pad) =================
        dpad_container = AnchorLayout(
            anchor_x="center", anchor_y="center", size_hint_x=0.4 if is_pc else 0.45
        )
        dpad_grid = GridLayout(cols=3, spacing=dp(12 * scale), size_hint=(None, None))
        dpad_grid.bind(
            minimum_width=dpad_grid.setter("width"),
            minimum_height=dpad_grid.setter("height"),
        )

        def _add_nav_btn(text, action, key_label, keys, special_color=None):
            if not text:
                dpad_grid.add_widget(
                    Widget(size_hint=(None, None), size=(dp(75), dp(75)))
                )
                return

            btn_kwargs = dict(
                text=text,
                action_name=action,
                key_label=key_label,
                func=self.send_motion,
                size=(dp(75), dp(75)),
            )
            if special_color:
                btn_kwargs["fill_color"] = special_color
                btn_kwargs["border_color"] = (
                    special_color[0] + 0.1,
                    special_color[1] + 0.1,
                    special_color[2] + 0.1,
                    0.8,
                )

            btn = ActionTechButton(**btn_kwargs)
            dpad_grid.add_widget(btn)
            for k in keys:
                self.key_actions[k.lower()] = action
            self.buttons[action] = btn
            return btn

        _add_nav_btn("", "", "", [])
        _add_nav_btn(
            "前进",
            "walk",
            "(W/↑)",
            ["w", "W", "up"],
            special_color=(0.1, 0.4, 0.2, 0.5),
        )
        _add_nav_btn("", "", "", [])

        _add_nav_btn("左转", "turn_left", "(A/←)", ["a", "A", "left"])
        _add_nav_btn(
            "站立", "stand", "(Space)", ["spacebar"], special_color=(0.5, 0.4, 0.1, 0.5)
        )
        _add_nav_btn("右转", "turn_right", "(D/→)", ["d", "D", "right"])

        _add_nav_btn("", "", "", [])
        _add_nav_btn(
            "后退",
            "backward",
            "(S/↓)",
            ["s", "S", "down"],
            special_color=(0.1, 0.4, 0.2, 0.5),
        )
        _add_nav_btn("", "", "", [])

        dpad_container.add_widget(dpad_grid)
        self.add_widget(dpad_container)

        if is_pc:
            from widgets.debug_ui_components import SquareTechButton
            from app.debug_panel_runtime import emergency_torque_release

            mid_container = AnchorLayout(
                anchor_x="center", anchor_y="center", size_hint_x=0.15
            )

            def _do_unload(*args):
                emergency_torque_release(self)

            unload_btn = ActionTechButton(
                text="断电\n卸力",
                action_name="emergency",
                key_label="(E)",
                size=(dp(60 * scale), dp(60 * scale)),
                font_size=btn_fs,
                fill_color=(0.8, 0.1, 0.1, 0.3),
                border_color=(1, 0.2, 0.2, 0.5),
                func=lambda *a: _do_unload(),
            )
            mid_container.add_widget(unload_btn)
            self.add_widget(mid_container)
            self.key_actions["e"] = "emergency"
            self.buttons["emergency"] = unload_btn

        # ================= 右侧：动作释放区 =================
        actions_scroll = ScrollView(size_hint_x=0.55)
        # 支持触摸滚动，加上一点内边距
        actions_grid = GridLayout(
            cols=action_cols,
            spacing=dp(12 * scale),
            padding=[dp(5), dp(5), dp(15), dp(5)],
            size_hint_y=None,
        )
        actions_grid.bind(minimum_height=actions_grid.setter("height"))

        actions = [
            ("蹲下", "crouch", "Z"),
            ("晃动", "swagger", "X"),
            ("叉腰", "akimbo", "C"),
            ("点头", "nod", "V"),
            ("摇头", "shake_head", "B"),
            ("弯腰", "bend_over", "N"),
            ("扎马步", "horse_stance", "M"),
            ("独立", "golden_rooster", "J"),
            ("手倒立", "handstand", "K"),
            ("单手", "one_hand_handstand", "L"),
            ("思考", "think", "U"),
            ("比心", "make_heart", "I"),
            ("挥手", "wave", "O"),
            ("拒绝", "refuse", "P"),
            ("爬行", "crawl", "F"),
            ("坐下", "sit", "G"),
            ("坐凳单", "sit_chair", "H"),
            ("小跑", "trot", "Y"),
            ("上楼", "climb_stairs", "T"),
        ]

        for label, act, key in actions:
            btn = ActionTechButton(
                text=label,
                action_name=act,
                key_label=f"({key})",
                func=self.send_motion,
                size=(dp(80), dp(60)),
                fill_color=(0.3, 0.1, 0.4, 0.15),  # 动作按钮紫色调
                border_color=(0.6, 0.2, 0.8, 0.3),
            )
            actions_grid.add_widget(btn)
            self.key_actions[key.lower()] = act
            self.buttons[act] = btn

        actions_scroll.add_widget(actions_grid)
        self.add_widget(actions_scroll)

        # Bind keyboard
        self._keyboard = None
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
                on_key_down=self._on_window_key_down, on_key_up=self._on_window_key_up
            )
            self._keyboard = True

    def unbind_keyboard(self):
        if getattr(self, "_keyboard", None):
            Window.unbind(
                on_key_down=self._on_window_key_down, on_key_up=self._on_window_key_up
            )
            self._keyboard = None

    def send_motion(self, action_name):
        ctrl = get_controller()
        if ctrl and ctrl.is_connected:
            ctrl.send_motion(action_name)
            logger.info(f"Gamepad sent: {action_name}")
        else:
            logger.warning(f"Gamepad: ESP32未连接 (Tried to send {action_name})")

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

    def _key_name_from_code(self, key_code, scancode=0):
        """从 Kivy key code 映射到小写键名，不依赖输入法和 CapsLock 状态"""
        # 优先使用 scancode，物理按键最可靠，不受输入法和大小写影响
        if scancode in GamepadLayout._SCANCODE_TO_NAME:
            return GamepadLayout._SCANCODE_TO_NAME[scancode]

        kmap = GamepadLayout._KEYCODE_TO_NAME
        if kmap is None:
            kmap = self._build_keycode_map()
        name = kmap.get(key_code)
        if name:
            return name.lower()
        # ASCII 可打印字符 fallback
        if 32 <= key_code <= 126:
            return chr(key_code).lower()
        return ""

    def _on_window_key_down(self, window, key, scancode, codepoint, modifiers):
        key_name = self._key_name_from_code(key, scancode)

        if key_name in self.key_actions:
            action = self.key_actions[key_name]
            self._simulate_button_down(action)
            return True
        return False

    def _on_window_key_up(self, window, key, scancode):
        key_name = self._key_name_from_code(key, scancode)

        handled = False
        if key_name in self.key_actions:
            action = self.key_actions[key_name]
            self._simulate_button_up(action)
            handled = True

        # 如果方向键松开，判断是否需要停止
        if key_name in ["w", "a", "s", "d", "up", "down", "left", "right"]:
            opp_map = {
                "w": "s",
                "s": "w",
                "up": "down",
                "down": "up",
                "a": "d",
                "d": "a",
                "left": "right",
                "right": "left",
            }
            req_stop = True
            if key_name in opp_map:
                opp = opp_map[key_name]
                btn_key = self.key_actions.get(opp)
                if btn_key:
                    btn = self.buttons.get(btn_key)
                    if btn and btn.state == "down":
                        req_stop = False

            if req_stop:
                self.send_motion("stand")

        return handled
