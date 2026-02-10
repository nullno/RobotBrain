#!/usr/bin/env python3
"""
test_motion.py

简单演示如何使用 `services/motion_controller.MotionController` 与本地舵机 SDK。
运行前请先打开电源并确保串口正确连接。
"""
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from services.uart_servo import UartServoManager
from services.imu import IMUReader
from services.balance_ctrl import BalanceController
from services.motion_controller import MotionController
import serial


def parse_id_list(s):
    s = s.strip()
    if not s:
        return list(range(1, 26))
    if '-' in s and ',' not in s:
        a,b = s.split('-',1)
        return list(range(int(a), int(b)+1))
    out = []
    for part in s.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a,b = part.split('-',1)
            out += list(range(int(a), int(b)+1))
        else:
            out.append(int(part))
    return out


def main():
    port = input('Serial port (e.g. COM3 or /dev/ttyUSB0) [COM3]: ') or 'COM3'
    baud = int(input('Baudrate [115200]: ') or 115200)
    ids = input('Servo IDs (e.g. 1-25 or 1,2,3) [1-25]: ') or '1-25'
    servo_ids = parse_id_list(ids)

    print('Opening serial...', port, baud)
    uart = serial.Serial(port, baud, timeout=0.02)
    servo_mgr = UartServoManager(uart, servo_id_list=servo_ids)

    # neutral positions (default mid-point)
    neutral = {i:2048 for i in servo_ids}

    # IMU：在无真实手机时使用仿真模式
    imu = IMUReader(simulate=True)
    imu.start()

    balance = BalanceController(neutral)
    mc = MotionController(servo_mgr, balance_ctrl=balance, imu_reader=imu, neutral_positions=neutral)

    ok = input('确认现场安全并允许移动舵机？(y/n) [n]: ') or 'n'
    if ok.lower() != 'y':
        print('取消 demo')
        return

    print('站立...')
    mc.stand()
    time.sleep(1.0)

    print('挥手(右)...')
    mc.wave(side='right', times=3)
    time.sleep(0.6)

    print('向前小步走...')
    mc.walk(steps=2, step_length=120, step_height=120, time_per_step_ms=350)
    time.sleep(0.6)

    print('坐下...')
    mc.sit()
    time.sleep(1.2)

    print('站起...')
    mc.stand()
    time.sleep(0.8)

    print('演示结束，回中位')
    mc.goto_neutral()

    imu.stop()
    try:
        uart.close()
    except Exception:
        pass


if __name__ == '__main__':
    main()
