import serial
from .uart_servo import UartServoManager
from .data_table import SERVO_ID_BRODCAST, TORQUE_ENABLE, TORQUE_DISABLE

class ServoBus:
    def __init__(self, port="COM3", baudrate=115200):
        self.is_mock = False
        try:
            # 参考实例配置：timeout=0 保证 Kivy 界面不卡死
            self.uart = serial.Serial(
                port=port, baudrate=baudrate,
                parity=serial.PARITY_NONE, stopbits=1,
                bytesize=8, timeout=0
            )
            # 默认管理 1-25 号舵机
            self.manager = UartServoManager(self.uart, servo_id_list=list(range(1, 26)))
            print(f"✅ JOHO SDK Link Start! Port: {port}")
        except Exception as e:
            print(f"⚠️  Hardware not found: {e}. Switching to MOCK mode.")
            self.is_mock = True

    def close(self):
        """优雅关闭串口并切换到 MOCK 模式。"""
        try:
            if not self.is_mock and hasattr(self, 'uart') and self.uart:
                try:
                    self.uart.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.is_mock = True
        except Exception:
            pass

    def move(self, sid, position, time_ms=300):
        """单舵机控制 (对应 set_position.py)"""
        if self.is_mock: return
        # SDK 内部会处理 0-4095 范围映射
        self.manager.set_position_time(sid, int(position), time_ms)

    def move_sync(self, targets: dict, time_ms=300):
        """同步执行 (对应 sync_set_position.py)"""
        if self.is_mock or not targets: return
        # 使用 SDK 提供的 sync_set_position 接口以保证原子同步写入
        servo_id_list = []
        position_list = []
        runtime_ms_list = []
        for sid, pos in targets.items():
            servo_id_list.append(int(sid))
            position_list.append(int(pos))
            runtime_ms_list.append(int(time_ms))
        try:
            self.manager.sync_set_position(servo_id_list, position_list, runtime_ms_list)
        except Exception:
            # 兼容：如果 SDK 不支持 sync_set_position（向后兼容），回退到逐个写入并广播 action
            for sid, pos in targets.items():
                try:
                    self.manager.set_position_time(int(sid), int(pos), time_ms)
                except Exception:
                    pass
            try:
                # 有些实现用 action 触发同步执行
                if hasattr(self.manager, 'async_action'):
                    self.manager.async_action()
            except Exception:
                pass

    def set_torque(self, enable=True):
        """全局扭矩开关 (对应 控制扭矩开关案例.py)"""
        if self.is_mock: return
        self.manager.torque_enable_all(enable)

    def get_status(self, sid):
        """读取实时数据 (对应 read_data.py)"""
        if self.is_mock: return None
        return {
            "pos": self.manager.read_data_by_name(sid, "CURRENT_POSITION"),
            "temp": self.manager.read_data_by_name(sid, "CURRENT_TEMPERATURE"),
            "volt": self.manager.read_data_by_name(sid, "CURRENT_VOLTAGE")
        }