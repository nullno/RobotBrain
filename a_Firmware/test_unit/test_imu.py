"""
IMU 模块的单元测试脚本。

用于 ESP32 固件测试，运行前请确保:
1. YbImu (I2C) 模块已正确连接。
2. I2C 引脚 SCL=22, SDA=21 (可根据接线修改)。
3. ESP32 处于 MicroPython 交互环境 或通过 mpremote/ampy 直接运行。
"""

import time
import machine

from imu_controller import IMUController

def test_imu():
    print("=" * 40)
    print(" 开始 IMU 模块连接测试")
    print("=" * 40)

    # 1. 挂载 I2C 总线
    try:
        # ESP32 默认引脚 (可自行修改以匹配实际硬件)
        i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(21), freq=400000)
        devices = i2c.scan()
        print(f"I2C 扫描完成，发现设备地址: {[hex(d) for d in devices]}")
        if 0x23 not in devices:
            print("警告: 未能在总线上发现 0x23 (YbImu 默认地址) ，请检查接线！")
    except Exception as e:
        print(f"I2C 总线初始化失败: {e}")
        return

    # 2. 初始化控制器
    print("\n初始化 IMU 控制器...")
    imu = IMUController(i2c, addr=0x23)
    
    if not imu.init():
        print(">> 错误: IMU 初始化失败或无法握手。请检查传感器！")
        return
    print(">> IMU 初始化成功！启动姿态直读...\n")

    # 3. 循环测试读取姿态
    start_time = time.time()
    read_count = 0
    error_count = 0
    
    try:
        # 测试 10秒 左右
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
                
            time.sleep(0.1) # 10Hz 采样打印
            
    except KeyboardInterrupt:
        print("\n>> 用户中断测试。")

    print("\n" + "=" * 40)
    print(" 测试结束报告:")
    print(f" 总共成功读取: {read_count} 次")
    print(f" 读取失败/丢包: {error_count} 次")
    if read_count > 0 and error_count == 0:
        print(" 状态: ★★★ 测试完美通过 ★★★")
    else:
        print(" 状态: 存在丢包或无连接，请检查传感器是否虚焊。")
    print("=" * 40)


if __name__ == "__main__":
    test_imu()
