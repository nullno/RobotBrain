"""
MotionController

提供面向人形机器人的通用动作 API：行走、小跑、坐、站起、挥手、抓取、叉腰、扭动等。
实现要点：
- 使用项目中的 UART 舵机 SDK（`UartServoManager`）发送同步位置指令
- 在每一步之前调用 `BalanceController.compute(pitch, roll, yaw)` 对目标位置做微调以保持平衡
- 支持在没有真实硬件时的安全检查（仅向已知舵机发送指令）

使用示例：
    mc = MotionController(servo_manager, balance_ctrl, imu_reader, neutral_positions)
    mc.stand()
    mc.walk(step_length=120, step_height=120, speed=1.0, steps=4)
    mc.wave(side='right')

注意：本实现为工程级起点，具体 gait 参数和增益需在实机上调参。
"""

import time
import threading
import math

class MotionController:
    def __init__(self, servo_manager, balance_ctrl=None, imu_reader=None, neutral_positions=None):
        """
        servo_manager: UartServoManager 或具有 sync_set_position/move_sync 接口的对象
        balance_ctrl: BalanceController 实例（可选，用于姿态补偿）
        imu_reader: IMUReader（可选，用于读取 pitch/roll/yaw）
        neutral_positions: dict {servo_id: position}
        """
        self.servo = servo_manager
        self.balance = balance_ctrl
        self.imu = imu_reader
        self.neutral = neutral_positions or {}

        # 关节映射（基于你的描述）
        self.JOINT = {
            'neck_yaw': 1, 'neck_pitch': 2,
            'l_shoulder_base': 3, 'l_shoulder_lift':4, 'l_upper_arm_rot':5, 'l_elbow':6, 'l_hand':7,
            'r_shoulder_base': 8, 'r_shoulder_lift':9, 'r_upper_arm_rot':10, 'r_elbow':11, 'r_hand':12,
            'waist':13,
            'l_hip':14, 'l_thigh':15, 'l_thigh_rot':16, 'l_knee':17, 'l_ankle_lr':18, 'l_ankle_fb':19,
            'r_hip':20, 'r_thigh':21, 'r_thigh_rot':22, 'r_knee':23, 'r_ankle_lr':24, 'r_ankle_fb':25
        }

        self._lock = threading.Lock()
        self._running = False

    # ---------- 辅助方法 ----------
    def _clamp_pos(self, pos):
        try:
            if hasattr(self.servo, 'get_legal_position'):
                return self.servo.get_legal_position(int(pos))
        except Exception:
            pass
        return max(0, min(4095, int(pos)))

    def _send_targets(self, targets, runtime_ms=100):
        # targets: dict id->position
        # 先过滤仅发送已知舵机
        ids = []
        poses = []
        for sid, p in targets.items():
            if hasattr(self.servo, 'servo_info_dict') and sid not in self.servo.servo_info_dict:
                continue
            ids.append(sid)
            poses.append(self._clamp_pos(p))

        if not ids:
            return False

        # 若有 balance controller 与 imu，则获取实时补偿并合并
        if self.balance and self.imu:
            try:
                pitch, roll, yaw = self.imu.get_orientation()
                balance_offsets = self.balance.compute(pitch, roll, yaw)
                # 合并：简单相加（仅对存在的 id）
                for i, sid in enumerate(ids):
                    off = balance_offsets.get(sid, 0)
                    poses[i] = self._clamp_pos(poses[i] + off - self.neutral.get(sid, 0) )
                    # convert back to absolute by adding neutral
                    poses[i] = self._clamp_pos(self.neutral.get(sid, 0) + poses[i])
            except Exception:
                pass

        # 发送：兼容不同封装
        try:
            if hasattr(self.servo, 'move_sync'):
                # expects dict targets
                packed = {ids[i]: poses[i] for i in range(len(ids))}
                self.servo.move_sync(packed, time_ms=runtime_ms)
                return True
            elif hasattr(self.servo, 'sync_set_position'):
                self.servo.sync_set_position(ids, poses, [runtime_ms]*len(ids))
                return True
            else:
                # try broadcast per-id
                for i, sid in enumerate(ids):
                    if hasattr(self.servo, 'set_position_time'):
                        self.servo.set_position_time(sid, poses[i], runtime_ms)
                    elif hasattr(self.servo, 'set_position'):
                        self.servo.set_position(sid, poses[i])
                return True
        except Exception:
            return False

    def _to_pos(self, angle):
        # 将角度转换为位置（若 SDK 提供），否则以中位点加偏移
        try:
            if hasattr(self.servo, 'ang2pos'):
                return int(self.servo.ang2pos(angle))
        except Exception:
            pass
        # fallback: treat angle as direct position
        return int(angle)

    # ---------- 基础动作 ----------
    def goto_neutral(self, time_ms=600):
        targets = {}
        for sid, val in self.neutral.items():
            targets[sid] = int(val)
        return self._send_targets(targets, runtime_ms=time_ms)

    def stand(self, time_ms=600):
        # 站立姿态即回中位
        return self.goto_neutral(time_ms=time_ms)

    def sit(self, time_ms=700):
        # 坐下：增加膝盖弯曲（减小伸展），腰部微屈
        targets = dict(self.neutral)
        # 加大膝盖角度 -> 对应位置调整：这里使用中位加偏量（需在真机调参）
        for k in ('l_knee', 'r_knee'):
            sid = self.JOINT[k]
            targets[sid] = targets.get(sid, 2048) + 450
        # 腰部向前
        targets[self.JOINT['waist']] = targets.get(self.JOINT['waist'], 2048) + 150
        return self._send_targets(targets, runtime_ms=time_ms)

    # ---------- 手臂动作 ----------
    def wave(self, side='right', time_ms=500, times=2):
        # 侧：'left' 或 'right'
        if side == 'right':
            sid_base = self.JOINT['r_shoulder_base']
            sid_lift = self.JOINT['r_shoulder_lift']
            sid_elbow = self.JOINT['r_elbow']
            sid_hand = self.JOINT['r_hand']
        else:
            sid_base = self.JOINT['l_shoulder_base']
            sid_lift = self.JOINT['l_shoulder_lift']
            sid_elbow = self.JOINT['l_elbow']
            sid_hand = self.JOINT['l_hand']

        # 抬臂
        targets = dict(self.neutral)
        targets[sid_lift] = targets.get(sid_lift, 2048) - 400
        targets[sid_elbow] = targets.get(sid_elbow, 2048) - 200
        self._send_targets(targets, runtime_ms=time_ms)
        time.sleep(time_ms/1000.0 + 0.05)

        # 挥手动作
        for i in range(times):
            t1 = dict(targets)
            t2 = dict(targets)
            t1[sid_hand] = t1.get(sid_hand, 2048) + 350
            t2[sid_hand] = t2.get(sid_hand, 2048) - 350
            self._send_targets(t1, runtime_ms=220)
            time.sleep(0.22)
            self._send_targets(t2, runtime_ms=220)
            time.sleep(0.22)

        # 回位
        self._send_targets(self.neutral, runtime_ms=300)
        return True

    def grab(self, side='right', close=True, time_ms=300):
        if side == 'right':
            sid = self.JOINT['r_hand']
        else:
            sid = self.JOINT['l_hand']
        targets = dict(self.neutral)
        targets[sid] = targets.get(sid, 2048) + (400 if close else -400)
        return self._send_targets(targets, runtime_ms=time_ms)

    def hands_on_hips(self, time_ms=600):
        targets = dict(self.neutral)
        # 双手叉腰：肩部外展并肘部弯曲
        targets[self.JOINT['l_shoulder_lift']] = targets.get(self.JOINT['l_shoulder_lift'],2048) + 200
        targets[self.JOINT['r_shoulder_lift']] = targets.get(self.JOINT['r_shoulder_lift'],2048) + 200
        targets[self.JOINT['l_elbow']] = targets.get(self.JOINT['l_elbow'],2048) + 350
        targets[self.JOINT['r_elbow']] = targets.get(self.JOINT['r_elbow'],2048) + 350
        return self._send_targets(targets, runtime_ms=time_ms)

    def twist(self, angle_deg=30, time_ms=400):
        # 腰部扭转（左右）
        targets = dict(self.neutral)
        targets[self.JOINT['waist']] = targets.get(self.JOINT['waist'],2048) + int(angle_deg*4)
        return self._send_targets(targets, runtime_ms=time_ms)

    # ---------- 简单行走（原地、向前） ----------
    def walk(self, step_length=120, step_height=120, speed=1.0, steps=4, time_per_step_ms=300):
        """简单的前行步态（示例实现，需在真机上调参）

        step_length, step_height in position units (approx)
        """
        # 使用左右腿交替
        for i in range(steps):
            # 抬左腿，右腿支撑
            t = dict(self.neutral)
            # 左腿：向前摆（hip）、抬起(thigh)，屈膝(knee)
            t[self.JOINT['l_hip']] = t.get(self.JOINT['l_hip'],2048) + int(step_length)
            t[self.JOINT['l_thigh']] = t.get(self.JOINT['l_thigh'],2048) - int(step_height/2)
            t[self.JOINT['l_knee']] = t.get(self.JOINT['l_knee'],2048) + int(step_height)
            # 右侧微调以保持平衡
            t[self.JOINT['r_ankle_lr']] = t.get(self.JOINT['r_ankle_lr'],2048) + int(60)
            self._send_targets(t, runtime_ms=int(time_per_step_ms/speed))
            time.sleep(time_per_step_ms/1000.0/speed + 0.02)

            # 收回左腿，换右腿抬起
            t2 = dict(self.neutral)
            t2[self.JOINT['l_hip']] = t2.get(self.JOINT['l_hip'],2048) - int(step_length/2)
            t2[self.JOINT['r_hip']] = t2.get(self.JOINT['r_hip'],2048) + int(step_length)
            t2[self.JOINT['r_thigh']] = t2.get(self.JOINT['r_thigh'],2048) - int(step_height/2)
            t2[self.JOINT['r_knee']] = t2.get(self.JOINT['r_knee'],2048) + int(step_height)
            t2[self.JOINT['l_ankle_lr']] = t2.get(self.JOINT['l_ankle_lr'],2048) - int(60)
            self._send_targets(t2, runtime_ms=int(time_per_step_ms/speed))
            time.sleep(time_per_step_ms/1000.0/speed + 0.02)

        # 结束回中
        self.goto_neutral(time_ms=300)
        return True

    def stop(self):
        with self._lock:
            self._running = False
        # 立即回中以保证安全
        self.goto_neutral(time_ms=300)

    def nod(self, times=1, amplitude=160, time_ms=180):
        sid = self.JOINT.get('neck_pitch')
        if not sid:
            return False
        base = int(self.neutral.get(sid, 2048))
        for _ in range(max(1, int(times))):
            self._send_targets({sid: base + int(amplitude)}, runtime_ms=time_ms)
            time.sleep(max(0.05, time_ms / 1000.0))
            self._send_targets({sid: base - int(amplitude // 2)}, runtime_ms=time_ms)
            time.sleep(max(0.05, time_ms / 1000.0))
        self._send_targets({sid: base}, runtime_ms=time_ms)
        return True

    def shake_head(self, times=1, amplitude=180, time_ms=180):
        sid = self.JOINT.get('neck_yaw')
        if not sid:
            return False
        base = int(self.neutral.get(sid, 2048))
        for _ in range(max(1, int(times))):
            self._send_targets({sid: base + int(amplitude)}, runtime_ms=time_ms)
            time.sleep(max(0.05, time_ms / 1000.0))
            self._send_targets({sid: base - int(amplitude)}, runtime_ms=time_ms)
            time.sleep(max(0.05, time_ms / 1000.0))
        self._send_targets({sid: base}, runtime_ms=time_ms)
        return True

    def run_action(self, action):
        action = str(action or '').strip().lower()
        if action in ('', 'none'):
            return True
        if action == 'walk':
            return self.walk(steps=2)
        if action == 'stop':
            self.stop()
            return True
        if action == 'nod':
            return self.nod(times=1)
        if action == 'shake_head':
            return self.shake_head(times=1)
        if action == 'wave':
            return self.wave(side='right', times=1)
        if action == 'sit':
            return self.sit()
        if action == 'stand':
            return self.stand()
        if action == 'twist':
            return self.twist(angle_deg=25)
        return False


if __name__ == '__main__':
    print('MotionController module - integrate with your servo manager/IMU for testing')
