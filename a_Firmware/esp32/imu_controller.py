"""
IMU 控制器模块 —— 基于 YbImu (IMUI2C) 高频低延迟版。

在 ESP32 MicroPython 固件中运行，提供：
- 硬件级卡尔曼/互补滤波解算（YbImu 内部完成）
- 高频姿态角 + 角速度采样（5ms 级）
- 批量 I2C 读取优化（减少总线开销）
- 角速度单位修正（rad/s → deg/s）
- 自动重连与故障恢复

重要：imuI2cLib.get_gyroscope_data() 返回的是 rad/s，
      本模块统一转换为 deg/s 供平衡控制器使用。
"""

import time
import math
import struct
from imuI2cLib import IMUI2C

# rad/s → deg/s 转换系数
_RAD_TO_DEG = 180.0 / math.pi

# 直接 I2C 高速读取常量（绕过库的 list→bytearray→unpack 开销）
_GYRO_TO_DEGS = 2000.0 / 32767.0                       # Raw int16 → deg/s（跳过 rad/s 中间步骤）
_GYRO_RAD_SCALE = _GYRO_TO_DEGS * 0.017453292519943295  # Raw int16 → rad/s（遥测兼容）
_ACCEL_SCALE = 16.0 / 32767.0                           # Raw int16 → g
_EULER_REG = 0x26   # 3×float32 (roll, pitch, yaw) = 12 bytes
_GYRO_REG = 0x0A    # 3×int16 (gx, gy, gz) = 6 bytes
_ACCEL_REG = 0x04   # 3×int16 (ax, ay, az) = 6 bytes


class IMUController:
    """高性能 IMU 读取（适用于 YbImu I2C 模块）。

    优化点：
    1. 姿态角由 YbImu 硬件融合输出，延迟极低
    2. 角速度从 rad/s 转换为 deg/s（修复之前的单位错误）
    3. 减少不必要的 I2C 延迟（禁用 debug 模式）
    4. 增加简易一阶低通滤波抑制高频噪声
    5. 快速更新模式：只读姿态角 + 陀螺仪（跳过加速度计节省时间）
    """

    def __init__(self, i2c, addr=0x23, alpha=0.96):
        self.i2c = i2c
        self.addr = addr
        self.alpha = alpha

        # 滤波后姿态角（度）
        self.pitch = 0.0
        self.roll = 0.0
        self.yaw = 0.0

        # 原始数据（最近一次采样）
        self.accel = (0.0, 0.0, 0.0)
        self.gyro = (0.0, 0.0, 0.0)  # rad/s 原始值

        # 角速度（度/秒）— 供平衡控制器前馈补偿
        self.gyro_pitch = 0.0
        self.gyro_roll = 0.0
        self.gyro_yaw = 0.0

        # 一阶低通滤波器系数（0~1, 越小越平滑，越大越灵敏）
        self._gyro_lpf = 0.6     # 角速度 LPF（保留快速响应）
        self._euler_lpf = 0.8    # 姿态角 LPF（在 YbImu 融合基础上轻微平滑）

        # 采样计数与时间戳
        self._sample_count = 0
        self._last_update_ms = 0
        self.dt_ms = 10  # 上次采样间隔（ms）

        # 连续读取失败计数（用于自动重连）
        self._fail_count = 0
        self._max_fail = 10  # 降低阈值，更快重连

        self._initialized = False
        self.imu_dev = None

    def init(self):
        """初始化 IMU 并进行必要的配置。"""
        print(">> [IMU] init addr={}".format(hex(self.addr)))
        if self.i2c is None:
            print(">> [IMU] Error: I2C is None!")
            return False

        try:
            # debug=False 减少 I2C 延迟（每次读取省去 print 和额外 sleep）
            self.imu_dev = IMUI2C(self.i2c, addr=self.addr, debug=False)
            self.imu_dev._delay_time = 0  # ★ 消除每次读取后的 1ms 等待（125Hz 下共省 250ms/s）

            version = self.imu_dev.get_version()
            if version:
                print(">> [IMU] YbImu v{} ok".format(version))

                # 9轴融合（带磁力计，提供绝对 yaw）
                self.imu_dev.set_algo_type(9)

                self._initialized = True
                self._fail_count = 0
                self._last_update_ms = time.ticks_ms()

                # 首次读取验证
                first = self.update()
                if first:
                    print(">> [IMU] P={:.1f} R={:.1f} Y={:.1f}".format(*first))
                return True
            else:
                print(">> [IMU] 未检测到 YbImu!")
                return False

        except Exception as e:
            print(">> [IMU] init failed: {}".format(e))
            return False

    def update(self):
        """V2 高速读取：直接 I2C 寄存器读取，绕过库开销。

        优化效果：
        - 直接 readfrom_mem → 省去库的 list→bytearray→unpack 调用链
        - 消除库的 1ms/次 I2C 等待（每周期省 2ms，125Hz 下共省 250ms/s）
        - 单次 struct.unpack 解析整块数据（零中间分配）
        - 角速度 raw → deg/s 直接转换（跳过 rad/s 中间步骤，省 2 次乘法）

        Returns:
            (pitch, roll, yaw) 度，或 None（读取失败）
        """
        if not self._initialized:
            return None

        try:
            now_ms = time.ticks_ms()

            # ---- 直接 I2C: 姿态角（3×float32 = 12B）----
            eb = self.i2c.readfrom_mem(self.addr, _EULER_REG, 12)
            r_r, p_r, y_r = struct.unpack('<fff', eb)

            a = self._euler_lpf
            self.roll = self.roll * (1 - a) + r_r * _RAD_TO_DEG * a
            self.pitch = self.pitch * (1 - a) + p_r * _RAD_TO_DEG * a
            self.yaw = self.yaw * (1 - a) + y_r * _RAD_TO_DEG * a

            # ---- 直接 I2C: 陀螺仪（3×int16 = 6B）----
            gb = self.i2c.readfrom_mem(self.addr, _GYRO_REG, 6)
            gx, gy, gz = struct.unpack('<hhh', gb)

            # Raw int16 → deg/s（跳过 rad/s 中间步骤）
            b = self._gyro_lpf
            self.gyro_roll = self.gyro_roll * (1 - b) + gx * _GYRO_TO_DEGS * b
            self.gyro_pitch = self.gyro_pitch * (1 - b) + gy * _GYRO_TO_DEGS * b
            self.gyro_yaw = self.gyro_yaw * (1 - b) + gz * _GYRO_TO_DEGS * b

            # rad/s 保留用于遥测兼容
            self.gyro = (gx * _GYRO_RAD_SCALE, gy * _GYRO_RAD_SCALE, gz * _GYRO_RAD_SCALE)

            # 采样间隔
            if self._last_update_ms > 0:
                self.dt_ms = time.ticks_diff(now_ms, self._last_update_ms)
            self._last_update_ms = now_ms
            self._sample_count += 1
            self._fail_count = 0

            return (self.pitch, self.roll, self.yaw)

        except OSError:
            self._fail_count += 1
            if self._fail_count >= self._max_fail:
                print(">> [IMU] {} fails, reinit".format(self._fail_count))
                self._fail_count = 0
                try:
                    self.init()
                except Exception:
                    pass
            return None

    def update_full(self):
        """完整读取：姿态角 + 陀螺仪 + 加速度计（用于遥测上报）。"""
        result = self.update()
        if result:
            try:
                ab = self.i2c.readfrom_mem(self.addr, _ACCEL_REG, 6)
                ax, ay, az = struct.unpack('<hhh', ab)
                self.accel = (ax * _ACCEL_SCALE, ay * _ACCEL_SCALE, az * _ACCEL_SCALE)
            except Exception:
                pass
        return result

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
            "gyro_pitch": round(self.gyro_pitch, 2),
            "gyro_roll": round(self.gyro_roll, 2),
            "gyro_yaw": round(self.gyro_yaw, 2),
            "dt_ms": self.dt_ms,
            "samples": self._sample_count,
        }
