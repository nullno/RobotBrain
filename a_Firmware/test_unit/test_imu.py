# coding: utf-8
"""
Unit test script for the IMU module.

Used for ESP32/ESP32-S3 firmware testing. Before running, please ensure:
1. YbImu (I2C) module is properly connected.
2. I2C pins correspond to your ESP32-S3 setup (Current code uses SCL=41, SDA=42).
3. ESP32 is in MicroPython interactive environment or running directly via mpremote/ampy.
"""

import time
import machine

from imu_controller import IMUController

def test_imu():
    print("=" * 40)
    print(" Start IMU module connection test")
    print("=" * 40)

    # 1. Mount I2C bus
    try:
        # ESP32-S3 common pins (Modify if differing from actually wired pins)
        i2c = machine.I2C(0, scl=machine.Pin(41), sda=machine.Pin(42), freq=100000)
        devices = i2c.scan()
        print(f"I2C scan complete, found device addresses: {[hex(d) for d in devices]}")
        
        if not devices:
            print("Error: No I2C devices found on the bus. Please check wiring (SCL=41, SDA=42)!")
            return
            
        if len(devices) > 5:
            print("Warning: Too many devices found. This usually indicates bus noise, missing pull-up resistors, or swapped SDA/SCL lines!")
            
        # Try to find common IMU addresses first (0x23, 0x68, 0x69), fallback to the first found
        target_addr = devices[0]
        for addr in [0x23, 0x68, 0x69]:
            if addr in devices:
                target_addr = addr
                break
                
        print(f"Selecting I2C IMU address: {hex(target_addr)}")

    except Exception as e:
        print(f"I2C bus initialization failed: {e}")
        return

    # 2. Initialize controller
    print("\nInitializing IMU controller...")
    imu = IMUController(i2c, addr=target_addr)
    
    if not imu.init():
        print(">> Error: IMU initialization or handshake failed. Please check the sensor!")
        return
    print(">> IMU initialization successful! Starting attitude direct reading...\n")

    # 3. Loop test reading attitude
    start_time = time.time()
    read_count = 0
    error_count = 0
    
    try:
        # Test for about 10 seconds
        while time.time() - start_time < 10:
            res = imu.update()
            if res:
                pitch, roll, yaw = res
                accel = imu.accel
                gyro = imu.gyro
                print(f"[{read_count:04d}] Pitch: {pitch:6.2f} | Roll: {roll:6.2f} | Yaw: {yaw:6.2f} | Accel z: {accel[2]:5.2f}g")
                read_count += 1
            else:
                error_count += 1
                
            time.sleep(0.1) # 10Hz sampling print
            
    except KeyboardInterrupt:
        print("\n>> Test interrupted by user.")

    print("\n" + "=" * 40)
    print(" Test End Report:")
    print(f" Total successful reads: {read_count}")
    print(f" Failed reads/packet loss: {error_count}")
    if read_count > 0 and error_count == 0:
        print(" Status: *** Test passed perfectly ***")
    else:
        print(" Status: Packet loss or no connection, please check if the sensor is poorly soldered.")
    print("=" * 40)


if __name__ == "__main__":
    test_imu()
