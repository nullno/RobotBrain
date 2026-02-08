import math

class Walker:
    def __init__(self):
        self.is_walking = False
        self.t = 0
        self.speed = 2.0  # 步频 (可以调整快慢)
        self.step_size = 300  # 步幅 (髋关节摆动幅度)
        self.lift_height = 200 # 抬腿高度 (膝关节弯曲幅度)
        
        # 舵机ID映射 (根据你的舵机分布)
        # 14/20: 胯部旋转(前后摆腿)
        # 17/23: 腿腕(膝盖)弯曲
        # 3/8: 肩部旋转(前后摆臂)
        self.SERVOS = {
            "left_hip": 14, 
            "left_knee": 17,
            "right_hip": 20, 
            "right_knee": 23,
            "left_arm": 3, 
            "right_arm": 8 
        }

    def start(self):
        """开始行走"""
        if not self.is_walking:
            self.is_walking = True
            self.t = 0

    def stop(self):
        """停止行走"""
        self.is_walking = False
        self.t = 0

    def compute(self, dt):
        """
        计算并返回当前帧的舵机目标偏移量。
        dt: a frame's delta-time.
        返回: 一个字典 {servo_id: offset_value}
        """
        offsets = {}
        if not self.is_walking:
            return offsets

        self.t += dt * self.speed
        phase = self.t % (2 * math.pi)

        # === 核心步态算法 (基于正弦波的逆运动学) ===
        
        # 1. 髋关节前后摆动 (左右腿相位差 180度)
        # 当 sin(phase) 为正时，左腿向前摆动
        hip_swing = math.sin(phase) * self.step_size
        offsets[self.SERVOS["left_hip"]] = int(hip_swing)
        offsets[self.SERVOS["right_hip"]] = int(-hip_swing) # 右腿反向摆动

        # 2. 膝盖抬起 (只在腿向前摆动时抬起)
        # 左腿在 0 ~ pi 相位期间 (sin > 0) 抬起
        if math.sin(phase) > 0:
            # 使用 sin^2 或 |sin| 确保抬起值为正
            offsets[self.SERVOS["left_knee"]] = int(math.sin(phase) * self.lift_height)
        else:
            offsets[self.SERVOS["left_knee"]] = 0 # 支撑阶段，膝盖伸直
            
        # 右腿在 pi ~ 2*pi 相位期间 (sin < 0) 抬起
        if math.sin(phase) < 0:
            offsets[self.SERVOS["right_knee"]] = int(-math.sin(phase) * self.lift_height)
        else:
            offsets[self.SERVOS["right_knee"]] = 0

        # 3. 手臂自然摆动 (与对侧腿同步，即与同侧腿反向)
        arm_swing = hip_swing * 0.8 # 摆臂幅度小一些
        offsets[self.SERVOS["left_arm"]] = int(-arm_swing) # 左臂与左腿反向
        offsets[self.SERVOS["right_arm"]] = int(arm_swing) # 右臂与右腿反向

        return offsets
