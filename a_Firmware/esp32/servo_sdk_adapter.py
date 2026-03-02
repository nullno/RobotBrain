"""
基于 uservo SDK 的舵机适配层。
提供：
- 批量位置下发（顺序写）
- 扭矩开关
- 位置读取
- Ping 检测
"""
from uservo import UartServoManager


class ServoSDKBridge:
    def __init__(self, uart, servo_count=25):
        self.uservo = UartServoManager(uart, srv_num=servo_count)
        self.servo_count = servo_count

    def ping(self, servo_id):
        return self.uservo.ping(int(servo_id))

    def set_positions(self, targets, duration_ms=300):
        if not targets:
            return
        dur = max(1, int(duration_ms))
        for sid, pos in targets.items():
            try:
                self.uservo.set_servo_position(int(sid), int(pos), dur)
            except Exception:
                pass

    def torque(self, enable=True, ids=None):
        ids = ids or range(1, self.servo_count + 1)
        flag = 1 if enable else 0
        for sid in ids:
            try:
                self.uservo.set_torque_switch(int(sid), flag)
            except Exception:
                pass

    def read_position(self, servo_id):
        try:
            return self.uservo.read_servo_position(int(servo_id))
        except Exception:
            return None
