'''
JOHO舵机
--控制舵机扭矩开关
'''
# 添加uservo.py的系统路径
from cgitb import enable
from os import system
from pickle import TRUE
import sys
from turtle import delay
sys.path.append("../../src")

import time
import serial
import struct
import sys
from uart_servo import UartServoManager
from data_table import *
# 参数配置
# SERVO_PORT_NAME =  '/dev/ttyUSB0' 	# 舵机串口号
SERVO_PORT_NAME =  'COM3' 	# win舵机串口号
SERVO_BAUDRATE = 115200 	# 舵机的波特率
SERVO_ID_1 = 1 				# 舵机ID 1
SERVO_ID_2 = 2				       # 舵机ID 2
# 初始化串口
uart = serial.Serial(port=SERVO_PORT_NAME, baudrate=SERVO_BAUDRATE,\
					 parity=serial.PARITY_NONE, stopbits=1,\
					 bytesize=8,timeout=0)
# 创建舵机对象
uservo = UartServoManager(uart)
# #servo_id_list,用于检测列表上的舵机是否在线
# servo_id_list=[1,2,3]
# uservo = UartServoManager(uart,servo_id_list)
position = 0
runtime_ms = 500
uservo.set_position_time(SERVO_ID_1, 2048, runtime_ms)
time.sleep(0.01)
uservo.set_position_time(SERVO_ID_2, 2048, runtime_ms)
time.sleep(0.8)

#start
while(1):

    # 读取ID1位置
    position1 = uservo.read_data_by_name(SERVO_ID_1, "CURRENT_POSITION")
    time.sleep(0.01)
    if position1 is not None:
        print(f"循环开始，舵机:{SERVO_ID_1} 当前位置:  {position1}")
    time.sleep(0.01)

    #执行位置控制
    print(f"舵机:{SERVO_ID_1} 控制其位置到2048")
    uservo.set_position_time(SERVO_ID_1, 2048, runtime_ms)
    time.sleep(3)
    

    position1 = uservo.read_data_by_name(SERVO_ID_1, "CURRENT_POSITION")
    if position1 is not None:
        print(f"舵机:{SERVO_ID_1}掰动前位置:  {position1}")

    #扭矩关
    uservo.torque_enable(SERVO_ID_1,TORQUE_DISABLE)
    print(f"请掰动舵机:{SERVO_ID_1},剩10秒")
    time.sleep(5)
    print(f"请掰动舵机:{SERVO_ID_1},剩5秒")
    time.sleep(5)
    #扭矩开
    uservo.torque_enable(SERVO_ID_1,TORQUE_ENABLE)
    # 读取ID1位置
    position1 = uservo.read_data_by_name(SERVO_ID_1, "CURRENT_POSITION")
    if position1 is not None:
        print(f"舵机:{SERVO_ID_1}掰动结束， 当前位置:  {position1}")

    time.sleep(5)
