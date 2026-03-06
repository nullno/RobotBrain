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
# 坐标系：X左右(肩膀)，Y前后(胸部正对+Y)，Z上下(垂直站立)
torso = vp.box(pos=vp.vector(0, 0, 0.5), size=vp.vector(2, 1, 3), color=vp.color.blue)
head = vp.box(pos=vp.vector(0, 0, 2.5), size=vp.vector(1, 1, 1), color=vp.color.orange)

# 添加面部特征以清楚标示"正面" (朝向 +Y 轴)
nose = vp.box(pos=vp.vector(0, 0.6, 2.5), size=vp.vector(0.2, 0.4, 0.4), color=vp.color.cyan)
eye_l = vp.sphere(pos=vp.vector(-0.3, 0.55, 2.7), radius=0.1, color=vp.color.white)
eye_r = vp.sphere(pos=vp.vector(0.3, 0.55, 2.7), radius=0.1, color=vp.color.white)

arm_l = vp.box(pos=vp.vector(-1.5, 0, 1.0), size=vp.vector(0.5, 0.5, 2.5), color=vp.color.red)
arm_r = vp.box(pos=vp.vector(1.5, 0, 1.0), size=vp.vector(0.5, 0.5, 2.5), color=vp.color.red)
leg_l = vp.box(pos=vp.vector(-0.5, 0, -2.0), size=vp.vector(0.6, 0.6, 2.5), color=vp.color.green)
leg_r = vp.box(pos=vp.vector(0.5, 0, -2.0), size=vp.vector(0.6, 0.6, 2.5), color=vp.color.green)

# 将部件组合为一个整体 compound，由初始创建时的坐标来决定原始方向
robot = vp.compound([torso, head, nose, eye_l, eye_r, arm_l, arm_r, leg_l, leg_r])

# 重新建立场景视角，让Z轴朝上
vp.scene.up = vp.vector(0, 0, 1)
# 相机指向设定：从 +Y 看向 -Y（让 +Y 正对屏幕外部），稍微向下倾斜一点看
vp.scene.forward = vp.vector(0, -1, -0.2)

# 添加地面参考
ground = vp.box(pos=vp.vector(0, 0, -3.5), size=vp.vector(10, 10, 0.1), color=vp.color.white, opacity=0.5)

# 添加坐标轴提示 和 文字标注
vp.arrow(pos=vp.vector(0, 0, -3.0), axis=vp.vector(3,0,0), color=vp.color.red, shaftwidth=0.1)    # X轴 (右)
vp.text(text='X (Right)', pos=vp.vector(3.2, 0, -3.0), align='center', height=0.4, color=vp.color.red, billboard=True)

vp.arrow(pos=vp.vector(0, 0, -3.0), axis=vp.vector(0,3,0), color=vp.color.green, shaftwidth=0.1)  # Y轴 (前)
vp.text(text='Y (Front)', pos=vp.vector(0, 3.2, -3.0), align='center', height=0.4, color=vp.color.green, billboard=True)

vp.arrow(pos=vp.vector(0, 0, -3.0), axis=vp.vector(0,0,3), color=vp.color.blue, shaftwidth=0.1)   # Z轴 (上)
vp.text(text='Z (Up)', pos=vp.vector(0, 0, 0.2), align='center', height=0.4, color=vp.color.blue, billboard=True)

# ==========================================
# 3. 主循环：实时读取 IMU 数据并更新 3D 姿态
# ==========================================
print("开始实时可视化，请在弹出的浏览器窗口中查看。(如无响应请检查 COM8 是否被占用)")

def ypr_to_vpython(roll_deg, pitch_deg, yaw_deg):
    """
    转换欧拉角并赋予3D模型
    """
    roll = math.radians(roll_deg)
    pitch = math.radians(pitch_deg)
    yaw = math.radians(yaw_deg)
    
    # 恢复 Vpython compound 的初始姿态
    # 默认建立模型时，axis 为 (1, 0, 0)， up 为 (0, 1, 0)
    robot.axis = vp.vector(1, 0, 0)
    robot.up = vp.vector(0, 1, 0)
    
    # 此时机器人：
    # X轴为机器人的左右（宽） - 对应 IMU 的 X 轴
    # Y轴为机器人的前后（厚） - 对应 IMU 的 Y 轴方向 (假设Y正是车头)
    # Z轴为机器人的上下（高） - 对应 IMU 的 Z 轴
    
    # 依次施加旋转（如果转动方向反了，可以把 angle=xxx 改为 angle=-xxx）
    # Yaw (偏航): 绕Z轴旋转
    robot.rotate(angle=yaw, axis=vp.vector(0, 0, 1))
    
    # Pitch (俯仰): 绕X轴旋转
    robot.rotate(angle=-pitch, axis=vp.vector(1, 0, 0))
    
    # Roll (滚转): 绕Y轴旋转
    robot.rotate(angle=roll, axis=vp.vector(0, 1, 0))

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
