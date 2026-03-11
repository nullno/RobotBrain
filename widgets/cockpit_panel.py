from kivy.uix.floatlayout import FloatLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.graphics import Color, Line
from kivy.app import App
from kivy.metrics import dp

from widgets.gamepad_layout import GamepadLayout

Builder.load_string('''
<CockpitPanel>:
    # 准星层（全屏捕获点击）
    FloatLayout:
        id: crosshair_layer
        on_touch_down: root._on_crosshair_touch_down(*args)
        
    # 下方控制器容器
    AnchorLayout:
        anchor_x: 'center'
        anchor_y: 'bottom'
        padding: [20, 20, 20, 20] # 距离底部留点缝隙
        
        BoxLayout:
            id: gamepad_container
            orientation: 'vertical'
            size_hint: None, None
            # 修改大小以适应 GamepadLayout
            size: dp(700), dp(250)

<CrosshairWidget>:
    size_hint: None, None
    size: dp(80), dp(80)
    canvas.before:
        Color:
            rgba: 0, 1, 0, 0.8
        Line:
            circle: self.center_x, self.center_y, dp(2)
        Line:
            points: [self.center_x, self.center_y + dp(10), self.center_x, self.center_y + dp(40)]
            width: dp(1.5)
        Line:
            points: [self.center_x, self.center_y - dp(10), self.center_x, self.center_y - dp(40)]
            width: dp(1.5)
        Line:
            points: [self.center_x - dp(10), self.center_y, self.center_x - dp(40), self.center_y]
            width: dp(1.5)
        Line:
            points: [self.center_x + dp(10), self.center_y, self.center_x + dp(40), self.center_y]
            width: dp(1.5)
        Color:
            rgba: 0, 1, 0, 0.3
        Line:
            rectangle: [self.x, self.y, self.width, self.height]
''')

class CrosshairWidget(Widget):
    pass

class CockpitPanel(FloatLayout):
    def on_touch_down(self, touch):
        if self.disabled or self.opacity == 0:
            return False
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
        self._current_crosshair = None
        
        is_pc = getattr(App.get_running_app(), "run_mode", "phone") == "pc"
        self.gamepad = GamepadLayout(scale=0.5 if is_pc else 1.0, action_cols=4 if is_pc else 3, is_pc=is_pc)
        # 由于 GamepadLayout 默认有 spacing，微调一下
        Clock.schedule_once(self._add_gamepad, 0)
        
        self.bind(disabled=self._on_disabled_change)
        Clock.schedule_once(lambda dt: self._on_disabled_change(self, self.disabled), 0)

    def _add_gamepad(self, dt):
        self.ids.gamepad_container.add_widget(self.gamepad)

    def _on_disabled_change(self, instance, value):
        if not value:
            self.gamepad.bind_keyboard()
        else:
            self.gamepad.unbind_keyboard()

    def _on_crosshair_touch_down(self, layout, touch):
        if getattr(self, "disabled", False) or getattr(self, "opacity", 1.0) == 0:
            return False

        if touch.y < dp(280): # 点击在控制区域内
            return False

        if self._current_crosshair:
            self.ids.crosshair_layer.remove_widget(self._current_crosshair)
            
        self._current_crosshair = CrosshairWidget()
        self._current_crosshair.center = (touch.x, touch.y)
        self.ids.crosshair_layer.add_widget(self._current_crosshair)
        
        app = App.get_running_app()
        if hasattr(app, 'runtime_status'):
            app.runtime_status.log_info(f"瞄准坐标: ({int(touch.x)}, {int(touch.y)})")
            
        return True
