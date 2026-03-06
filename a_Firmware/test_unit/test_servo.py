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
    print(
        ">>> Testing read {}, Address: 0x{:02X}, Length: {}".format(name, addr, length)
    )
    try:
        # Clear buffer
        while uart.any():
            uart.read()

        params = ustruct.pack(">BB", addr, length)
        pkt = pack_packet(servo_id, CODE_READ_DATA, params)
        print("Sending data: ", [hex(x) for x in pkt])
        uart.write(pkt)

        # Receive and print raw data
        start = time.ticks_ms()
        recv_data = bytearray()
        while time.ticks_diff(time.ticks_ms(), start) < 100:
            if uart.any():
                recv_data.extend(uart.read())
            time.sleep_ms(1)

        print("Received data: ", [hex(x) for x in recv_data])
        if recv_data:
            from uservo import unpack_packet

            parsed = unpack_packet(bytes(recv_data))
            print("Parsed result: ", parsed)
        else:
            print(
                "No response received for {}. Please check servo connection and ID.".format(
                    name
                )
            )
    except Exception as e:
        print("Test exception: ", e)
    print("-" * 40)


def run(servo_id=1):
    try:
        uart = UART(1, baudrate=115200, tx=47, rx=48, timeout=0)
    except Exception as e:
        print("UART initialization failed: ", e)
        return

    print("========== Servo Low-Level Communication Test ==========")

    test_read_register(uart, servo_id, 0x38, 2, "position (Position, 0x38)")
    time.sleep_ms(50)
    test_read_register(uart, servo_id, 0x3E, 1, "voltage (Voltage, 0x3E)")
    time.sleep_ms(50)
    test_read_register(uart, servo_id, 0x3F, 1, "temperature (Temperature, 0x3F)")
    time.sleep_ms(50)

    print("\n>>> Using ServoController to test encapsulated methods")
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

    print("========== test complete ==========")


if __name__ == "__main__":
    run()
