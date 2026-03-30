"""
人形机器人动态平衡控制器 —— 在 ESP32 固件中运行。

基于 IMU 姿态数据，使用 PID + ZMP(零力矩点)近似 + 踝关节策略 实时计算
各路舵机补偿量，实现站立与行走时的动态平衡，防止摔倒。

核心策略：
  1. 踝关节策略（Ankle Strategy）：小幅扰动时，踝关节施加反力矩快速恢复
  2. 髋关节策略（Hip Strategy）：中等扰动时，协调髋/膝降低重心
  3. 手臂反摆策略：大幅扰动时，手臂反向摆动增加角动量

安全机制：
  - 输出速率限制（防止突然大幅运动伤人）
  - 死区滤波（微小抖动不发指令，避免舵机颤振）
  - 角度限幅保护（永远不超出关节安全范围）
  - 倾倒检测（超过安全角度自动卸力保护）

舵机分布（25个关节）：
  颈部: ID 1(左右), 2(上下)
  左臂: ID 3(肩前后), 4(肩侧上), 5(上臂旋转), 6(肘), 7(腕)
  右臂: ID 8(肩前后), 9(肩侧上), 10(上臂旋转), 11(肘), 12(腕)
  腰部: ID 13(旋转)
  左腿: ID 14(胯旋转), 15(大腿弯曲), 16(大腿旋转), 17(膝), 18(踝左右), 19(踝前后)
  右腿: ID 20(胯旋转), 21(大腿弯曲), 22(大腿旋转), 23(膝), 24(踝左右), 25(踝前后)
"""

import time


def _clamp(val, lo, hi):
    if val < lo:
        return lo
    if val > hi:
        return hi
    return val


class _PID:
    """轻量级 PID 控制器，适合 MicroPython。"""
    __slots__ = ('kp', 'ki', 'kd', '_integral', '_prev_err', '_i_limit', '_last_t')

    def __init__(self, kp=1.0, ki=0.0, kd=0.0, i_limit=200.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self._integral = 0.0
        self._prev_err = 0.0
        self._i_limit = i_limit
        self._last_t = 0

    def reset(self):
        self._integral = 0.0
        self._prev_err = 0.0
        self._last_t = 0

    def update(self, error, now_ms=0):
        dt = 0.05  # 默认 50ms
        if self._last_t > 0 and now_ms > 0:
            elapsed = now_ms - self._last_t
            if 5 < elapsed < 500:
                dt = elapsed / 1000.0
        self._last_t = now_ms

        self._integral += error * dt
        self._integral = _clamp(self._integral, -self._i_limit, self._i_limit)

        derivative = (error - self._prev_err) / dt if dt > 0 else 0.0
        self._prev_err = error

        return self.kp * error + self.ki * self._integral + self.kd * derivative


# 关节安全范围（位置值 0-4095，来自 assembly_guide.md）
JOINT_LIMITS = {
    1: (1500, 2600), 2: (1600, 2500),
    3: (1200, 2900), 4: (1800, 3000), 5: (1500, 2600), 6: (1200, 2800), 7: (1400, 2700),
    8: (1200, 2900), 9: (1000, 2200), 10: (1500, 2600), 11: (1200, 2800), 12: (1400, 2700),
    13: (1600, 2500),
    14: (1700, 2400), 15: (1200, 2900), 16: (1700, 2400), 17: (1200, 2900), 18: (1600, 2500), 19: (1500, 2600),
    20: (1700, 2400), 21: (1200, 2900), 22: (1700, 2400), 23: (1200, 2900), 24: (1600, 2500), 25: (1500, 2600),
}

# 关键平衡关节集合
BALANCE_JOINTS = {15, 17, 18, 19, 21, 23, 24, 25}


class BalanceController:
    """IMU 驱动的 PID 动态平衡算法。

    使用分级策略：
      - 踝关节策略（0~8°倾斜）：踝关节 PID 快速响应
      - 髋膝联动策略（8~20°倾斜）：降低重心 + 踝关节配合
      - 防摔卸力（>25°）：发出倾倒警告，可选自动卸力
    """

    def __init__(self, neutral_positions=None):
        base = {}
        for sid in range(1, 26):
            base[sid] = 2048
        if neutral_positions:
            for sid, pos in neutral_positions.items():
                try:
                    base[int(sid)] = int(pos)
                except Exception:
                    pass
        self.neutral = base
        self.base_pose = dict(self.neutral)

        # ======== 传感器方向适配 ========
        self.invert_pitch = False
        self.invert_roll = False
        self.invert_yaw = False

        # ======== PID 控制器 ========
        # Pitch 通道（前后平衡，最关键 — 高重心+小脚需要更强响应）
        self.pid_pitch = _PID(kp=8.0, ki=1.0, kd=3.5, i_limit=350.0)
        # Roll 通道（左右平衡 — 行走时单脚支撑需要更强侧向稳定）
        self.pid_roll = _PID(kp=6.5, ki=0.8, kd=2.8, i_limit=300.0)
        # Yaw 通道（旋转修正，增益较小）
        self.pid_yaw = _PID(kp=1.2, ki=0.0, kd=0.4, i_limit=100.0)

        # ======== 角速度前馈增益（陀螺仪反馈，加速响应动态扰动）========
        self.gyro_pitch_gain = 3.0   # pitch 角速度前馈（deg/s → 位置值）
        self.gyro_roll_gain = 2.5    # roll 角速度前馈
        self._prev_pitch = 0.0       # 用于估算角速度（若 IMU 不直接提供）
        self._prev_roll = 0.0

        # ======== 关节策略增益 ========
        # 踝关节策略（主要平衡手段 — 35kg 脚部舵机扭矩充足）
        self.ankle_pitch_ratio = 1.5    # 踝前后对 pitch 的响应比（增强）
        self.ankle_roll_ratio = 1.3     # 踝左右对 roll 的响应比（增强）

        # 髋关节策略（中等扰动辅助）
        self.hip_pitch_ratio = 0.8      # 大腿弯曲对 pitch 的响应比
        self.knee_ratio = 1.0           # 膝盖对 pitch 的联动比（与髋反向）

        # 手臂反摆（大扰动时的角动量补偿 — 高重心机器人有效）
        self.arm_swing_ratio = 0.6

        # 头部稳定（视觉稳定，反向补偿躯干运动）
        self.head_pitch_scale = 0.3
        self.head_yaw_scale = 0.3

        # ======== 策略切换阈值（度）— 降低阈值使策略更早介入 ========
        self.ankle_threshold = 5.0      # 仅踝关节响应的最大角度（降低）
        self.hip_threshold = 15.0       # 髋膝启动的角度（降低）
        self.fall_threshold = 25.0      # 倾倒警告阈值

        # ======== 输出安全限制 ========
        self.max_offset = 550           # 单次最大偏移（适当增大以应对更大补偿需求）
        self.max_rate = 100             # 每周期最大变化量（提高响应速度）
        self.deadzone = 2.0             # 姿态死区（度），减小以提高灵敏度

        # ======== 行走感知 ========
        self._single_support = False    # 单脚支撑标志（行走中）
        self._support_side = 0          # 0=双脚, 1=左脚支撑, -1=右脚支撑

        self.enabled = True
        self.falling = False            # 倾倒标志

        # 上一次输出值（速率限制用）
        self._last_output = {}
        self._last_compute_ms = 0

    def set_base_pose(self, pose_dict):
        """设置动作基准姿态（行走/动作帧），平衡补偿在此基础上叠加。"""
        for sid, pos in pose_dict.items():
            try:
                self.base_pose[int(sid)] = int(pos)
            except Exception:
                pass

    def set_single_support(self, side=0):
        """设置单脚支撑状态（行走步态中调用）。

        Args:
            side: 0=双脚支撑, 1=左脚支撑, -1=右脚支撑
        """
        self._single_support = (side != 0)
        self._support_side = side

    def reset_base_pose(self):
        """恢复到站立基准。"""
        self.base_pose = dict(self.neutral)
        self._last_output.clear()
        self.pid_pitch.reset()
        self.pid_roll.reset()
        self.pid_yaw.reset()
        self.falling = False
        self._single_support = False
        self._support_side = 0
        self._prev_pitch = 0.0
        self._prev_roll = 0.0

    def set_gains(self, gain_p=None, gain_r=None, gain_y=None):
        """调整 PID Kp 增益（兼容旧接口）。"""
        if gain_p is not None:
            self.pid_pitch.kp = max(0.0, min(20.0, float(gain_p)))
        if gain_r is not None:
            self.pid_roll.kp = max(0.0, min(20.0, float(gain_r)))
        if gain_y is not None:
            self.pid_yaw.kp = max(0.0, min(20.0, float(gain_y)))

    @property
    def gain_p(self):
        return self.pid_pitch.kp

    @property
    def gain_r(self):
        return self.pid_roll.kp

    @property
    def gain_y(self):
        return self.pid_yaw.kp

    def compute(self, pitch, roll, yaw, gyro_pitch=None, gyro_roll=None):
        """基于 IMU 姿态角 + 角速度计算全身关节目标位置。

        Args:
            pitch: 俯仰角（度），前倾为正
            roll: 横滚角（度），右倾为正
            yaw: 偏航角（度）
            gyro_pitch: 俯仰角速度（度/秒），可选。None 则内部估算
            gyro_roll: 横滚角速度（度/秒），可选

        Returns:
            dict {servo_id: target_position}
        """
        if not self.enabled:
            return dict(self.base_pose)

        now_ms = time.ticks_ms()
        targets = dict(self.base_pose)

        # 方向适配
        p = float(pitch) * (-1 if self.invert_pitch else 1)
        r = float(roll) * (-1 if self.invert_roll else 1)
        y = float(yaw) * (-1 if self.invert_yaw else 1)

        abs_p = abs(p)
        abs_r = abs(r)

        # ======== 角速度估算/接收 ========
        dt_s = 0.05
        if self._last_compute_ms > 0:
            elapsed = time.ticks_diff(now_ms, self._last_compute_ms)
            if 5 < elapsed < 500:
                dt_s = elapsed / 1000.0

        if gyro_pitch is not None:
            gp = float(gyro_pitch)
        else:
            gp = (p - self._prev_pitch) / dt_s if dt_s > 0 else 0.0

        if gyro_roll is not None:
            gr = float(gyro_roll)
        else:
            gr = (r - self._prev_roll) / dt_s if dt_s > 0 else 0.0

        self._prev_pitch = p
        self._prev_roll = r

        # ======== 倾倒检测 ========
        if abs_p > self.fall_threshold or abs_r > self.fall_threshold:
            self.falling = True
        elif abs_p < self.fall_threshold * 0.6 and abs_r < self.fall_threshold * 0.6:
            self.falling = False

        # ======== 死区过滤 ========
        p_in = p if abs_p > self.deadzone else 0.0
        r_in = r if abs_r > self.deadzone else 0.0

        # ======== PID 计算 ========
        p_out = self.pid_pitch.update(p_in, now_ms)
        r_out = self.pid_roll.update(r_in, now_ms)
        y_out = self.pid_yaw.update(y, now_ms)

        # ======== 角速度前馈补偿（加速响应快速扰动）========
        # 角速度方向即将发生的趋势，提前施加补偿
        gyro_p_comp = int(gp * self.gyro_pitch_gain)
        gyro_r_comp = int(gr * self.gyro_roll_gain)
        gyro_p_comp = _clamp(gyro_p_comp, -200, 200)
        gyro_r_comp = _clamp(gyro_r_comp, -150, 150)

        p_offset = int(_clamp(p_out + gyro_p_comp, -self.max_offset, self.max_offset))
        r_offset = int(_clamp(r_out + gyro_r_comp, -self.max_offset, self.max_offset))

        # ======== 单脚支撑增益放大 ========
        # 行走中单脚着地时，支撑脚踝关节需承担全部平衡工作
        ankle_boost = 1.0
        if self._single_support:
            ankle_boost = 1.4  # 单脚时增大 40% 踝关节响应

        # ================================================================
        # 1. 踝关节策略（始终激活，快速响应小扰动）
        # ================================================================
        # 踝前后（ID 19, 25）：前倾时脚尖抬起产生后仰力矩
        ankle_p = int(p_offset * self.ankle_pitch_ratio * ankle_boost)
        # 踝左右（ID 18, 24）：侧倾时踝关节侧偏产生恢复力矩
        ankle_r = int(r_offset * self.ankle_roll_ratio * ankle_boost)

        if self._single_support and self._support_side == 1:
            # 左脚支撑：左踝全力补偿，右踝弱化（即将离地/抬起）
            targets[19] += ankle_p
            targets[25] += int(ankle_p * 0.3)
            targets[18] += ankle_r
            targets[24] += int(ankle_r * 0.3)
        elif self._single_support and self._support_side == -1:
            # 右脚支撑：右踝全力补偿，左踝弱化
            targets[19] += int(ankle_p * 0.3)
            targets[25] += ankle_p
            targets[18] += int(ankle_r * 0.3)
            targets[24] += ankle_r
        else:
            # 双脚支撑：均匀补偿
            targets[19] += ankle_p
            targets[25] += ankle_p
            targets[18] += ankle_r
            targets[24] += ankle_r

        # ================================================================
        # 2. 髋膝联动策略（中等以上扰动激活，降低重心）
        # ================================================================
        if abs_p > self.ankle_threshold or abs_r > self.ankle_threshold:
            # 渐进激活系数：从 ankle_threshold 开始线性增加到 1.0
            activation = min(1.0, (max(abs_p, abs_r) - self.ankle_threshold) /
                             (self.hip_threshold - self.ankle_threshold + 0.01))

            hip_comp = int(p_offset * self.hip_pitch_ratio * activation)
            knee_comp = int(p_offset * self.knee_ratio * activation)

            # 大腿弯曲（ID 15, 21）：前倾时髋关节前摆补偿
            targets[15] += hip_comp
            targets[21] += hip_comp

            # 膝盖（ID 17, 23）：与髋反向，屈膝降重心
            targets[17] -= knee_comp
            targets[23] -= knee_comp

            # 侧向：左右大腿旋转微调（ID 16, 22）
            side_comp = int(r_offset * 0.4 * activation)
            targets[16] += side_comp
            targets[22] -= side_comp

            # 胯旋转微调（ID 14, 20）：对抗侧倾时身体扭转
            hip_yaw_comp = int(r_offset * 0.15 * activation)
            targets[14] += hip_yaw_comp
            targets[20] -= hip_yaw_comp

        # ================================================================
        # 3. 手臂反摆策略（产生角动量辅助恢复）
        # ================================================================
        arm_offset = int(p_offset * self.arm_swing_ratio)
        targets[3] += arm_offset    # 左臂前后，前倾时前摆
        targets[8] -= arm_offset    # 右臂前后，反向

        # 侧向手臂辅助
        side_arm = int(r_offset * self.arm_swing_ratio * 0.5)
        targets[4] += side_arm      # 左肩侧举
        targets[9] -= side_arm      # 右肩侧举

        # ================================================================
        # 4. 躯干与头部稳定
        # ================================================================
        targets[13] += int(y_out * 0.3)   # 腰部补偿偏航

        # 头部反向运动保持视线稳定
        targets[1] -= int(y_out * self.head_yaw_scale)
        targets[2] -= int(p_offset * self.head_pitch_scale)

        # ================================================================
        # 5. 安全限幅 + 速率限制
        # ================================================================
        for sid in targets:
            base_val = self.base_pose.get(sid, 2048)

            # 偏移限幅
            offset = targets[sid] - base_val
            offset = _clamp(offset, -self.max_offset, self.max_offset)
            raw_target = base_val + offset

            # 关节物理限幅
            lo, hi = JOINT_LIMITS.get(sid, (0, 4095))
            raw_target = _clamp(raw_target, lo, hi)

            # 速率限制（防止突然大幅运动伤人）
            prev = self._last_output.get(sid)
            if prev is not None:
                diff = raw_target - prev
                if abs(diff) > self.max_rate:
                    raw_target = prev + (self.max_rate if diff > 0 else -self.max_rate)

            targets[sid] = int(raw_target)
            self._last_output[sid] = targets[sid]

        self._last_compute_ms = now_ms
        return targets

    def compute_incremental(self, pitch, roll, yaw, current_positions):
        """增量模式：基于舵机当前真实位置进行微调，仅输出有变化的关节。"""
        full_targets = self.compute(pitch, roll, yaw)
        result = {}
        for sid, target in full_targets.items():
            cur = current_positions.get(sid)
            if cur is None:
                continue
            diff = target - int(cur)
            # 死区：误差小于 8 个位置单位不发指令，防止伺服颤振
            if abs(diff) > 8:
                result[sid] = target
        return result

    def is_falling(self):
        """返回当前是否处于倾倒状态。"""
        return self.falling
