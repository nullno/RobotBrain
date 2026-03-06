'''
JOHO串口总线舵机 设置位置
--------------------------------------------------
- 作者: 阿凯爱玩机器人@成都深感机器人
- Email: xingshunkai@qq.com
- 更新时间: 2022-05-11 by JOHO
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
SERVO_PORT_NAME =  '/dev/ttyUSB0' 	# 舵机串口号
SERVO_BAUDRATE = 115200 	# 舵机的波特率
SERVO_ID = 1 				# 舵机ID 
# 初始化串口
uart = serial.Serial(port=SERVO_PORT_NAME, baudrate=SERVO_BAUDRATE,\
					 parity=serial.PARITY_NONE, stopbits=1,\
					 bytesize=8,timeout=0)
# 创建舵机对象
uservo = UartServoManager(uart, servo_id_list=[SERVO_ID])

# 在两点之间往复运动
for i in range(3):
    uservo.set_position_time(SERVO_ID, 500, 1000)
    time.sleep(2)
    uservo.set_position_time(SERVO_ID, 3500, 1000)
    time.sleep(2)
