"""
IMU 控制器模块 —— MPU6050 / ICM-20948 / BNO055 读取与互补滤波。

在 ESP32 MicroPython 固件中运行，提供：
- 原始加速度 / 陀螺仪读取
- 互补滤波计算 pitch / roll / yaw
- 陀螺仪零偏自动校准（上电前 1s 静止采集）
"""

import math
import time

# MPU6050 寄存器地址
_PWR_MGMT_1 = 0x6B
_ACCEL_XOUT_H = 0x3B
_GYRO_XOUT_H = 0x43
_WHO_AM_I = 0x75
_CONFIG = 0x1A
_SMPLRT_DIV = 0x19
_GYRO_CONFIG = 0x1B
_ACCEL_CONFIG = 0x1C

# 量程默认 ±2g / ±250°/s
_ACCEL_SCALE = 16384.0   # LSB/g  (±2g)
_GYRO_SCALE = 131.0      # LSB/(°/s) (±250°/s)


class IMUController:
    """MPU6050 IMU 读取 + 互补滤波（适用于 MicroPython I2C）。"""

    def __init__(self, i2c, addr=0x68, alpha=0.96):
        """
        Args:
            i2c: machine.I2C 实例
            addr: I2C 地址（默认 0x68）
            alpha: 互补滤波系数（0<α<1，越大越信陀螺仪）
        """
        self.i2c = i2c
        self.addr = addr
        self.alpha = alpha

        # 滤波后姿态角（度）
        self.pitch = 0.0
        self.roll = 0.0
        self.yaw = 0.0

        # 原始数据（最近一次采样）
        self.accel = (0.0, 0.0, 0.0)
        self.gyro = (0.0, 0.0, 0.0)

        # 零偏
        self._gyro_offset = (0.0, 0.0, 0.0)
        self._last_update_us = 0
        self._initialized = False

    def init(self):
        """初始化 MPU6050 并执行零偏校准。"""
        if self.i2c is None:
            return False
        try:
            # 唤醒
            self.i2c.writeto_mem(self.addr, _PWR_MGMT_1, b'\x00')
            time.sleep_ms(100)

            # 低通滤波器 ~44Hz
            self.i2c.writeto_mem(self.addr, _CONFIG, b'\x03')
            # 采样率分频 = 4 → 200Hz
            self.i2c.writeto_mem(self.addr, _SMPLRT_DIV, b'\x04')
            # 陀螺仪 ±250°/s
            self.i2c.writeto_mem(self.addr, _GYRO_CONFIG, b'\x00')
            # 加速度计 ±2g
            self.i2c.writeto_mem(self.addr, _ACCEL_CONFIG, b'\x00')

            # 零偏校准（采集 200 个样本取平均）
            self._calibrate_gyro(200)
            self._last_update_us = time.ticks_us()
            self._initialized = True
            return True
        except Exception as e:
            print("imu init failed: {}".format(e))
            return False

    def _calibrate_gyro(self, samples=200):
        """采集静止状态下陀螺仪零偏。"""
        sx, sy, sz = 0.0, 0.0, 0.0
        count = 0
        for _ in range(samples):
            try:
                raw = self._read_raw()
                if raw:
                    sx += raw[3]
                    sy += raw[4]
                    sz += raw[5]
                    count += 1
            except Exception:
                pass
            time.sleep_ms(5)
        if count > 0:
            self._gyro_offset = (sx / count, sy / count, sz / count)

    def _read_raw(self):
        """读取 14 字节原始数据，返回 (ax, ay, az, gx, gy, gz) 单位: g / °/s。"""
        try:
            data = self.i2c.readfrom_mem(self.addr, _ACCEL_XOUT_H, 14)
        except Exception:
            return None

        def to_i16(h, l):
            v = (h << 8) | l
            return v - 65536 if v & 0x8000 else v

        ax = to_i16(data[0], data[1]) / _ACCEL_SCALE
        ay = to_i16(data[2], data[3]) / _ACCEL_SCALE
        az = to_i16(data[4], data[5]) / _ACCEL_SCALE
        # 跳过温度 data[6:8]
        gx = to_i16(data[8], data[9]) / _GYRO_SCALE
        gy = to_i16(data[10], data[11]) / _GYRO_SCALE
        gz = to_i16(data[12], data[13]) / _GYRO_SCALE

        return (ax, ay, az, gx, gy, gz)

    def update(self):
        """执行一次互补滤波更新。应在 5~20ms 周期中调用。

        Returns:
            (pitch, roll, yaw) 度，或 None（读取失败）
        """
        if not self._initialized or self.i2c is None:
            return None

        raw = self._read_raw()
        if raw is None:
            return None

        ax, ay, az, gx, gy, gz = raw

        # 减去零偏
        gx -= self._gyro_offset[0]
        gy -= self._gyro_offset[1]
        gz -= self._gyro_offset[2]

        self.accel = (ax, ay, az)
        self.gyro = (gx, gy, gz)

        # 计算 dt
        now_us = time.ticks_us()
        dt = time.ticks_diff(now_us, self._last_update_us) / 1_000_000.0
        self._last_update_us = now_us
        if dt <= 0 or dt > 0.5:
            dt = 0.01

        # 加速度计计算倾角
        accel_pitch = math.atan2(ay, math.sqrt(ax * ax + az * az)) * 180.0 / math.pi
        accel_roll = math.atan2(-ax, math.sqrt(ay * ay + az * az)) * 180.0 / math.pi

        # 互补滤波
        alpha = self.alpha
        self.pitch = alpha * (self.pitch + gy * dt) + (1.0 - alpha) * accel_pitch
        self.roll = alpha * (self.roll + gx * dt) + (1.0 - alpha) * accel_roll
        self.yaw += gz * dt  # 仅陀螺仪积分，无磁力计无法校准

        return (self.pitch, self.roll, self.yaw)

    def get_orientation(self):
        """返回当前姿态角 (pitch, roll, yaw) 度。"""
        return (self.pitch, self.roll, self.yaw)

    def get_state_dict(self):
        """返回完整 IMU 状态字典（用于遥测上报）。"""
        return {
            "pitch": round(self.pitch, 2),
            "roll": round(self.roll, 2),
            "yaw": round(self.yaw, 2),
            "accel": tuple(round(v, 3) for v in self.accel),
            "gyro": tuple(round(v, 2) for v in self.gyro),
        }
