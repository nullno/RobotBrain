"""
robot_actions.py - 机器人动作定义与共享组件

PC驾驶舱(CockpitPanel)和手机遥控手柄(RemotePanel)共用的：
- 动作列表定义
- 键盘映射
- ActionTechButton 按钮组件
- 动作发送 / 应急函数
"""

import logging
from kivy.metrics import dp
from kivy.core.window import Window
from app.theme import FONT
from services.wifi_servo import get_controller
from widgets.debug_ui_components import SquareTechButton

logger = logging.getLogger(__name__)

# ==================== 动作定义 ====================
NAV_ACTIONS = [
    ("前进", "walk", "W", ["w", "up"]),
    ("后退", "backward", "S", ["s", "down"]),
    ("左转", "turn_left", "A", ["a", "left"]),
    ("右转", "turn_right", "D", ["d", "right"]),
    ("站立", "stand", "Space", ["spacebar"]),
]

MOTION_ACTIONS = [
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
    ("坐凳", "sit_chair", "H"),
    ("小跑", "trot", "Y"),
    ("上楼", "climb_stairs", "T"),
]

# 键盘→动作 映射
KEY_MAP = {
    "w": "walk", "up": "walk",
    "s": "backward", "down": "backward",
    "a": "turn_left", "left": "turn_left",
    "d": "turn_right", "right": "turn_right",
    "spacebar": "stand",
    "e": "emergency",
}
for _label, _act, _key in MOTION_ACTIONS:
    KEY_MAP[_key.lower()] = _act

# ==================== 键盘扫描码映射 ====================
SCANCODE_TO_NAME = {
    4: 'a', 5: 'b', 6: 'c', 7: 'd', 8: 'e', 9: 'f', 10: 'g', 11: 'h', 12: 'i',
    13: 'j', 14: 'k', 15: 'l', 16: 'm', 17: 'n', 18: 'o', 19: 'p', 20: 'q',
    21: 'r', 22: 's', 23: 't', 24: 'u', 25: 'v', 26: 'w', 27: 'x', 28: 'y', 29: 'z',
    44: 'spacebar', 79: 'right', 80: 'left', 81: 'down', 82: 'up', 41: 'escape'
}

_KEYCODE_TO_NAME = None


def _build_keycode_map():
    global _KEYCODE_TO_NAME
    from kivy.core.window import Keyboard
    _KEYCODE_TO_NAME = {v: k for k, v in Keyboard.keycodes.items()}
    return _KEYCODE_TO_NAME


def key_name_from_code(key_code, scancode=0):
    global _KEYCODE_TO_NAME
    if scancode in SCANCODE_TO_NAME:
        return SCANCODE_TO_NAME[scancode]
    kmap = _KEYCODE_TO_NAME
    if kmap is None:
        kmap = _build_keycode_map()
    name = kmap.get(key_code)
    if name:
        return name.lower()
    if 32 <= key_code <= 126:
        return chr(key_code).lower()
    return ""


# ==================== 共享函数 ====================
def send_motion(action_name):
    """发送动作到 ESP32"""
    ctrl = get_controller()
    if ctrl and ctrl.is_connected:
        ctrl.send_motion(action_name)
        logger.info(f"Robot action: {action_name}")
    else:
        logger.warning(f"ESP32未连接 (Tried: {action_name})")


def emergency_action(widget=None):
    """断电卸力"""
    try:
        from app.debug_panel_runtime import emergency_torque_release
        emergency_torque_release(widget)
    except Exception:
        pass


def unfocus_text_inputs():
    """取消所有TextInput的焦点，防止抢夺键盘事件"""
    try:
        from kivy.uix.textinput import TextInput as _TI
        for child in Window.children:
            for w in child.walk():
                if isinstance(w, _TI) and w.focus:
                    w.focus = False
                    return True
    except Exception:
        pass
    return False


# ==================== 共享按钮组件 ====================
class ActionTechButton(SquareTechButton):
    """手机端遥控手柄使用的方块动作按钮"""

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
