from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.properties import ObjectProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
import os
import threading

from serial_manager import PortMonitor
from knob import Knob
from universal_tip import UniversalTip
from runtime_status import RuntimeStatusPanel, RuntimeStatusLogger

try:
    from uart_servo import UartServoManager
except Exception:
    UartServoManager = None


KV_FILE = os.path.join(os.path.dirname(__file__), 'debug_panel.kv')
Builder.load_file(KV_FILE)


class DebugPanelRoot(BoxLayout):
    port_spinner = ObjectProperty(None)
    connect_btn = ObjectProperty(None)
    servo_id_input = ObjectProperty(None)
    status_label = ObjectProperty(None)
    knob_widget = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.port_monitor = PortMonitor()
        self.port_monitor.register_callback(self._on_ports_changed)
        self.port_monitor.start()
        self.ports = []
        self.serial_wrapper = None
        self.uart_mgr = None
        self.knob_widget.bind(angle=self.on_knob_angle)
        # runtime status panel
        try:
            self.runtime_panel = RuntimeStatusPanel()
            RuntimeStatusLogger.set_panel(self.runtime_panel)
            # add to layout as a compact third column
            self.add_widget(self.runtime_panel)
        except Exception:
            self.runtime_panel = None

    def _on_ports_changed(self, ports, added, removed):
        # schedule UI update on main thread
        Clock.schedule_once(lambda dt: self._update_ports(ports))

    def _update_ports(self, ports):
        self.ports = ports
        self.port_spinner.values = ports
        if len(ports) > 0 and not self.port_spinner.text:
            self.port_spinner.text = ports[0]

    def on_connect(self):
        if self.serial_wrapper:
            # disconnect
            try:
                self.serial_wrapper.close()
            except Exception:
                pass
            self.serial_wrapper = None
            self.connect_btn.text = '连接'
            self.status_label.text = '已断开'
            RuntimeStatusLogger.log_info('断开串口')
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
        # create UartServoManager if available
        if UartServoManager is not None:
            try:
                self.uart_mgr = UartServoManager(self.serial_wrapper)
            except Exception as e:
                self.status_label.text = f'创建SDK失败: {e}'
                self.uart_mgr = None
                UniversalTip(message=f"创建 SDK 失败: {e}").open()
                RuntimeStatusLogger.log_error(f'创建 SDK 失败: {e}')
                return
        self.connect_btn.text = '断开'
        self.status_label.text = f'已连接: {device}'
        RuntimeStatusLogger.log_info(f'已连接: {device}')

    def on_set_id(self):
        # set id not implemented in generic SDK; placeholder
        self.status_label.text = '设置ID 功能请使用 SDK 示例'
        UniversalTip(message='设置ID请参考UART示例，注意设备处于可编程模式。', title='设置ID').open()
        RuntimeStatusLogger.log_info('提示: 设置ID请参考SDK示例')

    def on_zero(self):
        if not self.uart_mgr:
            self.status_label.text = '未连接'
            return
        sid = int(self.servo_id_input.text or 1)
        # read current pos and write as zero offset (as example write TARGET_POSITION to 0)
        try:
            self.uart_mgr.set_position(sid, 0, is_wait=False)
            self.status_label.text = f'舵机 {sid} 置零指令已发'
            RuntimeStatusLogger.log_action('置零', f'ID={sid}')
        except Exception as e:
            self.status_label.text = f'错误: {e}'
            RuntimeStatusLogger.log_error(e)


    def on_set_mid(self):
        if not self.uart_mgr:
            self.status_label.text = '未连接'
            return
        sid = int(self.servo_id_input.text or 1)
        # user chooses mid angle via knob; convert angle to position
        angle = self.knob_widget.angle
        if hasattr(self.uart_mgr, 'servo_info_dict') and sid in self.uart_mgr.servo_info_dict:
            info = self.uart_mgr.servo_info_dict[sid]
            position = int(info.angle2position(angle))
        else:
            # assume 0-360 -> 0-4095
            position = int(angle / 360.0 * 4095)
        try:
            self.uart_mgr.set_position(sid, position)
            self.status_label.text = f'舵机 {sid} 设置中位 {angle:.1f}°'
            RuntimeStatusLogger.log_action('设置中位', f'ID={sid} Angle={angle:.1f}')
        except Exception as e:
            self.status_label.text = f'错误: {e}'
            RuntimeStatusLogger.log_error(e)

    def on_read_status(self):
        if not self.uart_mgr:
            self.status_label.text = '未连接'
            return
        sid = int(self.servo_id_input.text or 1)
        try:
            pos = self.uart_mgr.get_position(sid)
            if pos is None:
                self.status_label.text = f'舵机 {sid} 无响应'
                RuntimeStatusLogger.log_error(f'舵机 {sid} 无响应')
            else:
                # convert pos to angle
                angle = None
                if sid in self.uart_mgr.servo_info_dict:
                    angle = self.uart_mgr.servo_info_dict[sid].position2angle(pos)
                else:
                    angle = pos / 4095.0 * 360.0
                self.status_label.text = f'ID:{sid} 角度:{angle:.1f}° 位置:{pos}'
                RuntimeStatusLogger.log_info(f'读取状态 ID={sid} 角度={angle:.1f} 位置={pos}')
        except Exception as e:
            self.status_label.text = f'错误: {e}'
            RuntimeStatusLogger.log_error(e)

    def on_knob_angle(self, instance, value):
        # send position command while dragging
        if not self.uart_mgr:
            return
        sid = int(self.servo_id_input.text or 1)
        angle = value
        # map angle to position
        if sid in self.uart_mgr.servo_info_dict:
            info = self.uart_mgr.servo_info_dict[sid]
            pos = int(info.angle2position(angle))
        else:
            pos = int(angle / 360.0 * 4095)
        try:
            # send async set for smooth motion
            self.uart_mgr.async_set_position(sid, pos, runtime_ms=200)
            self.status_label.text = f'发送位置 {int(angle)}° -> {pos}'
            RuntimeStatusLogger.log_servo(sid, pos, angle)
        except Exception:
            pass


class DebugPanelApp(App):
    def build(self):
        return DebugPanelRoot()
