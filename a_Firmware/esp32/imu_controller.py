"""
IMU 控制器模块 —— 基于 YbImu (IMUI2C)。

在 ESP32 MicroPython 固件中运行，提供：
- 内部自带硬件级卡尔曼/互补滤波解算
- 原始加速度 / 陀螺仪 / 磁力计读取
- 四元数和欧拉角（Pitch / Roll / Yaw）直读 
"""

import time
import math
from imuI2cLib import IMUI2C

class IMUController:
    """IMU 读取（适用于 YbImu I2C 模块）。"""

    def __init__(self, i2c, addr=0x23, alpha=0.96):
        """
        Args:
            i2c: machine.I2C 实例
            addr: I2C 地址（默认 0x23）
            alpha: 保持兼容旧版代码的可选参数
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

        # 角速度（度/秒），由陀螺仪直接提供，用于平衡算法前馈
        self.gyro_pitch = 0.0
        self.gyro_roll = 0.0
        self.gyro_yaw = 0.0

        # 连续读取失败计数（用于自动重连）
        self._fail_count = 0
        self._max_fail = 20

        self._initialized = False
        self.imu_dev = None

    def init(self):
        """初始化 IMU 并进行必要的配置。"""
        print(">> [IMUController] Starting initialization... Target I2C Address: {}".format(hex(self.addr)))
        if self.i2c is None:
            print(">> [IMUController] Error: I2C object is None!")
            return False
        
        try:
            print(">> [IMUController] Creating IMUI2C instance (debug enabled)...")
            self.imu_dev = IMUI2C(self.i2c, addr=self.addr, debug=True)
            
            # 读取版本号，验证通讯是否成功
            print(">> [IMUController] Reading device version...")
            version = self.imu_dev.get_version()
            if version:
                print("YbImu (I2C) 初始化成功, Version: {}".format(version))
                
                # 设置融合算法为9轴 (带磁力计)
                self.imu_dev.set_algo_type(9) 
                
                self._initialized = True
                
                # 初始化成功后，读取一次 IMU 数据并打印
                print(">> [IMUController] Attempting first read after init...")
                first_read = self.update()
                if first_read:
                    print(">> [IMUController] First read success! Pitch={:.2f}, Roll={:.2f}, Yaw={:.2f}".format(*first_read))
                else:
                    print(">> [IMUController] Warning: First read returned None.")
                    
                return True
            else:
                print("未检测到 YbImu，请检查 I2C 接线！")
                return False
                
        except Exception as e:
            print("imu init failed: {}".format(e))
            return False

    def update(self):
        """读取一次 IMU 数据，更新当前的偏航和俯仰横滚角。

        Returns:
            (pitch, roll, yaw) 度，或 None（读取失败）
        """
        if not self._initialized or self.imu_dev is None:
            return None

        try:
            # 内部通过 I2C 连续读取姿态 (YbImu 返回的 euler 是 [roll, pitch, yaw] )
            euler = self.imu_dev.get_imu_attitude_data(ToAngle=True)
            if euler:
                self.roll = euler[0]
                self.pitch = euler[1]
                self.yaw = euler[2]
                
            # 同时也保持加速度、陀螺仪状态刷新
            accel_raw = self.imu_dev.get_accelerometer_data()
            if accel_raw:
                self.accel = tuple(accel_raw)
                
            gyro_raw = self.imu_dev.get_gyroscope_data()
            if gyro_raw:
                self.gyro = tuple(gyro_raw)
                # 陀螺仪输出的是角速度(deg/s)，直接映射到 pitch/roll/yaw
                # YbImu gyro 顺序: [gx, gy, gz] 对应 [roll_rate, pitch_rate, yaw_rate]
                self.gyro_roll = gyro_raw[0]
                self.gyro_pitch = gyro_raw[1]
                self.gyro_yaw = gyro_raw[2]

            self._fail_count = 0
            return (self.pitch, self.roll, self.yaw)
            
        except OSError as e:
            # i2c 总线脱落等问题，尝试自动恢复
            self._fail_count += 1
            if self._fail_count >= self._max_fail:
                print(">> [IMUController] Too many failures ({}), reinit...".format(self._fail_count))
                self._fail_count = 0
                try:
                    self.init()
                except Exception:
                    pass
            return None

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
        }
