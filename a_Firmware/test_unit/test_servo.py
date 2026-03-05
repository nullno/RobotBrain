"""
test_servo.py - 舵机底层通信单元测试模块
请在 ESP32 上执行此脚本：
import test_servo
test_servo.run()
"""

import time
from machine import UART
import ustruct
from uservo import UartServoManager, pack_packet, CODE_READ_DATA
from servo_controller import ServoController

def test_read_register(uart, servo_id, addr, length, name):
    print(">>> 测试读取 {}, 地址: 0x{:02X}, 长度: {}".format(name, addr, length))
    try:
        # 清理 buffer
        while uart.any():
            uart.read()
            
        params = ustruct.pack('>BB', addr, length)
        pkt = pack_packet(servo_id, CODE_READ_DATA, params)
        print("发送数据: ", [hex(x) for x in pkt])
        uart.write(pkt)
        
        # 接收并打印原始数据
        start = time.ticks_ms()
        recv_data = bytearray()
        while time.ticks_diff(time.ticks_ms(), start) < 100:
            if uart.any():
                recv_data.extend(uart.read())
            time.sleep_ms(1)
            
        print("接收数据: ", [hex(x) for x in recv_data])
        if recv_data:
            from uservo import unpack_packet
            parsed = unpack_packet(bytes(recv_data))
            print("解析结果: ", parsed)
        else:
            print("无响应")
    except Exception as e:
        print("测试异常: ", e)
    print("-" * 40)


def run(servo_id=1):
    try:
        uart = UART(1, baudrate=115200, tx=47, rx=48, timeout=0)
    except Exception as e:
        print("UART 初始化失败: ", e)
        return
        
    print("========== 舵机底层通信测试 ==========")
    
    test_read_register(uart, servo_id, 0x38, 2, "当前位置 (Position, 0x38)")
    time.sleep_ms(50)
    test_read_register(uart, servo_id, 0x3E, 1, "当前电压 (Voltage, 0x3E)")
    time.sleep_ms(50)
    test_read_register(uart, servo_id, 0x3F, 1, "当前温度 (Temperature, 0x3F)")
    time.sleep_ms(50)
    
    print("\n>>> 使用 ServoController 测试封装方法")
    ctrl = ServoController(uart, 10)
    ctrl.ping(servo_id)
    time.sleep_ms(50)
    
    pos = ctrl.read_position(servo_id)
    print("read_position(): ", pos)
    time.sleep_ms(50)
    
    volt = ctrl.read_voltage(servo_id)
    print("read_voltage(): ", volt)
    time.sleep_ms(50)
    
    temp = ctrl.read_temperature(servo_id)
    print("read_temperature(): ", temp)
    time.sleep_ms(50)
    
    full_status = ctrl.read_full_status(servo_id)
    print("read_full_status(): ", full_status)
    time.sleep_ms(50)

    print("========== 测试完成 ==========")

if __name__ == '__main__':
    run()
