"""迷你 ESP32 连接状态指示器 — 仅小图标。"""

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.image import Image


class Esp32Indicator(ButtonBehavior, BoxLayout):
    """极简 ESP32 状态图标徽章 (≈18×18dp)。"""

    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", size_hint=(None, None), **kwargs)
        self.padding = (0, 0)
        self.spacing = 0
        self.size = (dp(18), dp(18))

        self._icon = Image(
            source="assets/icon_offline.png",
            size_hint=(None, None),
            size=(dp(18), dp(18)),
            allow_stretch=True,
            keep_ratio=True,
        )

        self.add_widget(self._icon)

    def on_release(self):
        try:
            from widgets.remote_panel import RemotePanel
            panel = RemotePanel()
            panel.open()
        except Exception as e:
            print(e)



    # ── 外部接口 ──────────────────────────────
    def update_state(self, state: dict):
        connected = bool(state.get("connected"))

        new_source = "assets/icon_online.png" if connected else "assets/icon_offline.png"
        if self._icon.source != new_source:
            self._icon.source = new_source
            self._icon.reload()

        # 固定尺寸，保持图标紧凑
        side = dp(18)
        self.size = (side, side)
        self._icon.size = (side, side)


__all__ = ["Esp32Indicator"]
