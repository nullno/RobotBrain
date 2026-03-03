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
        # 更频繁地刷新以提高界面实时性
        Clock.schedule_once(lambda dt: self.refresh(), 0)
        Clock.schedule_interval(lambda dt: self.refresh(), 1.0)

    def refresh(self):
        app = App.get_running_app()
        try:
            from services.wifi_servo import get_controller
            ctrl = getattr(app, 'wifi_servo', None) or get_controller()
            if not ctrl or not ctrl.is_connected:
                self.lbl.text = '舞机: 未连接'
                return
            st = ctrl.request_status(timeout=0.5)
            if st and 'servos' in st:
                cnt = len(st['servos'])
                self.lbl.text = f'舞机在线: {cnt}'
            else:
                self.lbl.text = '舞机: 等待状态'
        except Exception:
            self.lbl.text = '舵机: 读取失败'
