"""迷你 ESP32 连接状态指示器 — 右上角药丸徽章。"""

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle, Ellipse
from kivy.animation import Animation


class _StatusDot(Widget):
    """呼吸闪烁的状态圆点。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._glow_color = Color(0.85, 0.35, 0.35, 0.25)
        self._glow = Ellipse()
        self._core_color = Color(0.85, 0.35, 0.35, 1)
        self._core = Ellipse()
        with self.canvas:
            self._glow_color; self._glow
            self._core_color; self._core
        self.bind(pos=self._sync, size=self._sync)

    def set_online(self, online: bool):
        if online:
            self._core_color.rgba = (0.2, 0.9, 0.55, 1)
            self._glow_color.rgba = (0.2, 0.9, 0.55, 0.3)
        else:
            self._core_color.rgba = (0.85, 0.35, 0.35, 1)
            self._glow_color.rgba = (0.85, 0.35, 0.35, 0.25)

    def _sync(self, *_):
        cx, cy = self.center_x, self.center_y
        r = min(self.width, self.height)
        # 外发光圈
        gr = r * 1.6
        self._glow.pos = (cx - gr / 2, cy - gr / 2)
        self._glow.size = (gr, gr)
        # 内实心圆
        self._core.pos = (cx - r / 2, cy - r / 2)
        self._core.size = (r, r)


class Esp32Indicator(BoxLayout):
    """紧凑药丸型 ESP32 状态徽章 (≈120×28dp)。"""

    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", size_hint=(None, None), **kwargs)
        self.size = (dp(120), dp(28))
        self.padding = (dp(8), dp(4))
        self.spacing = dp(6)

        with self.canvas.before:
            self._bg_color = Color(0.12, 0.14, 0.18, 0.75)
            self._bg = RoundedRectangle(radius=[dp(14)])
        self.bind(pos=self._sync_bg, size=self._sync_bg)

        # 状态圆点
        self._dot = _StatusDot(size_hint=(None, None), size=(dp(10), dp(10)))

        # 主标签（IP 或 "离线"）
        self._label = Label(
            text="ESP32",
            color=(0.7, 0.8, 0.9, 0.9),
            font_size="11sp",
            halign="left",
            valign="middle",
            size_hint=(1, 1),
        )
        self._label.bind(size=self._label.setter("text_size"))

        self.add_widget(self._dot)
        self.add_widget(self._label)

    # ── 外部接口 ──────────────────────────────
    def update_state(self, state: dict):
        connected = bool(state.get("connected"))
        host = state.get("host") or ""
        rssi = state.get("wifi_rssi")
        servo_count = state.get("servo_count")

        self._dot.set_online(connected)

        if connected:
            parts = [host] if host else ["在线"]
            if rssi:
                parts.append(f"{rssi}dB")
            if servo_count:
                parts.append(f"S{servo_count}")
            self._label.text = " · ".join(parts)
            self._label.color = (0.75, 0.95, 0.85, 1)
            self._bg_color.rgba = (0.15, 0.25, 0.2, 0.8)
        else:
            self._label.text = "ESP32 离线"
            self._label.color = (0.7, 0.5, 0.5, 0.85)
            self._bg_color.rgba = (0.2, 0.12, 0.12, 0.8)

        # 根据文字长度自适应宽度
        base = dp(50)  # dot + padding + spacing
        char_w = dp(7)
        self.width = max(dp(100), base + len(self._label.text) * char_w)

    # ── 内部 ──────────────────────────────────
    def _sync_bg(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size


__all__ = ["Esp32Indicator"]
