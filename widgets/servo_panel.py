from kivy.uix.boxlayout import BoxLayout
from kivy.properties import ObjectProperty, NumericProperty
from kivy.clock import Clock


class ServoPanel(BoxLayout):
    controller = ObjectProperty(None)

    def on_kv_post(self, base_widget):
        for sid in range(1, 26):
            self.add_servo_row(sid)

    def add_servo_row(self, sid):
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.slider import Slider

        row = BoxLayout(size_hint_y=None, height=40, spacing=6)
        row.add_widget(Label(text=f"S{sid}", size_hint_x=0.15))
        slider = Slider(min=0, max=1000, value=500)
        slider.bind(value=lambda inst, val, sid=sid: self.set_servo(sid, val))
        row.add_widget(slider)
        self.ids.container.add_widget(row)

    def set_servo(self, sid, value):
        if self.controller:
            self.controller.move(sid, int(value))
