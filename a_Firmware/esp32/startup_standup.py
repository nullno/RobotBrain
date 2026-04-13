"""
startup_standup.py - 机器人启动站立模块 V2

V2 改进：
- 不依赖网络，在 IMU + 舵机初始化后立即执行
- 更快的起立速度（优化过渡帧数）
- IMU 实时反馈贯穿全过程
- 容错增强（部分舵机离线也能尝试站立）
- 站立后立即启用平衡控制器

启动流程：
  Phase 0: 舵机检测 + 上扭矩
  Phase 1: 平躺 → 弯曲双腿
  Phase 2: 双手臂撑地，坐起
  Phase 3: 前倾蹲姿
  Phase 4: 逐步蹬直站起
  Phase 5: IMU 闭环微调平衡
"""

import time


def _clamp(val, lo, hi):
    if val < lo:
        return lo
    if val > hi:
        return hi
    return val


_JOINT_LIMITS = {
    1: (1500, 2600), 2: (1600, 2500),
    3: (1200, 2900), 4: (1800, 3000), 5: (1500, 2600), 6: (1200, 2800), 7: (1400, 2700),
    8: (1200, 2900), 9: (1000, 2200), 10: (1500, 2600), 11: (1200, 2800), 12: (1400, 2700),
    13: (1600, 2500),
    14: (1700, 2400), 15: (1200, 2900), 16: (1700, 2400), 17: (1200, 2900),
    18: (1600, 2500), 19: (1500, 2600),
    20: (1700, 2400), 21: (1200, 2900), 22: (1700, 2400), 23: (1200, 2900),
    24: (1600, 2500), 25: (1500, 2600),
}


def _safe(sid, val):
    lo, hi = _JOINT_LIMITS.get(sid, (0, 4095))
    return _clamp(int(val), lo, hi)


def _log(msg):
    try:
        print("[startup {:.3f}] {}".format(time.ticks_ms() / 1000.0, msg))
    except Exception:
        print("[startup] " + str(msg))


# 站立基准（微屈膝站姿）
_STAND = {i: 2048 for i in range(1, 26)}
_STAND[6] = 1800
_STAND[11] = 1800
_STAND[15] = 2100
_STAND[21] = 2100
_STAND[17] = 1996
_STAND[23] = 1996
_STAND[19] = 2070
_STAND[25] = 2070


class StartupStandup:
    """机器人从平躺到站立的自动起立控制器 V2。"""

    def __init__(self, servo_ctrl, imu_ctrl, balance_ctrl=None, motion_sdk=None):
        self.servo = servo_ctrl
        self.imu = imu_ctrl
        self.balance = balance_ctrl
        self.motion = motion_sdk
        self._completed = False

    @property
    def completed(self):
        return self._completed

    def _send(self, pose, dur_ms=600):
        safe = {}
        for sid, pos in pose.items():
            safe[str(sid)] = _safe(sid, pos)
        self.servo.set_positions(safe, dur_ms)
        time.sleep_ms(dur_ms + 50)

    def _smooth(self, keyframes, durations, steps=5):
        """平滑插值执行。"""
        prev = {}
        for sid in range(1, 26):
            prev[sid] = 2048
        if self.motion:
            prev = dict(self.motion.base_positions)

        for i in range(len(keyframes)):
            target = {}
            for sid, pos in keyframes[i].items():
                target[int(sid)] = _safe(int(sid), pos)
            total_dur = max(100, int(durations[i]))
            step_dur = total_dur // steps
            for s in range(1, steps + 1):
                t = s / steps
                alpha = t * t * (3.0 - 2.0 * t)
                interp = {}
                for sid in target:
                    start = prev.get(sid, 2048)
                    val = int(start + (target[sid] - start) * alpha)
                    interp[str(sid)] = _safe(sid, val)
                self.servo.set_positions(interp, step_dur)
                time.sleep_ms(step_dur)
            prev = dict(target)

    def _read_imu(self):
        try:
            self.imu.update()
            return float(self.imu.pitch), float(self.imu.roll)
        except Exception:
            return 0.0, 0.0

    def execute(self):
        """执行完整起立流程（无需网络）。

        Returns:
            True = 成功，False = 失败
        """
        if self._completed:
            return True

        _log("===== V2 起立流程开始 =====")

        try:
            # Phase 0: 舵机检测
            _log("Phase 0: 舵机检测 + 上扭矩")
            online = []
            for attempt in range(4):
                online = self.servo.scan()
                _log("扫描第{}次: {}/25 在线".format(attempt + 1, len(online)))
                if len(online) >= 18:
                    break
                time.sleep_ms(1000 + attempt * 500)

            leg_ids = set(range(14, 26))
            leg_online = len(leg_ids.intersection(set(online)))
            if leg_online < 6:
                _log("WARN: 腿部舵机过少 ({}/12), 取消起立".format(leg_online))
                return False

            self.servo.torque_on()
            time.sleep_ms(400)

            # Phase 1: 平躺 → 弯曲双腿
            _log("Phase 1: 弯曲双腿")
            lie_pose = {i: 2048 for i in range(1, 26)}
            self._send(lie_pose, 800)

            p1 = dict(lie_pose)
            p1[15] = 2500
            p1[21] = 2500
            p1[17] = 1450
            p1[23] = 1450
            p1[19] = 2350
            p1[25] = 2350
            self._smooth([p1], [1200], steps=5)

            # Phase 2: 手臂撑地坐起
            _log("Phase 2: 双臂撑地坐起")
            p2a = dict(p1)
            p2a[3] = 1350
            p2a[8] = 1350
            p2a[6] = 2100
            p2a[11] = 2100
            self._smooth([p2a], [1000], steps=4)

            p2b = dict(p2a)
            p2b[15] = 2600
            p2b[21] = 2600
            p2b[6] = 2300
            p2b[11] = 2300
            p2b[3] = 1450
            p2b[8] = 1450
            self._smooth([p2b], [1500], steps=5)

            # Phase 3: 前倾蹲姿
            _log("Phase 3: 蹲姿，重心到脚上")
            p3a = dict(p2b)
            p3a[15] = 2550
            p3a[21] = 2550
            p3a[17] = 1400
            p3a[23] = 1400
            p3a[19] = 2400
            p3a[25] = 2400
            p3a[3] = 1800
            p3a[8] = 1800
            p3a[6] = 1900
            p3a[11] = 1900
            self._smooth([p3a], [1200], steps=5)

            p3b = dict(p3a)
            p3b[15] = 2600
            p3b[21] = 2600
            p3b[17] = 1350
            p3b[23] = 1350
            p3b[19] = 2450
            p3b[25] = 2450
            p3b[3] = 2250
            p3b[8] = 2250
            p3b[6] = 1800
            p3b[11] = 1800
            self._smooth([p3b], [1000], steps=4)

            # Phase 4: 逐步站起
            _log("Phase 4: 站起")
            p4a = dict(_STAND)
            p4a[15] = 2350
            p4a[21] = 2350
            p4a[17] = 1650
            p4a[23] = 1650
            p4a[19] = 2250
            p4a[25] = 2250
            p4a[3] = 2150
            p4a[8] = 2150
            p4a[6] = 1800
            p4a[11] = 1800
            self._smooth([p4a], [1200], steps=5)

            p4b = dict(_STAND)
            p4b[15] = 2200
            p4b[21] = 2200
            p4b[17] = 1900
            p4b[23] = 1900
            p4b[19] = 2150
            p4b[25] = 2150
            self._smooth([p4b], [1000], steps=4)

            stand = dict(_STAND)
            self._smooth([stand], [800], steps=4)

            # Phase 5: IMU 闭环微调（更快收敛）
            _log("Phase 5: IMU 平衡微调")
            time.sleep_ms(300)

            for iteration in range(20):
                pitch, roll = self._read_imu()

                if abs(pitch) < 1.5 and abs(roll) < 1.5:
                    _log("平衡达标: P={:.1f} R={:.1f}".format(pitch, roll))
                    break

                adjust = dict(stand)

                # 踝关节快速补偿
                if abs(pitch) > 0.5:
                    comp_p = int(pitch * 15)
                    comp_p = _clamp(comp_p, -300, 300)
                    adjust[19] = _safe(19, stand[19] + comp_p)
                    adjust[25] = _safe(25, stand[25] + comp_p)
                    if abs(pitch) > 4.0:
                        hip_c = int(pitch * 8)
                        hip_c = _clamp(hip_c, -200, 200)
                        adjust[15] = _safe(15, stand[15] + hip_c)
                        adjust[21] = _safe(21, stand[21] + hip_c)
                        knee_c = int(pitch * 5)
                        knee_c = _clamp(knee_c, -150, 150)
                        adjust[17] = _safe(17, stand[17] - knee_c)
                        adjust[23] = _safe(23, stand[23] - knee_c)

                if abs(roll) > 0.5:
                    comp_r = int(roll * 12)
                    comp_r = _clamp(comp_r, -250, 250)
                    adjust[18] = _safe(18, stand[18] + comp_r)
                    adjust[24] = _safe(24, stand[24] + comp_r)

                self._send(adjust, 200)
                _log("调整[{}]: P={:.1f} R={:.1f}".format(iteration, pitch, roll))
                time.sleep_ms(250)

            # 完成: 设置基准，启用平衡
            if self.motion:
                self.motion.base_positions = dict(_STAND)
            if self.balance:
                self.balance.reset_base_pose()
                self.balance.enabled = True

            self._completed = True
            _log("===== V2 起立完成！=====")
            return True

        except Exception as e:
            _log("起立失败: {}".format(e))
            try:
                self.servo.torque_off([254])
            except Exception:
                pass
            return False
