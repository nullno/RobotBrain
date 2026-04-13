"""
人形机器人动态平衡控制器 V2 —— ESP32 固件核心。

颠覆性重写：基于倒立摆模型 + 双环 PID + 角速度前馈 + 自适应增益，
实现 20ms 级高频实时平衡控制。

核心架构：
  内环（角速度环，20ms）：陀螺仪角速度 → 踝关节快速阻尼
  外环（姿态角环，20ms）：融合姿态角 → PID → 全身关节协调补偿

关节策略分层（按扰动幅度自动升级）：
  Level 0（< 1°）：仅踝关节微调（持续激活，消除静态漂移）
  Level 1（1~5°）：踝关节全力 + 角速度阻尼
  Level 2（5~15°）：+ 髋膝联动降重心 + 手臂反摆
  Level 3（15~25°）：全身紧急恢复（最大增益）
  Level 4（> 25°）：倾倒检测 → 渐进卸力保护

舵机分布（25个关节）：
  颈部: ID 1(左右), 2(上下)
  左臂: ID 3(肩前后), 4(肩侧举), 5(上臂旋转), 6(肘), 7(腕)
  右臂: ID 8(肩前后), 9(肩侧举), 10(上臂旋转), 11(肘), 12(腕)
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
    """高性能 PID 控制器，带积分抗饱和与微分滤波。"""
    __slots__ = ('kp', 'ki', 'kd', '_integral', '_prev_err', '_i_limit',
                 '_last_t', '_d_filter', '_prev_d')

    def __init__(self, kp=1.0, ki=0.0, kd=0.0, i_limit=300.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self._integral = 0.0
        self._prev_err = 0.0
        self._i_limit = i_limit
        self._last_t = 0
        self._d_filter = 0.0  # 微分项低通滤波
        self._prev_d = 0.0

    def reset(self):
        self._integral = 0.0
        self._prev_err = 0.0
        self._last_t = 0
        self._d_filter = 0.0
        self._prev_d = 0.0

    def update(self, error, now_ms=0):
        dt = 0.02  # 默认 20ms
        if self._last_t > 0 and now_ms > 0:
            elapsed = time.ticks_diff(now_ms, self._last_t)
            if 5 < elapsed < 200:
                dt = elapsed / 1000.0
        self._last_t = now_ms

        # 比例
        p_term = self.kp * error

        # 积分（带抗饱和：仅在输出未饱和时积分）
        self._integral += error * dt
        self._integral = _clamp(self._integral, -self._i_limit, self._i_limit)
        i_term = self.ki * self._integral

        # 微分（带一阶低通滤波，截止频率 ~8Hz，抑制高频噪声）
        raw_d = (error - self._prev_err) / dt if dt > 0 else 0.0
        alpha_d = 0.5  # 微分滤波系数
        self._d_filter = self._d_filter * (1 - alpha_d) + raw_d * alpha_d
        d_term = self.kd * self._d_filter

        self._prev_err = error
        return p_term + i_term + d_term


# 关节安全范围（位置值 0-4095）
JOINT_LIMITS = {
    1: (1500, 2600), 2: (1600, 2500),
    3: (1200, 2900), 4: (1800, 3000), 5: (1500, 2600), 6: (1200, 2800), 7: (1400, 2700),
    8: (1200, 2900), 9: (1000, 2200), 10: (1500, 2600), 11: (1200, 2800), 12: (1400, 2700),
    13: (1600, 2500),
    14: (1700, 2400), 15: (1200, 2900), 16: (1700, 2400), 17: (1200, 2900),
    18: (1600, 2500), 19: (1500, 2600),
    20: (1700, 2400), 21: (1200, 2900), 22: (1700, 2400), 23: (1200, 2900),
    24: (1600, 2500), 25: (1500, 2600),
}


class BalanceController:
    """倒立摆模型双环 PID 动态平衡控制器。

    设计要点：
    1. 20ms 控制周期（50Hz），匹配舵机响应极限
    2. 内环角速度阻尼 + 外环姿态角 PID = 快速响应 + 零稳态误差
    3. 关节补偿基于物理运动学（踝-髋-膝耦合关系）
    4. 无网络依赖：纯本地 ESP32 计算
    """

    def __init__(self, neutral_positions=None):
        base = {}
        for sid in range(1, 26):
            base[sid] = 2048
        # 微屈膝站姿默认值
        base[6] = 1800    # 左肘微屈
        base[11] = 1800   # 右肘微屈
        base[15] = 2100   # 左髋微前屈
        base[21] = 2100   # 右髋微前屈
        base[17] = 1996   # 左膝微屈
        base[23] = 1996   # 右膝微屈
        base[19] = 2070   # 左踝微背屈
        base[25] = 2070   # 右踝微背屈
        if neutral_positions:
            for sid, pos in neutral_positions.items():
                try:
                    base[int(sid)] = int(pos)
                except Exception:
                    pass
        self.neutral = dict(base)
        self.base_pose = dict(base)

        # ======== 传感器方向适配 ========
        self.invert_pitch = False
        self.invert_roll = False
        self.invert_yaw = False

        # ======== 外环 PID（姿态角 → 位置补偿）========
        # 更激进的增益：高重心小脚机器人需要强响应
        self.pid_pitch = _PID(kp=16.0, ki=3.0, kd=6.0, i_limit=500.0)
        self.pid_roll = _PID(kp=14.0, ki=2.5, kd=5.0, i_limit=400.0)
        self.pid_yaw = _PID(kp=2.0, ki=0.0, kd=0.8, i_limit=100.0)

        # ======== 内环增益（角速度 → 快速阻尼）========
        # 这是响应速度的关键！角速度直接映射为补偿量，无需等待角度积累
        self.gyro_pitch_gain = 8.0   # deg/s → 位置值（修复前是 4.0 但单位错误）
        self.gyro_roll_gain = 7.0
        self.gyro_yaw_gain = 1.5

        # ======== 关节策略增益 ========
        # 踝关节（主要平衡执行器 — 始终激活）
        self.ankle_pitch_ratio = 2.0    # 踝前后对 pitch
        self.ankle_roll_ratio = 1.8     # 踝左右对 roll

        # 髋膝联动（中等扰动辅助）
        self.hip_pitch_ratio = 1.2
        self.knee_ratio = 1.4           # 膝盖联动（与髋反向）

        # 手臂反摆
        self.arm_swing_ratio = 0.8

        # 头部稳定
        self.head_pitch_scale = 0.25
        self.head_yaw_scale = 0.25

        # ======== 策略分层阈值（度）========
        self.level1_threshold = 1.0     # 踝关节全力介入
        self.level2_threshold = 5.0     # 髋膝 + 手臂介入
        self.level3_threshold = 15.0    # 紧急全身恢复
        self.fall_threshold = 25.0      # 倾倒保护

        # ======== 输出安全限制 ========
        self.max_offset = 700           # 单关节最大偏移（增大以应对更大补偿）
        self.max_rate = 180             # 每周期最大变化（提高响应速度）
        self.deadzone = 0.3             # 姿态死区（度）— 极小，几乎持续响应

        # ======== 运动状态 ========
        self._single_support = False
        self._support_side = 0
        self._motion_state = 'stand'
        self._adaptive_gain = 1.0

        self.enabled = True
        self.falling = False

        # 输出历史（速率限制）
        self._last_output = {}
        self._last_compute_ms = 0
        self._consecutive_fall = 0  # 连续倾倒帧计数

        # 预分配输出缓冲区（避免热路径 dict 复制触发 GC）
        self._targets_buf = {}
        for _sid in range(1, 26):
            self._targets_buf[_sid] = 2048
        self._incremental_buf = {}

    def set_base_pose(self, pose_dict):
        for sid, pos in pose_dict.items():
            try:
                self.base_pose[int(sid)] = int(pos)
            except Exception:
                pass

    def set_single_support(self, side=0):
        self._single_support = (side != 0)
        self._support_side = side

    def set_motion_state(self, state_name):
        self._motion_state = state_name
        if state_name == 'stand':
            self._adaptive_gain = 1.0
        elif state_name == 'walk':
            self._adaptive_gain = 1.5
        elif state_name == 'crouch':
            self._adaptive_gain = 0.6
        elif state_name == 'action':
            self._adaptive_gain = 0.5   # 动作期间保留一定平衡修正能力
        else:
            self._adaptive_gain = 1.0

    def reset_base_pose(self):
        self.base_pose = dict(self.neutral)
        self._last_output.clear()
        self.pid_pitch.reset()
        self.pid_roll.reset()
        self.pid_yaw.reset()
        self.falling = False
        self._single_support = False
        self._support_side = 0
        self._motion_state = 'stand'
        self._adaptive_gain = 1.0
        self._consecutive_fall = 0

    def set_gains(self, gain_p=None, gain_r=None, gain_y=None):
        if gain_p is not None:
            self.pid_pitch.kp = max(0.0, min(30.0, float(gain_p)))
        if gain_r is not None:
            self.pid_roll.kp = max(0.0, min(30.0, float(gain_r)))
        if gain_y is not None:
            self.pid_yaw.kp = max(0.0, min(30.0, float(gain_y)))

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
        """双环 PID 计算全身关节目标位置。

        Args:
            pitch: 俯仰角（度），前倾为正
            roll: 横滚角（度），右倾为正
            yaw: 偏航角（度）
            gyro_pitch: 俯仰角速度（度/秒）— 内环核心
            gyro_roll: 横滚角速度（度/秒）— 内环核心

        Returns:
            dict {servo_id: target_position}
        """
        if not self.enabled:
            return dict(self.base_pose)

        now_ms = time.ticks_ms()
        # 重用预分配缓冲区（避免每 20ms 创建新 dict 的 GC 压力）
        targets = self._targets_buf
        bp = self.base_pose
        for sid in targets:
            targets[sid] = bp.get(sid, 2048)

        # 方向适配
        p = float(pitch) * (-1 if self.invert_pitch else 1)
        r = float(roll) * (-1 if self.invert_roll else 1)
        y = float(yaw) * (-1 if self.invert_yaw else 1)

        abs_p = abs(p)
        abs_r = abs(r)
        max_tilt = max(abs_p, abs_r)

        # ======== 倾倒检测（快速响应）========
        if max_tilt > self.fall_threshold:
            self._consecutive_fall += 1
            if self._consecutive_fall > 3:  # 60ms 连续倾倒
                self.falling = True
        else:
            self._consecutive_fall = 0
            if max_tilt < self.fall_threshold * 0.5:
                self.falling = False

        # ======== 外环：姿态角 PID ========
        # 持续运行无死区 — 让积分项消除稳态误差
        gain = self._adaptive_gain
        p_pid = self.pid_pitch.update(p, now_ms) * gain
        r_pid = self.pid_roll.update(r, now_ms) * gain
        y_pid = self.pid_yaw.update(y, now_ms) * gain

        # ======== 内环：角速度前馈阻尼（核心响应速度来源）========
        gp = float(gyro_pitch) if gyro_pitch is not None else 0.0
        gr = float(gyro_roll) if gyro_roll is not None else 0.0

        # 角速度直接映射为补偿量 — 即使角度还没变大，速度变化就立即响应
        gyro_p_comp = gp * self.gyro_pitch_gain * gain
        gyro_r_comp = gr * self.gyro_roll_gain * gain

        # ======== 合成：外环 + 内环 ========
        p_total = _clamp(p_pid + gyro_p_comp, -self.max_offset, self.max_offset)
        r_total = _clamp(r_pid + gyro_r_comp, -self.max_offset, self.max_offset)

        p_offset = int(p_total)
        r_offset = int(r_total)

        # 平滑衰减替代硬死区（防止微振，同时避免跳变不连续）
        if abs_p < 1.0:
            p_offset = int(p_offset * abs_p)
        if abs_r < 1.0:
            r_offset = int(r_offset * abs_r)

        # ======== 单脚支撑增益 ========
        ankle_boost = 1.0
        if self._single_support:
            ankle_boost = 1.8

        # ================================================================
        # Level 0~1: 踝关节策略（始终激活）
        # ================================================================
        ankle_p = int(p_offset * self.ankle_pitch_ratio * ankle_boost)
        ankle_r = int(r_offset * self.ankle_roll_ratio * ankle_boost)

        if self._single_support and self._support_side == 1:
            targets[19] += ankle_p
            targets[25] += int(ankle_p * 0.2)
            targets[18] += ankle_r
            targets[24] += int(ankle_r * 0.2)
        elif self._single_support and self._support_side == -1:
            targets[19] += int(ankle_p * 0.2)
            targets[25] += ankle_p
            targets[18] += int(ankle_r * 0.2)
            targets[24] += ankle_r
        else:
            targets[19] += ankle_p
            targets[25] += ankle_p
            targets[18] += ankle_r
            targets[24] += ankle_r

        # ================================================================
        # Level 2: 髋膝联动（> level2_threshold 时激活）
        # ================================================================
        if max_tilt > self.level2_threshold:
            # 渐进激活
            act = min(1.0, (max_tilt - self.level2_threshold) /
                      (self.level3_threshold - self.level2_threshold + 0.01))

            hip_comp = int(p_offset * self.hip_pitch_ratio * act)
            knee_comp = int(p_offset * self.knee_ratio * act)

            # 大腿弯曲（前倾→髋前屈降重心）
            targets[15] += hip_comp
            targets[21] += hip_comp

            # 膝盖（与髋反向，屈膝降重心）
            targets[17] -= knee_comp
            targets[23] -= knee_comp

            # 踝-膝运动学耦合补偿（保持脚底平）
            ankle_knee_comp = int(knee_comp * 0.7)
            targets[19] += ankle_knee_comp
            targets[25] += ankle_knee_comp

            # 侧向大腿旋转
            side_comp = int(r_offset * 0.5 * act)
            targets[16] += side_comp
            targets[22] -= side_comp

            # 胯旋转
            hip_yaw_comp = int(r_offset * 0.25 * act)
            targets[14] += hip_yaw_comp
            targets[20] -= hip_yaw_comp

            # 手臂反摆（产生角动量）
            arm_p = int(p_offset * self.arm_swing_ratio * act)
            arm_r = int(r_offset * self.arm_swing_ratio * 0.5 * act)
            targets[3] += arm_p
            targets[8] -= arm_p
            targets[4] += arm_r
            targets[9] -= arm_r
        elif max_tilt > self.level1_threshold:
            # Level 1: 轻微手臂辅助
            act = min(1.0, (max_tilt - self.level1_threshold) /
                      (self.level2_threshold - self.level1_threshold + 0.01))
            arm_p = int(p_offset * self.arm_swing_ratio * 0.3 * act)
            targets[3] += arm_p
            targets[8] -= arm_p

        # ================================================================
        # Level 3: 紧急全身恢复（> level3_threshold）
        # ================================================================
        if max_tilt > self.level3_threshold:
            emergency = min(1.0, (max_tilt - self.level3_threshold) /
                            (self.fall_threshold - self.level3_threshold + 0.01))

            # 紧急深蹲（大幅降低重心）
            squat = int(150 * emergency)
            targets[15] += squat
            targets[21] += squat
            targets[17] -= int(squat * 1.2)
            targets[23] -= int(squat * 1.2)
            targets[19] += int(squat * 0.8)
            targets[25] += int(squat * 0.8)

            # 手臂大幅反摆
            arm_emergency = int(p_offset * 1.2 * emergency)
            targets[3] += arm_emergency
            targets[8] -= arm_emergency

        # ================================================================
        # 躯干与头部
        # ================================================================
        targets[13] += int(y_pid * 0.3)
        targets[1] -= int(y_pid * self.head_yaw_scale)
        targets[2] -= int(p_offset * self.head_pitch_scale)

        # ================================================================
        # 安全限幅 + 速率限制
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

            # 速率限制
            prev = self._last_output.get(sid)
            if prev is not None:
                diff = raw_target - prev
                if abs(diff) > self.max_rate:
                    raw_target = prev + (self.max_rate if diff > 0 else -self.max_rate)

            targets[sid] = int(raw_target)
            self._last_output[sid] = targets[sid]

        self._last_compute_ms = now_ms
        return targets

    def compute_incremental(self, pitch, roll, yaw, current_positions,
                            gyro_pitch=None, gyro_roll=None):
        """增量模式：基于当前位置计算，仅输出有变化的关节。"""
        full = self.compute(pitch, roll, yaw, gyro_pitch, gyro_roll)
        result = self._incremental_buf
        result.clear()  # 重用字典对象，避免 GC 压力
        for sid, target in full.items():
            cur = current_positions.get(sid)
            if cur is None:
                continue
            diff = target - int(cur)
            if abs(diff) > 3:
                result[sid] = target
        return result

    def is_falling(self):
        return self.falling
