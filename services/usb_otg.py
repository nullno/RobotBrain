"""
简单的 USB OTG (CH34x) 检测服务
通过轮询常见设备节点（/dev/ttyUSB*, /dev/ttyACM*）来检测 CH34x 设备的热插拔。
检测到变化时通过 RuntimeStatusLogger 打印，并可在 Android 上弹出提示。
"""
import threading
import time
import glob
import os
import sys

from kivy.clock import Clock
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.metrics import dp
from kivy.utils import platform as _kivy_platform
import logging

try:
    from widgets.runtime_status import RuntimeStatusLogger
except Exception:
    RuntimeStatusLogger = None

_monitor_thread = None
_stop_event = None
_last_devices = set()
_callbacks = []


def _scan_devices():
    """跨平台扫描可用串口/设备端点，返回一个字符串集合表示设备标识。"""
    devices = set()
    try:
        if sys.platform.startswith('win'):
            # Windows: 使用 pyserial 列出串口设备（COMx）
            try:
                from serial.tools import list_ports
                ports = list_ports.comports()
                for p in ports:
                    # 使用 device (例如 COM6) 加上 description 做唯一标识
                    dev_id = f"{p.device}::{p.description}"
                    devices.add(dev_id)
            except Exception:
                # 回退到扫描 COM1..COM256（代价较高，作为最后手段）
                for i in range(1, 257):
                    name = f"COM{i}"
                    devices.add(name)
        elif sys.platform.startswith('darwin'):
            # macOS: /dev/tty.* 和 /dev/cu.*
            for pattern in ('/dev/tty.*', '/dev/cu.*'):
                for p in glob.glob(pattern):
                    if os.path.exists(p):
                        devices.add(p)
        else:
            # Linux / other: 常见的 ttyUSB, ttyACM, ttyS
            for pattern in ('/dev/ttyUSB*', '/dev/ttyACM*', '/dev/ttyS*', '/dev/serial/by-id/*'):
                for p in glob.glob(pattern):
                    if os.path.exists(p):
                        devices.add(p)
    except Exception:
        pass
    return devices


def _monitor_loop(poll_interval=1.0):
    global _last_devices
    try:
        _last_devices = _scan_devices()
        # 初始设备列表记录（在主线程安全打印）
        try:
            msg = f"初始串口设备 ({sys.platform}): {list(_last_devices)}"
            if RuntimeStatusLogger:
                Clock.schedule_once(lambda dt, m=msg: RuntimeStatusLogger.log_info(m))
            else:
                logging.info(msg)
        except Exception:
            pass
    except Exception:
        _last_devices = set()

    while not _stop_event.is_set():
        try:
            now = _scan_devices()
            added = now - _last_devices
            removed = _last_devices - now
            if added:
                for d in added:
                    try:
                        msg = f"串口设备插入: {d}"
                        if RuntimeStatusLogger:
                            Clock.schedule_once(lambda dt, m=msg: RuntimeStatusLogger.log_info(m))
                        else:
                            logging.info(msg)
                    except Exception:
                        pass
                    # Android: 弹窗提示用户打开应用并可直接尝试通过 Intent 唤起 APK
                    try:
                        if _kivy_platform == 'android':
                            Clock.schedule_once(lambda dt, dev=d: _show_otg_popup(dev))
                        # 调用注册的回调（主线程）通知应用热插拔事件
                        for cb in list(_callbacks):
                            try:
                                Clock.schedule_once(lambda dt, c=cb, ev='added', dev=d: c(ev, dev))
                            except Exception:
                                pass
                    except Exception:
                        pass
            if removed:
                for d in removed:
                    try:
                        msg = f"串口设备拔出: {d}"
                        if RuntimeStatusLogger:
                            Clock.schedule_once(lambda dt, m=msg: RuntimeStatusLogger.log_info(m))
                        else:
                            logging.info(msg)
                    except Exception:
                        pass
                    # 通知回调（主线程）
                    for cb in list(_callbacks):
                        try:
                            Clock.schedule_once(lambda dt, c=cb, ev='removed', dev=d: c(ev, dev))
                        except Exception:
                            pass
            _last_devices = now
        except Exception as e:
            try:
                if RuntimeStatusLogger:
                    Clock.schedule_once(lambda dt, m=str(e): RuntimeStatusLogger.log_error(f"OTG/串口监测错误: {m}"))
                else:
                    logging.exception('OTG/串口监测错误: ' + str(e))
            except Exception:
                pass
        time.sleep(poll_interval)


def start_monitor():
    """启动监测线程（幂等）。支持 Windows/macOS/Linux。"""
    global _monitor_thread, _stop_event
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _stop_event = threading.Event()
    _monitor_thread = threading.Thread(target=_monitor_loop, args=(1.0,), daemon=True)
    _monitor_thread.start()


def register_device_callback(cb):
    """注册一个回调，回调签名为 fn(event, device_id)，event 为 'added' 或 'removed'。"""
    try:
        if cb and cb not in _callbacks:
            _callbacks.append(cb)
    except Exception:
        pass


def unregister_device_callback(cb):
    try:
        if cb in _callbacks:
            _callbacks.remove(cb)
    except Exception:
        pass


def stop_monitor():
    global _stop_event
    if _stop_event:
        _stop_event.set()


def _show_otg_popup(device_id=None):
    """在主线程弹出一个简单的提示，允许用户选择直接打开应用。"""
    try:
        title = 'USB 设备已连接'
        msg = f'检测到设备: {device_id}\n点击"打开应用"以允许本应用访问该设备。'

        content = BoxLayout(orientation='vertical', padding=12, spacing=8)
        lbl = Label(text=msg, halign='center', valign='middle')
        lbl.bind(size=lbl.setter('text_size'))
        btn_row = BoxLayout(size_hint_y=None, height=dp(52), spacing=8)
        btn_open = Button(text='打开应用', size_hint=(0.5, 1))
        btn_cancel = Button(text='取消', size_hint=(0.5, 1))

        btn_row.add_widget(btn_open)
        btn_row.add_widget(btn_cancel)

        content.add_widget(lbl)
        content.add_widget(btn_row)

        popup = Popup(title=title, content=content, size_hint=(None, None), size=(dp(320), dp(180)), auto_dismiss=True)

        def _open_app(_):
            popup.dismiss()
            RuntimeStatusLogger.log_info('用户选择打开应用（尝试通过 Intent 唤起）')
            _launch_app_via_intent()

        def _cancel(_):
            popup.dismiss()
            RuntimeStatusLogger.log_info('用户取消打开应用')

        btn_open.bind(on_release=_open_app)
        btn_cancel.bind(on_release=_cancel)
        popup.open()
    except Exception as e:
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_error(f"弹窗创建失败: {e}")


def _launch_app_via_intent(package_name=None):
    """尝试通过 pyjnius 使用 PackageManager 获取 launch intent 并启动应用。
    如果获取失败，会打开应用详情设置页，用户可以从中允许权限或启动应用。
    """
    try:
        from jnius import autoclass, cast
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity

        if not package_name:
            try:
                package_name = activity.getPackageName()
            except Exception:
                package_name = None

        PackageManager = autoclass('android.content.pm.PackageManager')
        Intent = autoclass('android.content.Intent')
        Uri = autoclass('android.net.Uri')

        pm = activity.getPackageManager()
        launch_intent = None
        if package_name:
            launch_intent = pm.getLaunchIntentForPackage(package_name)

        if launch_intent:
            launch_intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(launch_intent)
            RuntimeStatusLogger.log_info(f'已尝试唤起应用: {package_name}')
            return True
        else:
            # 回退到应用详情设置页，用户可在此授予权限或启动
            action_settings = autoclass('android.provider.Settings').ACTION_APPLICATION_DETAILS_SETTINGS
            uri = Uri.fromParts('package', package_name, None) if package_name else None
            intent = Intent(action_settings)
            if uri:
                intent.setData(uri)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            RuntimeStatusLogger.log_info('已打开应用详情页，等待用户操作')
            return True
    except Exception as e:
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_error(f'通过 Intent 唤起应用失败: {e}')
        return False
