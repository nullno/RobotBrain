'''
> MicroPython SDK设置位置指令 Example <
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
# RX: gpio 48
# TX: gpio 47
uart = UART(2, baudrate=115200, tx=47, rx=48)
# 创建舵机管理器
uservo = UartServoManager(uart, srv_num=servo_num)

uservo.set_servo_mode(servo_id,1)# 设置舵机模式,若舵机本身为舵机模式无需再次设置
time.sleep(1)

#位置04096阶段对应-180度180度
print("设置舵机位置为0")
uservo.set_servo_position(servo_id, 0, 200) # 设置舵机位置
time.sleep(1)
print("设置舵机位置为2048")
uservo.set_servo_position(servo_id, 1000, 200) # 设置舵机位置
time.sleep(1)

