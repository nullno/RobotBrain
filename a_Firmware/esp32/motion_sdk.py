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

# 站立基准姿态
STAND_POSE = {i: 2048 for i in range(1, 26)}
STAND_POSE[6] = 1800   # 左肘微屈
STAND_POSE[11] = 1800  # 右肘微屈


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
        - 通知平衡控制器更新基准姿态
        - 支持中止机制
        """
        self._running = True
        self._abort = False

        try:
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

    def _execute_smooth(self, keyframes, durations, steps_per_frame=4):
        """平滑插值执行：将每帧拆分为多个子步骤，实现更顺滑的运动。

        steps_per_frame: 每帧之间的插值细分数（越大越平滑，但延迟略增）
        """
        self._running = True
        self._abort = False

        try:
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
        pose = dict(self.base_positions)
        for sid in (15, 21):
            pose[sid] = 2550  # 髋前屈
        for sid in (17, 23):
            pose[sid] = 1550  # 屈膝
        for sid in (19, 25):
            pose[sid] = 2450  # 踝背屈
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

        # 阶段 1: 重心侧移到支撑脚（增大侧移量应对高重心）
        p1 = dict(base)
        side_shift = 80 if left_first else -80  # 增大侧移（原60→80）
        p1[18] = _safe_pos(18, base.get(18, 2048) + side_shift)
        p1[24] = _safe_pos(24, base.get(24, 2048) + side_shift)
        # 髋侧摆辅助重心转移
        hip_side = 30 if left_first else -30
        p1[16] = _safe_pos(16, base.get(16, 2048) + hip_side)
        p1[22] = _safe_pos(22, base.get(22, 2048) + hip_side)
        # 微屈膝降低重心，增加稳定性
        p1[stance_knee] = _safe_pos(stance_knee, base.get(stance_knee, 2048) - 40)
        p1[stance_hip] = _safe_pos(stance_hip, base.get(stance_hip, 2048) + 30)
        p1[stance_ankle_fb] = _safe_pos(stance_ankle_fb, base.get(stance_ankle_fb, 2048) + 20)

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
        arm_swing = step_length // 2  # 增大手臂摆幅（原 //3 → //2）
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

    def walk(self):
        """前进一步（左右交替步态）"""
        self._gait_step(left_first=True, step_length=100, step_duration=350)

    def backward(self):
        """后退一步"""
        self._gait_step(left_first=True, step_length=-80, step_duration=400)

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

    def wave(self):
        """挥手"""
        base = dict(self.base_positions)
        # 抬起右臂
        p1 = dict(base)
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

    def think(self):
        """思考（手托下巴）"""
        pose = dict(self.base_positions)
        pose[9] = 1400   # 右肩侧举
        pose[11] = 2600  # 右肘深屈
        pose[2] = 1850   # 微低头
        self._execute_smooth([pose], [700], steps_per_frame=4)

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

    def golden_rooster(self):
        """金鸡独立（左脚站立，右腿抬起）"""
        base = dict(self.base_positions)

        # 重心先移到左脚
        p1 = dict(base)
        p1[18] = 2200
        p1[24] = 2200
        # 双臂展开保持平衡
        p1[4] = 2600
        p1[9] = 1400

        # 抬起右腿
        p2 = dict(p1)
        p2[21] = 2600   # 右髋前屈
        p2[23] = 1400   # 右膝弯曲
        p2[25] = 2400   # 右踝

        self._execute_smooth([p1, p2], [500, 700], steps_per_frame=5)

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

    def one_hand_handstand(self):
        """单手倒立（安全演示：单臂高举）"""
        base = dict(self.base_positions)
        pose = dict(base)
        pose[4] = 2900   # 左臂高举
        pose[6] = 2048
        pose[9] = 1500   # 右臂自然
        self._execute_smooth([pose], [800], steps_per_frame=5)

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

        # 重心移右
        p1 = dict(base)
        p1[18] = _safe_pos(18, 2048 + 70)
        p1[24] = _safe_pos(24, 2048 + 70)
        p1[4] = 2600  # 展臂平衡
        p1[9] = 1400

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

        p1 = dict(base)
        p1[18] = _safe_pos(18, 2048 - 70)
        p1[24] = _safe_pos(24, 2048 - 70)
        p1[4] = 2600
        p1[9] = 1400

        p2 = dict(p1)
        p2[21] = 2500
        p2[23] = 1800

        p3 = dict(p2)
        p3[21] = 2700
        p3[23] = 2048

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
