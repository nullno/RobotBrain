"""
startup_standup.py - 机器人启动站立模块

机器人上电后默认平躺状态，ESP32 开机联网，完成舵机检测后自动执行起立流程：
  Phase 0: 全身舵机可靠检测 + 上扭矩
  Phase 1: 平躺 → 弯曲双腿，脚底贴地
  Phase 2: 双手臂向后撑地，支撑上半身坐起
  Phase 3: 身体前倾至蹲姿，重心移至双脚上方
  Phase 4: 腿部发力蹬直，双臂回收，逐步站起
  Phase 5: IMU 反馈微调平衡，到达稳定站立

所有关节默认中位值 2048，基于 assembly_guide.md 的关节映射。
"""

import time


def _clamp(val, lo, hi):
    if val < lo:
        return lo
    if val > hi:
        return hi
    return val


# 关节安全范围（与 motion_sdk 保持一致）
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


# 站立基准
_STAND = {i: 2048 for i in range(1, 26)}
_STAND[6] = 1800   # 左肘微屈
_STAND[11] = 1800  # 右肘微屈


class StartupStandup:
    """机器人从平躺到站立的自动起立控制器。"""

    def __init__(self, servo_ctrl, imu_ctrl, balance_ctrl=None, motion_sdk=None):
        self.servo = servo_ctrl
        self.imu = imu_ctrl
        self.balance = balance_ctrl
        self.motion = motion_sdk
        self._completed = False

    @property
    def completed(self):
        return self._completed

    # ─────────── 底层工具 ───────────

    def _send(self, pose, dur_ms=600):
        """安全发送一帧位置。"""
        safe = {}
        for sid, pos in pose.items():
            safe[str(sid)] = _safe(sid, pos)
        self.servo.set_positions(safe, dur_ms)
        time.sleep_ms(dur_ms + 80)

    def _smooth(self, keyframes, durations, steps=5):
        """平滑插值执行（借用 motion_sdk 或退化为逐帧）。"""
        if self.motion:
            # 暂不设置 _running，避免阻塞 balance_task
            prev = dict(self.motion.base_positions)
            for i in range(len(keyframes)):
                target = {}
                for sid, pos in keyframes[i].items():
                    target[int(sid)] = _safe(int(sid), pos)
                total_dur = max(100, int(durations[i]))
                step_dur = total_dur // steps
                for s in range(1, steps + 1):
                    t = s / steps
                    alpha = t * t * (3.0 - 2.0 * t)  # Smoothstep
                    interp = {}
                    for sid in target:
                        start = prev.get(sid, 2048)
                        val = int(start + (target[sid] - start) * alpha)
                        interp[str(sid)] = _safe(sid, val)
                    self.servo.set_positions(interp, step_dur)
                    time.sleep_ms(step_dur)
                prev = dict(target)
        else:
            for i, frame in enumerate(keyframes):
                dur = durations[i] if i < len(durations) else 600
                self._send(frame, dur)

    def _read_imu(self):
        """安全读取 IMU 姿态，返回 (pitch, roll)。"""
        try:
            self.imu.update()
            return float(self.imu.pitch), float(self.imu.roll)
        except Exception:
            return 0.0, 0.0

    # ─────────── 主流程 ───────────

    def execute(self):
        """执行完整从平躺到站立的起立流程。

        Returns:
            True  — 起立成功
            False — 起立失败（已安全卸力）
        """
        if self._completed:
            return True

        _log("===== 起立流程开始 =====")

        try:
            # ============================================================
            #  Phase 0: 舵机检测 + 上扭矩
            # ============================================================
            _log("Phase 0: 舵机检测 + 上扭矩")
            online = self.servo.scan()
            _log("在线舵机: {}/25  IDs={}".format(len(online), online))

            # 即使部分缺失也尝试起立（仅警告）
            if len(online) < 20:
                _log("WARNING: 在线舵机过少 ({}/25), 取消起立".format(len(online)))
                return False

            self.servo.torque_on()
            time.sleep_ms(500)

            # ============================================================
            #  Phase 1: 平躺 → 弯曲双腿（脚底贴地）
            # ============================================================
            _log("Phase 1: 弯曲双腿")

            # 1a: 先回到平躺直身姿态（确保已知起始状态）
            lie_pose = {i: 2048 for i in range(1, 26)}
            self._send(lie_pose, 1000)

            # 1b: 缓缓弯曲双腿，膝盖拱起，脚底贴地
            p1 = dict(lie_pose)
            p1[15] = 2500   # 左髋前屈（向胸部方向拉腿）
            p1[21] = 2500   # 右髋前屈
            p1[17] = 1450   # 左膝深弯
            p1[23] = 1450   # 右膝深弯
            p1[19] = 2350   # 左踝背屈（保持脚底平贴地面）
            p1[25] = 2350   # 右踝背屈
            self._smooth([p1], [1500], steps=6)

            # ============================================================
            #  Phase 2: 双手臂后撑身体，坐起
            # ============================================================
            _log("Phase 2: 双臂后撑，坐起")

            # 2a: 双臂向后伸展，准备撑地
            p2a = dict(p1)
            p2a[3] = 1350    # 左肩大幅后摆（手臂到身后）
            p2a[8] = 1350    # 右肩大幅后摆
            p2a[6] = 2100    # 左肘伸直准备撑地
            p2a[11] = 2100   # 右肘伸直
            p2a[4] = 2048    # 肩侧保持中立
            p2a[9] = 2048
            self._smooth([p2a], [1200], steps=5)

            # 2b: 手臂撑地发力 + 上半身抬起（腹肌 + 手臂协同）
            p2b = dict(p2a)
            p2b[15] = 2600   # 髋关节进一步前屈 → 上身坐起
            p2b[21] = 2600
            p2b[6] = 2300    # 肘部微屈发力推
            p2b[11] = 2300
            p2b[3] = 1450    # 肩内收一点
            p2b[8] = 1450
            self._smooth([p2b], [1800], steps=6)

            # ============================================================
            #  Phase 3: 身体前倾，重心转移到脚上方（蹲姿）
            # ============================================================
            _log("Phase 3: 前倾蹲姿，重心到脚上")

            # 3a: 上身前倾 + 手臂逐渐回收
            p3a = dict(p2b)
            p3a[15] = 2550   # 髋角调整
            p3a[21] = 2550
            p3a[17] = 1400   # 膝盖进一步弯曲
            p3a[23] = 1400
            p3a[19] = 2400   # 踝关节深背屈
            p3a[25] = 2400
            p3a[3] = 1800    # 手臂开始回到前方
            p3a[8] = 1800
            p3a[6] = 1900    # 肘部归位中
            p3a[11] = 1900
            self._smooth([p3a], [1400], steps=6)

            # 3b: 深蹲姿态 — 重心完全在脚上方，手臂前伸辅助平衡
            p3b = dict(p3a)
            p3b[15] = 2600   # 深蹲髋角
            p3b[21] = 2600
            p3b[17] = 1350   # 深蹲膝角
            p3b[23] = 1350
            p3b[19] = 2450   # 踝最大背屈
            p3b[25] = 2450
            p3b[3] = 2250    # 双臂前伸（配重 + 平衡）
            p3b[8] = 2250
            p3b[6] = 1800    # 肘微屈
            p3b[11] = 1800
            self._smooth([p3b], [1200], steps=5)

            # ============================================================
            #  Phase 4: 逐步蹬直双腿，站起来
            # ============================================================
            _log("Phase 4: 逐步站起")

            # 4a: 半站 — 膝盖仍微屈，重心稳定过渡
            p4a = {i: 2048 for i in range(1, 26)}
            p4a[15] = 2350   # 髋开始伸展
            p4a[21] = 2350
            p4a[17] = 1650   # 膝半伸
            p4a[23] = 1650
            p4a[19] = 2250   # 踝放松
            p4a[25] = 2250
            p4a[3] = 2150    # 手臂恢复中
            p4a[8] = 2150
            p4a[6] = 1800
            p4a[11] = 1800
            self._smooth([p4a], [1500], steps=6)

            # 4b: 接近直立 — 膝盖微屈保持弹性
            p4b = dict(p4a)
            p4b[15] = 2150
            p4b[21] = 2150
            p4b[17] = 1850
            p4b[23] = 1850
            p4b[19] = 2100
            p4b[25] = 2100
            p4b[3] = 2048
            p4b[8] = 2048
            self._smooth([p4b], [1200], steps=5)

            # 4c: 完全站直
            stand = dict(_STAND)
            self._smooth([stand], [1000], steps=5)

            # ============================================================
            #  Phase 5: IMU 微调平衡
            # ============================================================
            _log("Phase 5: IMU 平衡微调")

            # 给机械结构稳定的时间
            time.sleep_ms(500)

            for iteration in range(15):
                pitch, roll = self._read_imu()

                if abs(pitch) < 2.5 and abs(roll) < 2.5:
                    _log("平衡达标: pitch={:.1f} roll={:.1f}".format(pitch, roll))
                    break

                adjust = dict(stand)

                # 踝前后补偿 pitch（前倾→踝背屈推回）
                if abs(pitch) > 2.5:
                    comp_p = int(pitch * 10)
                    comp_p = _clamp(comp_p, -200, 200)
                    adjust[19] = _safe(19, 2048 + comp_p)
                    adjust[25] = _safe(25, 2048 + comp_p)
                    # 髋关节辅助（大幅倾斜时）
                    if abs(pitch) > 6.0:
                        hip_c = int(pitch * 5)
                        hip_c = _clamp(hip_c, -120, 120)
                        adjust[15] = _safe(15, 2048 + hip_c)
                        adjust[21] = _safe(21, 2048 + hip_c)

                # 踝左右补偿 roll
                if abs(roll) > 2.5:
                    comp_r = int(roll * 8)
                    comp_r = _clamp(comp_r, -160, 160)
                    adjust[18] = _safe(18, 2048 + comp_r)
                    adjust[24] = _safe(24, 2048 + comp_r)

                self._send(adjust, 250)
                _log("调整中[{}]: pitch={:.1f} roll={:.1f}".format(iteration, pitch, roll))
                time.sleep_ms(400)

            # ============================================================
            #  完成：设置运动 SDK 基准姿态，启用平衡控制
            # ============================================================
            if self.motion:
                self.motion.base_positions = dict(_STAND)
            if self.balance:
                self.balance.reset_base_pose()
                self.balance.enabled = True

            self._completed = True
            _log("===== 起立完成！=====")
            return True

        except Exception as e:
            _log("起立失败: {}".format(e))
            # 安全措施：卸力防止损坏
            try:
                self.servo.torque_off([254])
            except Exception:
                pass
            return False
