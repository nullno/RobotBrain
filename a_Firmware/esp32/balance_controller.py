"""
人形机器人动态平衡控制器 —— 在 ESP32 固件中运行。

基于 IMU 姿态数据实时计算各路舵机补偿量，实现站立、行走时的动态平衡，防摔倒。
具备推力抵抗功能（利用脚踝策略和膝盖反推补偿，抵消外界干扰和自重前倾等物理偏差）。

舵机分布（25个关节）：
  颈部: ID 1(左右), 2(上下)
  左臂: ID 3(肩前后), 4(肩侧上), 5(上臂旋转), 6(肘), 7(腕)
  右臂: ID 8(肩前后), 9(肩侧上), 10(上臂旋转), 11(肘), 12(腕)
  腰部: ID 13(旋转)
  左腿: ID 14(胯旋转), 15(大腿弯曲), 16(大腿旋转), 17(膝), 18(踝左右), 19(踝前后)
  右腿: ID 20(胯旋转), 21(大腿弯曲), 22(大腿旋转), 23(膝), 24(踝左右), 25(踝前后)
"""

class BalanceController:
    """IMU 驱动的动态平衡算法。"""

    def __init__(self, neutral_positions=None):
        # 默认基准值（所有舵机的初始/站立位置）
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
        
        # 动作基准姿态，默认等于站立基准，支持外部SDK传入（如行走动画帧），在此基础上做平衡
        self.base_pose = self.neutral.copy()

        # ======== 传感器方向适配 ========
        # X正后，X负前，Y左右，Z竖直
        # Y轴转动为Pitch（前推身体时产生前倾，假设设定前倾时Pitch为正）
        # X轴转动为Roll（侧推时身体侧倾，假设右倾时Roll为正）
        self.invert_pitch = False  # 是否反转俯仰角       
        self.invert_roll = False   # 是否反转横滚角        
        self.invert_yaw = False    # 是否反转偏航角    

        # === 动态抗扰平衡增益 ===
        # 根据受力方向计算关节反推力度，抵抗外力推它
        self.gain_p = 5.5   # 前后倾(Pitch)抗力增益
        self.gain_r = 4.2   # 左右倾(Roll)抗力增益
        self.gain_y = 0.5   # 旋转(Yaw)抗力增益

        # 踝关节策略(抵御推力核心)
        # 前后受力 -> 踝关节施加脚尖/脚跟力矩
        self.ankle_pitch_ratio = 1.2
        # 左右受力 -> 踝侧偏力矩
        self.ankle_roll_ratio = 1.0

        # 腰胯与膝关节联动(屈膝降重心防倒策略)
        self.hip_pitch_ratio = 1.0
        self.knee_ratio = 1.5

        # 辅助部位防抖代偿
        self.arm_swing = 1.0
        self.head_pitch_scale = 1.5
        self.head_yaw_scale = 1.5

        self.enabled = True
        self.max_offset = 600

    def set_base_pose(self, pose_dict):
        """外部输入行走或特殊动作的骨架基准姿态，在此基础上附加抗倾倒平衡计算"""
        for sid, pos in pose_dict.items():
            self.base_pose[sid] = pos

    def set_gains(self, gain_p=None, gain_r=None, gain_y=None):
        if gain_p is not None:
            self.gain_p = max(0.0, min(20.0, float(gain_p)))
        if gain_r is not None:
            self.gain_r = max(0.0, min(20.0, float(gain_r)))
        if gain_y is not None:
            self.gain_y = max(0.0, min(20.0, float(gain_y)))

    def compute(self, pitch, roll, yaw):
        """
        基于姿态偏差和当前动作基准帧，计算稳态目标值，保证不摔倒。
        """
        if not self.enabled:
            return dict(self.base_pose)

        targets = dict(self.base_pose)

        p = float(pitch) * (-1 if self.invert_pitch else 1)
        r = float(roll) * (-1 if self.invert_roll else 1)
        y = float(yaw) * (-1 if self.invert_yaw else 1)

        p_offset = int(p * self.gain_p)
        r_offset = int(r * self.gain_r)

        # 1. 骨盆/大腿根补偿重心
        for sid in (15, 21):
            targets[sid] += int(p_offset * self.hip_pitch_ratio)

        # 2. 膝盖联动(前倾时通常需屈膝以降低重心稳定底盘)
        for sid in (17, 23):
            targets[sid] -= int(p_offset * self.knee_ratio)

        # 3. 踝关节防推倒核心("脚踝策略")
        # 前倾时增加对应背屈/跖屈抗力
        for sid in (19, 25):
            targets[sid] += int(p_offset * self.ankle_pitch_ratio)
        
        # 侧摇晃补偿 (侧向被人推时的反抗)
        for sid in (18, 24):
            targets[sid] += int(r_offset * self.ankle_roll_ratio)

        # === 躯干防抖与动作代偿 ===
        targets[13] += int(y * self.gain_y)
        targets[1] -= int(y * self.head_yaw_scale)
        targets[2] -= int(p * self.head_pitch_scale)

        # 手臂摆动增加动态力矩平衡
        arm_offset = int(p * self.arm_swing)
        targets[3] += arm_offset   # 左臂
        targets[8] -= arm_offset   # 右臂

        # === 输出限幅保护 ===
        for sid in targets:
            base_val = self.base_pose.get(sid, 2048)
            offset = targets[sid] - base_val
            if abs(offset) > self.max_offset:
                offset = self.max_offset if offset > 0 else -self.max_offset
            targets[sid] = max(0, min(4095, base_val + offset))

        return targets

    def compute_incremental(self, pitch, roll, yaw, current_positions):
        """增量模式：基于伺服目前真实位置进行微调去噪。"""
        full_targets = self.compute(pitch, roll, yaw)
        result = {}
        for sid, target in full_targets.items():
            cur = current_positions.get(sid)
            if cur is None:
                continue
            diff = target - int(cur)
            if abs(diff) > 5:  # 死区：误差小于 5 个单位不发指令防止抖动
                result[sid] = target
        return result
