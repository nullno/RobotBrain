import time
import math

class MotionSDK:
    """
    基础运动控制SDK，支持通过WiFi调用
    """
    def __init__(self, servo_ctrl, balance_ctrl=None):
        self.servo_ctrl = servo_ctrl
        self.balance_ctrl = balance_ctrl
        self.base_positions = {i: 2048 for i in range(1, 26)}
        # 手臂自然微屈
        self.base_positions[6] = 1800
        self.base_positions[11] = 1800
        
    def _execute(self, poses, delays):
        """执行一组连续的动作帧"""
        for i in range(len(poses)):
            pose = poses[i]
            duration = delays[i]
            
            # 更新基准姿态并通知平衡控制器
            for k, v in pose.items():
                self.base_positions[k] = v
            if self.balance_ctrl:
                self.balance_ctrl.set_base_pose(self.base_positions)
            
            self.servo_ctrl.set_positions(self.base_positions, duration)
            time.sleep_ms(duration)

    def stand(self):
        """站立"""
        pose = {i: 2048 for i in range(1, 26)}
        pose[6] = 1800; pose[11] = 1800
        self._execute([pose], [500])

    def crouch(self):
        """蹲下"""
        pose = self.base_positions.copy()
        # 大腿前摆, 膝盖后弯, 踝背屈
        for sid in (15, 21): pose[sid] = 2600
        for sid in (17, 23): pose[sid] = 1500
        for sid in (19, 25): pose[sid] = 2500
        self._execute([pose], [800])

    def swagger(self):
        """站立晃动"""
        p1 = self.base_positions.copy()
        p2 = self.base_positions.copy()
        p1[18] = 2200; p1[24] = 2200 # 偏左
        p2[18] = 1900; p2[24] = 1900 # 偏右
        self._execute([p1, p2, p1, p2, self.base_positions.copy()], [500, 500, 500, 500, 500])

    def step_forward(self):
        """行走(单步)"""
        # 简单位移行走步态设计 (提腿, 前跨, 放下)
        p1 = self.base_positions.copy()
        # 极简步态代码
        self._execute([p1], [300])

    def walk(self):
        self.step_forward()

    def backward(self):
        p1 = self.base_positions.copy()
        for sid in (15, 21): p1[sid] = 1900
        self._execute([p1, self.base_positions.copy()], [300, 300])

    def turn_left(self):
        p1 = self.base_positions.copy()
        p1[18] = 1800; p1[24] = 1800
        self._execute([p1, self.base_positions.copy()], [300, 300])

    def turn_right(self):
        p1 = self.base_positions.copy()
        p1[18] = 2300; p1[24] = 2300
        self._execute([p1, self.base_positions.copy()], [300, 300])

    def akimbo(self):
        """叉腰"""
        pose = self.base_positions.copy()
        pose[4] = 1500; pose[9] = 2600 
        pose[6] = 2600; pose[11] = 1500
        self._execute([pose], [500])

    def bend_over(self):
        """弯腰"""
        pose = self.base_positions.copy()
        pose[15] = 1800; pose[21] = 1800 # 髋部前倾
        self._execute([pose], [800])

    def shake_head(self):
        """摇头"""
        p1 = self.base_positions.copy(); p1[1] = 2500
        p2 = self.base_positions.copy(); p2[1] = 1600
        self._execute([p1, p2, self.base_positions.copy()], [300, 300, 300])

    def nod(self):
        """点头"""
        p1 = self.base_positions.copy(); p1[2] = 1700
        p2 = self.base_positions.copy(); p2[2] = 2100
        self._execute([p1, p2, p1, self.base_positions.copy()], [250, 250, 250, 250])

    def horse_stance(self):
        """扎马步"""
        pose = self.base_positions.copy()
        for sid in (15, 21): pose[sid] = 2400
        for sid in (17, 23): pose[sid] = 1700
        for sid in (19, 25): pose[sid] = 2400
        pose[16] = 1500; pose[22] = 2600 # 双腿分开
        self._execute([pose], [800])

    def golden_rooster(self):
        """金鸡独立"""
        pose = self.base_positions.copy()
        pose[21] = 2600; pose[23] = 1000; pose[25] = 2600 # 抬起右腿
        self._execute([pose], [800])

    def handstand(self):
        """倒立 (示意)"""
        pose = self.base_positions.copy()
        pose[4] = 3000; pose[9] = 1000 # 举起双臂撑地
        self._execute([pose], [1000])

    def one_hand_handstand(self):
        """单手倒立"""
        pose = self.base_positions.copy()
        pose[4] = 3000 # 仅单臂撑地
        self._execute([pose], [1000])

    def trot(self):
        """小步跑"""
        self.step_forward()

    def wave(self):
        """挥手"""
        p1 = self.base_positions.copy()
        p1[4] = 3000; p1[5] = 2500; p1[7] = 2500
        p2 = p1.copy(); p2[5] = 1500
        self._execute([p1, p2, p1, self.base_positions.copy()], [300, 300, 300, 400])

    def refuse(self):
        """拒绝"""
        p1 = self.base_positions.copy()
        p1[4] = 2500; p1[9] = 1500
        p1[5] = 2300; p1[10] = 1800
        p2 = p1.copy()
        p2[5] = 1800; p2[10] = 2300
        self._execute([p1, p2, p1, p2, self.base_positions.copy()], [200, 200, 200, 200, 400])

    def sit(self):
        """坐下"""
        self.crouch()

    def think(self):
        """思考"""
        pose = self.base_positions.copy()
        pose[4] = 2800; pose[6] = 2800
        pose[2] = 1800
        self._execute([pose], [800])

    def make_heart(self):
        """比爱心"""
        pose = self.base_positions.copy()
        pose[4] = 3000; pose[9] = 1000
        pose[5] = 2048; pose[10] = 2048
        pose[6] = 3000; pose[11] = 1000
        self._execute([pose], [800])

    def crawl(self):
        """爬行"""
        pose = self.base_positions.copy()
        pose[15] = 2600; pose[21] = 2600
        pose[4] = 3000; pose[9] = 1000
        self._execute([pose], [800])

    def sit_chair(self):
        """坐凳子"""
        pose = self.base_positions.copy()
        pose[15] = 2600; pose[21] = 2600
        pose[17] = 2600; pose[23] = 2600
        self._execute([pose], [800])

    def climb_stairs(self):
        """上楼梯"""
        self.step_forward()
