from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.graphics import Color, RoundedRectangle
import time


class Esp32Indicator(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", size_hint=(None, None), **kwargs)
        self.width = dp(200)
        self.height = dp(64)
        self.padding = (dp(10), dp(8))
        self.spacing = dp(4)

        with self.canvas.before:
            self._bg_color = Color(0.08, 0.1, 0.14, 0.7)
            self._bg = RoundedRectangle(radius=[10])
        self.bind(pos=self._update_rect, size=self._update_rect)

        self._title = Label(
            text="ESP32 未连接",
            color=(0.86, 0.9, 0.98, 1),
            font_size="14sp",
            size_hint_y=None,
            height=dp(20),
            halign="left",
            valign="middle",
        )
        self._title.bind(size=self._title.setter("text_size"))
        self.add_widget(self._title)

        self._detail = Label(
            text="--",
            color=(0.7, 0.8, 0.9, 1),
            font_size="12sp",
            halign="left",
            valign="middle",
        )
        self._detail.bind(size=self._detail.setter("text_size"))
        self.add_widget(self._detail)

        self._signal = Label(
            text="信号: --",
            color=(0.6, 0.85, 1, 1),
            font_size="12sp",
            halign="left",
            valign="middle",
        )
        self._signal.bind(size=self._signal.setter("text_size"))
        self.add_widget(self._signal)

    def _update_rect(self, *_):
        if self._bg:
            self._bg.pos = self.pos
            self._bg.size = self.size

    def update_state(self, state: dict):
        connected = bool(state.get("connected"))
        host = state.get("host") or "--"
        port = state.get("port") or 5005
        rssi = state.get("rssi")
        quality = state.get("quality")
        bars = state.get("bars")
        ssid = state.get("ssid") or ""
        online = state.get("online_servos")
        total = state.get("total_servos")
        last_seen = state.get("last_seen")

        title_color = (0.3, 0.9, 0.65, 1) if connected else (0.9, 0.4, 0.35, 1)
        self._title.color = title_color
        status_txt = "ESP32 已连接" if connected else "ESP32 未连接"
        self._title.text = status_txt

        detail_parts = []
        if host:
            detail_parts.append(f"{host}:{port}")
        if ssid:
            detail_parts.append(f"Wi-Fi {ssid}")
        if online is not None and total:
            detail_parts.append(f"舵机 {online}/{total}")
        if last_seen:
            dt = max(0.0, time.time() - float(last_seen))
            if dt >= 1.5:
                detail_parts.append(f"上次 {dt:.1f}s")
        self._detail.text = " · ".join(detail_parts) if detail_parts else "--"

        if rssi is None:
            sig_txt = "信号: --"
        else:
            percent_txt = f"{quality}%" if quality is not None else "--"
            bars_txt = f"{bars}/4" if bars is not None else "--"
            sig_txt = f"信号: {rssi} dBm · {percent_txt} · {bars_txt}"
        self._signal.text = sig_txt

        # subtle background accent based on connection
        if connected:
            self._bg_color.rgba = (0.2, 0.8, 0.55, 0.12)
        else:
            self._bg_color.rgba = (0.8, 0.3, 0.25, 0.15)


__all__ = ["Esp32Indicator"]
