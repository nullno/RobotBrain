'''
> MicroPython SDK读取位置指令 Example <
-------------------------------------------------
 * 更新时间: 2025/8/27
-------------------------------------------------
'''
from machine import UART
from uservo import UartServoManager
import time

# 舵机个数
# 注：舵机ID编号 假定是依次递增的
# 例: [0, 1, 2, ..., srv_num-1]
servo_num = 1
# 舵机ID
servo_id = 1

# 创建串口对象 使用串口2作为控制对象
# 波特率: 115200
# RX: gpio 48
# TX: gpio 47
uart = UART(2, baudrate=115200)
# 创建舵机管理器
uservo = UartServoManager(uart, srv_num=servo_num)

# 舵机位置读取
while True:
    position = uservo.read_servo_position(1)
    print("当前舵机位置: {:d}".format(int(position)), end='\r')
    time.sleep(1)

