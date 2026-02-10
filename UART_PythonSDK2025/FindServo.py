'''
JOHO发现程序，执行本程序时，仅支持单舵机连接；同时连接多个舵机会引发通信冲突
'''
# 添加uservo.py的系统路径
from os import system
import sys
from turtle import delay
sys.path.append("./src")

import time
import serial
import struct
import sys
from uart_servo import UartServoManager
from data_table import *
# 参数配置
SERVO_PORT_NAME =  '/dev/ttyUSB0' 	# 舵机串口号
SERVO_BAUDRATE = 115200 	# 舵机的波特率
SERVO_ID =  1 				# 舵机ID选择254，PING所有舵机都会回复本机ID
# 初始化串口
uart = serial.Serial(port=SERVO_PORT_NAME, baudrate=SERVO_BAUDRATE,\
					 parity=serial.PARITY_NONE, stopbits=1,\
					 bytesize=8,timeout=0)
# 创建舵机对象
uservo = UartServoManager(uart)
stat = uservo.ping(SERVO_ID)
if(stat):
	print(f"舵机{SERVO_ID}在线")
else:
	print(f"舵机{SERVO_ID}无响应，请重试")


#搜索舵机,不知道舵机ID时
time.sleep(0.2)
fstat,sevid = uservo.find_servo()
time.sleep(1)
if(fstat):
	print(f"舵机{sevid}被发现")
else:
	print(f"无舵机响应，请重试")

