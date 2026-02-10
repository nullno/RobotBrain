#!/usr/bin/env python3
"""
test_servo_basic.py

基础舵机读写与扭矩控制的示例脚本。
"""
import os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from services.uart_servo import UartServoManager
import serial


def main():
    port = input('Serial port (e.g. COM3) [COM3]: ') or 'COM3'
    baud = int(input('Baudrate [115200]: ') or 115200)
    sid = int(input('Servo ID to test [1]: ') or 1)
    try:
        uart = serial.Serial(port, baud, timeout=0.02)
    except Exception as e:
        print('打开串口失败:', e)
        return
    us = UartServoManager(uart, servo_id_list=[sid])

    print('读取当前位置...')
    pos = us.read_data_by_name(sid, 'CURRENT_POSITION')
    print('CURRENT_POSITION =', pos)
    print('读取温度/电压/速度...')
    print('TEMP =', us.get_temperature(sid))
    print('VOLTAGE =', us.get_voltage(sid))
    print('VELOCITY =', us.get_velocity(sid))

    ans = input('是否启用扭矩?(y/n) [y]: ') or 'y'
    us.torque_enable(sid, 1 if ans.lower()=='y' else 0)
    print('设置目标到 2048 (中心)')
    us.set_position_time(sid, 2048, 800)
    time.sleep(1)
    print('完成')

if __name__=='__main__':
    main()
