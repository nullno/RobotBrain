"""
servo_controller.py - ESP32 舵机控制模块（增强版）。

功能：
- 舵机位置控制（带插值平滑算法）
- 舵机状态读取（位置、温度、电压、电流、速度）
- 扭矩控制、模式切换（舵机/电机）
- 电机模式旋转控制
- 在线扫描、ping 检测
- 异步位置设置 + 同步批量写入

参考: UART_PythonSDK2025 数据表定义
"""

import time

try:
    from uservo import UartServoManager, pack_packet, CODE_READ_DATA, CODE_WRITE_DATA
except ImportError:
    UartServoManager = None
    pack_packet = None
    CODE_READ_DATA = 0x02
    CODE_WRITE_DATA = 0x03

try:
    import ustruct
except ImportError:
    ustruct = None


def log(msg):
    try:
        ts = time.ticks_ms()
        print("[servo_ctrl {:.3f}] {}".format(ts / 1000.0, msg))
    except Exception:
        try:
            print("[servo_ctrl] " + str(msg))
        except Exception:
            pass


# ---- 舵机寄存器地址（与 UART_PythonSDK2025/src/data_table.py 对齐）----
ADDR_SERVO_ID = 0x05
ADDR_STALL_PROTECTION = 0x06
ADDR_ANGLE_LOWERB = 0x09
ADDR_ANGLE_UPPERB = 0x0B
ADDR_TEMP_PROTECTION = 0x0D
ADDR_VOLTAGE_UPPERB = 0x0E
ADDR_VOLTAGE_LOWERB = 0x0F
ADDR_TORQUE_UPPERB = 0x10
ADDR_MIDDLE_ADJUST = 0x14
ADDR_MOTOR_MODE = 0x1C
ADDR_MOTOR_DIR = 0x1D
ADDR_TORQUE_ENABLE = 0x28
ADDR_TARGET_POSITION = 0x2A
ADDR_RUNTIME_MS = 0x2C
ADDR_ELECTRIC_CURRENT = 0x2E
ADDR_CURRENT_POSITION = 0x38
ADDR_CURRENT_VELOCITY = 0x3A
ADDR_CURRENT_VOLTAGE = 0x3E
ADDR_CURRENT_TEMPERATURE = 0x3F
ADDR_MOTOR_SPEED = 0x41

# 协议指令类型
CMD_PING = 0x01
CMD_READ = 0x02
CMD_WRITE = 0x03
CMD_REG_WRITE = 0x04
CMD_ACTION = 0x05
CMD_RESET = 0x06
CMD_SYNC_WRITE = 0x83

SERVO_ID_BROADCAST = 0xFE
MOTOR_MODE_SERVO = 0x01
MOTOR_MODE_DC = 0x00
TORQUE_ON = 0x01
TORQUE_OFF = 0x00


class ServoController:
    """ESP32 舵机控制器（增强版）。"""

    def __init__(self, uart, servo_count=25):
        self.servo_count = servo_count
        self._uart = uart
        self._manager = None
        self._positions = {}
        self._online = set()
        self._status_cache = {}

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

    # ─────────────── Ping / Scan ───────────────

    def ping(self, servo_id):
        if not self._manager:
            return -1
        try:
            result = self._manager.ping(int(servo_id))
            if result == 0:
                self._online.add(int(servo_id))
            else:
                self._online.discard(int(servo_id))
            return result
        except Exception as e:
            log("ping id={} err: {}".format(servo_id, e))
            return -1

    def scan(self, id_range=None):
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
        log("scan: {} online".format(len(online)))
        return online

    # ─────────────── 位置控制（直接下发）───────────────

    def set_positions(self, targets, duration_ms=300):
        if not self._manager:
            return False
        dur = max(0, int(duration_ms))
        count = 0
        for sid, pos in targets.items():
            try:
                sid_i = int(sid)
                pos_i = self._clamp(int(pos), 0, 4095)
                self._positions[sid_i] = pos_i
                self._manager.set_servo_position(sid_i, pos_i, dur)
                count += 1
            except Exception as e:
                log("set_pos id={} err: {}".format(sid, e))
        return count > 0

    def set_single(self, servo_id, position, duration_ms=300):
        return self.set_positions({int(servo_id): int(position)}, duration_ms)

    def interpolation_step(self):
        """已禁用插值，直接返回。"""
        return False

    # ─────────────── 位置读取 ───────────────

    def read_position(self, servo_id):
        if not self._manager:
            return None
        try:
            pos = self._manager.read_servo_position(int(servo_id))
            if pos is not None:
                self._positions[int(servo_id)] = int(pos)
            return pos
        except Exception as e:
            log("read_pos id={} err: {}".format(servo_id, e))
            return None

    # ─────────────── 完整状态读取 ───────────────

    def read_temperature(self, servo_id):
        return self._read_register_byte(int(servo_id), ADDR_CURRENT_TEMPERATURE)

    def read_voltage(self, servo_id):
        return self._read_register_byte(int(servo_id), ADDR_CURRENT_VOLTAGE)

    def read_current_ma(self, servo_id):
        return self._read_register_word(int(servo_id), ADDR_ELECTRIC_CURRENT)

    def read_velocity(self, servo_id):
        return self._read_register_word(int(servo_id), ADDR_CURRENT_VELOCITY)

    def read_full_status(self, servo_id):
        """读取完整状态：位置、速度、电压、温度 (通过一次性连续读取优化速度)。"""
        result = {}
        sid = int(servo_id)
        
        # 0x38起连续读8字节，覆盖: 0x38(Pos,2), 0x3A(Vel,2), 0x3C(Teac,1), 0x3D(Res,1), 0x3E(Volt,1), 0x3F(Temp,1)
        data = self._read_register_bytes(sid, ADDR_CURRENT_POSITION, 8)
        if data and len(data) >= 8:
            pos = (data[0] << 8) | data[1]
            vel = (data[2] << 8) | data[3]
            volt = data[6]
            temp = data[7]
            
            result["position"] = int(pos)
            result["velocity"] = int(vel)
            result["voltage"] = int(volt)
            result["temperature"] = int(temp)
            
            self._positions[sid] = int(pos)
            
            # 单独读电流 (因为在 0x2E，与0x38不连续)
            current = self.read_current_ma(sid)
            if current is not None:
                result["current_ma"] = int(current)
            
            # 单独读扭矩状态 (0x28)
            torque_val = self._read_register_byte(sid, ADDR_TORQUE_ENABLE)
            if torque_val is not None:
                result["torque"] = (torque_val == TORQUE_ON)
                
            self._status_cache[sid] = result
        else:
            # 兼容后备逻辑
            pos = self.read_position(sid)
            if pos is not None:
                result["position"] = int(pos)
            temp = self.read_temperature(sid)
            if temp is not None:
                result["temperature"] = int(temp)
            volt = self.read_voltage(sid)
            if volt is not None:
                result["voltage"] = int(volt)
            current = self.read_current_ma(sid)
            if current is not None:
                result["current_ma"] = int(current)
            vel = self.read_velocity(sid)
            if vel is not None:
                result["velocity"] = int(vel)
            torque_val = self._read_register_byte(sid, ADDR_TORQUE_ENABLE)
            if torque_val is not None:
                result["torque"] = (torque_val == TORQUE_ON)
            
            if result:
                self._status_cache[sid] = result
                
        return result if result else None

    # ─────────────── 扭矩控制 ───────────────

    def torque_on(self, ids=None):
        return self._set_torque(True, ids)

    def torque_off(self, ids=None):
        return self._set_torque(False, ids)

    def _set_torque(self, enable, ids=None):
        if not self._manager:
            return False
        ids = ids or range(1, self.servo_count + 1)
        flag = TORQUE_ON if enable else TORQUE_OFF
        count = 0
        for sid in ids:
            try:
                self._write_register_byte(int(sid), ADDR_TORQUE_ENABLE, flag)
                # 记录扭矩状态到内存，以便状态查询时立刻得到更新
                if int(sid) not in self._status_cache:
                    self._status_cache[int(sid)] = {}
                self._status_cache[int(sid)]["torque"] = enable
                count += 1
            except Exception:
                pass
        log("torque {}={} servos".format("on" if enable else "off", count))
        return count > 0

    def set_torque_limit(self, servo_id, limit):
        limit = max(0, min(1000, int(limit)))
        return self._write_register_word(int(servo_id), ADDR_TORQUE_UPPERB, limit)

    # ─────────────── 模式切换 ───────────────

    def set_motor_mode(self, servo_id):
        return self._write_register_byte(int(servo_id), ADDR_MOTOR_MODE, MOTOR_MODE_DC)

    def set_servo_mode(self, servo_id):
        return self._write_register_byte(int(servo_id), ADDR_MOTOR_MODE, MOTOR_MODE_SERVO)

    def set_motor_direction(self, servo_id, direction):
        return self._write_register_byte(int(servo_id), ADDR_MOTOR_DIR, int(direction))

    def set_motor_speed(self, servo_id, speed):
        speed = max(0, min(100, int(speed)))
        return self._write_register_byte(int(servo_id), ADDR_MOTOR_SPEED, speed)

    def motor_stop(self, servo_id):
        return self.set_motor_speed(int(servo_id), 0)

    # ─────────────── 高级功能 ───────────────

    def set_servo_id(self, old_id, new_id):
        return self._write_register_byte(int(old_id), ADDR_SERVO_ID, int(new_id))

    def set_angle_limits(self, servo_id, lower, upper):
        self._write_register_word(int(servo_id), ADDR_ANGLE_LOWERB, self._clamp(int(lower), 0, 4095))
        self._write_register_word(int(servo_id), ADDR_ANGLE_UPPERB, self._clamp(int(upper), 0, 4095))

    def set_middle_adjust(self, servo_id, offset):
        return self._write_register_word(int(servo_id), ADDR_MIDDLE_ADJUST, int(offset))

    # ─────────────── 批量同步写入 ───────────────

    def sync_set_positions(self, id_list, pos_list, time_list):
        """同步批量写入多个舵机位置（一帧完成）。"""
        if not self._manager or not id_list or not ustruct:
            return False
        try:
            params = ustruct.pack('>BB', ADDR_TARGET_POSITION, 0x04)
            for i in range(len(id_list)):
                sid = int(id_list[i])
                pos = self._clamp(int(pos_list[i]), 0, 4095)
                t = int(time_list[i]) if i < len(time_list) else 300
                params += ustruct.pack('>BHH', sid, pos, t)
            if pack_packet:
                pkt = pack_packet(SERVO_ID_BROADCAST, CMD_SYNC_WRITE, params)
                self._manager.uart.write(pkt)
            for i in range(len(id_list)):
                self._positions[int(id_list[i])] = int(pos_list[i])
            return True
        except Exception as e:
            log("sync_set err: {}".format(e))
            return False

    # ─────────────── 状态汇总 ───────────────

    def get_all_status(self):
        result = {}
        ids = list(self._online) if self._online else list(range(1, self.servo_count + 1))
        for sid in ids:
            try:
                st = self.read_full_status(sid)
                if st:
                    result[sid] = st
            except Exception:
                pass
            time.sleep_ms(5)
        for sid, pos in self._positions.items():
            if sid not in result:
                result[sid] = {"position": int(pos)}
        return result

    def get_cached_positions(self):
        return dict(self._positions)

    def get_cached_status(self):
        return dict(self._status_cache)

    def get_online_ids(self):
        return sorted(list(self._online))

    # ─────────────── 底层寄存器读写 ───────────────

    def _read_register_byte(self, servo_id, addr):
        if not self._manager or not pack_packet or not ustruct:
            return None
        try:
            params = ustruct.pack('>BB', addr, 0x01)
            pkt = pack_packet(int(servo_id), CODE_READ_DATA, params)
            if hasattr(self._manager, "clear_buffer"):
                self._manager.clear_buffer()
            self._manager.uart.write(pkt)
            resp = self._manager.read_response(timeout=80)
            if resp and resp.get("type") == "read_data":
                data = resp.get("data") or []
                return data[0] if len(data) >= 1 else None
            if resp and resp.get("type") == "read_position":
                val = resp.get("pos")
                return val & 0xFF if val is not None else None
            return None
        except Exception as e:
            log("read_reg 0x{:02X} id={} err: {}".format(addr, servo_id, e))
            return None

    def _read_register_bytes(self, servo_id, addr, length):
        if not self._manager or not pack_packet or not ustruct:
            return None
        try:
            params = ustruct.pack('>BB', addr, length & 0xFF)
            pkt = pack_packet(int(servo_id), CODE_READ_DATA, params)
            if hasattr(self._manager, "clear_buffer"):
                self._manager.clear_buffer()
            self._manager.uart.write(pkt)
            resp = self._manager.read_response(timeout=80)
            if resp and resp.get("type") == "read_data":
                data = resp.get("data") or []
                return data if len(data) >= length else None
            # 兼容处理
            if length == 2 and resp and resp.get("type") == "read_position":
                val = resp.get("pos")
                return [(val >> 8) & 0xFF, val & 0xFF]
            return None
        except Exception as e:
            log("read_regs 0x{:02X} id={} err: {}".format(addr, servo_id, e))
            return None

    def _read_register_word(self, servo_id, addr):
        if not self._manager or not pack_packet or not ustruct:
            return None
        try:
            params = ustruct.pack('>BB', addr, 0x02)
            pkt = pack_packet(int(servo_id), CODE_READ_DATA, params)
            if hasattr(self._manager, "clear_buffer"):
                self._manager.clear_buffer()
            self._manager.uart.write(pkt)
            resp = self._manager.read_response(timeout=80)
            if resp and resp.get("type") == "read_data":
                data = resp.get("data") or []
                if len(data) >= 2:
                    return (data[0] << 8) | data[1]
                return data[0] if data else None
            if resp and resp.get("type") == "read_position":
                return resp.get("pos")
            return None
        except Exception as e:
            log("read_reg 0x{:02X} id={} err: {}".format(addr, servo_id, e))
            return None

    def _write_register_byte(self, servo_id, addr, value):
        if not self._manager or not pack_packet or not ustruct:
            return False
        try:
            params = ustruct.pack('>BB', addr, int(value) & 0xFF)
            pkt = pack_packet(int(servo_id), CODE_WRITE_DATA, params)
            self._manager.uart.write(pkt)
            return True
        except Exception as e:
            log("write_reg 0x{:02X} id={} err: {}".format(addr, servo_id, e))
            return False

    def _write_register_word(self, servo_id, addr, value):
        if not self._manager or not pack_packet or not ustruct:
            return False
        try:
            params = ustruct.pack('>BH', addr, int(value) & 0xFFFF)
            pkt = pack_packet(int(servo_id), CODE_WRITE_DATA, params)
            self._manager.uart.write(pkt)
            return True
        except Exception as e:
            log("write_reg 0x{:02X} id={} err: {}".format(addr, servo_id, e))
            return False

    @staticmethod
    def _clamp(val, lo, hi):
        if val < lo:
            return lo
        if val > hi:
            return hi
        return val
