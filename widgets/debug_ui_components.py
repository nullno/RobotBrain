from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.metrics import dp


class TechButton(Button):
    radius = 8

    def __init__(
        self,
        border_color=(0.2, 0.7, 0.95, 0.2),
        fill_color=(0.2, 0.7, 0.95, 0.1),
        text_color=(0.9, 0.96, 1, 1),
        **kwargs,
    ):
        self.border_color = border_color
        self.fill_color = fill_color
        self.text_color = text_color

        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("color", self.text_color)
        kwargs.setdefault("size_hint_y", None)

        if "height" not in kwargs and "size" not in kwargs:
            kwargs.setdefault("height", dp(40))

        super().__init__(**kwargs)

        with self.canvas.before:
            self._bg_color = Color(*self.fill_color)
            self._bg_rect = RoundedRectangle(radius=[self.radius])
        with self.canvas.after:
            self._border_color = Color(*self.border_color)
            self._border_line = Line(
                rounded_rectangle=(0, 0, 100, 100, self.radius), width=1.4
            )

        self.bind(pos=self._update, size=self._update, state=self._on_state)

    def _update(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._border_line.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            self.radius,
        )

    def _on_state(self, *args):
        if self.state == "down":
            self._bg_color.rgba = (
                min(self.fill_color[0] + 0.15, 1),
                min(self.fill_color[1] + 0.15, 1),
                min(self.fill_color[2] + 0.15, 1),
                self.fill_color[3],
            )
            self._border_color.rgba = (
                min(self.border_color[0] + 0.15, 1),
                min(self.border_color[1] + 0.15, 1),
                min(self.border_color[2] + 0.15, 1),
                1,
            )
        else:
            self._bg_color.rgba = self.fill_color
            self._border_color.rgba = self.border_color


class SquareTechButton(TechButton):
    def __init__(self, **kwargs):
        side_len = dp(70)
        kwargs["size_hint"] = (None, None)
        kwargs["size"] = (side_len, side_len)

        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        kwargs.setdefault("font_size", "15sp")

        super().__init__(**kwargs)
        self.bind(size=self._update_text_size)

    def _update_text_size(self, *args):
        self.text_size = (self.width - dp(10), self.height - dp(10))


class DangerButton(Button):
    radius = 8

    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("color", (1, 1, 1, 1))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(40))
        super().__init__(**kwargs)

        with self.canvas.before:
            self._bg_color = Color(0.92, 0.25, 0.25, 1)
            self._bg_rect = RoundedRectangle(radius=[self.radius])

        self.bind(pos=self._update, size=self._update, state=self._on_state)

    def _update(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _on_state(self, *args):
        self._bg_color.rgba = (
            (1, 0.35, 0.35, 1) if self.state == "down" else (0.92, 0.25, 0.25, 1)
        )


class ServoStatusCard(FloatLayout):
    radius = 8

    def __init__(self, sid, data=None, online=True, on_click=None, **kwargs):
        super().__init__(
            size_hint=(None, None),
            size=(dp(95), dp(90)),
            **kwargs,
        )

        self.sid = sid
        self.on_click = on_click

        with self.canvas.before:
            if online:
                self._bg_color = Color(0.12, 0.16, 0.2, 0.2)
                self._border_color = Color(0.2, 0.7, 0.95, 0.2)
            else:
                self._bg_color = Color(0.12, 0.12, 0.15, 0.7)
                self._border_color = Color(0.4, 0.4, 0.45, 0.6)
            self._bg_rect = RoundedRectangle(radius=[self.radius])
            self._border_line = Line(
                rounded_rectangle=(0, 0, 90, 90, self.radius), width=1.2
            )

        self.bind(pos=self._update, size=self._update)

        self.lbl_id = Label(
            text=f"ID {sid}",
            color=(0.3, 0.85, 1, 1),
            bold=True,
            size_hint=(None, None),
            size=(dp(60), dp(20)),
            halign="left",
            valign="middle",
            pos_hint={"x": -0.12, "y": 0.8},
        )
        self.lbl_id.bind(size=self.lbl_id.setter("text_size"))
        self.add_widget(self.lbl_id)

        self.lbl_conn = Label(
            text="●",
            color=(0.4, 1.0, 0.1, 1) if online else (0.6, 0.6, 0.6, 0.6),
            size_hint=(None, None),
            size=(dp(10), dp(10)),
            halign="right",
            valign="top",
            font_size="10sp",
            pos_hint={"right": 0.98, "top": 0.98},
        )
        self.lbl_conn.bind(size=self.lbl_conn.setter("text_size"))
        self.add_widget(self.lbl_conn)

        self.body = GridLayout(
            cols=2,
            spacing=dp(6),
            size_hint=(0.9, None),
            pos_hint={"center_x": 0.5, "center_y": 0.42},
        )
        self.body.bind(minimum_height=self.body.setter("height"))
        self.add_widget(self.body)

        self.update_data(data)

    def set_online(self, online):
        try:
            if online:
                self.lbl_conn.color = (0.4, 1.0, 0.1, 1)
                self._bg_color.rgba = (0.12, 0.16, 0.2, 0.2)
                self._border_color.rgba = (0.2, 0.7, 0.95, 0.2)
            else:
                self.lbl_conn.color = (0.6, 0.6, 0.6, 0.6)
                self._bg_color.rgba = (0.12, 0.12, 0.15, 0.7)
                self._border_color.rgba = (0.4, 0.4, 0.45, 0.6)
        except Exception:
            pass

    def _update(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._border_line.rounded_rectangle = (
            self.x,
            self.y,
            self.width,
            self.height,
            self.radius,
        )

    def update_data(self, data):
        def _format_voltage(v):
            if v is None:
                return "-"
            try:
                fv = float(v)
            except Exception:
                return "-"
            # 兼容两种固件：有的直接返回 V（如 8/9），有的返回 0.1V（如 87 -> 8.7V）
            if fv > 30:
                fv = fv / 10.0
            return f"{fv:.1f}V"

        self.body.clear_widgets()
        fields = [
            ("角度", "-" if not data or data.get("pos") is None else str(data.get("pos"))),
            ("温度", "-" if not data or data.get("temp") is None else f"{data.get('temp')}°C"),
            ("电压", "-" if not data or data.get("volt") is None else _format_voltage(data.get("volt"))),
            ("扭矩", "-" if not data or data.get("torque") is None else ("ON" if data.get("torque") else "OFF")),
        ]

        for key, val in fields:
            cell = BoxLayout(
                orientation="vertical",
                size_hint=(1, None),
                height=dp(30),
                padding=(2, 2),
            )
            lbl_k = Label(
                text=key,
                color=(0.7, 0.8, 0.9, 1),
                font_size="12sp",
                halign="center",
                valign="middle",
            )
            lbl_v = Label(
                text=str(val),
                color=(0.9, 0.95, 1, 1),
                font_size="14sp",
                bold=True,
                halign="center",
                valign="middle",
            )
            lbl_k.bind(size=lbl_k.setter("text_size"))
            lbl_v.bind(size=lbl_v.setter("text_size"))
            cell.add_widget(lbl_k)
            cell.add_widget(lbl_v)
            self.body.add_widget(cell)

        try:
            self.set_online(data is not None)
        except Exception:
            pass

    def on_touch_down(self, touch):
        try:
            if self.collide_point(*touch.pos):
                cb = getattr(self, "on_click", None)
                if callable(cb):
                    cb(int(self.sid))
                return True
        except Exception:
            pass
        return super().on_touch_down(touch)
