'''
JOHO串口总线舵机 DC模式示例
--------------------------------------------------
- 作者: 阿凯爱玩机器人@成都深感机器人
- Email: xingshunkai@qq.com
- 更新时间: 2021-12-19
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
SERVO_ID = 1 				# 舵机ID 
# 初始化串口
uart = serial.Serial(port=SERVO_PORT_NAME, baudrate=SERVO_BAUDRATE,\
					 parity=serial.PARITY_NONE, stopbits=1,\
					 bytesize=8,timeout=0)
# 创建舵机对象
uservo = UartServoManager(uart, servo_id_list=[SERVO_ID])
# 设置为DC模式
uservo.set_motor_mode(SERVO_ID, MOTOR_MODE_DC)
# 开始旋转
direction = DC_DIR_CW # 顺时针
# direction = DC_DIR_CCW # 逆时针
pwm = 50 # 转速
uservo.dc_rotate(SERVO_ID, direction, pwm)
# 延时5s
time.sleep(5)
# 电机停止转动
uservo.dc_stop(SERVO_ID)