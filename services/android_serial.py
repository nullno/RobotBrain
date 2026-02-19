import threading
import time
from kivy.utils import platform
import logging

_last_status = "init"
_perm_req_last = {}
_perm_req_interval_sec = 2.5


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


def _is_missing_usbserial_class_error(err):
    text = str(err or "")
    low = text.lower()
    return (
        "com.hoho.android.usbserial.driver.usbserialprober" in low
        or "didn't find class" in low
        or "classnotfoundexception" in low
        or "noclassdeffounderror" in low
    )


def _chip_name_by_vid_pid(vid, pid):
    try:
        v = int(vid)
        p = int(pid)
    except Exception:
        return "UNKNOWN"
    if v == 0x1A86 and p in (0x7523, 0x5523):
        return "CH34x"
    if v == 0x10C4:
        return "CP210x"
    if v == 0x0403:
        return "FTDI"
    if v == 0x067B:
        return "PL2303"
    return "UNKNOWN"


def _score_driver(driver):
    score = 0
    try:
        dev = driver.getDevice()
        vid = int(dev.getVendorId())
        pid = int(dev.getProductId())
        chip = _chip_name_by_vid_pid(vid, pid)
        if chip == "CH34x":
            score += 100
        elif chip in ("CP210x", "FTDI", "PL2303"):
            score += 80
    except Exception:
        pass

    try:
        n = str(driver.getClass().getSimpleName()).lower()
        if "ch34" in n:
            score += 80
        elif "cp21" in n or "ftdi" in n or "cdc" in n or "prolific" in n:
            score += 60
    except Exception:
        pass
    return score


def _driver_matches_hint(driver, prefer_device_id):
    if not prefer_device_id:
        return True
    hint = str(prefer_device_id).lower()
    try:
        dev = driver.getDevice()
        name = str(dev.getDeviceName()).lower()
    except Exception:
        name = ""
    try:
        vid = int(dev.getVendorId())
        pid = int(dev.getProductId())
        vp = f"vid={vid}:pid={pid}".lower()
    except Exception:
        vp = ""
    return (name and name in hint) or (vp and vp in hint)

def open_first_usb_serial(baud=115200, open_timeout_ms=1000, prefer_device_id=None):
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
        try:
            UsbSerialProber = autoclass('com.hoho.android.usbserial.driver.UsbSerialProber')
        except Exception as e:
            if _is_missing_usbserial_class_error(e):
                _set_status(
                    'fail: usb-serial class missing in APK; check buildozer.spec android.add_aars and rebuild with clean'
                )
                return None
            _set_status(f'fail: usb-serial class load error: {e}')
            return None

        activity = PythonActivity.mActivity
        usb_manager = cast('android.hardware.usb.UsbManager',
                           activity.getSystemService(activity.USB_SERVICE))

        available_drivers = UsbSerialProber.getDefaultProber().findAllDrivers(usb_manager)
        if not available_drivers:
            _set_status('fail: no usb-serial drivers found')
            return None

        drivers = []
        try:
            for i in range(int(available_drivers.size())):
                drv = available_drivers.get(i)
                if _driver_matches_hint(drv, prefer_device_id):
                    drivers.append(drv)
            if not drivers:
                for i in range(int(available_drivers.size())):
                    drivers.append(available_drivers.get(i))
        except Exception:
            drivers = [available_drivers.get(0)]

        try:
            drivers.sort(key=_score_driver, reverse=True)
        except Exception:
            pass

        saw_permission_wait = False
        last_open_err = None

        class _Wrapper:
            def __init__(self, port, connection):
                self._port = port
                self._conn = connection
                self._lock = threading.Lock()
                # Android USB Host 栈抖动较大：
                # 单次 read 超时不宜过长，否则上层 receive_timeout 窗口内可读轮次过少，
                # 容易出现“写入正常、读取应答超时”。
                self._read_timeout_ms = 20

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
                        data = self._port.read(4096, int(self._read_timeout_ms))
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

        for driver in drivers:
            try:
                device = driver.getDevice()
                vid = int(device.getVendorId())
                pid = int(device.getProductId())
                dev_name = str(device.getDeviceName())
                chip = _chip_name_by_vid_pid(vid, pid)
            except Exception:
                device = None
                vid, pid, dev_name, chip = -1, -1, 'unknown', 'UNKNOWN'

            if not device:
                continue

            # 请求权限（若尚未授权，会弹出系统授权窗口）
            if not usb_manager.hasPermission(device):
                saw_permission_wait = True
                key = f"{vid}:{pid}:{dev_name}"
                now = time.time()
                can_request = (now - float(_perm_req_last.get(key, 0.0))) >= _perm_req_interval_sec
                try:
                    if can_request:
                        PendingIntent = autoclass('android.app.PendingIntent')
                        Intent = autoclass('android.content.Intent')
                        flags = 0
                        try:
                            flags = PendingIntent.FLAG_IMMUTABLE
                        except Exception:
                            flags = 0
                        pi = PendingIntent.getBroadcast(activity, 0, Intent('USB_PERMISSION'), flags)
                        usb_manager.requestPermission(device, pi)
                        _perm_req_last[key] = now
                except Exception:
                    pass
                if can_request:
                    _set_status(f'wait: permission requested for {chip} vid={vid} pid={pid} dev={dev_name}')
                else:
                    _set_status(f'wait: permission pending for {chip} vid={vid} pid={pid} dev={dev_name}')
                continue

            # 打开端口
            try:
                port = driver.getPorts().get(0)
                connection = usb_manager.openDevice(device)
                port.open(connection)
                port.setParameters(int(baud), 8, 1, 0)
                try:
                    # JOHO 总线转接在部分手机上需要显式拉高控制线才能稳定收发
                    port.setDTR(True)
                except Exception:
                    pass
                try:
                    port.setRTS(True)
                except Exception:
                    pass
                try:
                    # 清理可能残留的垃圾数据，避免首轮 ping 被污染
                    port.purgeHwBuffers(True, True)
                except Exception:
                    pass
                # 端口参数设置后等待硬件稳定，避免“刚连上立即扫描”导致首轮全超时
                time.sleep(0.12)
            except Exception as e:
                last_open_err = e
                try:
                    connection.close()
                except Exception:
                    pass
                continue
            _set_status(f'ok: opened {chip} vid={vid} pid={pid} dev={dev_name}')
            return _Wrapper(port, connection)

        if saw_permission_wait:
            return None

        if last_open_err is not None:
            _set_status(f'fail: all candidate ports open failed: {last_open_err}')
            return None

        _set_status('fail: no usable usb-serial driver after filtering')
        return None
    except Exception as e:
        if _is_missing_usbserial_class_error(e):
            _set_status(
                'fail: usb-serial class missing in APK; check buildozer.spec android.add_aars and rebuild with clean'
            )
            return None
        _set_status(f'fail: unexpected error: {e}')
        return None
