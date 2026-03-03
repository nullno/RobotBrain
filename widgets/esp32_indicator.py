from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle, Ellipse, Rectangle


class _Dot(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            self._color = Color(0.8, 0.35, 0.35, 1)
            self._circle = Ellipse(pos=self.pos, size=self.size)
        self.bind(pos=self._update_shape, size=self._update_shape)

    def set_color(self, rgba):
        self._color.rgba = rgba

    def _update_shape(self, *_):
        self._circle.pos = self.pos
        self._circle.size = self.size


class _Bars(Widget):
    def __init__(self, max_bars=4, **kwargs):
        super().__init__(**kwargs)
        self.max_bars = max_bars
        self._bars = 0
        self.bind(pos=self._redraw, size=self._redraw)

    def set_level(self, bars):
        try:
            self._bars = max(0, min(self.max_bars, int(bars or 0)))
        except Exception:
            self._bars = 0
        self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        spacing = self.width * 0.08
        bar_w = (self.width - spacing * (self.max_bars - 1)) / float(self.max_bars)
        base_y = self.y
        for i in range(self.max_bars):
            level = (i + 1) / float(self.max_bars)
            h = self.height * (0.35 + 0.55 * level)
            x = self.x + i * (bar_w + spacing)
            color = (0.25, 0.55, 0.85, 0.45)
            if i < self._bars:
                color = (0.25, 0.85, 0.65, 0.9)
            with self.canvas:
                Color(*color)
                Rectangle(pos=(x, base_y), size=(bar_w, h))


class Esp32Indicator(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", size_hint=(None, None), **kwargs)
        self.width = dp(220)
        self.height = dp(70)
        self.padding = (dp(12), dp(10))
        self.spacing = dp(12)

        with self.canvas.before:
            self._bg_color = Color(0.08, 0.1, 0.14, 0.7)
            self._bg = RoundedRectangle(radius=[12])
        self.bind(pos=self._update_rect, size=self._update_rect)

        # 连接状态图标 + 文本
        left = BoxLayout(orientation="vertical", size_hint=(None, 1), width=dp(48), spacing=dp(2))
        self._dot = _Dot(size_hint=(None, None), size=(dp(16), dp(16)))
        self._conn_lbl = Label(
            text="OFF",
            color=(0.8, 0.35, 0.35, 1),
            font_size="12sp",
            halign="center",
            valign="middle",
            size_hint=(1, None),
            height=dp(18),
        )
        self._conn_lbl.bind(size=self._conn_lbl.setter("text_size"))
        left.add_widget(self._dot)
        left.add_widget(self._conn_lbl)

        # Wi-Fi 强度条 + RSSI 数字
        wifi_col = BoxLayout(orientation="vertical", spacing=dp(2))
        self._bars = _Bars(size_hint=(None, None), size=(dp(60), dp(28)))
        self._rssi_lbl = Label(
            text="-- dBm",
            color=(0.7, 0.85, 1, 1),
            font_size="12sp",
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=dp(18),
        )
        self._rssi_lbl.bind(size=self._rssi_lbl.setter("text_size"))
        wifi_col.add_widget(self._bars)
        wifi_col.add_widget(self._rssi_lbl)

        # 舵机数量 + 主机信息
        right = BoxLayout(orientation="vertical", spacing=dp(2))
        self._servo_lbl = Label(
            text="S 0/0",
            color=(0.9, 0.95, 1, 1),
            font_size="13sp",
            halign="left",
            valign="middle",
            size_hint=(1, None),
            height=dp(20),
        )
        self._servo_lbl.bind(size=self._servo_lbl.setter("text_size"))
        self._host_lbl = Label(
            text="--",
            color=(0.65, 0.75, 0.85, 1),
            font_size="11sp",
            halign="left",
            valign="middle",
        )
        self._host_lbl.bind(size=self._host_lbl.setter("text_size"))
        right.add_widget(self._servo_lbl)
        right.add_widget(self._host_lbl)

        self.add_widget(left)
        self.add_widget(wifi_col)
        self.add_widget(right)

    def _update_rect(self, *_):
        if self._bg:
            self._bg.pos = self.pos
            self._bg.size = self.size

    def update_state(self, state: dict):
        connected = bool(state.get("connected"))
        host = state.get("host") or "--"
        port = state.get("port") or 5005
        rssi = state.get("rssi")
        bars = state.get("bars")
        ssid = state.get("ssid") or ""
        online = state.get("online_servos")
        total = state.get("total_servos")
        dot_color = (0.2, 0.8, 0.6, 1) if connected else (0.85, 0.35, 0.35, 1)
        self._dot.set_color(dot_color)
        self._conn_lbl.color = dot_color
        self._conn_lbl.text = "ON" if connected else "OFF"

        self._bars.set_level(bars if bars is not None else 0)
        self._rssi_lbl.text = f"{rssi:.0f} dBm" if rssi is not None else "-- dBm"

        if online is None:
            online = 0
        if total is None:
            total = 0
        self._servo_lbl.text = f"S {online}/{total}"

        host_txt = host if host else "--"
        if ssid:
            self._host_lbl.text = f"{host_txt}:{port} · {ssid}"
        else:
            self._host_lbl.text = f"{host_txt}:{port}"

        if connected:
            self._bg_color.rgba = (0.2, 0.8, 0.55, 0.12)
        else:
            self._bg_color.rgba = (0.8, 0.3, 0.25, 0.15)


__all__ = ["Esp32Indicator"]
