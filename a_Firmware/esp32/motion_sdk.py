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

    # TODO: 扩充其他动作: 行走、后退、左右转身、叉腰、弯腰、摇头、点头、扎马步、单腿站立、倒立、单手倒立、小步跑、挥手、拒绝、坐下、思考、比爱心、金鸡站立、爬行、坐凳子、上楼梯等
