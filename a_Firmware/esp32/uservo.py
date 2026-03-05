from machine import UART
import ustruct

# -----------------------------
# 协议常量
# -----------------------------
HEADER = b'\xff\xff'        # 主控发送包头
HEADER_RESP = b'\xff\xf5'   # 舵机回包包头

# 指令常量
CODE_PING = 0x01  # Ping指令
CODE_READ_DATA = 0x02  # 读取指令
CODE_WRITE_DATA = 0x03  # 写入指令
CODE_REG_WRIT = 0x04  # 异步写指令
CODE_ACTION = 0x05  # 执行异步写指令
CODE_RESET = 0x06  # 恢复出厂设置
CODE_SYNC_WRITE = 0x83  # 同步写指令


# 命令地址
ADDR_SERVO_MODE = 0X1C # 舵机电机模式 （0x01：舵机模式 0x00：电机模式）
ADDR_MOTOR_DIRECTION = 0X1D # 舵机电机模式方向
ADDR_TORQUE_SWITCH = 0X28 #扭矩开关 0：扭矩关闭 非0：扭矩打开
ADDR_POSITION = 0x2A  # 目前位置
ADDR_READ_POSITION = 0x38  # 读取目前位置
ADDR_CURRENT_VOLTAGE = 0x3E # 当前电压
ADDR_CURRENT_TEMPERATURE = 0x3F # 当前温度
ADDR_REG_WRITE_FLG = 0x40  # REG WRITE标志
ADDR_MOTOR_SPEED = 0x41  # 速度调整 (在电机模式下，同过PWM的占空比给电机调速，数值范围0-100)


# -----------------------------
# 主控发包校验（FF FF）
# -----------------------------
def calc_checksum(servo_id, code, params=b''):
    total = servo_id + (len(params) + 2) + code + sum(params)
    return (~total) & 0xFF


# -----------------------------
# 主控打包（FF FF）
# -----------------------------
def pack_packet(servo_id, code, params=b''):
    size = len(params) + 2
    checksum = calc_checksum(servo_id, code, params)
    return HEADER + bytes([servo_id, size, code]) + params + bytes([checksum])


# -----------------------------
# 舵机回包（支持 6 字节与 8 字节）
# -----------------------------
def unpack_packet(packet):

    # ---------- 普通 6 字节回包（无参数） ----------
    if len(packet) == 6 and packet[0:2] == HEADER_RESP:
        servo_id = packet[2]
        length = packet[3]
        status = packet[4]
        checksum = packet[5]

        calc = (~(servo_id + length + status)) & 0xFF
        if checksum != calc:
            return None

        return {
            "header": 0xFFF5,
            "id": servo_id,
            "status": status,
            "type": "status"
        }

    # ---------- 读取位置或其他响应（大于等于 6 字节） ----------
    if len(packet) >= 6 and packet[0:2] == HEADER_RESP:
        servo_id = packet[2]
        length = packet[3]
        status = packet[4]
        
        expected_len = 4 + length
        if len(packet) != expected_len:
            return None
            
        data_len = max(0, length - 2)
        data_bytes = list(packet[5:5 + data_len]) if data_len > 0 else []
        checksum = packet[-1]
        
        calc = (~(servo_id + length + status + sum(data_bytes))) & 0xFF
        if checksum != calc:
            return None
            
        # 兼容老逻辑：如果是 2 字节数据，顺便算个 pos
        res = {
            "header": 0xFFF5,
            "id": servo_id,
            "status": status,
            "type": "read_data",
            "data": data_bytes,
        }
        
        if data_len == 2:
            res["pos"] = (data_bytes[0] << 8) | data_bytes[1]
            # 保留 read_position 兼容性
            res["type"] = "read_position"
            
        return res

    return None


# -----------------------------
# UART 解析器（支持 6/8 字节）
# -----------------------------
class PacketParser:
    def __init__(self):
        self.buf = bytearray()

    def input(self, data):
        packets = []
        self.buf.extend(data)

        while True:
            # 最少要 6 字节
            if len(self.buf) < 6:
                break

            # 找头
            idx = self.buf.find(HEADER_RESP)
            if idx < 0:
                self.buf = bytearray()
                break

            if idx > 0:
                self.buf = self.buf[idx:]

            if len(self.buf) < 6:
                break

            # 判断长度字段
            length = self.buf[3]
            need = 4 + length  # header(2)+id(1)+len(1)+payload(len)

            if len(self.buf) < need:
                break

            raw = bytes(self.buf[:need])
            self.buf = self.buf[need:]

            pkt = unpack_packet(raw)
            if pkt:
                packets.append(pkt)

        return packets


# -----------------------------
# 舵机管理器
# -----------------------------
class UartServoManager:
    def __init__(self, uart, srv_num=1):
        self.uart = uart
        self.srv_num = srv_num
        self.parser = PacketParser()

    def clear_buffer(self):
        """清空串口接收缓冲区与解析器缓存，防止旧数据干扰"""
        self.parser.buf = bytearray()
        try:
            while self.uart.any():
                self.uart.read()
        except:
            pass

    # 读舵机回包
    def read_response(self, timeout=100):
        import time
        start = time.ticks_ms()

        while time.ticks_diff(time.ticks_ms(), start) < timeout:
            data = self.uart.read()
            if data:
                pkts = self.parser.input(data)
                if pkts:
                    return pkts[0]
        return None

    # -------------------------
    # ping 只返回 status
    # -------------------------
    def ping(self, servo_id):
        pkt = pack_packet(servo_id, CODE_PING, b'')
        self.clear_buffer()
        self.uart.write(pkt)

        resp = self.read_response()
        if resp and resp["type"] == "status":
            return resp["status"]
        return None

    # -------------------------
    # 写位置
    # -------------------------
    def set_servo_position(self, servo_id, position, time_ms):
        position = max(0, min(4095, position))
        params = ustruct.pack('>BHH', ADDR_POSITION, position, time_ms)
        pkt = pack_packet(servo_id, CODE_WRITE_DATA, params)
        self.uart.write(pkt)

    # -------------------------
    # 读位置（返回原始 POS）
    # -------------------------
    def read_servo_position(self, servo_id):
        params = ustruct.pack('>BB', ADDR_READ_POSITION, 0x02)
        pkt = pack_packet(servo_id, CODE_READ_DATA, params)
        self.clear_buffer()
        self.uart.write(pkt)

        resp = self.read_response()
        if not resp:
            return None

        if resp["type"] == "read_position":
            return resp["pos"]   # 返回 0~4095 原始值

        return None

    # -------------------------
    # 扭矩开关
    # 0：扭矩关闭 非0：扭矩打开
    # 舵机上电默认锁力，需要关闭扭矩才可自由掰动
    # -------------------------
    def set_qorque_switch(self, servo_id, enable):
        params = ustruct.pack('>BB', ADDR_TORQUE_SWITCH, enable)
        pkt = pack_packet(servo_id, CODE_WRITE_DATA, params)
        self.uart.write(pkt)

    # -------------------------
    # 舵机模式切换
    # 0X01:舵机模式 0x00:电机模式
    # 使用对应功能需要切换，在舵机模式下无法使用电机模式功能，反之相同
    # -------------------------
    def set_servo_mode(self, servo_id, mode):
        params = ustruct.pack('>BB', ADDR_SERVO_MODE, mode)
        pkt = pack_packet(servo_id, CODE_WRITE_DATA, params)
        self.uart.write(pkt)
        
    # -------------------------
    # 电机运行方向
    # 0x01:正向 0X00:反向
    # -------------------------
    def set_motor_direction(self, servo_id, direction):
        params = ustruct.pack('>BB', ADDR_MOTOR_DIRECTION, direction)
        pkt = pack_packet(servo_id, CODE_WRITE_DATA, params)
        self.uart.write(pkt)

    # -------------------------
    # 电机速度
    # -------------------------
    def set_motor_speed(self, servo_id, speed):
        speed = max(0, min(100, speed))
        params = ustruct.pack('>BHH', ADDR_MOTOR_SPEED, speed, 0)
        pkt = pack_packet(servo_id, CODE_WRITE_DATA, params)
        self.uart.write(pkt)

