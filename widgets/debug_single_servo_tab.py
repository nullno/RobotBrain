import threading
import time

from services.wifi_servo import SERVO_MAX, angle_to_pos, pos_to_angle

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.utils import platform
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, RoundedRectangle, Line

try:
    from widgets.runtime_status import RuntimeStatusLogger
except Exception:
    RuntimeStatusLogger = None


def build_single_servo_tab_content(owner, tab_item, tech_button_cls, square_button_cls, angle_knob_cls):
    sv = ScrollView(size_hint=(1, 1))

    box = BoxLayout(
        orientation="vertical",
        padding=dp(12),
        spacing=dp(12),
        size_hint_y=None,
    )
    box.bind(minimum_height=box.setter("height"))

    id_anchor = AnchorLayout(
        anchor_x="center", anchor_y="center", size_hint_y=None, height=dp(60)
    )

    id_row = BoxLayout(
        size_hint=(None, None), width=dp(190), height=dp(42), spacing=dp(10)
    )

    common_height = dp(40)

    owner._single_id_label = Label(
        text="1",
        color=(0.3, 0.85, 1, 1),
        bold=True,
        size_hint=(None, None),
        size=(dp(20), common_height),
        halign="center",
        valign="middle",
        font_size="25sp",
    )

    btn_dec = tech_button_cls(
        text="-",
        border_color=(1.0, 0.35, 0.35, 1),
        fill_color=(1.0, 0.35, 0.35, 0.35),
        size_hint=(None, None),
        size=(dp(80), common_height),
    )
    btn_dec.font_size = "22sp"

    btn_inc = tech_button_cls(
        text="+",
        border_color=(0.2, 0.9, 0.7, 1),
        fill_color=(0.2, 0.9, 0.7, 0.35),
        size_hint=(None, None),
        size=(dp(80), common_height),
    )
    btn_inc.font_size = "25sp"

    id_row.add_widget(btn_dec)
    id_row.add_widget(owner._single_id_label)
    id_row.add_widget(btn_inc)

    id_anchor.add_widget(id_row)
    box.add_widget(id_anchor)

    grid = GridLayout(
        cols=4, padding=dp(10), spacing=dp(15), size_hint=(None, None)
    )
    grid.bind(minimum_height=grid.setter("height"))

    btn_zero = square_button_cls(text="归零\n(回中位)")
    btn_read = square_button_cls(text="读取状态")
    btn_360 = square_button_cls(text="转动360°")
    btn_torque_toggle = square_button_cls(text="扭矩: ON")

    grid.add_widget(btn_zero)
    grid.add_widget(btn_read)
    grid.add_widget(btn_360)
    grid.add_widget(btn_torque_toggle)

    grid_anchor = AnchorLayout(
        anchor_x="center", anchor_y="top", size_hint=(1, None)
    )
    grid_anchor.add_widget(grid)
    box.add_widget(grid_anchor)

    box.add_widget(BoxLayout(size_hint_y=None, height=dp(10)))

    control_panel = BoxLayout(
        orientation="vertical",
        size_hint_y=None,
        height=dp(136),
        padding=(dp(15), dp(10)),
        spacing=dp(8),
    )
    with control_panel.canvas.before:
        Color(0.12, 0.14, 0.17, 0.6)
        cp_bg = RoundedRectangle(radius=[8])
        Color(1, 1, 1, 0.1)
        cp_border = Line(width=1)

    def _update_cp_bg(inst, _):
        cp_bg.pos = inst.pos
        cp_bg.size = inst.size
        cp_border.rounded_rectangle = (inst.x, inst.y, inst.width, inst.height, 8)

    control_panel.bind(pos=_update_cp_bg, size=_update_cp_bg)

    def _style_ti(ti):
        ti.write_tab = False
        ti.background_normal = ""
        ti.background_active = ""
        ti.background_color = (0.08, 0.08, 0.1, 1)
        ti.foreground_color = (0.9, 0.9, 0.9, 1)
        ti.cursor_color = (0.2, 0.7, 0.95, 1)
        ti.halign = "center"
        ti.padding_y = [dp(6), 0]

    row_params = BoxLayout(spacing=dp(12))
    lbl_dur = Label(text="时间(ms)", size_hint=(None, 1), width=dp(60),
                   font_size="14sp", color=(0.6, 0.7, 0.8, 1), halign='right', valign='middle')
    lbl_dur.bind(size=lbl_dur.setter('text_size'))

    ti_dur = TextInput(text="500", multiline=False, input_filter="int",
                      size_hint=(None, None), size=(dp(60), dp(32)))
    _style_ti(ti_dur)

    row_params.add_widget(lbl_dur)
    row_params.add_widget(ti_dur)
    row_params.add_widget(Label())
    control_panel.add_widget(row_params)

    row_cust = BoxLayout(spacing=dp(12))

    lbl_c_angle = Label(text="定点(°)", size_hint=(None, 1), width=dp(60),
                       font_size="14sp", color=(0.6, 0.7, 0.8, 1), halign='right', valign='middle')
    lbl_c_angle.bind(size=lbl_c_angle.setter('text_size'))

    ti_c_angle = TextInput(text="90", multiline=False, input_filter="float",
                          size_hint=(None, None), size=(dp(60), dp(32)))
    _style_ti(ti_c_angle)

    btn_c_go = tech_button_cls(text="执行", size_hint=(None, None), size=(dp(60), dp(32)))

    row_cust.add_widget(lbl_c_angle)
    row_cust.add_widget(ti_c_angle)
    row_cust.add_widget(btn_c_go)
    row_cust.add_widget(Label())
    control_panel.add_widget(row_cust)

    row_cycle = BoxLayout(spacing=dp(8))

    lbl_cy = Label(text="循环(°)", size_hint=(None, 1), width=dp(60),
                  font_size="14sp", color=(0.6, 0.7, 0.8, 1), halign='right', valign='middle')
    lbl_cy.bind(size=lbl_cy.setter('text_size'))

    ti_cy_a = TextInput(text="0", multiline=False, input_filter="float",
                       size_hint=(None, None), size=(dp(50), dp(32)))
    _style_ti(ti_cy_a)

    lbl_cy_mid = Label(text="~", size_hint=(None, 1), width=dp(15), color=(0.5,0.5,0.5,1))

    ti_cy_b = TextInput(text="180", multiline=False, input_filter="float",
                       size_hint=(None, None), size=(dp(50), dp(32)))
    _style_ti(ti_cy_b)

    btn_cy_run = tech_button_cls(text="开始", size_hint=(None, None), size=(dp(50), dp(32)),
                               border_color=(0.2, 0.8, 0.4, 0.8), fill_color=(0.2, 0.8, 0.4, 0.2))
    btn_cy_stop = tech_button_cls(text="停止", size_hint=(None, None), size=(dp(50), dp(32)),
                                border_color=(1, 0.3, 0.3, 0.8), fill_color=(1, 0.3, 0.3, 0.2))

    row_cycle.add_widget(lbl_cy)
    row_cycle.add_widget(ti_cy_a)
    row_cycle.add_widget(lbl_cy_mid)
    row_cycle.add_widget(ti_cy_b)
    row_cycle.add_widget(btn_cy_run)
    row_cycle.add_widget(btn_cy_stop)

    control_panel.add_widget(row_cycle)

    box.add_widget(control_panel)

    knob_wrap = BoxLayout(
        orientation="vertical",
        size_hint_y=None,
        height=dp(230),
        padding=(dp(15), dp(8)),
        spacing=dp(6),
    )
    with knob_wrap.canvas.before:
        Color(0.12, 0.14, 0.17, 0.6)
        kw_bg = RoundedRectangle(radius=[8])
        Color(1, 1, 1, 0.1)
        kw_border = Line(width=1)

    def _update_kw_bg(inst, _):
        kw_bg.pos = inst.pos
        kw_bg.size = inst.size
        kw_border.rounded_rectangle = (inst.x, inst.y, inst.width, inst.height, 8)

    knob_wrap.bind(pos=_update_kw_bg, size=_update_kw_bg)

    knob_caption = Label(
        text="ANGLE 0-360",
        color=(0.7, 0.8, 0.9, 1),
        font_size="14sp",
        size_hint_y=None,
        height=dp(24),
    )
    knob_wrap.add_widget(knob_caption)

    knob_anchor = AnchorLayout(anchor_x="center", anchor_y="center")
    angle_knob = angle_knob_cls(size=(dp(180), dp(180)))
    knob_anchor.add_widget(angle_knob)
    knob_wrap.add_widget(knob_anchor)
    box.add_widget(knob_wrap)
    sv.add_widget(box)

    def _reflow_single_grid(instance, width):
        cols = max(1, grid.cols)
        spacing = (
            grid.spacing[0]
            if isinstance(grid.spacing, (list, tuple))
            else grid.spacing
        )
        pad = (
            grid.padding[0] * 2
            if isinstance(grid.padding, (list, tuple))
            else grid.padding * 2
        )

        avail = max(dp(200), sv.width - pad)
        item_w = max(dp(80), (avail - spacing * (cols - 1)) / cols)
        item_h = dp(90)

        grid.width = avail
        grid.size_hint_x = None
        grid.size_hint_y = None

        rows = (len(grid.children) + cols - 1) // cols
        grid.height = rows * item_h + max(0, rows - 1) * spacing
        grid_anchor.height = grid.height

        for c in grid.children:
            c.size_hint = (None, None)
            c.width = item_w * 0.96
            c.height = item_h

    sv.bind(width=_reflow_single_grid)
    Clock.schedule_once(lambda dt: _reflow_single_grid(None, sv.width), 0)

    try:
        tab_item.clear_widgets()
    except Exception:
        pass
    tab_item.add_widget(sv)

    def _get_sid():
        try:
            v = int(owner._single_id_label.text)
            return max(1, min(250, v))
        except Exception:
            return 1

    def _set_sid(n):
        n = max(1, min(250, int(n)))
        owner._single_id_label.text = str(n)

    def _inc(_):
        _set_sid(_get_sid() + 1)

    def _dec(_):
        _set_sid(_get_sid() - 1)

    owner._single_id_label.bind(text=lambda *_: _set_sid(_get_sid()))

    def _ensure_torque():
        app = App.get_running_app()
        try:
            wifi_ctrl = getattr(app, "wifi_servo", None)
            if wifi_ctrl and wifi_ctrl.is_connected:
                wifi_ctrl.set_torque(True)
                return True
        except Exception:
            pass
        return False

    def _is_sid_online(sid):
        app = App.get_running_app()
        try:
            wifi_ctrl = getattr(app, "wifi_servo", None)
            if wifi_ctrl and wifi_ctrl.is_connected:
                return True
        except Exception:
            pass
        return False

    def _require_sid_online(sid, strict=True):
        ok = _is_sid_online(sid)
        if not ok:
            # 关节调试不显示“未确认在线，已尝试下发”，统一提示“未连接”
            owner._show_info_popup(f"ID {sid} 未连接")
        return ok

    def _move_to_angle(angle_deg, show_tip=True, duration_override=None):
        app = App.get_running_app()
        sid = _get_sid()

        # 优先 WiFi 舵机控制器（固件范围 0-4095）
        wifi_ctrl = getattr(app, "wifi_servo", None)
        if not (wifi_ctrl and wifi_ctrl.is_connected):
            if show_tip:
                owner._show_info_popup("未连接舵机")
            return

        def _do_wifi():
            try:
                _ensure_torque()
                pos = angle_to_pos(angle_deg)
                if duration_override is not None:
                    dur = max(0, int(duration_override))
                else:
                    try:
                        dur = int(ti_dur.text)
                        dur = max(0, dur)
                    except Exception:
                        dur = 500
                wifi_ctrl.set_single(sid, pos, duration_ms=dur)
                owner._mark_servo_writable(sid)
                if show_tip:
                    msg = f"ID {sid} 转到 {angle_deg:.0f}\u00b0 ({dur}ms) [WiFi]"
                    Clock.schedule_once(lambda dt, m=msg: owner._show_info_popup(m))
            except Exception as e:
                msg = f"移动失败: {e}"
                Clock.schedule_once(lambda dt, m=msg: owner._show_info_popup(m))
        threading.Thread(target=_do_wifi, daemon=True).start()

    knob_sync_state = {"busy": False}

    def _set_knob_and_text(value):
        try:
            v = float(value)
        except Exception:
            v = 0.0
        knob_sync_state["busy"] = True
        angle_knob.set_value(v)
        ti_c_angle.text = str(int(round(max(0.0, min(360.0, v)))))
        Clock.schedule_once(lambda dt: knob_sync_state.__setitem__("busy", False), 0)

    def _move_zero(_):
        _move_to_angle(0, duration_override=500)
        _set_knob_and_text(0)

    def _move_60(_):
        _move_to_angle(60)
        _set_knob_and_text(60)

    def _move_360(_):
        _move_to_angle(360)
        _set_knob_and_text(360)

    _knob_timer = {}

    def _move_knob_angle(dt=None):
        """旋钮实时控制舵机 —— 节流与防抖发送"""
        try:
            if knob_sync_state.get("busy"):
                return
            ang = float(getattr(angle_knob, "value", 0.0))
            ti_c_angle.text = str(int(round(ang)))
            
            # 使用简单的节流(Throttle)机制：30ms 频率上限
            now = time.time()
            last_t = _knob_timer.get("last_send_time", 0.0)
            
            if now - last_t < 0.03:
                # 仍在节流期内，取消之前的定时发送，重新计划最后一次发送
                if "pending_event" in _knob_timer:
                    _knob_timer["pending_event"].cancel()
                _knob_timer["pending_event"] = Clock.schedule_once(_move_knob_angle, 0.03 - (now - last_t))
                return
                
            _knob_timer["last_send_time"] = now
            
            app = App.get_running_app()
            sid = _get_sid()
            wifi_ctrl = getattr(app, "wifi_servo", None)
            if not (wifi_ctrl and wifi_ctrl.is_connected):
                return
                
            # 发送指令，采用 40ms 平滑时间，降低延迟且更丝滑
            pos = angle_to_pos(ang)
            wifi_ctrl.set_single(sid, pos, duration_ms=40)
            owner._mark_servo_writable(sid)
            
        except Exception:
            pass

    def _format_voltage(v):
        if v is None:
            return "-"
        try:
            fv = float(v)
        except Exception:
            return "-"
        if fv > 30:
            fv = fv / 10.0
        return f"{fv:.1f}"

    def _read_status(_):
        app = App.get_running_app()
        sid = _get_sid()
        try:
            app._latest_probe_sid = int(sid)
        except Exception:
            pass

        wifi_ctrl = getattr(app, "wifi_servo", None)
        if not (wifi_ctrl and wifi_ctrl.is_connected):
            owner._show_info_popup("未连接舵机")
            return

        def _do_read():
            try:
                # 尝试获取完整状态（温度/电压），不阻塞主要流程
                info = wifi_ctrl.read_full_status(sid, timeout=1.0)
                if not info:
                    # 退级至只读位置
                    pos = wifi_ctrl.read_servo_position(sid, timeout=1.0)
                    if pos is not None:
                        try:
                            deg = pos_to_angle(pos)
                            Clock.schedule_once(lambda dt, d=deg: _set_knob_and_text(d), 0)
                        except Exception:
                            pass
                        msg = f"ID {sid} -> pos:{pos} ({deg:.0f}\u00b0)"
                    else:
                        msg = f"ID {sid} 读取失败：未收到返回数据"
                else:
                    pos = info.get("position", "-")
                    if pos != "-":
                        try:
                            deg = pos_to_angle(pos)
                            Clock.schedule_once(lambda dt, d=deg: _set_knob_and_text(d), 0)
                            msg = f"ID {sid} -> pos:{pos} ({deg:.0f}\u00b0)"
                        except Exception:
                            msg = f"ID {sid} -> pos:{pos}"
                    else:
                        msg = f"ID {sid} -> 状态读取成功, 无位置信息"
                        
                    temp = info.get("temperature", "-")
                    volt = info.get("voltage")
                    current = info.get("current_ma", "-")
                    vel = info.get("velocity", "-")
                    torque = info.get("torque")
                    
                    # 容错：如果 torque 字段存在，则将其同步到按钮状态
                    if torque is not None:
                        tq_str = "ON" if torque else "OFF"
                        Clock.schedule_once(lambda dt, t=tq_str: setattr(btn_torque_toggle, 'text', f"扭矩: {t}"), 0)
                    else:
                        tq_str = "未知"
                    
                    volt_str = _format_voltage(volt)
                    if volt is not None:
                        volt_str += "V"
                        
                    msg += f"\n温:{temp}℃ 压:{volt_str} 流:{current}mA 速:{vel} 力:{tq_str}"
                    
                    # 尝试更新到界面缓存中，虽然有心跳也在更新
                    owner._mark_servo_writable(sid)

                Clock.schedule_once(lambda dt, m=msg: owner._show_info_popup(m))
            except Exception as e:
                msg = f"读取失败: {e}"
                Clock.schedule_once(lambda dt, m=msg: owner._show_info_popup(m))

        threading.Thread(target=_do_read, daemon=True).start()

    def _update_torque_label(dt=None):
        btn_torque_toggle.text = "扭矩: ON"

    def _toggle_torque(_):
        app = App.get_running_app()
        sid = _get_sid()
        wifi_ctrl = getattr(app, "wifi_servo", None)
        if not (wifi_ctrl and wifi_ctrl.is_connected):
            owner._show_info_popup("未连接舵机")
            return
        
        # 获取当前扭矩状态，尝试反转
        current_torque = True
        try:
            info = wifi_ctrl.read_full_status(sid, timeout=0.8)
            if info and "torque" in info:
                current_torque = info["torque"]
        except Exception:
            pass
            
        target_torque = not current_torque
        try:
            # 兼容 WiFi 传字典的方式，或者全局
            wifi_ctrl.set_torque(target_torque) 
            owner._mark_servo_writable(sid)
            t_str = "启用" if target_torque else "释放"
            owner._show_info_popup(f"已{t_str}扭矩")
            btn_torque_toggle.text = f"扭矩:{'ON' if target_torque else 'OFF'}"
        except Exception as ex:
            owner._show_info_popup(f"扭矩操作失败: {ex}")

    def _do_c_go(_):
        try:
            ang = float(ti_c_angle.text)
            _move_to_angle(ang)
            _set_knob_and_text(ang)
        except Exception:
            owner._show_info_popup("请输入有效角度数字")

    btn_c_go.bind(on_release=_do_c_go)

    def _do_cycle_stop(_):
        sid = _get_sid()
        ctrl = owner._spin_controllers.get(sid)
        if ctrl and ctrl.get('running'):
            ctrl['running'] = False
            owner._show_info_popup(f"已停止 ID{sid} 循环")

    def _do_cycle_run(_):
        sid = _get_sid()
        _do_cycle_stop(None)

        try:
            deg_a = float(ti_cy_a.text)
            deg_b = float(ti_cy_b.text)
        except Exception:
            owner._show_info_popup("角度输入无效")
            return

        app = App.get_running_app()
        wifi_ctrl = getattr(app, "wifi_servo", None)
        if not (wifi_ctrl and wifi_ctrl.is_connected):
            owner._show_info_popup("未连接舵机")
            return
        if not _require_sid_online(sid, strict=False):
            return

        ctrl = {'running': True}
        owner._spin_controllers[sid] = ctrl

        def _thread_bg():
            try:
                _ensure_torque()
                pos_a = int(deg_a / 360.0 * SERVO_MAX)
                pos_b = int(deg_b / 360.0 * SERVO_MAX)

                while ctrl['running']:
                    try:
                        dur = int(ti_dur.text)
                        dur = max(100, dur)
                    except Exception:
                        dur = 500

                    try:
                        wifi_ctrl.set_single(sid, pos_a, duration_ms=dur)
                    except Exception:
                        pass

                    wait_steps = int((dur + 200) / 100)
                    for _ in range(wait_steps):
                        if not ctrl['running']:
                            break
                        time.sleep(0.1)
                    if not ctrl['running']:
                        break

                    try:
                        wifi_ctrl.set_single(sid, pos_b, duration_ms=dur)
                    except Exception:
                        pass

                    for _ in range(wait_steps):
                        if not ctrl['running']:
                            break
                        time.sleep(0.1)
            except Exception:
                pass

        threading.Thread(target=_thread_bg, daemon=True).start()
        owner._show_info_popup(f"开始循环 ID{sid}: {deg_a}°↔{deg_b}°")

    btn_cy_run.bind(on_release=_do_cycle_run)
    btn_cy_stop.bind(on_release=_do_cycle_stop)

    btn_inc.bind(on_release=_inc)
    btn_dec.bind(on_release=_dec)
    btn_zero.bind(on_release=_move_zero)
    btn_360.bind(on_release=_move_360)
    btn_read.bind(on_release=_read_status)
    btn_torque_toggle.bind(on_release=_toggle_torque)

    knob_move_trigger = Clock.create_trigger(_move_knob_angle, 0.02)
    angle_knob.bind(value=lambda *_: knob_move_trigger())
    Clock.schedule_once(lambda dt: _set_knob_and_text(0), 0)

    owner._single_id_label.bind(
        text=lambda *_: (
            _set_sid(_get_sid()),
            Clock.schedule_once(lambda dt: _update_torque_label(), 0),
        )
    )
    Clock.schedule_once(lambda dt: _update_torque_label(), 0)
