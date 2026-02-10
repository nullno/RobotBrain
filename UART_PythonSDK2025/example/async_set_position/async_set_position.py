'''
JOHO串口总线舵机 - 异步写
--------------------------------------------------
- 适用于多个舵机不同时间配置位置，配置好后统一发送指令执行
- 更新时间: 2024-04-27
--------------------------------------------------
'''

# 添加uservo.py的系统路径
import sys
sys.path.append("../../src")

import time
import serial
import struct
import sys
from uart_servo import UartServoManager
from data_table import *
# 参数配置
SERVO_PORT_NAME =  'COM3' 	# 舵机串口号
SERVO_BAUDRATE = 115200 	# 舵机的波特率
SERVO_ID_1 = 1 				# 舵机ID
SERVO_ID_2 = 2 				# 舵机ID  
# 初始化串口
uart = serial.Serial(port=SERVO_PORT_NAME, baudrate=SERVO_BAUDRATE,\
					 parity=serial.PARITY_NONE, stopbits=1,\
					 bytesize=8,timeout=0)
# 创建舵机对象
uservo = UartServoManager(uart, servo_id_list=[SERVO_ID_1,SERVO_ID_2])

# 上电确认能运行
uservo.set_position_time(SERVO_ID_1, 2048, 1000)
time.sleep(0.01)
uservo.set_position_time(SERVO_ID_2, 2048, 1000)
time.sleep(1)

position = 3095
runtime_ms = 500
uservo.async_set_position(SERVO_ID_1, position, runtime_ms)

time.sleep(0.01)
# 这里写其他舵机的 async_set_position, 举例子：
uservo.async_set_position(SERVO_ID_2, position, runtime_ms)
time.sleep(0.01)
# 统一开始执行
uservo.async_action()

# 等待所有舵机执行完成动作
uservo.wait_all()
