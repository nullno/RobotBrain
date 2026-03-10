from kivy.uix.modalview import ModalView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.metrics import dp
from kivy.core.window import Window
from app.theme import FONT
from services.wifi_servo import get_controller
from widgets.debug_ui_components import SquareTechButton, TechButton, DangerButton
import logging

logger = logging.getLogger(__name__)

class ActionTechButton(SquareTechButton):
    def __init__(self, action_name="", key_label="", func=None, **kwargs):
        self.action_name = action_name
        self.func = func
        
        # Merge action name and key hint into text
        display_text = kwargs.pop("text", "")
        if key_label:
            display_text = f"{display_text}\n{key_label}"
            
        kwargs.setdefault('font_name', FONT)
        kwargs.setdefault('halign', 'center')
        kwargs.setdefault('valign', 'middle')
        kwargs['text'] = display_text
        
        super().__init__(**kwargs)
        self.bind(on_release=self._trigger)
        
    def _trigger(self, *args):
        if self.func:
            self.func(self.action_name)

    def _on_state(self, *args):
        if self.state == "down":
            # 按下或触发时产生强高亮反馈
            self._bg_color.rgba = (
                min(self.fill_color[0] + 0.4, 1.0),
                min(self.fill_color[1] + 0.4, 1.0),
                min(self.fill_color[2] + 0.4, 1.0),
                max(self.fill_color[3], 0.7)
            )
            self._border_color.rgba = (1, 1, 1, 1)  # 耀眼的纯白边框
            self.color = (1, 1, 1, 1)
        else:
            # 恢复正常状态
            self._bg_color.rgba = self.fill_color
            self._border_color.rgba = self.border_color
            self.color = self.text_color

class RemotePanel(ModalView):
    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint', (0.9, 0.85))
        kwargs.setdefault('auto_dismiss', True)
        kwargs.setdefault('background_color', (0, 0, 0, 0.8))
        super().__init__(**kwargs)
        
        # 科技风边框和背景
        self.main_layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        with self.main_layout.canvas.before:
            Color(0.08, 0.1, 0.12, 0.95)
            self.bg_rect = RoundedRectangle(pos=self.main_layout.pos, size=self.main_layout.size, radius=[dp(15)])
            Color(0.2, 0.6, 0.9, 0.3)
            self.border_line = Line(rounded_rectangle=(self.main_layout.x, self.main_layout.y, self.main_layout.width, self.main_layout.height, dp(15)), width=1.5)
            
            # 发光效果
            Color(0.2, 0.6, 0.9, 0.1)
            self.glow_rect = RoundedRectangle(pos=(self.main_layout.x - 4, self.main_layout.y - 4), size=(self.main_layout.width + 8, self.main_layout.height + 8), radius=[dp(18)])
            
        self.main_layout.bind(pos=self._update_bg, size=self._update_bg)

        # 标题
        title = Label(
            text="机 器 人 操 作 手 柄", 
            font_name=FONT, 
            font_size="22sp", 
            bold=True, 
            size_hint_y=None, 
            height=dp(40), 
            color=(0.2, 0.8, 1, 1) # 科技感青蓝色
        )
        self.main_layout.add_widget(title)
        
        # 注册按键映射
        self.key_actions = {}
        self.shift_actions = {}
        
        gamepad_area = BoxLayout(orientation='horizontal', spacing=dp(40))
        
        # ================= 左侧：方向键 (D-Pad) =================
        dpad_container = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_x=0.45)
        dpad_grid = GridLayout(cols=3, spacing=dp(12), size_hint=(None, None))
        dpad_grid.bind(minimum_width=dpad_grid.setter('width'), minimum_height=dpad_grid.setter('height'))
        
        self.buttons = {}
        def _add_nav_btn(text, action, key_label, keys, special_color=None):
            if not text:
                dpad_grid.add_widget(Widget(size_hint=(None, None), size=(dp(75), dp(75))))
                return
                
            btn_kwargs = dict(text=text, action_name=action, key_label=key_label, func=self.send_motion, size=(dp(75), dp(75)))
            if special_color:
                btn_kwargs['fill_color'] = special_color
                btn_kwargs['border_color'] = (special_color[0]+0.1, special_color[1]+0.1, special_color[2]+0.1, 0.8)
                
            btn = ActionTechButton(**btn_kwargs)
            dpad_grid.add_widget(btn)
            for k in keys:
                self.key_actions[k] = action
            self.buttons[action] = btn
            return btn
            
        _add_nav_btn("", "", "", [])
        _add_nav_btn("前进", "walk", "(W/)", ["w", "up"], special_color=(0.1, 0.4, 0.2, 0.5))
        _add_nav_btn("", "", "", [])
        
        _add_nav_btn("左转", "turn_left", "(A/)", ["a", "left"])
        _add_nav_btn("站立", "stand", "(Space)", ["spacebar"], special_color=(0.5, 0.4, 0.1, 0.5))
        _add_nav_btn("右转", "turn_right", "(D/)", ["d", "right"])
        
        _add_nav_btn("", "", "", [])
        _add_nav_btn("后退", "backward", "(S/)", ["s", "down"], special_color=(0.1, 0.4, 0.2, 0.5))
        _add_nav_btn("", "", "", [])
        
        dpad_container.add_widget(dpad_grid)
        gamepad_area.add_widget(dpad_container)
        
        # ================= 右侧：动作释放区 =================
        actions_scroll = ScrollView(size_hint_x=0.55)
        # 支持触摸滚动，加上一点内边距
        actions_grid = GridLayout(cols=3, spacing=dp(12), padding=[dp(5), dp(5), dp(15), dp(5)], size_hint_y=None)
        actions_grid.bind(minimum_height=actions_grid.setter('height'))
        
        actions = [
            ("蹲下", "crouch", "Z"), ("晃动", "swagger", "X"), ("叉腰", "akimbo", "C"),
            ("点头", "nod", "V"),     ("摇头", "shake_head", "B"), ("弯腰", "bend_over", "N"),
            ("扎马步", "horse_stance", "M"), ("独立", "golden_rooster", "J"), ("手倒立", "handstand", "K"),
            ("单手", "one_hand_handstand", "L"), ("思考", "think", "U"), ("比心", "make_heart", "I"),
            ("挥手", "wave", "O"), ("拒绝", "refuse", "P"), ("爬行", "crawl", "F"),
            ("坐下", "sit", "G"), ("坐凳单", "sit_chair", "H"), ("小跑", "trot", "Y"),
            ("上楼", "climb_stairs", "T")
        ]
        
        for label, act, key in actions:
            btn = ActionTechButton(
                text=label, 
                action_name=act, 
                key_label=f"(Sh+{key})", 
                func=self.send_motion,
                size=(dp(80), dp(60)),
                fill_color=(0.3, 0.1, 0.4, 0.3),    # 动作按钮紫色调
                border_color=(0.6, 0.2, 0.8, 0.5)
            )
            actions_grid.add_widget(btn)
            self.shift_actions[key.lower()] = act
            self.buttons[f"shift_{key.lower()}"] = btn
            
        actions_scroll.add_widget(actions_grid)
        gamepad_area.add_widget(actions_scroll)
        
        self.main_layout.add_widget(gamepad_area)
        
        # 底部按钮区
        bottom_area = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(20), padding=[dp(20), 0])
        close_btn = TechButton(text="关闭手柄 (Esc)", size_hint_x=0.5, border_color=(0.6, 0.6, 0.7, 1), fill_color=(0.5, 0.5, 0.6, 0.25))
        close_btn.bind(on_release=self.dismiss)
        
        emergency_btn = ActionTechButton(
            text="断电卸力", 
            key_label="(Sh+E)",
            size_hint_x=0.5,
            fill_color=(0.8, 0.1, 0.1, 0.3),
            border_color=(1, 0.2, 0.2, 0.8),
            func=self._emergency
        )
        self.shift_actions['e'] = "emergency"
        self.buttons["shift_e"] = emergency_btn
        
        bottom_area.add_widget(emergency_btn)
        bottom_area.add_widget(close_btn)
        self.main_layout.add_widget(bottom_area)
        
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
        
    def _show_info_popup(self, text):
        from app.debug_panel_runtime import show_info_popup
        show_info_popup(self, text)

    def send_motion(self, action_name):
        ctrl = get_controller()
        if ctrl and ctrl.is_connected:
            ctrl.send_motion(action_name)
            logger.info(f"Handpad sent: {action_name}")
        else:
            logger.warning("Handpad: ESP32未连接")

    # 键盘监听支持
    def on_open(self):
        Window.bind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)

    def on_dismiss(self):
        Window.unbind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)

    def _simulate_button_down(self, btn_key):
        btn = self.buttons.get(btn_key)
        if btn and btn.state == 'normal':
            btn.state = 'down'
            # 手动触发 _on_state 以防有些情况 Kivy 属性绑定没立刻生效
            if hasattr(btn, '_on_state'):
                btn._on_state()

    def _simulate_button_up(self, btn_key):
        btn = self.buttons.get(btn_key)
        if btn and btn.state == 'down':
            btn.state = 'normal'
            if hasattr(btn, '_on_state'):
                btn._on_state()
            btn.dispatch('on_release')

    def _on_key_down(self, window, keycode, scancode, codepoint, modifiers):
        key_name = str(keycode[1]).lower() if isinstance(keycode, tuple) else str(keycode).lower()

        if key_name == "escape":
            self.dismiss()
            return True

        if "shift" in modifiers:
            if key_name in self.shift_actions:
                self._simulate_button_down(f"shift_{key_name}")
                return True
        else:
            if key_name in self.key_actions:
                action = self.key_actions[key_name]
                self._simulate_button_down(action)
                return True
                
        return False

    def _on_key_up(self, window, keycode, scancode):
        key_name = str(keycode[1]).lower() if isinstance(keycode, tuple) else str(keycode).lower()
        
        # 释放shift情况
        if key_name in self.shift_actions:
            self._simulate_button_up(f"shift_{key_name}")
            return True
            
        if key_name in self.key_actions:
            action = self.key_actions[key_name]
            self._simulate_button_up(action)
            return True
            
