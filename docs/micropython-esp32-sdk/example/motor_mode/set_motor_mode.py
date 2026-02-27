'''
> MicroPython SDK电机控制指令 Example <
-------------------------------------------------
 * 更新时间: 2025/8/27
-------------------------------------------------
'''

from machine import UART
from uservo import UartServoManager
import time

# 舵机个数
# 舵机ID编号: [0, 1, 2, ..., srv_num-1]
servo_num = 2
# 舵机ID
servo_id = 1

# 创建串口对象 使用串口2作为控制对象
# 波特率: 115200
# RX: gpio 16
# TX: gpio 17
uart = UART(2, baudrate=115200)
# 创建舵机管理器
uservo = UartServoManager(uart, srv_num=servo_num)

#注意：
# 使用后想用舵机模式需要切换回舵机模式！！！！

# 舵机当电机旋转需要设置为电机模式，再发送速度控制旋转
print("设置舵机为电机模式")
uservo.set_servo_mode(servo_id,00) # 设置为电机模式
time.sleep(0.1)
#正转5s
uservo.set_motor_direction(servo_id,1)# 设置为正向
time.sleep(0.1)
uservo.set_motor_speed(servo_id,100) # 设置电机运行速度 0~100
time.sleep(5)                       #运行5s
uservo.set_motor_speed(servo_id,0) # 设置电机运行速度0，停止
time.sleep(1)
#反转5s
uservo.set_motor_direction(servo_id,0)# 设置为反向
time.sleep(0.1)
uservo.set_motor_speed(servo_id,100) # 设置电机运行速度 0~100
time.sleep(5)                       #运行5s
uservo.set_motor_speed(servo_id,0) # 设置电机运行速度0，停止
time.sleep(1)