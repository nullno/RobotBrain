"""Android BLE 实现 (pyjnius) —— 在 Android 平台替代 bleak。"""
import logging
import time

logger = logging.getLogger(__name__)

try:
    from jnius import autoclass

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    BLEScanHelper = autoclass("com.nullno.robot.ble.BLEScanHelper")
    BLEGattHelper = autoclass("com.nullno.robot.ble.BLEGattHelper")
    _available = True
except Exception as e:
    logger.warning("Android BLE not available: %s", e)
    _available = False


def is_available():
    return _available


def scan_devices(timeout=6):
    """扫描 BLE 设备，返回 [(name, address), ...]。"""
    context = PythonActivity.mActivity
    scanner = BLEScanHelper(context)
    scanner.startScan()
    time.sleep(timeout)
    scanner.stopScan()

    devices = []
    java_list = scanner.getDiscoveredDevices()
    for i in range(java_list.size()):
        entry = str(java_list.get(i))
        parts = entry.split("|", 1)
        if len(parts) == 2:
            devices.append((parts[0], parts[1]))
    return devices


def connect_and_read_char(address, service_uuid, char_uuid, timeout=10):
    """连接设备并读取特征值，返回 bytes 或 None。"""
    context = PythonActivity.mActivity
    helper = BLEGattHelper()
    try:
        if not helper.connect(context, address, timeout):
            return None
        raw = helper.readCharacteristic(service_uuid, char_uuid, timeout)
        if raw is None:
            return None
        return bytes(raw)
    finally:
        helper.disconnect()


def connect_and_write_char(address, service_uuid, char_uuid, data: bytes, timeout=10):
    """连接设备并写入特征值，成功返回 True。"""
    context = PythonActivity.mActivity
    helper = BLEGattHelper()
    try:
        if not helper.connect(context, address, timeout):
            return False
        return helper.writeCharacteristic(service_uuid, char_uuid, data, timeout)
    finally:
        helper.disconnect()
