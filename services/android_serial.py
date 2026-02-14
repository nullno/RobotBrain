import threading
import time
from kivy.utils import platform
import logging

_last_status = "init"


def get_last_usb_serial_status():
    """返回最近一次 open_first_usb_serial 的状态字符串，便于上层记录日志。"""
    return _last_status


def _set_status(msg):
    global _last_status
    _last_status = msg
    try:
        logging.info("android_serial: %s", msg)
    except Exception:
        pass

def open_first_usb_serial(baud=115200, open_timeout_ms=1000):
    """尝试使用 usb-serial-for-android 打开第一个检测到的 USB 串口设备。
    返回一个实现了 `write(bytes)`、`readall()`、`close()` 的对象；
    若需要系统授权或未找到设备则返回 None。
    """
    if platform != 'android':
        _set_status('skip: non-android platform')
        return None
    try:
        from jnius import autoclass, cast
    except Exception as e:
        _set_status(f'fail: pyjnius import error: {e}')
        return None

    try:
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        UsbManager = autoclass('android.hardware.usb.UsbManager')
        UsbSerialProber = autoclass('com.hoho.android.usbserial.driver.UsbSerialProber')

        activity = PythonActivity.mActivity
        usb_manager = cast('android.hardware.usb.UsbManager',
                           activity.getSystemService(activity.USB_SERVICE))

        available_drivers = UsbSerialProber.getDefaultProber().findAllDrivers(usb_manager)
        if not available_drivers:
            _set_status('fail: no usb-serial drivers found')
            return None

        driver = available_drivers.get(0)
        device = driver.getDevice()

        # 请求权限（若尚未授权，会弹出系统授权窗口）
        if not usb_manager.hasPermission(device):
            try:
                PendingIntent = autoclass('android.app.PendingIntent')
                Intent = autoclass('android.content.Intent')
                flags = 0
                try:
                    flags = PendingIntent.FLAG_IMMUTABLE
                except Exception:
                    flags = 0
                pi = PendingIntent.getBroadcast(activity, 0, Intent('USB_PERMISSION'), flags)
                usb_manager.requestPermission(device, pi)
                _set_status('wait: usb permission requested')
            except Exception:
                _set_status('fail: usb permission missing and request failed')
                pass
            # 尚未获得权限，返回 None，让上层等待或提示
            return None

        # 打开端口
        port = driver.getPorts().get(0)
        connection = usb_manager.openDevice(device)
        try:
            port.open(connection)
            port.setParameters(int(baud), 8, 1, 0)
        except Exception:
            try:
                connection.close()
            except Exception:
                pass
            _set_status('fail: open serial port failed')
            return None

        class _Wrapper:
            def __init__(self, port, connection):
                self._port = port
                self._conn = connection
                self._lock = threading.Lock()

            def write(self, data):
                try:
                    if not data:
                        return 0
                    # usb-serial-for-android 的 write(signature) 接受 byte[]，Pyjnius 会做类型转换
                    with self._lock:
                        return self._port.write(data, 1000)
                except Exception:
                    return 0

            def readall(self):
                try:
                    # 读取当前可用的数据（短超时以保证非阻塞返回）
                    with self._lock:
                        data = self._port.read(4096, 10)
                    if data is None:
                        return b''
                    try:
                        return bytes(data)
                    except Exception:
                        # 若 data 是 java array-like，尝试逐项构造
                        try:
                            return bytes([int(x) & 0xFF for x in list(data)])
                        except Exception:
                            return b''
                except Exception:
                    return b''

            def close(self):
                try:
                    try:
                        self._port.close()
                    except Exception:
                        pass
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                except Exception:
                    pass

        _set_status('ok: usb serial opened')
        return _Wrapper(port, connection)
    except Exception as e:
        _set_status(f'fail: unexpected error: {e}')
        return None
