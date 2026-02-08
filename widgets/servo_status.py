from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.app import App

class ServoStatus(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=6, padding=6, size_hint=(None, None), **kwargs)
        self.size = (220, 100)
        self.lbl = Label(text='舵机: 未连接', size_hint=(1, None), height=30)
        self.add_widget(self.lbl)
        self.btn = Button(text='刷新状态', size_hint=(1, None), height=36)
        self.btn.bind(on_release=lambda *a: self.refresh())
        self.add_widget(self.btn)
        Clock.schedule_interval(lambda dt: self.refresh(), 5.0)

    def refresh(self):
        app = App.get_running_app()
        if not hasattr(app, 'servo_bus') or not app.servo_bus:
            self.lbl.text = '舵机: 未初始化'
            return
        sb = app.servo_bus
        if getattr(sb, 'is_mock', True):
            self.lbl.text = '舵机: MOCK 模式'
            return
        try:
            mgr = sb.manager
            online = [sid for sid in mgr.servo_info_dict.keys() if mgr.servo_info_dict[sid].is_online]
            self.lbl.text = f'舵机在线: {len(online)}/{len(mgr.servo_info_dict)}'
        except Exception:
            self.lbl.text = '舵机: 读取失败'
