from kivy.uix.widget import Widget
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.scrollview import ScrollView
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
import threading
import time
from widgets.angle_knob import AngleKnob
from widgets.debug_status_tab import build_status_tab_content
from widgets.debug_ai_model_tab import build_ai_model_tab_content
from widgets.debug_other_settings_tab import build_other_settings_tab_content
from widgets.debug_single_servo_tab import build_single_servo_tab_content
from widgets.debug_ui_components import (
    TechButton,
    SquareTechButton,
    DangerButton,
)
# 串口调试已移除：功能由 ESP32 网络方案替代
from app import debug_panel_runtime


# ===================== 主调试面板 =====================
class DebugPanel(Widget):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._debug_popup = None
        self._debug_tp = None
        self._debug_tab_build_queue = []
        self._debug_tab_build_ev = None
        self._last_status_refresh_req = 0.0
        self._status_cards_cache = None
        self._status_cards_cache_time = 0.0
        self._status_cache_ttl = 1.2
        self._writable_servo_ids = set()
        self._status_slow_fields_cache = {}
        self._status_slow_fields_interval = 3.0
        self._status_data_cache = {}
        self._status_card_widgets = {}
        self._status_rr_index = 0
        self._status_read_batch_size = 6
        self._status_read_backoff = {}
        self._status_backoff_base_sec = 0.8
        self._status_backoff_max_sec = 5.0
        self._lazy_tabs = {}
        self._pending_single_servo_sid = None

    def _mark_servo_writable(self, sid):
        try:
            sid = int(sid)
            if sid > 0:
                self._writable_servo_ids.add(sid)
        except Exception:
            pass

    # ---------------- TAB 样式 ----------------
    def _style_tab(self, tab):
        tab.background_normal = ""
        tab.background_down = ""
        tab.background_color = (0, 0, 0, 0)

        with tab.canvas.before:
            tab._hl_color = Color(0.2, 0.7, 0.95, 0.0)
            tab._hl_rect = RoundedRectangle(radius=[8])

        def _upd(*_):
            tab._hl_rect.pos = tab.pos
            tab._hl_rect.size = tab.size

        tab.bind(pos=_upd, size=_upd)

    def _update_tab_highlight(self, tp, current):
        for tab in tp.tab_list:
            if tab == current:
                tab._hl_color.rgba = (0.2, 0.7, 0.95, 0.22)
            else:
                tab._hl_color.rgba = (0, 0, 0, 0)

    def _register_lazy_tab(self, tp, text, builder):
        tab = TabbedPanelItem(text=text, font_size="15sp")
        self._style_tab(tab)
        try:
            tab.add_widget(
                Label(
                    text="加载中...",
                    color=(0.7, 0.8, 0.9, 1),
                )
            )
        except Exception:
            pass
        tp.add_widget(tab)
        self._lazy_tabs[str(text)] = {
            "tab": tab,
            "builder": builder,
            "built": False,
        }
        try:
            tab.bind(on_release=lambda *_: self._ensure_lazy_tab_built(tp, tab))
        except Exception:
            pass
        return tab

    def _ensure_lazy_tab_built(self, tp, tab):
        if tp is None or tab is None:
            return
        text = str(getattr(tab, "text", "") or "")
        item = self._lazy_tabs.get(text)
        if not item:
            return
        if item.get("built"):
            return
        try:
            builder = item.get("builder")
            if callable(builder):
                builder(tp, tab_item=tab)
                item["built"] = True
        except Exception:
            pass

    def _ensure_lazy_tab_built_deferred(self, tp, tab, delay=0):
        def _do(_dt):
            self._ensure_lazy_tab_built(tp, tab)

        try:
            Clock.schedule_once(_do, delay)
        except Exception:
            self._ensure_lazy_tab_built(tp, tab)

    # -------------------------------------------------

    def _build_status_tab(self, tp, tab_item=None):
        t_status = tab_item if tab_item is not None else TabbedPanelItem(text="连接状态", font_size="15sp")
        if tab_item is None:
            self._style_tab(t_status)
        self._status_grid = build_status_tab_content(t_status)
        if tab_item is None:
            tp.add_widget(t_status)
        # 立即填充全部25张离线占位卡，避免空白等待
        placeholder_cards = [(sid, None, False) for sid in range(1, 26)]
        debug_panel_runtime.render_status_cards(self, placeholder_cards)
        # 异步刷新在线状态
        threading.Thread(target=self.refresh_servo_status, daemon=True).start()

    def _on_status_card_click(self, sid):
        self._jump_to_single_servo_tab(sid)

    def _jump_to_single_servo_tab(self, sid):
        try:
            sid = max(1, min(250, int(sid)))
        except Exception:
            return

        tp = getattr(self, "_debug_tp", None)
        if tp is None:
            return

        self._pending_single_servo_sid = sid

        item = self._lazy_tabs.get("关节调试", {})
        target_tab = item.get("tab")
        if target_tab is None:
            return

        try:
            tp.switch_to(target_tab)
        except Exception:
            pass

        self._ensure_lazy_tab_built(tp, target_tab)

        def _apply_sid(_dt=0):
            try:
                lbl = getattr(self, "_single_id_label", None)
                pending = int(getattr(self, "_pending_single_servo_sid", sid) or sid)
                if lbl is not None:
                    lbl.text = str(max(1, min(250, pending)))
                self._pending_single_servo_sid = None
            except Exception:
                pass

        Clock.schedule_once(_apply_sid, 0)

    def open_debug(self):
        if self._debug_popup is not None:
            try:
                self._debug_popup.open()
                tp = getattr(self, "_debug_tp", None)
                cur = getattr(tp, "current_tab", None)
                self._ensure_lazy_tab_built(tp, cur)
                if cur and getattr(cur, "text", "") == "连接状态":
                    threading.Thread(target=self.refresh_servo_status, daemon=True).start()
                return
            except Exception:
                self._debug_popup = None
                self._debug_tp = None

        app = App.get_running_app()
        accent_blue = (0.2, 0.7, 0.95, 1.0)

        content = BoxLayout(orientation="vertical", spacing=8, padding=10)

        with content.canvas.before:
            Color(0.12, 0.15, 0.18, 0.95)
            self._bg_rect = RoundedRectangle(radius=[12])
        with content.canvas.after:
            Color(accent_blue[0], accent_blue[1], accent_blue[2], 0.08)
            self._glow_rect = RoundedRectangle(radius=[14])
            Color(0.2, 0.7, 0.95, 0.6)
            self._border_line = Line(rounded_rectangle=(0, 0, 100, 100, 12), width=2)

        def _update_rect(*_):
            self._bg_rect.pos = content.pos
            self._bg_rect.size = content.size
            self._glow_rect.pos = (content.x - 6, content.y - 6)
            self._glow_rect.size = (content.width + 12, content.height + 12)
            self._border_line.rounded_rectangle = (
                content.x,
                content.y,
                content.width,
                content.height,
                12,
            )

        content.bind(pos=_update_rect, size=_update_rect)

        info = Label(
            text="调试面板 — 谨慎操作注意夹手",
            size_hint_y=None,
            height=dp(28),
            color=(0.85, 0.9, 0.98, 1),
        )
        content.add_widget(info)

        # ---------------- TabbedPanel ----------------
        tp = TabbedPanel(do_default_tab=False, tab_width=dp(90), size_hint_y=0.78)
        tp.tab_height = dp(40)

        self._lazy_tabs = {}
        t_status = self._register_lazy_tab(tp, "连接状态", self._build_status_tab)
        t_single = self._register_lazy_tab(tp, "关节调试", self._build_single_servo_tab)
        self._register_lazy_tab(tp, "AI模型", self._build_ai_model_tab)
        self._register_lazy_tab(tp, "高级设置", self._build_other_settings_tab)

        try:
            tp.switch_to(t_status)
        except Exception:
            pass

        self._ensure_lazy_tab_built(tp, t_status)
        # 关节调试预构建改为延迟构建：避免打开弹窗时主线程被重构 UI 阻塞
        try:
            self._ensure_lazy_tab_built_deferred(tp, t_single, delay=0.08)
        except Exception:
            self._ensure_lazy_tab_built(tp, t_single)

        tp.bind(current_tab=lambda inst, val: self._update_tab_highlight(inst, val))
        Clock.schedule_once(
            lambda dt: self._update_tab_highlight(tp, tp.current_tab), 0
        )

        content.add_widget(tp)

        # ---------------- 底部按钮 ----------------
        bottom = BoxLayout(size_hint_y=None, height=dp(40), spacing=8)

        btn_emergency = DangerButton(text="紧急释放扭矩")
        btn_close = TechButton(
            text="关闭",
            border_color=(0.6, 0.6, 0.7, 1),
            fill_color=(0.5, 0.5, 0.6, 0.25),
        )

        bottom.add_widget(btn_emergency)
        bottom.add_widget(btn_close)
        content.add_widget(bottom)

        popup = Popup(
            title="",
            content=content,
            size_hint=(None, None),
            separator_height=0,
            background="",
            background_color=(0, 0, 0, 0),
        )

        # 固定弹窗宽度为 600
        popup_width = dp(600) 
        popup_height =dp(380)
        popup.size = (popup_width, popup_height)

        def _emergency(_):
            popup.dismiss()
            self._emergency_torque_release()

        btn_emergency.bind(on_release=_emergency)
        btn_close.bind(on_release=lambda *a: popup.dismiss())

        def _on_popup_dismiss(*_):
            try:
                panel = getattr(self, "_other_settings_panel", None)
                if panel and hasattr(panel, "on_panel_closed"):
                    panel.on_panel_closed()
            except Exception:
                pass

        popup.bind(on_dismiss=_on_popup_dismiss)

        def _on_tab_switch(instance, value):
            self._ensure_lazy_tab_built(tp, value)
            if value and getattr(value, "text", "") == "连接状态":
                now = time.time()
                if (now - getattr(self, "_last_status_refresh_req", 0.0)) >= 0.8:
                    self._last_status_refresh_req = now
                    threading.Thread(target=self.refresh_servo_status, daemon=True).start()

        tp.bind(current_tab=_on_tab_switch)
        self._debug_popup = popup
        self._debug_tp = tp
        popup.open()
        self._ensure_lazy_tab_built_deferred(tp, getattr(tp, "current_tab", None), 0)
        try:
            if getattr(self, "_debug_tab_build_queue", None):
                self._schedule_build_next_debug_tab()
        except Exception:
            pass

    def _schedule_build_next_debug_tab(self):
        if getattr(self, "_debug_tab_build_ev", None) is not None:
            return
        self._debug_tab_build_ev = Clock.schedule_once(self._build_next_debug_tab, 0)

    def _build_next_debug_tab(self, dt=0):
        self._debug_tab_build_ev = None
        queue = getattr(self, "_debug_tab_build_queue", None) or []
        tp = getattr(self, "_debug_tp", None)
        popup = getattr(self, "_debug_popup", None)
        if not queue or tp is None or popup is None:
            return
        try:
            builder = queue.pop(0)
            builder(tp)
        except Exception:
            pass
        if queue:
            self._debug_tab_build_ev = Clock.schedule_once(self._build_next_debug_tab, 0)

    # ---------------- 原有功能代码 ----------------

    def _start_demo_thread(self):
        debug_panel_runtime.start_demo_thread(self)

    def _run_demo_motion(self):
        debug_panel_runtime.run_demo_motion(self)

    def _start_zero_id_thread(self):
        debug_panel_runtime.start_zero_id_thread(self)

    def _run_zero_id_script(self):
        debug_panel_runtime.run_zero_id_script(self)

    def _emergency_torque_release(self):
        debug_panel_runtime.emergency_torque_release(self)

    # ===================== 舵机状态刷新 =====================
    def _render_status_cards(self, cards):
        debug_panel_runtime.render_status_cards(self, cards)

    def refresh_servo_status(self):
        debug_panel_runtime.refresh_servo_status(self)

    # ------------------------------------------------------

    def _show_info_popup(self, text):
        debug_panel_runtime.show_info_popup(self, text)

    def _call_motion(self, action):
        debug_panel_runtime.call_motion(self, action)

    # ================= 其他功能页 =================
    def _build_ai_model_tab(self, tp, tab_item=None):
        t_ai_model = tab_item if tab_item is not None else TabbedPanelItem(text="AI模型", font_size="15sp")
        if tab_item is None:
            self._style_tab(t_ai_model)

        build_ai_model_tab_content(t_ai_model)
        if tab_item is None:
            tp.add_widget(t_ai_model)

    # ================= 其他设置 =================
    def _build_other_settings_tab(self, tp, tab_item=None):
        t_other = tab_item if tab_item is not None else TabbedPanelItem(text="高级设置", font_size="15sp")
        if tab_item is None:
            self._style_tab(t_other)

        self._other_settings_panel = build_other_settings_tab_content(
            t_other,
            show_message=self._show_info_popup,
            debug_panel=self,
            button_factory=lambda **kwargs: TechButton(**kwargs),
        )
        if tab_item is None:
            tp.add_widget(t_other)

    # ================= 单舵机快捷调试 =================
    def _build_single_servo_tab(self, tp, tab_item=None):
        t_single = tab_item if tab_item is not None else TabbedPanelItem(text="关节调试", font_size="15sp")
        if tab_item is None:
            self._style_tab(t_single)

        build_single_servo_tab_content(
            owner=self,
            tab_item=t_single,
            tech_button_cls=TechButton,
            square_button_cls=SquareTechButton,
            angle_knob_cls=AngleKnob,
        )
        if tab_item is None:
            tp.add_widget(t_single)
