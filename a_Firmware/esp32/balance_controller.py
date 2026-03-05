"""
人形机器人动态平衡控制器 —— 在 ESP32 固件中运行。

基于 IMU 姿态数据实时计算 25 路舵机补偿量，实现站立/行走时的动态平衡。

舵机分布（25个关节）：
  颈部: ID 1(左右), 2(上下)
  左臂: ID 3(肩前后), 4(肩侧举), 5(上臂旋转), 6(肘), 7(腕)
  右臂: ID 8(肩前后), 9(肩侧举), 10(上臂旋转), 11(肘), 12(腕)
  腰部: ID 13(旋转)
  左腿: ID 14(胯旋转), 15(大腿弯曲), 16(大腿旋转), 17(膝), 18(踝左右), 19(踝前后)
  右腿: ID 20(胯旋转), 21(大腿弯曲), 22(大腿旋转), 23(膝), 24(踝左右), 25(踝前后)
"""


class BalanceController:
    """IMU 驱动的动态平衡算法。

    使用方法:
        bc = BalanceController(neutral_positions)
        targets = bc.compute(pitch, roll, yaw)
        # targets = {1: 2048, 2: 2100, ...} 可直接传给 ServoController
    """

    def __init__(self, neutral_positions=None):
        # 中位值（所有舵机的初始/站立位置）
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

        # ======== 传感器安装方向适配 ========
        # 如果 YbImu 模块安装方向导致横滚俯仰反相，可修改此处
        self.invert_pitch = False  # 是否反转俯仰角 (前倾应为正)
        self.invert_roll = False   # 是否反转横滚角 (右倾应为正)
        self.invert_yaw = False    # 是否反转偏航角
        # ==================================

        # 平衡增益（可通过 WiFi 指令动态调整）
        self.gain_p = 5.5   # Pitch (前后) 增益
        self.gain_r = 4.2   # Roll  (左右) 增益
        self.gain_y = 0.5   # Yaw   (旋转) 增益

        # 手臂摆动增益
        self.arm_swing = 0.8

        # 头部防抖增益
        self.head_pitch_scale = 1.5
        self.head_yaw_scale = 1.5

        # 膝盖补偿倍率（膝盖需要更大补偿）
        self.knee_ratio = 1.5
        # 踝部前后补偿倍率
        self.ankle_pitch_ratio = 0.5

        # 启用/禁用标志
        self.enabled = True

        # 平衡输出限幅（相对中位偏移量最大值）
        self.max_offset = 500

    def set_gains(self, gain_p=None, gain_r=None, gain_y=None):
        """动态设置增益参数。"""
        if gain_p is not None:
            self.gain_p = max(0.0, min(20.0, float(gain_p)))
        if gain_r is not None:
            self.gain_r = max(0.0, min(20.0, float(gain_r)))
        if gain_y is not None:
            self.gain_y = max(0.0, min(20.0, float(gain_y)))

    def compute(self, pitch, roll, yaw):
        """根据 IMU 姿态计算 25 路舵机目标位置。

        Args:
            pitch: 俯仰角（度），逻辑要求 正=前倾
            roll:  横滚角（度），逻辑要求 正=右倾
            yaw:   偏航角（度），逻辑要求 正=左转

        Returns:
            dict {servo_id: position} 范围 0-4095
        """
        if not self.enabled:
            return dict(self.neutral)

        targets = dict(self.neutral)
        
        # 适配安装方向
        p = float(pitch) * (-1 if self.invert_pitch else 1)
        r = float(roll) * (-1 if self.invert_roll else 1)
        y = float(yaw) * (-1 if self.invert_yaw else 1)

        # === 腿部平衡（核心） ===
        p_offset = int(p * self.gain_p)
        r_offset = int(r * self.gain_r)

        # 大腿弯曲: ID 15(左), 21(右) — Pitch 补偿
        for sid in (15, 21):
            targets[sid] = targets[sid] + p_offset

        # 膝盖: ID 17(左), 23(右) — Pitch 反向补偿（更大幅度）
        for sid in (17, 23):
            targets[sid] = targets[sid] - int(p_offset * self.knee_ratio)

        # 踝前后: ID 19(左), 25(右) — Pitch 同向小幅补偿
        for sid in (19, 25):
            targets[sid] = targets[sid] + int(p_offset * self.ankle_pitch_ratio)

        # 踝左右: ID 18(左), 24(右) — Roll 补偿
        for sid in (18, 24):
            targets[sid] = targets[sid] + r_offset

        # === 腰部 ===
        # ID 13 — Yaw 补偿
        targets[13] = targets[13] + int(y * self.gain_y)

        # === 头部防抖 ===
        # ID 1(颈左右) — 反向 Yaw
        targets[1] = targets[1] - int(y * self.head_yaw_scale)
        # ID 2(颈上下) — 反向 Pitch
        targets[2] = targets[2] - int(p * self.head_pitch_scale)

        # === 手臂自然摆动 ===
        arm_offset = int(p * self.arm_swing)
        targets[3] = targets[3] + arm_offset   # 左肩前后
        targets[8] = targets[8] - arm_offset   # 右肩前后（反相）

        # === 限幅 ===
        for sid in targets:
            # 偏移量限幅
            offset = targets[sid] - self.neutral[sid]
            if abs(offset) > self.max_offset:
                offset = self.max_offset if offset > 0 else -self.max_offset
            val = self.neutral[sid] + offset
            targets[sid] = max(0, min(4095, val))

        return targets

    def compute_incremental(self, pitch, roll, yaw, current_positions):
        """增量式计算 —— 基于当前实际位置做微调，更适合实时平衡。

        Args:
            pitch, roll, yaw: IMU 角度（度）
            current_positions: dict {sid: current_pos} 当前实际位置

        Returns:
            dict {servo_id: position} 仅包含需要调整的舵机
        """
        full_targets = self.compute(pitch, roll, yaw)
        result = {}
        for sid, target in full_targets.items():
            cur = current_positions.get(sid)
            if cur is None:
                continue
            diff = target - int(cur)
            # 仅当偏差超过死区时才输出
            if abs(diff) > 5:
                result[sid] = target
        return result
