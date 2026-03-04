"""
servo_controller.py — ESP32 舵机控制模块。

封装 uservo SDK 的所有舵机操作，提供清晰的 API 接口。
由 main.py 加载使用，后续可扩展 IMU、摄像头等传感器模块。

功能:
- ping / 批量 ping
- 批量设置位置 (set_positions)
- 单舵机设置位置 (set_single)
- 读取单舵机位置 (read_position)
- 扭矩开关 (torque_on / torque_off)
- 电机模式 (set_motor_mode / set_servo_mode / set_motor_speed)
- 批量状态查询 (get_all_status)
"""

import time

try:
    from uservo import UartServoManager
except ImportError:
    UartServoManager = None


def log(msg):
    """统一日志输出。"""
    try:
        ts = time.ticks_ms()
        print("[servo_ctrl {:.3f}] {}".format(ts / 1000.0, msg))
    except Exception:
        try:
            print("[servo_ctrl] " + str(msg))
        except Exception:
            pass


class ServoController:
    """ESP32 舵机控制器 — 基于 uservo SDK。"""

    def __init__(self, uart, servo_count=25):
        self.servo_count = servo_count
        self._uart = uart
        self._manager = None
        self._positions = {}   # {sid: last_known_pos}
        self._online = set()   # 在线舵机 ID 集合

        if uart and UartServoManager:
            try:
                self._manager = UartServoManager(uart, srv_num=servo_count)
                log("init ok, servo_count={}".format(servo_count))
            except Exception as e:
                log("init failed: {}".format(e))
        else:
            log("uart or SDK not available")

    @property
    def available(self):
        return self._manager is not None

    # ──────────── Ping ────────────

    def ping(self, servo_id):
        """Ping 单个舵机,返回 0=在线, 非0=离线。"""
        if not self._manager:
            return -1
        try:
            result = self._manager.ping(int(servo_id))
            if result == 0:
                self._online.add(int(servo_id))
            else:
                self._online.discard(int(servo_id))
            log("ping id={} result={}".format(servo_id, result))
            return result
        except Exception as e:
            log("ping id={} error: {}".format(servo_id, e))
            return -1

    def scan(self, id_range=None):
        """扫描指定范围的舵机,返回在线 ID 列表。"""
        if not self._manager:
            return []
        ids = id_range or range(1, self.servo_count + 1)
        online = []
        for sid in ids:
            try:
                if self._manager.ping(int(sid)) == 0:
                    online.append(int(sid))
                    self._online.add(int(sid))
                else:
                    self._online.discard(int(sid))
            except Exception:
                pass
        log("scan: {} servos online".format(len(online)))
        return online

    # ──────────── 位置控制 ────────────

    def set_positions(self, targets, duration_ms=300):
        """批量设置舵机位置。targets: {sid: position}"""
        if not self._manager:
            log("set_positions: no manager")
            return False
        dur = max(1, int(duration_ms))
        count = 0
        for sid, pos in targets.items():
            try:
                sid_i = int(sid)
                pos_i = self._clamp(int(pos), 0, 4096)
                self._manager.set_servo_position(sid_i, pos_i, dur)
                self._positions[sid_i] = pos_i
                count += 1
            except Exception as e:
                log("set_pos id={} err: {}".format(sid, e))
        if count > 0:
            log("set_positions: {} servos, dur={}ms".format(count, dur))
        return count > 0

    def set_single(self, servo_id, position, duration_ms=300):
        """设置单个舵机位置。"""
        return self.set_positions({int(servo_id): int(position)}, duration_ms)

    def read_position(self, servo_id):
        """读取单个舵机当前位置,返回 int 或 None。"""
        if not self._manager:
            return None
        try:
            pos = self._manager.read_servo_position(int(servo_id))
            if pos is not None:
                self._positions[int(servo_id)] = int(pos)
                log("read_pos id={} pos={}".format(servo_id, pos))
            return pos
        except Exception as e:
            log("read_pos id={} err: {}".format(servo_id, e))
            return None

    # ──────────── 扭矩控制 ────────────

    def torque_on(self, ids=None):
        """启用扭矩。ids=None 表示全部。"""
        return self._set_torque(True, ids)

    def torque_off(self, ids=None):
        """释放扭矩。ids=None 表示全部。"""
        return self._set_torque(False, ids)

    def _set_torque(self, enable, ids=None):
        if not self._manager:
            return False
        ids = ids or range(1, self.servo_count + 1)
        flag = 1 if enable else 0
        count = 0
        for sid in ids:
            try:
                self._manager.set_torque_switch(int(sid), flag)
                count += 1
            except Exception:
                pass
        log("torque {}={} servos".format("on" if enable else "off", count))
        return count > 0

    # ──────────── 电机模式 ────────────

    def set_motor_mode(self, servo_id):
        """将舵机切换为电机模式。"""
        if not self._manager:
            return False
        try:
            self._manager.set_servo_mode(int(servo_id), 0)
            log("motor_mode id={}".format(servo_id))
            return True
        except Exception as e:
            log("motor_mode id={} err: {}".format(servo_id, e))
            return False

    def set_servo_mode(self, servo_id):
        """将舵机切换为舵机模式。"""
        if not self._manager:
            return False
        try:
            self._manager.set_servo_mode(int(servo_id), 1)
            log("servo_mode id={}".format(servo_id))
            return True
        except Exception as e:
            log("servo_mode id={} err: {}".format(servo_id, e))
            return False

    def set_motor_speed(self, servo_id, speed):
        """设置电机转速 (0~100)。"""
        if not self._manager:
            return False
        try:
            self._manager.set_motor_speed(int(servo_id), int(speed))
            log("motor_speed id={} speed={}".format(servo_id, speed))
            return True
        except Exception as e:
            log("motor_speed err: {}".format(e))
            return False

    def set_motor_direction(self, servo_id, direction):
        """设置电机方向 (0/1)。"""
        if not self._manager:
            return False
        try:
            self._manager.set_motor_direction(int(servo_id), int(direction))
            return True
        except Exception as e:
            log("motor_dir err: {}".format(e))
            return False

    # ──────────── 批量状态 ────────────

    def get_all_status(self):
        """读取所有已知在线舵机的位置,返回 {sid: {position: int}}。"""
        result = {}
        ids = list(self._online) if self._online else list(range(1, self.servo_count + 1))
        for sid in ids:
            pos = self.read_position(sid)
            if pos is not None:
                result[sid] = {"position": int(pos)}
        # 也包含缓存的位置（那些 read 失败但之前 set 过的）
        for sid, pos in self._positions.items():
            if sid not in result:
                result[sid] = {"position": int(pos)}
        return result

    def get_cached_positions(self):
        """返回缓存的舵机位置（不发起新读取）。"""
        return dict(self._positions)

    # ──────────── 工具方法 ────────────

    @staticmethod
    def _clamp(val, lo, hi):
        if val < lo:
            return lo
        if val > hi:
            return hi
        return val
