"""
ConnectionStatus — ESP32 配网门禁 + 主界面延迟加载逻辑。

职责：
- 未连接 ESP32 时显示遮罩（gate）,阻止用户操作主界面
- 轮询检测连接状态，连接成功后移除遮罩，显示主界面
- 提供蓝牙配网入口
"""

from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.metrics import dp
from kivy.graphics import Color, Rectangle
from kivy.clock import Clock

from widgets.debug_ui_components import TechButton
from widgets.runtime_status import RuntimeStatusLogger
from services.wifi_servo import get_controller as get_wifi_servo

import logging

logger = logging.getLogger(__name__)


class ConnectionGate(FloatLayout):
    """遮罩层：未连接 ESP32 时覆盖主界面。"""

    def __init__(self, on_ble_setup=None, font_name=None, **kwargs):
        super().__init__(size_hint=(1, 1), **kwargs)
        self._on_ble_setup = on_ble_setup

        with self.canvas.before:
            Color(0, 0, 0, 0.86)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_bg, size=self._sync_bg)

        font_kw = {"font_name": font_name} if font_name else {}

        self.status_lbl = Label(
            text="等待 ESP32 连接 Wi-Fi",
            font_size="18sp",
            color=(0.9, 0.95, 1, 1),
            size_hint=(None, None),
            halign="center", valign="middle",
            width=dp(520), height=dp(60),
            pos_hint={"center_x": 0.5, "center_y": 0.6},
            **font_kw,
        )
        self.status_lbl.bind(size=self.status_lbl.setter("text_size"))

        self.tip_lbl = Label(
            text="请先完成 ESP32 配网，完成后自动进入主界面",
            font_size="14sp",
            color=(0.75, 0.82, 0.92, 1),
            size_hint=(None, None),
            width=dp(520), height=dp(40),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
            halign="center", valign="middle",
            **font_kw,
        )
        self.tip_lbl.bind(size=self.tip_lbl.setter("text_size"))

        action_btn = TechButton(
            text="蓝牙配网",
            size_hint=(None, None),
            width=dp(150), height=dp(44),
            pos_hint={"center_x": 0.5, "center_y": 0.4},
        )
        action_btn.bind(on_release=self._on_action)

        self.add_widget(self.status_lbl)
        self.add_widget(self.tip_lbl)
        self.add_widget(action_btn)

    def _sync_bg(self, *_):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _on_action(self, *_):
        if callable(self._on_ble_setup):
            self._on_ble_setup()

    def update_status(self, text: str):
        try:
            self.status_lbl.text = text
        except Exception:
            pass


def is_esp32_ready(app=None):
    """检查 ESP32 是否已在线；若仅有 host 未标记 connected，则主动探测一次。"""
    try:
        ctrl = getattr(app, "wifi_servo", None) if app else None
        ctrl = ctrl or get_wifi_servo()
        if not ctrl:
            return False
        if ctrl.is_connected:
            return True
        # 尚未标记 connected，但已经知道 host，则尝试一次快速 status 以拉起连接标记
        if getattr(ctrl, "host", None):
            try:
                st = ctrl.request_status(timeout=0.5)
                if st:
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False


def setup_connection_gate(app):
    """创建并挂载配网门禁遮罩，返回 gate 实例。

    如果 ESP32 已在线则不创建。
    """
    if is_esp32_ready(app):
        return None

    def _open_ble():
        popup = getattr(app, "_esp32_setup_popup", None)
        if popup:
            try:
                popup.open_popup()
            except Exception:
                pass

    font = getattr(app, "theme_font", None)
    gate = ConnectionGate(on_ble_setup=_open_ble, font_name=font)

    root = getattr(app, "root_widget", None)
    if root:
        root.add_widget(gate)

    return gate


def poll_connection(app, gate, dt=0):
    """轮询 ESP32 连接状态；已连接时移除 gate 并显示主界面。

    返回 False 表示停止定时器。
    """
    try:
        if is_esp32_ready(app):
            _enter_main_ui(app, gate)
            return False
        _update_gate_status(app, gate)
    except Exception:
        pass
    return True


def _update_gate_status(app, gate):
    """更新遮罩上的状态文本。"""
    if gate is None:
        return
    try:
        status = "等待 ESP32 连接 Wi-Fi"
        ctrl = getattr(app, "wifi_servo", None) or get_wifi_servo()
        if ctrl and ctrl.host:
            status = f"正在连接 ESP32 ({ctrl.host})"
            if ctrl.is_connected:
                status = f"ESP32 已连接 ({ctrl.host})"
        gate.update_status(status)
    except Exception:
        pass


def _enter_main_ui(app, gate):
    """连接成功：移除遮罩，显示主界面组件。"""
    try:
        if gate and gate.parent:
            gate.parent.remove_widget(gate)
    except Exception:
        pass
    # 显示主界面组件
    try:
        root = getattr(app, "root_widget", None)
        if root and hasattr(root, "ids"):
            main = root.ids.get("main_content")
            if main:
                main.opacity = 1
                main.disabled = False
    except Exception:
        pass
    try:
        RuntimeStatusLogger.log_info("ESP32 已在线，进入主界面")
    except Exception:
        pass


def refresh_link_indicator(app, dt=0):
    """周期刷新右上角 ESP32 指示器。"""
    try:
        indicator = None
        root = getattr(app, "root_widget", None)
        if root and getattr(root, "ids", None):
            indicator = root.ids.get("esp32_indicator")
        ctrl = getattr(app, "wifi_servo", None) or get_wifi_servo()
        if indicator:
            state = {
                "connected": bool(ctrl and ctrl.is_connected),
                "host": getattr(ctrl, "host", "") if ctrl else "",
            }
            if ctrl and ctrl.is_connected:
                try:
                    st = ctrl.request_status(timeout=0.8)
                    if st:
                        state["wifi_rssi"] = st.get("wifi", {}).get("rssi", 0)
                        state["servo_count"] = len(st.get("servos", {}))
                except Exception:
                    pass
            indicator.update_state(state)
    except Exception:
        pass


__all__ = [
    "ConnectionGate",
    "is_esp32_ready",
    "setup_connection_gate",
    "poll_connection",
    "refresh_link_indicator",
]
