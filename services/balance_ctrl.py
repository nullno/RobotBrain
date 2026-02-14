class BalanceController:
    """
    集成了 UVC (Upper body Vertical Control) 的平衡算法
    """
    def __init__(self, neutral_positions: dict, is_landscape=True):
        # neutral_positions 存储 1-25 号舵机的中位值 (通常为 2048)
        # 为避免缺失键导致 compute() 中 KeyError，这里统一补齐 1-25
        base = {sid: 2048 for sid in range(1, 26)}
        try:
            for sid, pos in (neutral_positions or {}).items():
                base[int(sid)] = int(pos)
        except Exception:
            pass
        self.neutral = base
        self.is_landscape = is_landscape  # 是否横屏
        
        # --- UVC 补偿增益系数 (需根据实机调试) ---
        # 增幅提高~2x或更高以改善行走时的平衡反应速度
        # 横屏时，手机重力投影改变，每个轴提高系数
        if self.is_landscape:
            self.gain_p = 5.5   # Pitch 增益（前后平衡）
            self.gain_r = 4.2   # Roll 增益（左右平衡）
        else:
            self.gain_p = 5.0
            self.gain_r = 3.8

    def compute(self, pitch, roll, yaw):
        """
        输入: 陀螺仪实时角度 (度)
        输出: 25路舵机目标位置数据包
        """
        targets = self.neutral.copy()

        # 1. 【平衡核心】左腿 (ID 14-19) 与 右腿 (ID 20-25) 
        # 假设你的腿部舵机定义顺序如下（需根据实际安装调整正负号）：
        # ID 14/20: 胯部旋转 | 15/21: 大腿弯曲 | 16/22: 大腿旋转 
        # ID 17/23: 腿腕弯曲 | 18/24: 脚腕左右 | 19/25: 脚腕前后

        # 前后平衡 (Pitch) 补偿
        p_offset = int(pitch * self.gain_p)
        for sid in [15, 21]: # 大腿弯曲
            targets[sid] += p_offset
        for sid in [17, 23]: # 腿腕弯曲
            targets[sid] -= p_offset * 1.5 # 膝盖通常需要更大的补偿
        for sid in [19, 25]: # 脚腕前后
            targets[sid] += p_offset * 0.5

        # 左右平衡 (Roll) 补偿
        r_offset = int(roll * self.gain_r)
        for sid in [18, 24]: # 脚腕左右摆动
            targets[sid] += r_offset

        # 2. 【上肢协同】
        # 腰部 (ID 13) 旋转补偿
        targets[13] += int(yaw * 0.5)

        # 颈部 (ID 1, 2) 头部防抖及平衡一优先 (为了更好地与机器人姿态一致)
        # 如果注意到机器人倒或会影响体态，请于想比鲜明嗎呢墨印例们下命令一堁准不准
        head_pitch_scale = 1.5  # 头部俯仰的缩放，是预想已略到的，并不是平衡二控作的了葆汗巨
        targets[1] -= int(yaw * 1.5)    # 颈部左右反向对冲旋转
        targets[2] -= int(pitch * head_pitch_scale)  # 颈部上下反向对冲（预平衡姿态）

        # 3. 【手臂自然摆动】
        # 左/右手 (ID 3-7, 8-12) 
        # 走路时或倾斜时，手臂可以微动来辅助视觉平衡
        arm_swing = int(pitch * 0.8)
        targets[3] += arm_swing  # 左肩前后
        targets[8] -= arm_swing  # 右肩前后

        # 限制范围在 SDK 要求内 (0-4095)
        for sid in targets:
            targets[sid] = max(0, min(4095, targets[sid]))
            
        return targets

    # ------------------ 实时控制循环 ------------------
    def start_loop(self, servo_manager, imu_reader, period=0.05):
        """启动控制循环：定期读取 IMU，计算舵机目标并发送同步位置指令

        servo_manager: UartServoManager 实例
        imu_reader: IMUReader 或其他实现 get_orientation() 的对象
        period: 控制周期（秒）
        """
        if hasattr(self, '_loop_running') and self._loop_running:
            return
        import threading, time
        self._loop_running = True
        
        # 用于限制日志输出频率
        log_counter = [0]

        def _loop():
            while self._loop_running:
                try:
                    pitch, roll, yaw = imu_reader.get_orientation()
                    targets = self.compute(pitch, roll, yaw)

                    # 只向已知舵机发送指令
                    servo_ids = []
                    pos_list = []
                    for sid, pos in targets.items():
                        if sid in servo_manager.servo_info_dict:
                            servo_ids.append(sid)
                            pos_list.append(int(pos))

                    if servo_ids:
                        runtime_ms = max(30, int(period * 1000))
                        servo_manager.sync_set_position(servo_ids, pos_list, [runtime_ms] * len(servo_ids))
                        
                        # 每隔 10 次循环打印一次日志（约 0.5 秒一次）
                        log_counter[0] += 1
                        if log_counter[0] % 10 == 0:
                            try:
                                from widgets.runtime_status import RuntimeStatusLogger
                                imu_info = f"IMU: P={pitch:.1f}° R={roll:.1f}° Y={yaw:.1f}°"
                                servo_info = f"舵机数: {len(servo_ids)} IDs: {servo_ids[:5]}..."
                                RuntimeStatusLogger.log_info(imu_info)
                            except:
                                pass
                except Exception:
                    pass
                time.sleep(period)

        self._loop_thread = threading.Thread(target=_loop, daemon=True)
        self._loop_thread.start()

    def stop_loop(self):
        if hasattr(self, '_loop_running') and self._loop_running:
            self._loop_running = False
            try:
                self._loop_thread.join(timeout=0.5)
            except Exception:
                pass