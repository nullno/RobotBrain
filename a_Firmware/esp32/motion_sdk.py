"""
motion_sdk.py - 人形机器人运动控制 SDK（ESP32 固件层）

核心设计原则：
  1. 安全第一：所有动作通过多帧关键帧插值执行，禁止单帧大角度跳变
  2. 丝滑流畅：关键帧之间使用梯形速度曲线进行平滑过渡
  3. 平衡联动：每帧执行时自动同步到 BalanceController 的 base_pose
  4. 关节保护：所有输出值严格限制在安全范围内

舵机 ID 映射（25自由度）：
  颈部: 1(左右), 2(上下)
  左臂: 3(肩前后), 4(肩侧举), 5(上臂旋转), 6(肘), 7(腕)
  右臂: 8(肩前后), 9(肩侧举), 10(上臂旋转), 11(肘), 12(腕)
  腰部: 13(旋转)
  左腿: 14(胯旋转), 15(髋弯曲), 16(大腿旋转), 17(膝), 18(踝左右), 19(踝前后)
  右腿: 20(胯旋转), 21(髋弯曲), 22(大腿旋转), 23(膝), 24(踝左右), 25(踝前后)

所有位置值范围 0-4095，中位 2048。
"""

import time
import math


def _clamp(val, lo, hi):
    if val < lo:
        return lo
    if val > hi:
        return hi
    return val


# 关节安全范围
JOINT_LIMITS = {
    1: (1500, 2600), 2: (1600, 2500),
    3: (1200, 2900), 4: (1800, 3000), 5: (1500, 2600), 6: (1200, 2800), 7: (1400, 2700),
    8: (1200, 2900), 9: (1000, 2200), 10: (1500, 2600), 11: (1200, 2800), 12: (1400, 2700),
    13: (1600, 2500),
    14: (1700, 2400), 15: (1200, 2900), 16: (1700, 2400), 17: (1200, 2900), 18: (1600, 2500), 19: (1500, 2600),
    20: (1700, 2400), 21: (1200, 2900), 22: (1700, 2400), 23: (1200, 2900), 24: (1600, 2500), 25: (1500, 2600),
}

# 站立基准姿态（微屈膝站姿 - 降低重心、增大平衡裕度）
STAND_POSE = {i: 2048 for i in range(1, 26)}
STAND_POSE[6] = 1800   # 左肘微屈
STAND_POSE[11] = 1800  # 右肘微屈
STAND_POSE[15] = 2100  # 左髋微前屈
STAND_POSE[21] = 2100  # 右髋微前屈
STAND_POSE[17] = 1996  # 左膝微屈
STAND_POSE[23] = 1996  # 右膝微屈
STAND_POSE[19] = 2070  # 左踝微背屈（配合屈膝）
STAND_POSE[25] = 2070  # 右踝微背屈


def _safe_pos(sid, val):
    """确保位置值在关节安全范围内。"""
    lo, hi = JOINT_LIMITS.get(sid, (0, 4095))
    return _clamp(int(val), lo, hi)


def _mirror_pose(pose, mapping):
    """将左侧姿态镜像到右侧（或反之）。

    mapping: [(left_id, right_id, invert_bool), ...]
    """
    result = dict(pose)
    for l_id, r_id, invert in mapping:
        if l_id in pose:
            base = 2048
            offset = pose[l_id] - base
            result[r_id] = _safe_pos(r_id, base + (-offset if invert else offset))
    return result


# 左右腿镜像映射（左→右时是否反转偏移）
LEG_MIRROR = [
    (14, 20, False),  # 胯旋转
    (15, 21, False),  # 髋弯曲
    (16, 22, True),   # 大腿旋转（镜像反向）
    (17, 23, False),  # 膝
    (18, 24, False),  # 踝左右
    (19, 25, False),  # 踝前后
]

# 左右臂镜像映射
ARM_MIRROR = [
    (3, 8, False),    # 肩前后
    (4, 9, True),     # 肩侧举（镜像反向）
    (5, 10, True),    # 上臂旋转
    (6, 11, False),   # 肘
    (7, 12, True),    # 腕
]


class MotionSDK:
    """人形机器人运动控制 SDK.

    所有动作使用多帧关键帧序列实现平滑运动，
    每帧执行后通知 BalanceController 更新基准姿态。
    """

    def __init__(self, servo_ctrl, balance_ctrl=None):
        self.servo_ctrl = servo_ctrl
        self.balance_ctrl = balance_ctrl
        self.base_positions = dict(STAND_POSE)
        self._running = False   # 当前是否有动作在执行
        self._abort = False     # 中止标志

    def abort(self):
        """请求中止当前动作。"""
        self._abort = True

    def is_running(self):
        return self._running

    def _execute(self, keyframes, durations):
        """执行一组关键帧序列。

        每一帧都是 {servo_id: position} 字典，只需包含需要变化的关节。
        不在帧中的关节保持上一帧的位置不变。

        安全措施：
        - 所有位置值经过关节限幅
        - 通知平衡控制器更新基准姿态 + 运动状态
        - 支持中止机制
        """
        self._running = True
        self._abort = False

        try:
            # 通知平衡器正在执行动作
            if self.balance_ctrl and hasattr(self.balance_ctrl, 'set_motion_state'):
                self.balance_ctrl.set_motion_state('action')

            for i in range(len(keyframes)):
                if self._abort:
                    break

                frame = keyframes[i]
                duration = max(50, int(durations[i]))

                # 合并到当前基准
                safe_frame = {}
                for sid, pos in frame.items():
                    sid_i = int(sid)
                    safe_val = _safe_pos(sid_i, pos)
                    self.base_positions[sid_i] = safe_val
                    safe_frame[sid_i] = safe_val

                # 通知平衡控制器
                if self.balance_ctrl:
                    self.balance_ctrl.set_base_pose(self.base_positions)

                # 发送到舵机
                self.servo_ctrl.set_positions(safe_frame, duration)
                time.sleep_ms(duration)
        finally:
            self._running = False
            self._abort = False
            # 恢复平衡器为站立模式
            if self.balance_ctrl and hasattr(self.balance_ctrl, 'set_motion_state'):
                self.balance_ctrl.set_motion_state('stand')

    def _execute_smooth(self, keyframes, durations, steps_per_frame=4):
        """平滑插值执行：将每帧拆分为多个子步骤，实现更顺滑的运动。

        steps_per_frame: 每帧之间的插值细分数（越大越平滑，但延迟略增）
        """
        self._running = True
        self._abort = False

        try:
            # 通知平衡器正在执行动作
            if self.balance_ctrl and hasattr(self.balance_ctrl, 'set_motion_state'):
                self.balance_ctrl.set_motion_state('action')

            prev_frame = dict(self.base_positions)

            for i in range(len(keyframes)):
                if self._abort:
                    break

                target_frame = dict(prev_frame)
                for sid, pos in keyframes[i].items():
                    target_frame[int(sid)] = _safe_pos(int(sid), pos)

                total_dur = max(50, int(durations[i]))
                step_dur = total_dur // steps_per_frame

                for step in range(1, steps_per_frame + 1):
                    if self._abort:
                        break

                    # 线性插值比例（使用平滑的正弦曲线 ease-in-out）
                    t = step / steps_per_frame
                    # Smoothstep: 3t² - 2t³ (比线性更平滑)
                    alpha = t * t * (3.0 - 2.0 * t)

                    interp = {}
                    for sid in target_frame:
                        start = prev_frame.get(sid, 2048)
                        end = target_frame[sid]
                        val = int(start + (end - start) * alpha)
                        interp[sid] = _safe_pos(sid, val)

                    # 更新基准并发送
                    self.base_positions.update(interp)
                    if self.balance_ctrl:
                        self.balance_ctrl.set_base_pose(self.base_positions)

                    self.servo_ctrl.set_positions(interp, step_dur)
                    time.sleep_ms(step_dur)

                prev_frame = dict(target_frame)
        finally:
            self._running = False
            self._abort = False
            # 恢复平衡器为站立模式
            if self.balance_ctrl and hasattr(self.balance_ctrl, 'set_motion_state'):
                self.balance_ctrl.set_motion_state('stand')

    # =================================================================
    #  安全功能
    # =================================================================

    def gradual_torque_release(self):
        """渐进式安全卸力 —— 先蹲下降低重心，再逐步释放扭矩。"""
        # 1. 缓慢蹲下（降低重心，减少摔倒冲击）
        crouch_pose = dict(self.base_positions)
        for sid in (15, 21):
            crouch_pose[sid] = 2500  # 髋前屈
        for sid in (17, 23):
            crouch_pose[sid] = 1500  # 屈膝
        for sid in (19, 25):
            crouch_pose[sid] = 2400  # 踝背屈
        self._execute_smooth([crouch_pose], [1200], steps_per_frame=6)

        # 2. 逐步降低扭矩上限
        for limit in range(800, -1, -100):
            self.servo_ctrl.set_torque_limit(254, max(0, limit))
            time.sleep_ms(80)

        # 3. 完全关闭扭矩
        self.servo_ctrl.torque_off([254])

        # 4. 恢复默认扭矩上限（供下次使能用）
        time.sleep_ms(100)
        self.servo_ctrl.set_torque_limit(254, 1000)

    # =================================================================
    #  基础姿态
    # =================================================================

    def stand(self):
        """站立归位"""
        self.base_positions = dict(STAND_POSE)
        if self.balance_ctrl:
            self.balance_ctrl.reset_base_pose()
        self._execute_smooth([dict(STAND_POSE)], [600], steps_per_frame=5)

    def crouch(self):
        """蹲下"""
        if self.balance_ctrl and hasattr(self.balance_ctrl, 'set_motion_state'):
            self.balance_ctrl.set_motion_state('crouch')
        pose = dict(self.base_positions)
        for sid in (15, 21):
            pose[sid] = 2550  # 髋前屈
        for sid in (17, 23):
            pose[sid] = 1550  # 屈膝
        for sid in (19, 25):
            pose[sid] = 2450  # 踝背屈
        # 手臂微前伸辅助平衡
        pose[3] = 2200
        pose[8] = 2200
        self._execute_smooth([pose], [800], steps_per_frame=5)

    def sit(self):
        """坐下（深蹲到底）"""
        p1 = dict(self.base_positions)
        for sid in (15, 21):
            p1[sid] = 2400
        for sid in (17, 23):
            p1[sid] = 1700
        for sid in (19, 25):
            p1[sid] = 2350

        p2 = dict(p1)
        for sid in (15, 21):
            p2[sid] = 2650
        for sid in (17, 23):
            p2[sid] = 1400
        for sid in (19, 25):
            p2[sid] = 2500
        # 手臂前伸保持平衡
        p2[3] = 2400
        p2[8] = 2400

        self._execute_smooth([p1, p2], [500, 600], steps_per_frame=5)

    def sit_chair(self):
        """坐凳子"""
        pose = dict(self.base_positions)
        for sid in (15, 21):
            pose[sid] = 2600
        for sid in (17, 23):
            pose[sid] = 2600
        for sid in (19, 25):
            pose[sid] = 2048
        self._execute_smooth([pose], [800], steps_per_frame=5)

    # =================================================================
    #  行走步态（核心算法）
    # =================================================================

    def _gait_step(self, left_first=True, step_length=120, lift_height=100,
                   step_duration=400):
        """单步行走步态发生器。

        使用 5 阶段步态 + 平衡控制器单脚支撑感知：
          1. 重心侧移到支撑脚（通过踝关节 + 髋侧移）
          2. 摆动腿抬起
          3. 摆动腿前伸 + 支撑腿后蹬
          4. 摆动腿落地
          5. 重心回正（恢复双脚支撑）

        针对高重心、小脚机器人优化：
          - 增大侧移量确保重心转移到支撑脚
          - 降低抬脚高度减少单脚支撑时的不稳定
          - 手臂大幅反摆产生角动量
          - 基于微屈膝站姿，更低的重心提供更大稳定裕度

        Args:
            left_first: True=左脚先迈
            step_length: 步长（位置值增量）
            lift_height: 抬脚高度
            step_duration: 每阶段持续时间(ms)
        """
        if left_first:
            swing_hip, swing_knee, swing_ankle_fb, swing_ankle_lr = 15, 17, 19, 18
            stance_hip, stance_knee, stance_ankle_fb, stance_ankle_lr = 21, 23, 25, 24
            support_side = -1  # 右脚支撑
        else:
            swing_hip, swing_knee, swing_ankle_fb, swing_ankle_lr = 21, 23, 25, 24
            stance_hip, stance_knee, stance_ankle_fb, stance_ankle_lr = 15, 17, 19, 18
            support_side = 1   # 左脚支撑

        base = dict(self.base_positions)
        half_dur = step_duration // 2

        # 通知平衡器进入行走模式
        if self.balance_ctrl and hasattr(self.balance_ctrl, 'set_motion_state'):
            self.balance_ctrl.set_motion_state('walk')

        # 阶段 1: 重心侧移到支撑脚（增大侧移量应对高重心）
        p1 = dict(base)
        side_shift = 90 if left_first else -90  # 加大侧移（应对高重心）
        p1[18] = _safe_pos(18, base.get(18, 2048) + side_shift)
        p1[24] = _safe_pos(24, base.get(24, 2048) + side_shift)
        # 髋侧摆辅助重心转移
        hip_side = 35 if left_first else -35
        p1[16] = _safe_pos(16, base.get(16, 2048) + hip_side)
        p1[22] = _safe_pos(22, base.get(22, 2048) + hip_side)
        # 支撑腿深弯膝降低重心，增加稳定性
        p1[stance_knee] = _safe_pos(stance_knee, base.get(stance_knee, 2048) - 60)
        p1[stance_hip] = _safe_pos(stance_hip, base.get(stance_hip, 2048) + 40)
        p1[stance_ankle_fb] = _safe_pos(stance_ankle_fb, base.get(stance_ankle_fb, 2048) + 30)

        # 通知平衡控制器进入单脚支撑阶段
        if self.balance_ctrl:
            self.balance_ctrl.set_single_support(support_side)

        # 阶段 2: 摆动腿抬起（适度抬腿，减少不稳定）
        p2 = dict(p1)
        actual_lift = min(lift_height, 90)  # 限制抬脚高度
        p2[swing_hip] = _safe_pos(swing_hip, base.get(swing_hip, 2048) + actual_lift)
        p2[swing_knee] = _safe_pos(swing_knee, base.get(swing_knee, 2048) - actual_lift)
        p2[swing_ankle_fb] = _safe_pos(swing_ankle_fb, base.get(swing_ankle_fb, 2048) + actual_lift // 2)

        # 阶段 3: 摆动腿前伸 + 支撑腿微后蹬
        p3 = dict(p2)
        p3[swing_hip] = _safe_pos(swing_hip, base.get(swing_hip, 2048) + step_length)
        p3[swing_knee] = _safe_pos(swing_knee, base.get(swing_knee, 2048) - step_length // 3)
        p3[stance_hip] = _safe_pos(stance_hip, base.get(stance_hip, 2048) - step_length // 3)
        # 上身微前倾辅助推进
        p3[13] = _safe_pos(13, base.get(13, 2048))

        # 阶段 4: 摆动腿落地（膝踝恢复）
        p4 = dict(p3)
        p4[swing_knee] = _safe_pos(swing_knee, base.get(swing_knee, 2048))
        p4[swing_ankle_fb] = _safe_pos(swing_ankle_fb, base.get(swing_ankle_fb, 2048))
        # 开始回正侧移
        p4[18] = _safe_pos(18, base.get(18, 2048) + side_shift // 2)
        p4[24] = _safe_pos(24, base.get(24, 2048) + side_shift // 2)

        # 阶段 5: 重心回正 + 双脚负重均分
        p5 = dict(base)
        p5[18] = 2048
        p5[24] = 2048
        p5[16] = base.get(16, 2048)
        p5[22] = base.get(22, 2048)

        # 手臂自然摆动（与腿反相，增大摆幅助稳定）
        arm_swing = step_length * 2 // 3  # 进一步增大手臂摆幅
        if left_first:
            for p in [p2, p3, p4]:
                p[3] = _safe_pos(3, base.get(3, 2048) - arm_swing)
                p[8] = _safe_pos(8, base.get(8, 2048) + arm_swing)
        else:
            for p in [p2, p3, p4]:
                p[3] = _safe_pos(3, base.get(3, 2048) + arm_swing)
                p[8] = _safe_pos(8, base.get(8, 2048) - arm_swing)

        self._execute_smooth(
            [p1, p2, p3, p4, p5],
            [half_dur, step_duration, step_duration, half_dur, half_dur],
            steps_per_frame=3
        )

        # 恢复双脚支撑
        if self.balance_ctrl:
            self.balance_ctrl.set_single_support(0)
            if hasattr(self.balance_ctrl, 'set_motion_state'):
                self.balance_ctrl.set_motion_state('stand')

    def walk(self):
        """前进一步（左右交替步态）"""
        self._gait_step(left_first=True, step_length=90, step_duration=400)

    def backward(self):
        """后退一步"""
        self._gait_step(left_first=True, step_length=-70, step_duration=450)

    def turn_left(self):
        """左转（原地转向）"""
        base = dict(self.base_positions)
        turn_angle = 80

        # 身体侧移 + 左脚外旋 + 右脚内旋
        p1 = dict(base)
        p1[18] = _safe_pos(18, 2048 + 50)
        p1[24] = _safe_pos(24, 2048 + 50)

        p2 = dict(p1)
        p2[14] = _safe_pos(14, base.get(14, 2048) - turn_angle)  # 左胯外旋
        p2[15] = _safe_pos(15, base.get(15, 2048) + 60)  # 左腿微抬
        p2[17] = _safe_pos(17, base.get(17, 2048) - 60)

        p3 = dict(base)
        p3[14] = _safe_pos(14, base.get(14, 2048) - turn_angle // 2)
        p3[20] = _safe_pos(20, base.get(20, 2048) - turn_angle // 2)

        self._execute_smooth([p1, p2, p3, dict(base)], [250, 350, 350, 300], steps_per_frame=3)

    def turn_right(self):
        """右转（原地转向）"""
        base = dict(self.base_positions)
        turn_angle = 80

        p1 = dict(base)
        p1[18] = _safe_pos(18, 2048 - 50)
        p1[24] = _safe_pos(24, 2048 - 50)

        p2 = dict(p1)
        p2[20] = _safe_pos(20, base.get(20, 2048) + turn_angle)  # 右胯外旋
        p2[21] = _safe_pos(21, base.get(21, 2048) + 60)
        p2[23] = _safe_pos(23, base.get(23, 2048) - 60)

        p3 = dict(base)
        p3[14] = _safe_pos(14, base.get(14, 2048) + turn_angle // 2)
        p3[20] = _safe_pos(20, base.get(20, 2048) + turn_angle // 2)

        self._execute_smooth([p1, p2, p3, dict(base)], [250, 350, 350, 300], steps_per_frame=3)

    def step_forward(self):
        """向前迈一步（walk 别名）"""
        self.walk()

    def trot(self):
        """小跑（加速步态）"""
        self._gait_step(left_first=True, step_length=80, lift_height=80, step_duration=250)

    # =================================================================
    #  上半身动作
    # =================================================================

    def swagger(self):
        """站立晃动（左右摇摆）"""
        base = dict(self.base_positions)
        p1 = dict(base)
        p2 = dict(base)
        p1[18] = 2200
        p1[24] = 2200
        p2[18] = 1900
        p2[24] = 1900
        self._execute_smooth(
            [p1, p2, p1, p2, dict(base)],
            [400, 400, 400, 400, 400],
            steps_per_frame=3
        )

    def akimbo(self):
        """叉腰"""
        pose = dict(self.base_positions)
        pose[4] = 1500
        pose[9] = 2600
        pose[6] = 2600
        pose[11] = 1500
        self._execute_smooth([pose], [600], steps_per_frame=4)

    def wave_right(self):
        """右臂挥手"""
        base = dict(self.base_positions)
        # 抬起右臂
        p1 = dict(base)
        p1[8] = 1200   # 右肩前后（前伸）
        p1[9] = 1200   # 右肩侧举（高举）
        p1[10] = 2048
        p1[11] = 2200  # 右肘微屈

        # 挥动：腕部左右摇摆
        p2 = dict(p1)
        p2[12] = 2400

        p3 = dict(p1)
        p3[12] = 1700

        self._execute_smooth(
            [p1, p2, p3, p2, p3, dict(base)],
            [400, 250, 250, 250, 250, 400],
            steps_per_frame=3
        )

    def wave_left(self):
        """左臂挥手"""
        base = dict(self.base_positions)
        # 使用镜像映射生成左臂动作
        p1_right = {
            8: 1200,   # 右肩前后
            9: 1200,   # 右肩侧举
            10: 2048,
            11: 2200,  # 右肘微屈
        }
        p1 = dict(base)
        p1.update(_mirror_pose(p1_right, ARM_MIRROR))

        p2 = dict(p1)
        p2[7] = 2400  # 左腕（镜像右腕的2400）

        p3 = dict(p1)
        p3[7] = 1700  # 左腕（镜像右腕的1700）

        self._execute_smooth(
            [p1, p2, p3, p2, p3, dict(base)],
            [400, 250, 250, 250, 250, 400],
            steps_per_frame=3
        )

    def wave(self):
        """挥手（右臂，向后兼容）"""
        self.wave_right()

    def shake_head(self):
        """摇头"""
        base = dict(self.base_positions)
        p1 = dict(base)
        p1[1] = 2400
        p2 = dict(base)
        p2[1] = 1700
        self._execute_smooth(
            [p1, p2, p1, p2, dict(base)],
            [250, 250, 250, 250, 250],
            steps_per_frame=3
        )

    def nod(self):
        """点头"""
        base = dict(self.base_positions)
        p1 = dict(base)
        p1[2] = 1750
        p2 = dict(base)
        p2[2] = 2150
        self._execute_smooth(
            [p1, p2, p1, p2, dict(base)],
            [200, 200, 200, 200, 200],
            steps_per_frame=3
        )

    def bend_over(self):
        """弯腰鞠躬"""
        base = dict(self.base_positions)
        # 中间过渡：微屈膝保持平衡
        p1 = dict(base)
        p1[15] = 1900
        p1[21] = 1900
        p1[17] = 1900
        p1[23] = 1900

        # 深鞠躬
        p2 = dict(p1)
        p2[15] = 1700
        p2[21] = 1700
        # 手臂自然下垂
        p2[3] = 2300
        p2[8] = 2300

        self._execute_smooth(
            [p1, p2, p1, dict(base)],
            [400, 500, 500, 400],
            steps_per_frame=4
        )

    def refuse(self):
        """拒绝（双手交叉摆动）"""
        base = dict(self.base_positions)
        p1 = dict(base)
        p1[4] = 2500
        p1[9] = 1500
        p1[5] = 2300
        p1[10] = 1800

        p2 = dict(p1)
        p2[5] = 1800
        p2[10] = 2300

        self._execute_smooth(
            [p1, p2, p1, p2, dict(base)],
            [200, 200, 200, 200, 350],
            steps_per_frame=2
        )

    def think_right(self):
        """思考（右手托下巴）"""
        pose = dict(self.base_positions)
        pose[8] = 1400   # 右肩侧举
        pose[11] = 2600  # 右肘深屈
        pose[2] = 1850   # 低下巴
        self._execute_smooth([pose], [700], steps_per_frame=4)

    def think_left(self):
        """思考（左手托下巴）"""
        pose = dict(self.base_positions)
        # 使用镜像映射生成左手托下巴的动作
        pose_right = {
            8: 1400,   # 右肩侧举
            11: 2600,  # 右肘深屈
        }
        pose.update(_mirror_pose(pose_right, ARM_MIRROR))
        pose[2] = 1850   # 低下巴
        self._execute_smooth([pose], [700], steps_per_frame=4)

    def think(self):
        """思考（右手，向后兼容）"""
        self.think_right()

    def make_heart(self):
        """比爱心（双手在头顶合拢成心形）"""
        base = dict(self.base_positions)

        # 展开双臂
        p1 = dict(base)
        p1[4] = 2800
        p1[9] = 1200
        p1[6] = 2500
        p1[11] = 1500

        # 合拢成心形
        p2 = dict(p1)
        p2[4] = 2900
        p2[9] = 1100
        p2[6] = 2700
        p2[11] = 1300

        self._execute_smooth(
            [p1, p2],
            [500, 500],
            steps_per_frame=4
        )

    # =================================================================
    #  复合动作
    # =================================================================

    def horse_stance(self):
        """扎马步"""
        base = dict(self.base_positions)
        # 过渡：微蹲
        p1 = dict(base)
        for sid in (15, 21):
            p1[sid] = 2300
        for sid in (17, 23):
            p1[sid] = 1800

        # 马步：双腿分开深蹲
        p2 = dict(p1)
        for sid in (15, 21):
            p2[sid] = 2400
        for sid in (17, 23):
            p2[sid] = 1700
        for sid in (19, 25):
            p2[sid] = 2350
        p2[16] = 1800  # 左腿外旋
        p2[22] = 2300  # 右腿外旋
        # 双手叉腰
        p2[4] = 1600
        p2[9] = 2500
        p2[6] = 2500
        p2[11] = 1600

        self._execute_smooth([p1, p2], [500, 600], steps_per_frame=5)

    def golden_rooster_right(self):
        """金鸡独立（右脚站立，左腿抬起）"""
        base = dict(self.base_positions)

        # 重心先移到右脚（加大侧移）
        p1 = dict(base)
        p1[18] = 1850   # 踝侧移到右
        p1[24] = 1850
        # 双臂展开保持平衡
        p1[4] = 1400    # 左臂扬起
        p1[9] = 2600    # 右臂内收
        # 支撑腿微弯膝增加稳定性
        p1[23] = _safe_pos(23, base.get(23, 2048) - 50)
        p1[21] = _safe_pos(21, base.get(21, 2048) + 30)
        p1[25] = _safe_pos(25, base.get(25, 2048) + 20)

        # 抬起左腿
        p2 = dict(p1)
        p2[15] = 2600   # 左髋前屈
        p2[17] = 1400   # 左膝弯曲
        p2[19] = 2400   # 左踝

        self._execute_smooth([p1, p2], [600, 800], steps_per_frame=5)

    def golden_rooster(self):
        """金鸡独立（左脚站立，右腿抬起）"""
        base = dict(self.base_positions)

        # 重心先移到左脚（加大侧移）
        p1 = dict(base)
        p1[18] = 2250
        p1[24] = 2250
        # 双臂展开保持平衡
        p1[4] = 2600
        p1[9] = 1400
        # 支撑腿微弯膝增加稳定性
        p1[17] = _safe_pos(17, base.get(17, 2048) - 50)
        p1[15] = _safe_pos(15, base.get(15, 2048) + 30)
        p1[19] = _safe_pos(19, base.get(19, 2048) + 20)

        # 抬起右腿
        p2 = dict(p1)
        p2[21] = 2600   # 右髋前屈
        p2[23] = 1400   # 右膝弯曲
        p2[25] = 2400   # 右踝

        self._execute_smooth([p1, p2], [600, 800], steps_per_frame=5)

    def handstand(self):
        """倒立（安全演示：双手张开上举 + 身体前倾）"""
        base = dict(self.base_positions)
        pose = dict(base)
        # 双臂高举
        pose[4] = 2900
        pose[9] = 1100
        pose[6] = 2048
        pose[11] = 2048
        # 微前倾
        pose[15] = 1900
        pose[21] = 1900

        self._execute_smooth([pose], [800], steps_per_frame=5)

    def one_hand_handstand_left(self):
        """单手倒立（左臂高举）"""
        base = dict(self.base_positions)
        pose = dict(base)
        pose[4] = 2900   # 左臂高举
        pose[6] = 2048
        pose[9] = 1500   # 右臂自然
        self._execute_smooth([pose], [800], steps_per_frame=5)

    def one_hand_handstand_right(self):
        """单手倒立（右臂高举）"""
        base = dict(self.base_positions)
        pose = dict(base)
        pose[4] = 1500   # 左臂自然
        pose[9] = 2900   # 右臂高举
        pose[11] = 2048
        self._execute_smooth([pose], [800], steps_per_frame=5)

    def one_hand_handstand(self):
        """单手倒立（左臂，向后兼容）"""
        self.one_hand_handstand_left()

    def crawl(self):
        """爬行姿态（深蹲 + 双臂前伸）"""
        base = dict(self.base_positions)
        p1 = dict(base)
        # 深蹲
        for sid in (15, 21):
            p1[sid] = 2650
        for sid in (17, 23):
            p1[sid] = 1350
        for sid in (19, 25):
            p1[sid] = 2500
        # 双臂前伸
        p1[3] = 2600
        p1[8] = 2600
        p1[6] = 2048
        p1[11] = 2048

        self._execute_smooth([p1], [1000], steps_per_frame=5)

    def climb_stairs(self):
        """上楼梯（高抬腿步态）"""
        self._gait_step(left_first=True, step_length=100, lift_height=150, step_duration=500)

    # =================================================================
    #  侧移步态
    # =================================================================

    def side_left(self):
        """左侧移步"""
        base = dict(self.base_positions)
        shift = 80

        # 重心移到右脚
        p1 = dict(base)
        p1[18] = _safe_pos(18, 2048 - 60)
        p1[24] = _safe_pos(24, 2048 - 60)

        # 左脚抬起侧移
        p2 = dict(p1)
        p2[15] = _safe_pos(15, 2048 + 50)
        p2[17] = _safe_pos(17, 2048 - 50)
        p2[16] = _safe_pos(16, 2048 - shift)

        # 左脚落地
        p3 = dict(base)
        p3[16] = _safe_pos(16, 2048 - shift // 2)
        p3[22] = _safe_pos(22, 2048 - shift // 2)

        self._execute_smooth([p1, p2, p3, dict(base)], [300, 350, 350, 300], steps_per_frame=3)

    def side_right(self):
        """右侧移步"""
        base = dict(self.base_positions)
        shift = 80

        # 重心移到左脚
        p1 = dict(base)
        p1[18] = _safe_pos(18, 2048 + 60)
        p1[24] = _safe_pos(24, 2048 + 60)

        # 右脚抬起侧移
        p2 = dict(p1)
        p2[21] = _safe_pos(21, 2048 + 50)
        p2[23] = _safe_pos(23, 2048 - 50)
        p2[22] = _safe_pos(22, 2048 + shift)

        # 右脚落地
        p3 = dict(base)
        p3[16] = _safe_pos(16, 2048 + shift // 2)
        p3[22] = _safe_pos(22, 2048 + shift // 2)

        self._execute_smooth([p1, p2, p3, dict(base)], [300, 350, 350, 300], steps_per_frame=3)

    # =================================================================
    #  连续动作（持续行走）
    # =================================================================

    def walk_continuous(self, steps=4):
        """连续行走多步。"""
        for i in range(steps):
            if self._abort:
                break
            self._gait_step(left_first=(i % 2 == 0), step_length=100, step_duration=350)

    def backward_continuous(self, steps=4):
        """连续后退多步。"""
        for i in range(steps):
            if self._abort:
                break
            self._gait_step(left_first=(i % 2 == 0), step_length=-80, step_duration=400)

    # =================================================================
    #  踢腿
    # =================================================================

    def kick_left(self):
        """左脚踢"""
        base = dict(self.base_positions)

        # 重心移右（支撑右脚）
        p1 = dict(base)
        p1[18] = _safe_pos(18, 2048 + 70)
        p1[24] = _safe_pos(24, 2048 + 70)
        p1[4] = 1600   # 左肩侧举（展开）
        p1[9] = 2400   # 右肩侧举（收缩）

        # 抬左腿
        p2 = dict(p1)
        p2[15] = 2500  # 髋前屈
        p2[17] = 1800  # 屈膝蓄力

        # 踢出
        p3 = dict(p2)
        p3[15] = 2700  # 髋大幅前屈
        p3[17] = 2048  # 伸膝踢出

        self._execute_smooth(
            [p1, p2, p3, p1, dict(base)],
            [300, 300, 200, 300, 300],
            steps_per_frame=3
        )

    def kick_right(self):
        """右脚踢"""
        base = dict(self.base_positions)

        # 重心移左（支撑左脚）
        p1 = dict(base)
        p1[18] = _safe_pos(18, 2048 - 70)
        p1[24] = _safe_pos(24, 2048 - 70)
        p1[4] = 2400   # 左肩侧举（收缩）
        p1[9] = 1600   # 右肩侧举（展开）

        p2 = dict(p1)
        p2[21] = 2500  # 右髋前屈
        p2[23] = 1800  # 右膝屈膝蓄力

        p3 = dict(p2)
        p3[21] = 2700  # 右髋大幅前屈
        p3[23] = 2048  # 右膝伸膝踢出

        self._execute_smooth(
            [p1, p2, p3, p1, dict(base)],
            [300, 300, 200, 300, 300],
            steps_per_frame=3
        )

    # =================================================================
    #  舞蹈
    # =================================================================

    def dance(self):
        """简单舞蹈组合动作"""
        base = dict(self.base_positions)

        # 节拍 1: 左右摇摆 + 手臂交替
        p1 = dict(base)
        p1[18] = 2200
        p1[24] = 2200
        p1[4] = 2600
        p1[9] = 2048

        p2 = dict(base)
        p2[18] = 1850
        p2[24] = 1850
        p2[4] = 2048
        p2[9] = 1400

        # 节拍 2: 微蹲上下弹
        p3 = dict(base)
        p3[15] = 2200
        p3[21] = 2200
        p3[17] = 1900
        p3[23] = 1900

        p4 = dict(base)

        self._execute_smooth(
            [p1, p2, p3, p4, p1, p2, p3, p4],
            [300, 300, 300, 300, 300, 300, 300, 300],
            steps_per_frame=3
        )

    def bow(self):
        """鞠躬致敬"""
        self.bend_over()

    # =================================================================
    #  扩展动作库：Greetings / Social
    # =================================================================

    def salute(self):
        """敬礼（右臂举至太阳穴）"""
        base = dict(self.base_positions)
        # 右臂上举至头侧
        p1 = dict(base)
        p1[8] = _safe_pos(8, 1350)   # 右肩前伸
        p1[9] = _safe_pos(9, 1150)   # 右肩举高（手近头侧）
        p1[10] = _safe_pos(10, 2100) # 上臂微旋
        p1[11] = _safe_pos(11, 2550) # 肘深屈（手在太阳穴附近）
        p1[12] = _safe_pos(12, 2100) # 腕直（敬礼手型）

        # 微微抬头，保持敬礼姿态
        p2 = dict(p1)
        p2[2] = _safe_pos(2, 1900)   # 头微抬

        self._execute_smooth(
            [p1, p2, p1, dict(base)],
            [400, 600, 600, 500],
            steps_per_frame=4
        )

    def clap(self):
        """拍手（双手在胸前合拢拍击）"""
        base = dict(self.base_positions)
        # 双臂张开
        p_open = dict(base)
        p_open[3] = _safe_pos(3, 1500)   # 左肩前
        p_open[4] = _safe_pos(4, 2100)   # 左臂胸前高度
        p_open[6] = _safe_pos(6, 1750)   # 左肘微屈
        p_open[8] = _safe_pos(8, 2600)   # 右肩后展
        p_open[9] = _safe_pos(9, 2000)   # 右臂胸前高度
        p_open[11] = _safe_pos(11, 1750) # 右肘微屈

        # 双手合拢（拍击）
        p_clap = dict(base)
        p_clap[3] = _safe_pos(3, 1700)   # 左臂向中线
        p_clap[8] = _safe_pos(8, 2400)   # 右臂向中线
        p_clap[6] = _safe_pos(6, 2200)   # 左肘屈（双手靠拢）
        p_clap[11] = _safe_pos(11, 2200) # 右肘屈
        p_clap[4] = _safe_pos(4, 2048)
        p_clap[9] = _safe_pos(9, 2048)

        self._execute_smooth(
            [p_open, p_clap, p_open, p_clap, p_open, p_clap, dict(base)],
            [300, 200, 200, 200, 200, 200, 400],
            steps_per_frame=3
        )

    def greeting(self):
        """问候（鞠躬+手放胸前+点头）"""
        base = dict(self.base_positions)

        # 阶段1：微鞠躬
        p1 = dict(base)
        p1[15] = _safe_pos(15, 1980) # 髋微前倾
        p1[21] = _safe_pos(21, 1980)
        p1[2] = _safe_pos(2, 2150)   # 头微低

        # 阶段2：深鞠躬 + 右手放胸前
        p2 = dict(p1)
        p2[15] = _safe_pos(15, 1900)
        p2[21] = _safe_pos(21, 1900)
        p2[8] = _safe_pos(8, 2400)   # 右手移至胸前
        p2[9] = _safe_pos(9, 2100)
        p2[11] = _safe_pos(11, 2500) # 肘屈（手贴心口）

        # 阶段3：起身 + 抬头致意
        p3 = dict(base)
        p3[2] = _safe_pos(2, 1900)   # 头微抬
        p3[8] = _safe_pos(8, 2400)
        p3[9] = _safe_pos(9, 2100)
        p3[11] = _safe_pos(11, 2500)

        # 阶段4：点头
        p4 = dict(p3)
        p4[2] = _safe_pos(2, 2200)   # 头低

        self._execute_smooth(
            [p1, p2, p3, p4, p3, dict(base)],
            [400, 500, 400, 250, 250, 400],
            steps_per_frame=4
        )

    def point_right(self):
        """右手指向"""
        base = dict(self.base_positions)
        pose = dict(base)
        pose[8] = _safe_pos(8, 1350)   # 右肩前伸
        pose[9] = _safe_pos(9, 1980)   # 右臂齐肩高（水平指向）
        pose[10] = _safe_pos(10, 2048) # 上臂中位
        pose[11] = _safe_pos(11, 1450) # 肘近伸直（手指远方）
        pose[12] = _safe_pos(12, 2048) # 腕中位
        pose[2] = _safe_pos(2, 2000)   # 头微微转向指向方向

        self._execute_smooth([pose], [600], steps_per_frame=4)

    def point_left(self):
        """左手指向（使用镜像映射）"""
        base = dict(self.base_positions)
        right_pose = {
            8: 1350,   # 右肩前伸
            9: 1980,   # 右臂齐肩高
            10: 2048,
            11: 1450,  # 肘近伸直
        }
        pose = dict(base)
        pose.update(_mirror_pose(right_pose, ARM_MIRROR))
        pose[2] = _safe_pos(2, 2000)   # 头微微转向

        self._execute_smooth([pose], [600], steps_per_frame=4)

    def point(self):
        """指向（右手，向后兼容）"""
        self.point_right()

    # =================================================================
    #  扩展动作库：Exercises（运动健身）
    # =================================================================

    def stretch(self):
        """伸懒腰（双臂上举，全身伸展）"""
        base = dict(self.base_positions)

        # 阶段1：双臂开始上举
        p1 = dict(base)
        p1[4] = _safe_pos(4, 2600)   # 左臂上举中段
        p1[9] = _safe_pos(9, 1400)   # 右臂上举中段
        p1[6] = _safe_pos(6, 1600)   # 左肘伸展
        p1[11] = _safe_pos(11, 1600) # 右肘伸展
        p1[2] = _safe_pos(2, 1800)   # 仰头
        p1[15] = _safe_pos(15, 2020) # 微挺髋
        p1[21] = _safe_pos(21, 2020)

        # 阶段2：完全伸展（手臂打直朝天）
        p2 = dict(p1)
        p2[4] = _safe_pos(4, 2900)   # 左臂最高
        p2[9] = _safe_pos(9, 1100)   # 右臂最高
        p2[6] = _safe_pos(6, 1400)   # 左肘近直
        p2[11] = _safe_pos(11, 1300) # 右肘近直
        p2[2] = _safe_pos(2, 1700)   # 头完全后仰
        p2[13] = _safe_pos(13, 2080) # 腰微伸展

        # 阶段3：保持伸展
        p3 = dict(p2)

        self._execute_smooth(
            [p1, p2, p3, p1, dict(base)],
            [500, 600, 800, 500, 500],
            steps_per_frame=5
        )

    def head_exercise(self):
        """头部运动（颈部绕环）"""
        base = dict(self.base_positions)

        p1 = dict(base); p1[1] = _safe_pos(1, 1750)                     # 头左
        p2 = dict(base); p2[1] = _safe_pos(1, 1850); p2[2] = _safe_pos(2, 2220)  # 头左下
        p3 = dict(base); p3[2] = _safe_pos(2, 2280)                     # 头正下
        p4 = dict(base); p4[1] = _safe_pos(1, 2280); p4[2] = _safe_pos(2, 2220)  # 头右下
        p5 = dict(base); p5[1] = _safe_pos(1, 2380)                     # 头右
        p6 = dict(base); p6[1] = _safe_pos(1, 2280); p6[2] = _safe_pos(2, 1850)  # 头右上
        p7 = dict(base); p7[2] = _safe_pos(2, 1750)                     # 头正上
        p8 = dict(base); p8[1] = _safe_pos(1, 1850); p8[2] = _safe_pos(2, 1850)  # 头左上

        self._execute_smooth(
            [p1, p2, p3, p4, p5, p6, p7, p8, dict(base)],
            [250, 250, 250, 250, 250, 250, 250, 250, 250],
            steps_per_frame=3
        )

    def waist_twist(self):
        """扭腰（左右转腰 + 手臂随摆）"""
        base = dict(self.base_positions)

        # 左转：腰左旋，臂右摆
        p_left = dict(base)
        p_left[13] = _safe_pos(13, 1800)  # 腰左旋
        p_left[3] = _safe_pos(3, 2200)    # 左肩后（臂右摆）
        p_left[8] = _safe_pos(8, 2400)    # 右肩前
        p_left[4] = _safe_pos(4, 2150)    # 左臂微外展
        p_left[9] = _safe_pos(9, 1800)    # 右臂微外展

        # 右转：腰右旋，臂左摆
        p_right = dict(base)
        p_right[13] = _safe_pos(13, 2300) # 腰右旋
        p_right[3] = _safe_pos(3, 1800)   # 左肩前（臂左摆）
        p_right[8] = _safe_pos(8, 1800)   # 右肩后
        p_right[4] = _safe_pos(4, 1800)   # 左臂内收
        p_right[9] = _safe_pos(9, 2100)   # 右臂内收

        self._execute_smooth(
            [p_left, p_right, p_left, p_right, p_left, p_right, dict(base)],
            [300, 300, 300, 300, 300, 300, 400],
            steps_per_frame=3
        )

    # =================================================================
    #  扩展动作库：Emotional Expressions（情绪表达）
    # =================================================================

    def cheer(self):
        """欢呼（双臂上举 + 身体微弹）"""
        base = dict(self.base_positions)

        # 双臂高举
        p_up = dict(base)
        p_up[4] = _safe_pos(4, 2800)   # 左臂高举
        p_up[9] = _safe_pos(9, 1150)   # 右臂高举
        p_up[6] = _safe_pos(6, 1400)   # 左肘近直
        p_up[11] = _safe_pos(11, 1250) # 右肘近直
        p_up[2] = _safe_pos(2, 1750)   # 仰头
        p_up[15] = _safe_pos(15, 2020) # 挺身
        p_up[21] = _safe_pos(21, 2020)

        # 微蹲弹动（欢呼跳跃感）
        p_down = dict(p_up)
        p_down[17] = _safe_pos(17, 1850) # 微屈膝
        p_down[23] = _safe_pos(23, 1850)
        p_down[15] = _safe_pos(15, 2150) # 髋微屈
        p_down[21] = _safe_pos(21, 2150)

        # 弹起
        p_bounce = dict(p_up)
        p_bounce[17] = _safe_pos(17, 2000)
        p_bounce[23] = _safe_pos(23, 2000)
        p_bounce[15] = _safe_pos(15, 2020)
        p_bounce[21] = _safe_pos(21, 2020)

        self._execute_smooth(
            [p_up, p_down, p_bounce, p_down, p_bounce, dict(base)],
            [300, 200, 200, 200, 200, 400],
            steps_per_frame=3
        )

    def sad(self):
        """悲伤（垂头、塌肩、微蹲）"""
        base = dict(self.base_positions)

        # 垂头塌肩
        p1 = dict(base)
        p1[2] = _safe_pos(2, 2300)   # 头深深低下
        p1[3] = _safe_pos(3, 2400)   # 左肩前塌
        p1[8] = _safe_pos(8, 2400)   # 右肩前塌
        p1[4] = _safe_pos(4, 1950)   # 左臂低频下垂
        p1[9] = _safe_pos(9, 2100)   # 右臂低频下垂
        p1[6] = _safe_pos(6, 2400)   # 左肘内收
        p1[11] = _safe_pos(11, 2400) # 右肘内收

        # 更进一步的低落姿态
        p2 = dict(p1)
        p2[2] = _safe_pos(2, 2380)   # 头更低
        p2[15] = _safe_pos(15, 1950) # 髋微沉
        p2[21] = _safe_pos(21, 1950)
        p2[17] = _safe_pos(17, 1950) # 膝微弯（无力感）
        p2[23] = _safe_pos(23, 1950)

        self._execute_smooth([p1, p2], [600, 400], steps_per_frame=4)

    def shrug(self):
        """耸肩（双肩耸起 + 手臂外旋摊手）"""
        base = dict(self.base_positions)

        # 耸肩摊手
        p1 = dict(base)
        p1[3] = _safe_pos(3, 2200)   # 左肩耸
        p1[8] = _safe_pos(8, 2200)   # 右肩耸
        p1[4] = _safe_pos(4, 2100)   # 左臂微外展
        p1[9] = _safe_pos(9, 1900)   # 右臂微外展
        p1[5] = _safe_pos(5, 2350)   # 左上臂外旋（掌心朝外）
        p1[10] = _safe_pos(10, 1700) # 右上臂外旋（镜像）
        p1[7] = _safe_pos(7, 2300)   # 左腕翻
        p1[12] = _safe_pos(12, 1700) # 右腕翻
        p1[2] = _safe_pos(2, 1950)   # 头微偏
        p1[1] = _safe_pos(1, 2100)   # 头微侧

        # 保持
        p2 = dict(p1)

        self._execute_smooth([p1, p2, dict(base)], [400, 500, 400], steps_per_frame=4)

    def proud(self):
        """骄傲挺胸（昂首、挺胸、叉腰）"""
        base = dict(self.base_positions)

        pose = dict(base)
        pose[2] = _safe_pos(2, 1850)   # 昂首（下巴抬高）
        pose[4] = _safe_pos(4, 1650)   # 左臂叉腰（下压后展）
        pose[9] = _safe_pos(9, 2450)   # 右臂叉腰（镜像）
        pose[6] = _safe_pos(6, 2550)   # 左肘外展（气势）
        pose[11] = _safe_pos(11, 1550) # 右肘外展（镜像）
        pose[15] = _safe_pos(15, 2050) # 挺身收髋
        pose[21] = _safe_pos(21, 2050)
        pose[17] = _safe_pos(17, 2050) # 腿微直（挺拔）
        pose[23] = _safe_pos(23, 2050)
        pose[13] = _safe_pos(13, 2048) # 腰正

        self._execute_smooth([pose], [600], steps_per_frame=4)

    # =================================================================
    #  扩展动作库：Performance / Demo
    # =================================================================

    def march(self):
        """原地踏步（交替抬腿 + 摆臂）"""
        base = dict(self.base_positions)

        # 左腿抬 + 右臂前摆
        p1 = dict(base)
        p1[15] = _safe_pos(15, 2500)  # 左髋屈（抬左腿）
        p1[17] = _safe_pos(17, 1550)  # 左膝屈
        p1[19] = _safe_pos(19, 2350)  # 左踝背屈
        p1[3] = _safe_pos(3, 1500)    # 右臂前摆（与左腿对侧）
        p1[8] = _safe_pos(8, 2500)    # 左臂后摆

        # 中立
        p_center = dict(base)

        # 右腿抬 + 左臂前摆
        p3 = dict(base)
        p3[21] = _safe_pos(21, 2500)  # 右髋屈（抬右腿）
        p3[23] = _safe_pos(23, 1550)  # 右膝屈
        p3[25] = _safe_pos(25, 2350)  # 右踝背屈
        p3[8] = _safe_pos(8, 1500)    # 左臂前摆（与右腿对侧）
        p3[3] = _safe_pos(3, 2500)    # 右臂后摆

        self._execute_smooth(
            [p1, p_center, p3, p_center, p1, p_center, p3, p_center, dict(base)],
            [250, 250, 250, 250, 250, 250, 250, 250, 300],
            steps_per_frame=3
        )

    def dance2(self):
        """第二套舞蹈（侧摆+挥臂+抖胯+身体wave）"""
        base = dict(self.base_positions)

        # 节拍1-2：左右侧摆
        p1 = dict(base)
        p1[13] = _safe_pos(13, 1900)  # 腰左
        p1[18] = _safe_pos(18, 2200)  # 踝左倾
        p1[24] = _safe_pos(24, 2200)
        p1[4] = _safe_pos(4, 2700)    # 左臂上扫
        p1[9] = _safe_pos(9, 2000)    # 右臂下

        p2 = dict(base)
        p2[13] = _safe_pos(13, 2200)  # 腰右
        p2[18] = _safe_pos(18, 1900)  # 踝右倾
        p2[24] = _safe_pos(24, 1900)
        p2[4] = _safe_pos(4, 2000)    # 左臂下
        p2[9] = _safe_pos(9, 1200)    # 右臂上扫

        # 节拍3：双臂过头wave
        p3 = dict(base)
        p3[4] = _safe_pos(4, 2900)    # 左臂最高
        p3[9] = _safe_pos(9, 1150)    # 右臂最高
        p3[6] = _safe_pos(6, 1600)    # 肘微屈
        p3[11] = _safe_pos(11, 1600)
        p3[13] = _safe_pos(13, 2048)  # 腰回正

        # 节拍4：蹲弹
        p4 = dict(base)
        p4[17] = _safe_pos(17, 1800)  # 屈膝
        p4[23] = _safe_pos(23, 1800)
        p4[15] = _safe_pos(15, 2250)  # 髋屈
        p4[21] = _safe_pos(21, 2250)

        # 节拍5-6：抖胯
        p5 = dict(base)
        p5[13] = _safe_pos(13, 1800)  # 腰左
        p5[18] = _safe_pos(18, 2250)
        p5[24] = _safe_pos(24, 2250)

        p6 = dict(base)
        p6[13] = _safe_pos(13, 2300)  # 腰右
        p6[18] = _safe_pos(18, 1850)
        p6[24] = _safe_pos(24, 1850)

        # 节拍7-8：身体wave（腰回旋 + 头配合）
        p7 = dict(base)
        p7[13] = _safe_pos(13, 1900)  # 腰左前
        p7[2] = _safe_pos(2, 2100)    # 头低

        p8 = dict(base)
        p8[13] = _safe_pos(13, 2200)  # 腰右后
        p8[2] = _safe_pos(2, 1900)    # 头抬

        self._execute_smooth(
            [p1, p2, p1, p2, p3, p4, p5, p6, p7, p8, dict(base)],
            [250, 250, 250, 250, 300, 300, 250, 250, 300, 300, 400],
            steps_per_frame=3
        )

    def push_up_pose(self):
        """俯卧撑准备姿势（身体前倾、双臂前撑）"""
        base = dict(self.base_positions)

        # 前倾 + 双臂前伸（模拟俯卧撑起始位）
        p1 = dict(base)
        p1[3] = _safe_pos(3, 2600)   # 左臂前伸
        p1[8] = _safe_pos(8, 2600)   # 右臂前伸
        p1[6] = _safe_pos(6, 1350)   # 左肘近直
        p1[11] = _safe_pos(11, 1350) # 右肘近直
        p1[15] = _safe_pos(15, 1850) # 髋伸展（身体前倾）
        p1[21] = _safe_pos(21, 1850)
        p1[17] = _safe_pos(17, 2050) # 腿打直
        p1[23] = _safe_pos(23, 2050)
        p1[19] = _safe_pos(19, 2200) # 踝背屈
        p1[25] = _safe_pos(25, 2200)

        # 保持 + 抬头
        p2 = dict(p1)
        p2[2] = _safe_pos(2, 1900)   # 头抬目视前方

        self._execute_smooth([p1, p2], [600, 500], steps_per_frame=5)
