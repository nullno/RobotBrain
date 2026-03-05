import time
import math
from YbImuSerialLib import YbImuSerial
import vpython as vp

# ==========================================
# 1. 初始化 IMU 串口通信
# ==========================================
PORT = "COM8"
BAUDRATE = 115200

print(f"尝试连接 IMU，端口: {PORT}")
bot = YbImuSerial(PORT, debug=False)
bot.create_receive_threading()

# 等待串口初始化并获取初始数据
time.sleep(1)

# ==========================================
# 2. 构建 VPython 3D 场景与人形机器人模型
# ==========================================
vp.scene.title = "IMU 实时 3D 姿态可视化"
vp.scene.width = 800
vp.scene.height = 600
vp.scene.background = vp.vector(0.8, 0.8, 0.8)

# 定义机器人各个身体部件
# 坐标系说明 (vpython): x向右, y向上, z向屏幕外
torso = vp.box(pos=vp.vector(0, 0, 0), size=vp.vector(2, 3, 1), color=vp.color.blue)
head = vp.box(pos=vp.vector(0, 2.0, 0), size=vp.vector(1, 1, 1), color=vp.color.orange)
arm_l = vp.box(pos=vp.vector(-1.5, 0.5, 0), size=vp.vector(0.5, 2.5, 0.5), color=vp.color.red)
arm_r = vp.box(pos=vp.vector(1.5, 0.5, 0), size=vp.vector(0.5, 2.5, 0.5), color=vp.color.red)
leg_l = vp.box(pos=vp.vector(-0.5, -2.5, 0), size=vp.vector(0.6, 2.5, 0.6), color=vp.color.green)
leg_r = vp.box(pos=vp.vector(0.5, -2.5, 0), size=vp.vector(0.6, 2.5, 0.6), color=vp.color.green)

# 将部件组合为一个整体 compound，方便整体旋转
robot = vp.compound([torso, head, arm_l, arm_r, leg_l, leg_r])

# 添加地面参考
ground = vp.box(pos=vp.vector(0, -5, 0), size=vp.vector(10, 0.1, 10), color=vp.color.white, opacity=0.5)
# 添加坐标轴提示
vp.arrow(pos=vp.vector(0,-4.5,0), axis=vp.vector(2,0,0), color=vp.color.red, shaftwidth=0.1)    # X轴
vp.arrow(pos=vp.vector(0,-4.5,0), axis=vp.vector(0,2,0), color=vp.color.green, shaftwidth=0.1)  # Y轴
vp.arrow(pos=vp.vector(0,-4.5,0), axis=vp.vector(0,0,2), color=vp.color.blue, shaftwidth=0.1)   # Z轴

# ==========================================
# 3. 主循环：实时读取 IMU 数据并更新 3D 姿态
# ==========================================
print("开始实时可视化，请在弹出的浏览器窗口中查看。(如无响应请检查 COM8 是否被占用)")

def ypr_to_vpython(roll_deg, pitch_deg, yaw_deg):
    """
    转换欧拉角并赋予3D模型
    (根据实际IMU的安装方向可能需要改变翻转轴或正负号)
    """
    roll = math.radians(roll_deg)
    pitch = math.radians(pitch_deg)
    yaw = math.radians(yaw_deg)
    
    # 每次重置向上的方向，以防累积误差变换
    robot.axis = vp.vector(0, 1, 0)
    robot.up = vp.vector(0, 0, -1)
    
    # 依次施加旋转 (具体旋转方向可能需要根据所用IMU自身的XYZ进行测试微调)
    robot.rotate(angle=-yaw, axis=vp.vector(0, 1, 0))   # 偏航 (Y轴)
    robot.rotate(angle=pitch, axis=vp.vector(1, 0, 0))  # 俯仰 (X轴)
    robot.rotate(angle=roll, axis=vp.vector(0, 0, 1))   # 滚转 (Z轴)

try:
    while True:
        vp.rate(60) # 限制刷新率为 60 fps
        
        # 获取欧拉角姿态 (返回 [roll, pitch, yaw], 单位: 角度)
        euler = bot.get_imu_attitude_data(ToAngle=True)
        
        if euler:
            r, p, y = euler[0], euler[1], euler[2]
            ypr_to_vpython(r, p, y)
            
except KeyboardInterrupt:
    print("\n程序结束。")
