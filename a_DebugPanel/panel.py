from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.properties import (
    ListProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
import os
import threading
import time

from serial_manager import PortMonitor
from knob import Knob
from universal_tip import UniversalTip
from runtime_status import RuntimeStatusPanel, RuntimeStatusLogger
try:
    from data_table import MOTOR_MODE_SERVO, MOTOR_MODE_DC, DC_DIR_CW
except Exception:
    MOTOR_MODE_SERVO, MOTOR_MODE_DC, DC_DIR_CW = 1, 0, 0

try:
    from uart_servo import UartServoManager
except Exception:
    UartServoManager = None


KV_FILE = os.path.join(os.path.dirname(__file__), 'debug_panel.kv')
Builder.load_file(KV_FILE)


def _pick_main_font():
    """Pick a CJK-capable font to avoid garbled Chinese text."""
    base = os.path.dirname(__file__)
    candidates = [
        os.path.join(base, 'assets', 'fonts', 'simhei.ttf'),
        r'C:\\Windows\\Fonts\\msyh.ttc',
        r'C:\\Windows\\Fonts\\simhei.ttf',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/PingFang.ttc',
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                return p
        except Exception:
            pass
    return ''


class DebugPanelRoot(BoxLayout):
    # default state flags to avoid early access during kv on_parent
    _torque_enabled = None
    _servo_mode_servo = None

    port_spinner = ObjectProperty(None, allownone=True)
    connect_btn = ObjectProperty(None, allownone=True)
    servo_selector = ObjectProperty(None, allownone=True)
    uart_mgr = ObjectProperty(None, allownone=True)
    serial_wrapper = ObjectProperty(None, allownone=True)
    new_id_input = ObjectProperty(None)
    status_label = ObjectProperty(None)
    knob_widget = ObjectProperty(None)
    angle_input = ObjectProperty(None)
    servo_range_spinner = ObjectProperty(None)
    log_container = ObjectProperty(None)
    torque_btn = ObjectProperty(None, allownone=True)
    mode_btn = ObjectProperty(None, allownone=True)

    font_path = StringProperty('')
    accent = ListProperty([0.0, 0.9, 1.0, 0.85])
    accent_soft = ListProperty([0.0, 0.9, 1.0, 0.2])
    panel_bg = ListProperty([0.08, 0.12, 0.16, 0.94])
    panel_border = ListProperty([0.06, 0.16, 0.22, 1])

    servo_id_display = StringProperty('--')
    servo_angle_display = StringProperty('--')
    servo_temp_display = StringProperty('--')
    servo_voltage_display = StringProperty('--')
    servo_speed_display = StringProperty('--')
    connection_text = StringProperty('未连接')
    servo_type_display = StringProperty('360°')
    servo_scan_display = StringProperty('未扫描')
    servo_scan_count = StringProperty('0')
    baud_rate_display = StringProperty('115200')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.font_path = _pick_main_font()
        self.port_monitor = PortMonitor()
        self.port_monitor.register_callback(self._on_ports_changed)
        self.port_monitor.start()
        self.ports = []
        self.serial_wrapper = None
        self.uart_mgr = None
        self.connected_port = ''
        self._syncing_knob = False
        self._torque_enabled = None
        self._servo_mode_servo = None
        # runtime status panel
        try:
            self.runtime_panel = RuntimeStatusPanel()
            RuntimeStatusLogger.set_panel(self.runtime_panel)
        except Exception:
            self.runtime_panel = None
        self._last_select_warn = 0.0
        Clock.schedule_once(self._post_init, 0)

    def _post_init(self, *_):
        # Bind knob after kv ids are ready.
        if self.knob_widget:
            self.knob_widget.bind(angle=self.on_knob_angle)
        if self.servo_selector:
            self.servo_selector.text = '请选择'
        if self.new_id_input and not self.new_id_input.text:
            if self.servo_id_display not in ('--', ''):
                self.new_id_input.text = self.servo_id_display
        if self.log_container:
            try:
                self.log_container.clear_widgets()
                if self.runtime_panel:
                    try:
                        self.runtime_panel.size_hint = (1, 1)
                    except Exception:
                        pass
                    self.log_container.add_widget(self.runtime_panel)
                else:
                    from kivy.uix.label import Label

                    self.log_container.add_widget(
                        Label(
                            text='日志面板加载失败',
                            color=(0.8, 0.85, 0.95, 1),
                            font_name=self.font_path if self.font_path else '',
                        )
                    )
            except Exception:
                pass
        if self.servo_range_spinner:
            self.on_range_changed(self.servo_range_spinner.text)

    def _on_ports_changed(self, ports, added, removed):
        # schedule UI update on main thread
        Clock.schedule_once(lambda dt: self._update_ports(ports, added, removed))

    def _update_ports(self, ports, added=None, removed=None):
        ports = list(sorted(ports))
        self.ports = ports
        if self.port_spinner:
            self.port_spinner.values = ports
            if len(ports) > 0 and not self.port_spinner.text:
                self.port_spinner.text = ports[0]
        # handle hot-unplug
        if self.serial_wrapper and self.connected_port and self.connected_port not in ports:
            self._handle_disconnect('串口已拔出')
        elif added and self.serial_wrapper:
            self.scan_servos(max_id=30)
        elif added and (not self.serial_wrapper) and self.port_spinner and not self.port_spinner.text and ports:
            self.port_spinner.text = ports[0]

    def _handle_disconnect(self, reason='已断开'):
        try:
            if self.serial_wrapper:
                self.serial_wrapper.close()
        except Exception:
            pass
        self.serial_wrapper = None
        self.uart_mgr = None
        self.connected_port = ''
        self.baud_rate_display = '115200'
        self.servo_scan_count = '0'
        if self.connect_btn:
            self.connect_btn.text = '连接'
        if self.status_label:
            self.status_label.text = reason
        self.connection_text = '未连接'
        self._update_status_fields(angle='--', voltage='--', temp='--', speed='--')
        self._torque_enabled = None
        self._servo_mode_servo = None
        self._update_toggle_labels()
        self._clear_servo_selection()
        RuntimeStatusLogger.log_info(reason)

    def on_connect(self):
        if self.serial_wrapper:
            # disconnect
            self._handle_disconnect('已断开')
            return

        device = self.port_spinner.text
        if not device:
            self.status_label.text = '请选择端口'
            return
        wrapper = self.port_monitor.open_port(device)
        if wrapper is None:
            self.status_label.text = '打开串口失败'
            RuntimeStatusLogger.log_error(f'打开串口失败: {device}')
            return
        self.serial_wrapper = wrapper
        try:
            if hasattr(wrapper, 'ser') and hasattr(wrapper.ser, 'baudrate'):
                self.baud_rate_display = str(wrapper.ser.baudrate)
        except Exception:
            pass
        # create UartServoManager if available
        if UartServoManager is not None:
            try:
                self.uart_mgr = UartServoManager(self.serial_wrapper)
            except Exception as e:
                self.status_label.text = f'创建SDK失败: {e}'
                self.uart_mgr = None
                self.connection_text = '未连接'
                try:
                    if self.serial_wrapper:
                        self.serial_wrapper.close()
                except Exception:
                    pass
                self.serial_wrapper = None
                if self.connect_btn:
                    self.connect_btn.text = '连接'
                UniversalTip(message=f"创建 SDK 失败: {e}").open()
                RuntimeStatusLogger.log_error(f'创建 SDK 失败: {e}')
                return
        self.connect_btn.text = '断开'
        self.status_label.text = f'已连接: {device}'
        self.connection_text = f'已连接: {device}'
        self.connected_port = device
        RuntimeStatusLogger.log_info(f'已连接: {device}')
        self.scan_servos(max_id=30)

    def _require_selected_id(self):
        if not self.uart_mgr:
            if self.status_label:
                self.status_label.text = '请选择id或关节未连接'
            now = time.time()
            if now - getattr(self, '_last_select_warn', 0.0) > 0.9:
                UniversalTip(message='请选择id或关节未连接').open()
                self._last_select_warn = now
            return None
        sid_text = ''
        if self.servo_selector:
            sid_text = (self.servo_selector.text or '').strip()
        try:
            sid = int(sid_text)
        except Exception:
            if self.status_label:
                self.status_label.text = '请选择id或关节未连接'
            now = time.time()
            if now - getattr(self, '_last_select_warn', 0.0) > 0.9:
                UniversalTip(message='请选择id或关节未连接').open()
                self._last_select_warn = now
            return None
        self.servo_id_display = str(sid)
        return sid

    def on_servo_selected(self, text):
        if not text or text == '请选择':
            self._update_status_fields(angle='--', voltage='--', temp='--', speed='--')
            self._torque_enabled = None
            self._servo_mode_servo = None
            self._update_toggle_labels()
            return
        self.servo_id_display = text
        if self.new_id_input:
            self.new_id_input.text = text
        # sync angle info on selection
        if self.uart_mgr:
            try:
                self.on_read_status()
            except Exception:
                pass

    def on_set_id(self):
        sid = self._require_selected_id()
        if sid is None:
            return
        try:
            new_id = int(self.new_id_input.text or sid)
        except Exception:
            new_id = sid
        try:
            if hasattr(self.uart_mgr, 'write_data_by_name'):
                # SDK使用SERVO_ID键
                self.uart_mgr.write_data_by_name(sid, 'SERVO_ID', new_id)
            self.status_label.text = f'ID {sid} -> {new_id} 已写入'
            RuntimeStatusLogger.log_action('写入ID', f'{sid}->{new_id}')
            if self.servo_selector:
                self.servo_selector.text = str(new_id)
            self.servo_id_display = str(new_id)
            # 重连扫描
            self.scan_servos(max_id=30)
            UniversalTip(message=f"新ID {new_id} 已生效", title='ID 写入').open()
        except Exception as e:
            self.status_label.text = f'错误: {e}'
            RuntimeStatusLogger.log_error(e)

    def on_zero(self):
        sid = self._require_selected_id()
        if sid is None:
            return
        cap = float(self.knob_widget.max_angle if self.knob_widget else 360.0)
        target_angle = 0.0
        position = self._angle_to_position(target_angle, cap)
        try:
            if hasattr(self.uart_mgr, 'set_position_time'):
                self.uart_mgr.set_position_time(sid, position, runtime_ms=400)
            else:
                self.uart_mgr.set_position(sid, position, is_wait=False)
            self.status_label.text = f'舵机 {sid} 置零指令已发'
            RuntimeStatusLogger.log_action('置零', f'ID={sid}')
            if self.knob_widget:
                try:
                    self._syncing_knob = True
                    self.knob_widget.set_angle(target_angle)
                finally:
                    self._syncing_knob = False
            if self.angle_input is not None:
                self.angle_input.text = '0'
            self._update_status_fields(angle='0°')
        except Exception as e:
            self.status_label.text = f'错误: {e}'
            RuntimeStatusLogger.log_error(e)


    def on_toggle_torque(self):
        sid = self._require_selected_id()
        if sid is None:
            return
        new_state = not bool(self._torque_enabled)
        try:
            if hasattr(self.uart_mgr, 'torque_enable'):
                self.uart_mgr.torque_enable(sid, new_state)
            self._torque_enabled = new_state
            self.status_label.text = f'扭矩已{"开启" if new_state else "关闭"}'
            RuntimeStatusLogger.log_action('扭矩开关', f'ID={sid} 开={new_state}')
        except Exception as e:
            self.status_label.text = f'扭矩错误: {e}'
            RuntimeStatusLogger.log_error(e)
        finally:
            self._update_toggle_labels()


    def on_set_mid(self):
        sid = self._require_selected_id()
        if sid is None:
            return
        cap = float(self.knob_widget.max_angle if self.knob_widget else 360.0)
        target_angle = cap / 2.0
        if self.knob_widget:
            self.knob_widget.set_angle(target_angle)
        angle = float(target_angle)
        ang_int = int(round(angle))
        position = self._angle_to_position(angle, cap)
        try:
            if hasattr(self.uart_mgr, 'set_position_time'):
                self.uart_mgr.set_position_time(sid, position, runtime_ms=400)
            else:
                self.uart_mgr.set_position(sid, position)
            # self.status_label.text = f'舵机 {sid} 中位 {ang_int}° 已设置'
            RuntimeStatusLogger.log_action('设置中位', f'ID={sid} Angle={ang_int} 范围={int(cap)}°')
            self._update_status_fields(angle=f'{ang_int}°')
        except Exception as e:
            self.status_label.text = f'错误: {e}'
            RuntimeStatusLogger.log_error(e)

    def on_read_status(self):
        sid = self._require_selected_id()
        if sid is None:
            return
        try:
            pos = self.uart_mgr.get_position(sid)
            if pos is None:
                self.status_label.text = f'舵机 {sid} 无响应'
                RuntimeStatusLogger.log_error(f'舵机 {sid} 无响应')
            else:
                # convert pos to angle
                cap = float(self.knob_widget.max_angle or 360.0)
                if sid in self.uart_mgr.servo_info_dict:
                    angle = self.uart_mgr.servo_info_dict[sid].position2angle(pos)
                else:
                    angle = pos / 4095.0 * cap
                # try to read temperature / voltage when available
                temp = None
                volt = None
                vel = None
                try:
                    if hasattr(self.uart_mgr, 'get_temperature'):
                        temp = self.uart_mgr.get_temperature(sid)
                except Exception:
                    temp = None
                try:
                    if hasattr(self.uart_mgr, 'get_voltage'):
                        volt = self.uart_mgr.get_voltage(sid)
                except Exception:
                    volt = None
                try:
                    if hasattr(self.uart_mgr, 'get_velocity'):
                        vel = self.uart_mgr.get_velocity(sid)
                except Exception:
                    vel = None
                # keep torque/mode state unknown unless explicitly toggled

                ang_int = int(round(angle))
                # self.status_label.text = f'ID:{sid} 角度:{ang_int}° 位置:{pos}'
                RuntimeStatusLogger.log_info(f'读取状态 ID={sid} 角度={ang_int} 位置={pos}')
                if self.angle_input:
                    self.angle_input.text = f"{ang_int}"
                if self.knob_widget:
                    try:
                        self._syncing_knob = True
                        self.knob_widget.set_angle(ang_int)
                    finally:
                        self._syncing_knob = False
                self._update_status_fields(
                    servo_id=sid,
                    angle=f'{ang_int}°',
                    voltage=self._format_voltage(volt),
                    temp=self._format_temp(temp),
                    speed=self._format_speed(vel),
                )
        except Exception as e:
            self.status_label.text = f'错误: {e}'
            RuntimeStatusLogger.log_error(e)

    def on_knob_angle(self, instance, value):
        # send position command while dragging
        if getattr(self, '_syncing_knob', False):
            self._update_status_fields(angle=f'{value:.1f}°')
            return
        sid = self._require_selected_id()
        if sid is None:
            self._update_status_fields(angle=f'{value:.1f}°')
            return
        angle = float(value)
        ang_int = int(round(angle))
        cap = float(self.knob_widget.max_angle or 360.0)
        pos = self._angle_to_position(angle, cap)
        try:
            # smooth move with explicit runtime to ensure execution
            if hasattr(self.uart_mgr, 'set_position_time'):
                self.uart_mgr.set_position_time(sid, pos, runtime_ms=280)
            else:
                self.uart_mgr.set_position(sid, pos, is_wait=False)
            self.status_label.text = f'{ang_int}° -> {pos}'
            RuntimeStatusLogger.log_servo(sid, pos, ang_int)
            self._update_status_fields(angle=f'{ang_int}°')
            if self.angle_input:
                self.angle_input.text = f"{ang_int}"
        except Exception as e:
            self.status_label.text = f'错误: {e}'
            RuntimeStatusLogger.log_error(e)

    def on_toggle_mode(self):
        sid = self._require_selected_id()
        if sid is None:
            return
        current = bool(self._servo_mode_servo)
        new_mode_servo = not current
        try:
            if hasattr(self.uart_mgr, 'set_motor_mode'):
                self.uart_mgr.set_motor_mode(sid, MOTOR_MODE_SERVO if new_mode_servo else MOTOR_MODE_DC)
            # when entering DC模式，给出一个缓慢旋转示例；回到舵机模式时停止直流输出
            if not new_mode_servo and hasattr(self.uart_mgr, 'dc_rotate'):
                try:
                    self.uart_mgr.dc_rotate(sid, DC_DIR_CW, 20)
                except Exception:
                    pass
            if new_mode_servo and hasattr(self.uart_mgr, 'dc_stop'):
                try:
                    self.uart_mgr.dc_stop(sid)
                except Exception:
                    pass
            self._servo_mode_servo = new_mode_servo
            self.status_label.text = f'模式已切换为 {"舵机" if new_mode_servo else "电机"}'
            RuntimeStatusLogger.log_action('模式切换', f'ID={sid} 模式={"舵机" if new_mode_servo else "电机"}')
        except Exception as e:
            self.status_label.text = f'模式切换错误: {e}'
            RuntimeStatusLogger.log_error(e)
        finally:
            self._update_toggle_labels()

    def on_apply_angle(self):
        if not self.angle_input:
            return
        try:
            val = float(self.angle_input.text or 0)
        except Exception:
            val = 0.0
        val = int(round(val))
        if self.knob_widget:
            self.knob_widget.set_angle(val)
            self.on_knob_angle(self.knob_widget, self.knob_widget.angle)
        else:
            self._update_status_fields(angle=f'{val}°')

    def on_range_changed(self, text):
        try:
            cap = float(text)
        except Exception:
            cap = 360.0
        if cap not in (270.0, 360.0):
            cap = 360.0
            if self.servo_range_spinner:
                self.servo_range_spinner.text = '360'
        if self.knob_widget:
            self.knob_widget.max_angle = max(1.0, cap)
            if self.knob_widget.angle > cap:
                self.knob_widget.set_angle(cap)
        if self.angle_input:
            self.angle_input.hint_text = f'0 - {int(cap)}'
        self.servo_type_display = f"{int(cap)}°"

    def _update_status_fields(self, servo_id=None, angle=None, voltage=None, temp=None, speed=None):
        if servo_id is not None:
            self.servo_id_display = str(servo_id)
        if angle is not None:
            try:
                self.servo_angle_display = f"{int(round(float(str(angle).replace('°',''))))}°"
            except Exception:
                self.servo_angle_display = str(angle)
        if voltage is not None:
            self.servo_voltage_display = str(voltage)
        if temp is not None:
            self.servo_temp_display = str(temp)
        if speed is not None:
            self.servo_speed_display = str(speed)

    def _update_toggle_labels(self):
        torque_state = getattr(self, '_torque_enabled', None)
        torque_txt = '--'
        if torque_state is True:
            torque_txt = '开'
        elif torque_state is False:
            torque_txt = '关'
        if self.torque_btn:
            self.torque_btn.text = f'扭矩: {torque_txt}'

        mode_state = getattr(self, '_servo_mode_servo', None)
        mode_txt = '--'
        if mode_state is True:
            mode_txt = '舵机'
        elif mode_state is False:
            mode_txt = '电机'
        if self.mode_btn:
            self.mode_btn.text = f'模式: {mode_txt}'

    def _format_voltage(self, raw):
        try:
            v = float(raw)
        except Exception:
            return '--'
        if v > 30:  # raw value likely *10
            v = v / 10.0
        return f'{v:.1f}V'

    def _format_temp(self, raw):
        try:
            t = float(raw)
        except Exception:
            return '--'
        return f'{t:.1f}°C'

    def _format_speed(self, raw):
        try:
            v = float(raw)
        except Exception:
            return '--'
        return f'{v:.1f}°/s'

    def _angle_to_position(self, angle, cap):
        try:
            cap_val = float(cap) if cap else 360.0
        except Exception:
            cap_val = 360.0
        cap_val = max(1.0, cap_val)
        pos = int(angle / cap_val * 4095)
        return max(0, min(4095, pos))

    def scan_servos(self, max_id=30):
        if not self.uart_mgr:
            self.servo_scan_display = '未连接'
            self.servo_scan_count = '0'
            return

        # show scanning state
        self.servo_scan_display = '扫描中...'
        self.servo_scan_count = '扫描中...'
        if self.status_label:
            try:
                self.status_label.text = '扫描中...'
            except Exception:
                pass
        RuntimeStatusLogger.log_info('开始扫描舵机')

        def _worker():
            found = []
            for sid in range(1, max_id + 1):
                try:
                    pos = self.uart_mgr.get_position(sid)
                    if pos is None:
                        continue
                    if sid in self.uart_mgr.servo_info_dict:
                        angle = self.uart_mgr.servo_info_dict[sid].position2angle(pos)
                    else:
                        cap = float(self.knob_widget.max_angle or 360.0) if self.knob_widget else 360.0
                        angle = pos / 4095.0 * cap
                    temp = None
                    volt = None
                    try:
                        if hasattr(self.uart_mgr, 'get_temperature'):
                            temp = self.uart_mgr.get_temperature(sid)
                    except Exception:
                        temp = None
                    try:
                        if hasattr(self.uart_mgr, 'get_voltage'):
                            volt = self.uart_mgr.get_voltage(sid)
                    except Exception:
                        volt = None
                    found.append((sid, angle, temp, volt))
                except Exception:
                    continue
            Clock.schedule_once(lambda dt: self._apply_scan_result(found), 0)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_scan_result(self, found):
        if not found:
            self.servo_scan_display = '未发现舵机'
            self.servo_scan_count = '0'
            self._clear_servo_selection()
            if self.status_label:
                try:
                    self.status_label.text = '未发现舵机'
                except Exception:
                    pass
            return
        ids = [str(x[0]) for x in found]
        self.servo_scan_display =', '.join(ids)
        self.servo_scan_count = str(len(ids))
        # sync first servo status to UI
        sid, angle, temp, volt = found[0]
        if self.servo_selector:
            self.servo_selector.values = ids
            self.servo_selector.text = str(sid)
        if self.knob_widget:
            self.knob_widget.set_angle(angle)
        if self.angle_input:
            self.angle_input.text = f"{angle:.1f}"
        self._update_status_fields(
            servo_id=sid,
            angle=f'{angle:.1f}°',
            voltage=self._format_voltage(volt),
            temp=self._format_temp(temp),
            speed='--',
        )
        RuntimeStatusLogger.log_info(f'扫描到舵机: {self.servo_scan_display}')

    def _clear_servo_selection(self):
        if self.servo_selector:
            self.servo_selector.values = []
            self.servo_selector.text = '请选择'
        self.servo_id_display = '--'
        if self.angle_input:
            self.angle_input.text = ''
        self._update_status_fields(angle='--', voltage='--', temp='--', speed='--')
        self.servo_scan_display = '未扫描'
        self.servo_scan_count = '0'
        if self.new_id_input:
            self.new_id_input.text = ''
        self._torque_enabled = None
        self._servo_mode_servo = None
        self._update_toggle_labels()


class DebugPanelApp(App):
    def build(self):
        return DebugPanelRoot()
