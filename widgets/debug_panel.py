from kivy.uix.widget import Widget
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
import threading
import subprocess
import os
import sys
import time


# ===================== 科技风基础按钮 =====================
class TechButton(Button):
    radius = 8

    def __init__(
        self,
        border_color=(0.2, 0.7, 0.95, 1),
        fill_color=(0.2, 0.7, 0.95, 0.25),
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
            try:
                from kivy.utils import platform

                kwargs.setdefault("height", dp(56) if platform == "android" else 40)
            except Exception:
                kwargs.setdefault("height", 40)

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


# ===================== 正方形科技风按钮 (用于 Grid) =====================
class SquareTechButton(TechButton):
    def __init__(self, **kwargs):
        side_len = dp(90)
        kwargs["size_hint"] = (None, None)
        kwargs["size"] = (side_len, side_len)

        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        kwargs.setdefault("font_size", "13sp")

        super().__init__(**kwargs)
        self.bind(size=self._update_text_size)

    def _update_text_size(self, *args):
        self.text_size = (self.width - dp(10), self.height - dp(10))


# ===================== 红色实心紧急按钮 =====================
class DangerButton(Button):
    radius = 8

    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("color", (1, 1, 1, 1))
        kwargs.setdefault("size_hint_y", None)
        try:
            from kivy.utils import platform

            kwargs.setdefault("height", dp(58) if platform == "android" else 42)
        except Exception:
            kwargs.setdefault("height", 42)
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


# ===================== 科技风状态卡片 =====================
class ServoStatusCard(FloatLayout):
    radius = 8

    def __init__(self, sid, data=None, online=True, **kwargs):
        super().__init__(
            size_hint=(None, None),
            size=(dp(160), dp(120)),
            **kwargs,
        )

        self.sid = sid

        with self.canvas.before:
            if online:
                self._bg_color = Color(0.12, 0.16, 0.2, 0.9)
                self._border_color = Color(0.2, 0.7, 0.95, 0.9)
            else:
                self._bg_color = Color(0.12, 0.12, 0.15, 0.7)
                self._border_color = Color(0.4, 0.4, 0.45, 0.6)
            self._bg_rect = RoundedRectangle(radius=[self.radius])
            self._border_line = Line(
                rounded_rectangle=(0, 0, 100, 100, self.radius), width=1.2
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
            pos_hint={"x": -0.02, "y": 0.8},
        )
        self.lbl_id.bind(size=self.lbl_id.setter("text_size"))
        self.add_widget(self.lbl_id)

        self.lbl_conn = Label(
            text="●",
            color=(0.3, 0.9, 0.5, 1) if online else (0.6, 0.6, 0.6, 0.6),
            size_hint=(None, None),
            size=(dp(20), dp(20)),
            halign="right",
            valign="top",
            font_size="18sp",
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
        self.body.clear_widgets()
        fields = [
            ("角度", "-" if not data else str(data.get("pos", 0))),
            ("温度", "-" if not data else f"{data.get('temp',0)}°C"),
            ("电压", "-" if not data else f"{data.get('volt',0)}V"),
            ("扭矩", "-" if not data else ("ON" if data.get("torque") else "OFF")),
        ]

        for key, val in fields:
            cell = BoxLayout(
                orientation="vertical",
                size_hint=(1, None),
                height=dp(40),
                padding=(4, 2),
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
            if data is None:
                self.lbl_conn.color = (0.6, 0.6, 0.6, 0.6)
            else:
                self.lbl_conn.color = (0.3, 0.9, 0.5, 1)
        except Exception:
            pass


# ===================== 主调试面板 =====================
class DebugPanel(Widget):

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

    # -------------------------------------------------

    def open_debug(self):
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
            text="调试面板 — 谨慎操作舵机。确保周围无人。",
            size_hint_y=None,
            height=28,
            color=(0.85, 0.9, 0.98, 1),
        )
        content.add_widget(info)

        # ---------------- TabbedPanel ----------------
        tp = TabbedPanel(do_default_tab=False, tab_width=150, size_hint_y=0.78)
        try:
            from kivy.utils import platform

            tp.tab_height = dp(56) if platform == "android" else 42
        except Exception:
            tp.tab_height = 42

        # ---------- 动作 Tab ----------
        t_actions = TabbedPanelItem(text="动作")
        self._style_tab(t_actions)

        sv_actions = ScrollView(size_hint=(1, 1))
        sv_actions.do_scroll_x = False
        sv_actions.do_scroll_y = True

        grid = GridLayout(cols=5, padding=dp(5), spacing=dp(15), size_hint=(None, None))
        grid.bind(minimum_height=grid.setter("height"))

        actions_anchor = AnchorLayout(anchor_x="center", anchor_y="top", size_hint=(1, None))

        btn_run_demo = SquareTechButton(text="运行示例\nDemo")
        btn_stand = SquareTechButton(text="站立")
        btn_sit = SquareTechButton(text="坐下")
        btn_walk = SquareTechButton(text="前行小步")
        btn_wave = SquareTechButton(text="挥手(右)")
        btn_dance = SquareTechButton(text="舞蹈")
        btn_jump = SquareTechButton(text="跳跃")
        btn_turn = SquareTechButton(text="原地转身")
        btn_squat = SquareTechButton(text="下蹲")
        btn_kick = SquareTechButton(text="踢腿")
        btn_zero_id = SquareTechButton(text="归零写ID")

        grid.add_widget(btn_run_demo)
        grid.add_widget(btn_zero_id)
        grid.add_widget(btn_stand)
        grid.add_widget(btn_sit)
        grid.add_widget(btn_walk)
        grid.add_widget(btn_wave)
        grid.add_widget(btn_dance)
        grid.add_widget(btn_jump)
        grid.add_widget(btn_turn)
        grid.add_widget(btn_squat)
        grid.add_widget(btn_kick)

        actions_anchor.add_widget(grid)
        sv_actions.add_widget(actions_anchor)

        def _reflow_actions(instance, width):
            cols = max(1, grid.cols)
            spacing = grid.spacing[0] if isinstance(grid.spacing, (list, tuple)) else grid.spacing
            pad = grid.padding[0] * 2 if isinstance(grid.padding, (list, tuple)) else grid.padding * 2

            avail = max(dp(200), sv_actions.width - pad)
            item_w = max(dp(80), (avail - spacing * (cols - 1)) / cols)
            item_h = dp(90)

            grid.width = avail*1.01
            grid.size_hint_x = None
            grid.size_hint_y = None

            rows = (len(grid.children) + cols - 1) // cols
            grid.height = rows * item_h + max(0, rows - 1) * spacing
            actions_anchor.height = grid.height

            for c in grid.children:
                c.size_hint = (None, None)
                c.width = item_w
                c.height = item_h

        sv_actions.bind(width=_reflow_actions)
        Clock.schedule_once(lambda dt: _reflow_actions(None, sv_actions.width), 0)

        t_actions.add_widget(sv_actions)
        tp.add_widget(t_actions)

        # ---------- ✅ 舵机状态 Tab（宽度自适应 + 无抖动最终版） ----------
        t_status = TabbedPanelItem(text="舵机状态")
        self._style_tab(t_status)

        sv = ScrollView(size_hint=(1, 1))
        sv.do_scroll_x = False
        sv.do_scroll_y = True

        self._status_grid = GridLayout(
            spacing=dp(12),
            padding=dp(15),
            size_hint=(1, None),
            cols=1,   # 动态列数
        )
        self._status_grid.bind(minimum_height=self._status_grid.setter("height"))
        sv.add_widget(self._status_grid)

        def _reflow_status(*_):
            width = sv.width
            spacing = self._status_grid.spacing
            pad = self._status_grid.padding

            spacing = spacing[0] if isinstance(spacing, (list, tuple)) else spacing
            pad = pad[0] * 2 if isinstance(pad, (list, tuple)) else pad * 2

            min_card_w = dp(150)
            avail = max(dp(200), width - pad)
            cols = max(1, int(avail // min_card_w))
            self._status_grid.cols = cols

            card_w = ((avail - spacing * (cols - 1)) / cols)
            card_h = dp(120)

            for c in self._status_grid.children:
                c.size_hint = (None, None)
                c.width = card_w
                c.height = card_h

        sv.bind(width=_reflow_status)
        Clock.schedule_once(lambda dt: _reflow_status(), 0)

        t_status.add_widget(sv)
        tp.add_widget(t_status)

        try:
            self._build_single_servo_tab(tp)
        except Exception:
            pass

        tp.bind(current_tab=lambda inst, val: self._update_tab_highlight(inst, val))
        Clock.schedule_once(lambda dt: self._update_tab_highlight(tp, tp.current_tab), 0)

        content.add_widget(tp)

        # ---------------- 底部按钮 ----------------
        bottom = BoxLayout(size_hint_y=None, height=42, spacing=8)

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

        # 固定弹窗宽度为 900（高度仍根据屏幕比例限制）
        popup_width = 920
        if Window.width > Window.height:
            popup_height = min(1000, Window.height * 0.85)
        else:
            popup_height = min(1120, Window.height * 0.95)
        popup.size = (popup_width, popup_height)

        # ---------------- 事件绑定 ----------------
        def _run_demo(_):
            popup.dismiss()
            self._start_demo_thread()

        def _zero_id(_):
            popup.dismiss()
            self._start_zero_id_thread()

        def _stand(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=("stand",), daemon=True).start()

        def _sit(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=("sit",), daemon=True).start()

        def _walk(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=("walk",), daemon=True).start()

        def _wave(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=("wave",), daemon=True).start()

        def _dance(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=("dance",), daemon=True).start()

        def _jump(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=("jump",), daemon=True).start()

        def _turn(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=("turn",), daemon=True).start()

        def _squat(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=("squat",), daemon=True).start()

        def _kick(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=("kick",), daemon=True).start()

        def _emergency(_):
            popup.dismiss()
            self._emergency_torque_release()

        btn_run_demo.bind(on_release=_run_demo)
        btn_stand.bind(on_release=_stand)
        btn_sit.bind(on_release=_sit)
        btn_walk.bind(on_release=_walk)
        btn_wave.bind(on_release=_wave)
        btn_dance.bind(on_release=_dance)
        btn_jump.bind(on_release=_jump)
        btn_turn.bind(on_release=_turn)
        btn_squat.bind(on_release=_squat)
        btn_kick.bind(on_release=_kick)
        btn_zero_id.bind(on_release=_zero_id)
        btn_emergency.bind(on_release=_emergency)
        btn_close.bind(on_release=lambda *a: popup.dismiss())

        def _on_tab_switch(instance, value):
            if value and getattr(value, "text", "") == "舵机状态":
                threading.Thread(target=self.refresh_servo_status, daemon=True).start()

        tp.bind(current_tab=_on_tab_switch)

        popup.open()

    # ---------------- 原有功能代码 ----------------

    def _start_demo_thread(self):
        t = threading.Thread(target=self._run_demo_motion, daemon=True)
        t.start()

    def _run_demo_motion(self):
        app = App.get_running_app()

        def show_msg(txt):
            self._show_info_popup(txt)

        try:
            from widgets.runtime_status import RuntimeStatusLogger
        except:
            RuntimeStatusLogger = None

        if (
            not hasattr(app, "servo_bus")
            or not app.servo_bus
            or getattr(app.servo_bus, "is_mock", True)
        ):
            show_msg("未连接舵机或为 MOCK 模式，无法运行 Demo")
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_error("Demo 启动失败：未连接舵机或为 MOCK 模式")
            return

        try:
            from services.motion_controller import MotionController
            from services.imu import IMUReader
        except Exception as e:
            show_msg(f"模块导入失败: {e}")
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_error(f"Demo 模块导入失败: {e}")
            return

        servo_mgr = app.servo_bus.manager
        neutral = (
            {i: 2048 for i in servo_mgr.servo_info_dict.keys()}
            if hasattr(servo_mgr, "servo_info_dict")
            else {i: 2048 for i in range(1, 26)}
        )
        imu = IMUReader(simulate=True)
        imu.start()
        mc = MotionController(
            servo_mgr,
            balance_ctrl=app.balance_ctrl,
            imu_reader=imu,
            neutral_positions=neutral,
        )

        show_msg("开始 Demo: 站立")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo 开始 - 站立")
        mc.stand()
        time.sleep(1.0)

        show_msg("Demo: 挥手")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo - 挥手")
        mc.wave(side="right", times=3)
        time.sleep(0.6)

        show_msg("Demo: 前行小步")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo - 前行小步")
        mc.walk(steps=2, step_length=120, step_height=120, time_per_step_ms=350)
        time.sleep(0.6)

        show_msg("Demo: 坐下")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo - 坐下")
        mc.sit()
        time.sleep(1.2)

        show_msg("Demo: 站起并回中位")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo - 站起并回中位")
        mc.stand()
        time.sleep(0.8)

        imu.stop()
        show_msg("Demo 完成")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo 完成")

    def _start_zero_id_thread(self):
        t = threading.Thread(target=self._run_zero_id_script, daemon=True)
        t.start()

    def _run_zero_id_script(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        script = os.path.join(root, "tools", "testbench", "servo_zero_and_id.py")
        if not os.path.exists(script):
            script = os.path.join(
                os.path.abspath(os.path.join(root, "..")),
                "tools",
                "testbench",
                "servo_zero_and_id.py",
            )
        if not os.path.exists(script):
            self._show_info_popup("未找到 servo_zero_and_id.py 脚本")
            return
        try:
            subprocess.Popen([sys.executable, script])
            self._show_info_popup("归零/写ID脚本已在独立进程启动")
        except Exception as e:
            self._show_info_popup(f"启动脚本失败: {e}")

    def _emergency_torque_release(self):
        app = App.get_running_app()

        try:
            from widgets.runtime_status import RuntimeStatusLogger
        except:
            RuntimeStatusLogger = None

        if not hasattr(app, "servo_bus") or not app.servo_bus:
            self._show_info_popup("未找到 ServoBus")
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_error("未找到 ServoBus 无法释放扭矩")
            return
        try:
            app.servo_bus.set_torque(False)
            self._show_info_popup("已发送：紧急释放扭矩")
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_action("紧急释放扭矩")
        except Exception as e:
            self._show_info_popup(f"释放扭矩失败: {e}")
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_error(f"释放扭矩失败: {e}")

    # ===================== 舵机状态刷新 =====================
    def refresh_servo_status(self):
        app = App.get_running_app()
        mgr = getattr(app, "servo_bus", None)

        def _clear():
            self._status_grid.clear_widgets()

        Clock.schedule_once(lambda dt: _clear(), 0)

        if not mgr or getattr(mgr, "is_mock", False):
            max_id = 25
            for sid in range(1, max_id + 1):
                Clock.schedule_once(
                    lambda dt, s=sid: self._status_grid.add_widget(
                        ServoStatusCard(s, data=None, online=False)
                    ),
                    0,
                )
            return

        mgr = app.servo_bus.manager
        known_ids = set(getattr(mgr, "servo_info_dict", {}).keys())
        max_known = max(known_ids) if known_ids else 25
        max_id = max(max_known, getattr(mgr, "max_id", 25))

        for sid in range(1, max_id + 1):
            data = None
            online = False

            if sid in known_ids:
                try:
                    pos = mgr.read_data_by_name(sid, "CURRENT_POSITION")
                    temp = mgr.read_data_by_name(sid, "CURRENT_TEMPERATURE")
                    volt = mgr.read_data_by_name(sid, "CURRENT_VOLTAGE")
                    torque_flag = mgr.read_data_by_name(sid, "TORQUE_ENABLE")
                    online = mgr.servo_info_dict[sid].is_online

                    data = dict(pos=pos, temp=temp, volt=volt, torque=torque_flag)
                except Exception:
                    data = None
                    online = False

            Clock.schedule_once(
                lambda dt, s=sid, d=data, o=online: self._status_grid.add_widget(
                    ServoStatusCard(s, data=d, online=o)
                ),
                0,
            )

    # ------------------------------------------------------

    def _show_info_popup(self, text):
        def _create_popup_ui(dt):
            content = BoxLayout(padding=(20, 10), orientation="vertical")

            with content.canvas.before:
                Color(0.1, 0.12, 0.15, 0.95)
                bg_rect = RoundedRectangle(radius=[10])
            with content.canvas.after:
                Color(0.2, 0.7, 0.95, 0.8)
                border_line = Line(width=1.5)

            def _update_bg(inst, val):
                bg_rect.pos = inst.pos
                bg_rect.size = inst.size
                border_line.rounded_rectangle = (
                    inst.x,
                    inst.y,
                    inst.width,
                    inst.height,
                    10,
                )

            content.bind(pos=_update_bg, size=_update_bg)

            lbl = Label(
                text=text,
                color=(0.9, 0.95, 1, 1),
                font_size="16sp",
                halign="center",
                valign="middle",
            )
            lbl.bind(size=lbl.setter("text_size"))
            content.add_widget(lbl)

            popup = Popup(
                title="",
                title_size=0,
                separator_height=0,
                content=content,
                size_hint=(None, None),
                size=(400, 100),
                auto_dismiss=False,
                background="",
                background_color=(0, 0, 0, 0),
                overlay_color=(0, 0, 0, 0.3),
            )

            popup.open()
            Clock.schedule_once(lambda dt: popup.dismiss(), 2.0)

        Clock.schedule_once(_create_popup_ui, 0)

    def _call_motion(self, action):
        app = App.get_running_app()
        mc = getattr(app, "motion_controller", None)
        if not mc:
            self._show_info_popup("MotionController 未初始化或为 MOCK 模式")
            return

        try:
            if (
                hasattr(app, "servo_bus")
                and app.servo_bus
                and not getattr(app.servo_bus, "is_mock", True)
            ):
                try:
                    app.servo_bus.set_torque(True)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            from widgets.runtime_status import RuntimeStatusLogger
        except:
            RuntimeStatusLogger = None

        try:
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_action(action)

            if action == "stand":
                mc.stand()
            elif action == "sit":
                mc.sit()
            elif action == "walk":
                mc.walk(steps=2, step_length=120, step_height=120, time_per_step_ms=350)
            elif action == "wave":
                mc.wave(side="right", times=3)
            elif action == "dance":
                mc.dance() if hasattr(mc, "dance") else None
            elif action == "jump":
                mc.jump() if hasattr(mc, "jump") else None
            elif action == "turn":
                mc.turn(angle=360) if hasattr(mc, "turn") else None
            elif action == "squat":
                mc.squat() if hasattr(mc, "squat") else None
            elif action == "kick":
                mc.kick() if hasattr(mc, "kick") else None

            self._show_info_popup(f"动作 {action} 已发送")
        except Exception as e:
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_error(f"动作 {action} 执行失败: {e}")
            self._show_info_popup(f"动作执行失败: {e}")

    # ================= 单舵机快捷调试 =================
    def _build_single_servo_tab(self, tp):
        app = App.get_running_app()
        t_single = TabbedPanelItem(text="单舵机")
        self._style_tab(t_single)

        sv = ScrollView(size_hint=(1, 1))

        box = BoxLayout(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(12),
            size_hint_y=None,
        )
        box.bind(minimum_height=box.setter("height"))

        # ---------- 1. ID 控制行 ----------
        id_anchor = AnchorLayout(
            anchor_x="center", anchor_y="center", size_hint_y=None, height=dp(60)
        )

        id_row = BoxLayout(
            size_hint=(None, None), width=dp(190), height=dp(42), spacing=dp(10)
        )

        common_height = dp(42)

        self._single_id_label = Label(
            text="1",
            color=(0.3, 0.85, 1, 1),
            bold=True,
            size_hint=(None, None),
            size=(dp(20), common_height),
            halign="center",
            valign="middle",
            font_size="20sp",
        )

        btn_dec = TechButton(
            text="-",
            border_color=(1.0, 0.35, 0.35, 1),
            fill_color=(1.0, 0.35, 0.35, 0.35),
            size_hint=(None, None),
            size=(dp(80), common_height),
        )
        btn_dec.font_size = "22sp"

        btn_inc = TechButton(
            text="+",
            border_color=(0.2, 0.9, 0.7, 1),
            fill_color=(0.2, 0.9, 0.7, 0.35),
            size_hint=(None, None),
            size=(dp(80), common_height),
        )
        btn_inc.font_size = "22sp"

        id_row.add_widget(btn_dec)
        id_row.add_widget(self._single_id_label)
        id_row.add_widget(btn_inc)

        id_anchor.add_widget(id_row)
        box.add_widget(id_anchor)

        # ---------- 2. 快捷操作行 ----------
        grid = GridLayout(cols=4, padding=dp(10), spacing=dp(15), size_hint=(None, None))
        grid.bind(minimum_height=grid.setter("height"))

        btn_zero = SquareTechButton(text="归零\n(回中位)")
        btn_read = SquareTechButton(text="读取状态")
        btn_60 = SquareTechButton(text="转动60°")
        btn_360 = SquareTechButton(text="转动360°")
        btn_torque_toggle = SquareTechButton(text="扭矩: ?")
        btn_spin = SquareTechButton(text="间歇旋转")
        btn_set_id = SquareTechButton(text="设置ID")
        btn_motor_mode = SquareTechButton(text="电机模式")

        grid.add_widget(btn_zero)
        grid.add_widget(btn_read)
        grid.add_widget(btn_60)
        grid.add_widget(btn_360)
        grid.add_widget(btn_torque_toggle)
        grid.add_widget(btn_spin)
        grid.add_widget(btn_set_id)
        grid.add_widget(btn_motor_mode)

        grid_anchor = AnchorLayout(anchor_x="center", anchor_y="top", size_hint=(1, None))
        grid_anchor.add_widget(grid)
        box.add_widget(grid_anchor)
        sv.add_widget(box)

        def _reflow_single_grid(instance, width):
            cols = max(1, grid.cols)
            spacing = grid.spacing[0] if isinstance(grid.spacing, (list, tuple)) else grid.spacing
            pad = grid.padding[0] * 2 if isinstance(grid.padding, (list, tuple)) else grid.padding * 2

            avail = max(dp(200), sv.width - pad)
            item_w = max(dp(80), (avail - spacing * (cols - 1)) / cols)
            item_h = dp(90)

            grid.width = avail*1.02
            grid.size_hint_x = None
            grid.size_hint_y = None

            rows = (len(grid.children) + cols - 1) // cols
            grid.height = rows * item_h + max(0, rows - 1) * spacing
            grid_anchor.height = grid.height

            for c in grid.children:
                c.size_hint = (None, None)
                c.width = item_w
                c.height = item_h

        sv.bind(width=_reflow_single_grid)
        Clock.schedule_once(lambda dt: _reflow_single_grid(None, sv.width), 0)

        t_single.add_widget(sv)
        tp.add_widget(t_single)

        # ---------- helpers ----------
        def _get_sid():
            try:
                v = int(self._single_id_label.text)
                return max(1, min(250, v))
            except Exception:
                return 1

        def _set_sid(n):
            n = max(1, min(250, int(n)))
            self._single_id_label.text = str(n)

        def _inc(_):
            _set_sid(_get_sid() + 1)

        def _dec(_):
            _set_sid(_get_sid() - 1)

        self._single_id_label.bind(text=lambda *_: _set_sid(_get_sid()))

        def _ensure_torque():
            app = App.get_running_app()
            try:
                if (
                    hasattr(app, "servo_bus")
                    and app.servo_bus
                    and not getattr(app.servo_bus, "is_mock", True)
                ):
                    app.servo_bus.set_torque(True)
                    return True
            except Exception:
                pass
            return False

        def _move_to_angle(angle_deg):
            app = App.get_running_app()
            sid = _get_sid()
            if (
                not hasattr(app, "servo_bus")
                or not app.servo_bus
                or getattr(app.servo_bus, "is_mock", True)
            ):
                self._show_info_popup("未连接舵机或为 MOCK 模式")
                return

            def _do():
                try:
                    _ensure_torque()
                    mgr = app.servo_bus.manager
                    pos = int(angle_deg / 360.0 * 4095)
                    mgr.set_position_time(sid, pos, time_ms=400)
                    msg = f"ID {sid} 转到 {angle_deg}°"
                    Clock.schedule_once(lambda dt, m=msg: self._show_info_popup(m))
                except Exception as e:
                    msg = f"移动失败: {e}"
                    Clock.schedule_once(lambda dt, m=msg: self._show_info_popup(m))

            threading.Thread(target=_do, daemon=True).start()

        def _move_zero(_):
            _move_to_angle(0)

        def _move_60(_):
            _move_to_angle(60)

        def _move_360(_):
            _move_to_angle(360)

        def _read_status(_):
            app = App.get_running_app()
            sid = _get_sid()
            if (
                not hasattr(app, "servo_bus")
                or not app.servo_bus
                or getattr(app.servo_bus, "is_mock", True)
            ):
                self._show_info_popup("未连接舵机或为 MOCK 模式")
                return

            def _do_read():
                try:
                    mgr = app.servo_bus.manager
                    pos = mgr.read_data_by_name(sid, "CURRENT_POSITION")
                    temp = mgr.read_data_by_name(sid, "CURRENT_TEMPERATURE")
                    volt = mgr.read_data_by_name(sid, "CURRENT_VOLTAGE")
                    msg = f"ID {sid} -> pos:{pos} temp:{temp}C volt:{volt}V"
                    Clock.schedule_once(lambda dt, m=msg: self._show_info_popup(m))
                except Exception as e:
                    msg = f"读取失败: {e}"
                    Clock.schedule_once(lambda dt, m=msg: self._show_info_popup(m))

            threading.Thread(target=_do_read, daemon=True).start()

        # 单一扭矩开关（针对当前选中 ID）
        def _update_torque_label(dt=None):
            app = App.get_running_app()
            sid = _get_sid()
            try:
                if (
                    hasattr(app, "servo_bus")
                    and app.servo_bus
                    and not getattr(app.servo_bus, "is_mock", True)
                ):
                    mgr = app.servo_bus.manager
                    val = mgr.read_data_by_name(sid, "TORQUE_ENABLE")
                    text = "扭矩: ON" if val else "扭矩: OFF"
                    btn_torque_toggle.text = text
                else:
                    btn_torque_toggle.text = "扭矩: ?"
            except Exception:
                btn_torque_toggle.text = "扭矩: ?"

        def _toggle_torque(_):
            app = App.get_running_app()
            sid = _get_sid()
            try:
                if not (hasattr(app, "servo_bus") and app.servo_bus and not getattr(app.servo_bus, "is_mock", True)):
                    self._show_info_popup("ServoBus 未连接")
                    return
                mgr = app.servo_bus.manager
                cur = mgr.read_data_by_name(sid, "TORQUE_ENABLE")
                new = 0x01 if not cur else 0x00
                mgr.write_data_by_name(sid, "TORQUE_ENABLE", new)
                Clock.schedule_once(lambda dt: _update_torque_label(), 0.2)
                self._show_info_popup("已切换扭矩")
            except Exception as ex:
                self._show_info_popup(f"扭矩操作失败: {ex}")

        # 间歇旋转：在后台线程循环移动，直到停止
        if not hasattr(self, '_spin_controllers'):
            self._spin_controllers = {}

        def _spin_toggle(_):
            sid = _get_sid()
            ctrl = self._spin_controllers.get(sid)
            if ctrl and ctrl.get('running'):
                ctrl['running'] = False
                self._show_info_popup('停止间歇旋转')
                return

            app = App.get_running_app()
            if not (hasattr(app, "servo_bus") and app.servo_bus and not getattr(app.servo_bus, "is_mock", True)):
                self._show_info_popup('ServoBus 未连接')
                return

            stop_flag = {'running': True}
            self._spin_controllers[sid] = stop_flag

            def _run_spin():
                mgr = app.servo_bus.manager
                a = 500
                b = 3500
                try:
                    while stop_flag['running']:
                        try:
                            mgr.set_position_time(sid, a, time_ms=400)
                        except Exception:
                            pass
                        time.sleep(0.6)
                        if not stop_flag['running']:
                            break
                        try:
                            mgr.set_position_time(sid, b, time_ms=400)
                        except Exception:
                            pass
                        time.sleep(0.6)
                finally:
                    stop_flag['running'] = False

            threading.Thread(target=_run_spin, daemon=True).start()
            self._show_info_popup('开始间歇旋转')

        def _set_id(_):
            sid = _get_sid()
            app = App.get_running_app()
            if not (hasattr(app, "servo_bus") and app.servo_bus and not getattr(app.servo_bus, "is_mock", True)):
                self._show_info_popup('ServoBus 未连接')
                return

            from kivy.uix.textinput import TextInput
            content = BoxLayout(orientation='vertical', spacing=8, padding=8)
            ti = TextInput(text=str(sid), multiline=False, input_filter='int')
            content.add_widget(ti)
            btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=8)
            ok = TechButton(text='写入')
            cancel = TechButton(text='取消')
            btn_row.add_widget(ok)
            btn_row.add_widget(cancel)
            content.add_widget(btn_row)
            popup = Popup(title='设置舵机ID', content=content, size_hint=(None,None), size=(320,160))

            def _do_ok(_):
                try:
                    new_id = int(ti.text)
                    mgr = app.servo_bus.manager
                    mgr.write_data_by_name(sid, 'SERVO_ID', new_id)
                    time.sleep(0.2)
                    ok_ping = mgr.ping(new_id)
                    popup.dismiss()
                    self._show_info_popup('写入ID ' + ('成功' if ok_ping else '失败'))
                except Exception as ex:
                    popup.dismiss()
                    self._show_info_popup(f'写ID失败: {ex}')

            def _do_cancel(_):
                popup.dismiss()

            ok.bind(on_release=_do_ok)
            cancel.bind(on_release=_do_cancel)
            popup.open()

        def _set_motor_mode(_):
            sid = _get_sid()
            app = App.get_running_app()
            if not (hasattr(app, "servo_bus") and app.servo_bus and not getattr(app.servo_bus, "is_mock", True)):
                self._show_info_popup('ServoBus 未连接')
                return
            content = BoxLayout(orientation='vertical', spacing=8, padding=8)
            btn_servo = TechButton(text='舵机模式')
            btn_dc = TechButton(text='直流电机模式')
            btn_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=8)
            btn_row.add_widget(btn_servo)
            btn_row.add_widget(btn_dc)
            content.add_widget(btn_row)
            popup = Popup(title='设置电机模式', content=content, size_hint=(None,None), size=(320,120))

            def _do(mode):
                try:
                    mgr = app.servo_bus.manager
                    mgr.write_data_by_name(sid, 'MOTOR_MODE', mode)
                    popup.dismiss()
                    self._show_info_popup('已设置电机模式')
                except Exception as ex:
                    popup.dismiss()
                    self._show_info_popup(f'设置模式失败: {ex}')

            btn_servo.bind(on_release=lambda *_: _do(0x01))
            btn_dc.bind(on_release=lambda *_: _do(0x00))

        btn_inc.bind(on_release=_inc)
        btn_dec.bind(on_release=_dec)
        btn_zero.bind(on_release=_move_zero)
        btn_60.bind(on_release=_move_60)
        btn_360.bind(on_release=_move_360)
        btn_read.bind(on_release=_read_status)
        btn_torque_toggle.bind(on_release=_toggle_torque)
        btn_spin.bind(on_release=_spin_toggle)
        btn_set_id.bind(on_release=_set_id)
        btn_motor_mode.bind(on_release=_set_motor_mode)

        # 更新扭矩显示当 ID 变化时，并在创建时立即刷新一次扭矩状态
        self._single_id_label.bind(text=lambda *_: (_set_sid(_get_sid()), Clock.schedule_once(lambda dt: _update_torque_label(), 0)))
        Clock.schedule_once(lambda dt: _update_torque_label(), 0)
