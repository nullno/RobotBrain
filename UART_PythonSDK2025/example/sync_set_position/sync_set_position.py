'''
JOHO串口总线舵机 位置命令同步执行
--------------------------------------------------
- 功能说明：多个舵机命令合并一条指令发送
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
#SERVO_PORT_NAME =  '/dev/ttyUSB0' 	# LINUX串口号
SERVO_PORT_NAME =  'COM3' 	# WIN 舵机串口号
SERVO_BAUDRATE = 115200 	# 舵机的波特率
#配置舵机ID
SERVO_ID_1 = 1 				# 舵机ID 1
SERVO_ID_2 = 2				# 舵机ID 2
SERVO_ID_3 = 3				# 舵机ID 3
# 初始化串口
uart = serial.Serial(port=SERVO_PORT_NAME, baudrate=SERVO_BAUDRATE,\
					 parity=serial.PARITY_NONE, stopbits=1,\
					 bytesize=8,timeout=0)
# 创建舵机对象
uservo = UartServoManager(uart, servo_id_list=[SERVO_ID_1,SERVO_ID_2,SERVO_ID_3])

# 上电确认能运行
uservo.set_position_time(SERVO_ID_1, 2048, 1000)
time.sleep(0.01)
uservo.set_position_time(SERVO_ID_2, 2048, 1000)
time.sleep(1)


# 同步写位置
servo_id_list = [SERVO_ID_1,SERVO_ID_2,SERVO_ID_3]
position_list = [1000, 1024, 1024]
runtime_ms_list = [1000, 1000, 1000]
uservo.sync_set_position(servo_id_list, position_list, runtime_ms_list)
# 等待所有舵机执行完成动作
uservo.wait_all()