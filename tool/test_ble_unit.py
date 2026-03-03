# 【测试BLE连接的工具，使用Bleak库进行扫描和连接】
import asyncio
import os
import sys

# === 关键修复：在导入 bleak 之前设置环境变量 ===
if sys.platform == "win32":
    os.environ["BLEAK_BACKEND"] = "winrt"  # 强制使用 WinRT 后端
    # 解决 Windows 事件循环问题
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 现在导入 bleak
from bleak import BleakScanner, BleakClient

TARGET_NAME = "ROBOT-ESP32-S3-BLE"

async def test_connect():
    print("扫描设备...")
    
    # 扫描设备
    devices = await BleakScanner.discover(timeout=5)
    
    target = None
    for d in devices:
        if d.name and TARGET_NAME in d.name:
            target = d
            print(f"✅ 找到设备: {d.name}")
            print(f"   地址: {d.address}")
            break
    
    if not target:
        print("❌ 未找到设备")
        return
    
    print(f"\n尝试连接 {target.address}...")
    
    try:
        # 增加超时时间，使用更稳定的连接参数
        async with BleakClient(
            target.address,
            timeout=30.0,  # 增加超时
            disconnected_callback=lambda c: print("设备断开连接")
        ) as client:
            print(f"✅ 连接成功!")
            # bleak 不同后端的 MTU 属性名不一致，WinRT 没有 client.mtu
            mtu_value = getattr(client, "mtu_size", None) or getattr(client, "mtu", None)
            print(f"   MTU: {mtu_value if mtu_value is not None else '未知/后端未提供'}")
            print(f"   是否已连接: {client.is_connected}")
            
            # 等待服务发现
            await asyncio.sleep(1)
            
            # 打印服务
            services = list(client.services) if client.services is not None else []
            print(f"\n发现 {len(services)} 个服务:")
            for service in services:
                print(f"\n服务: {service.uuid}")
                for char in service.characteristics:
                    print(f"  特征: {char.uuid}")
                    print(f"    属性: {char.properties}")
            
            # 保持连接一段时间
            print("\n保持连接10秒...")
            await asyncio.sleep(10)
            
    except asyncio.TimeoutError:
        print("❌ 连接超时")
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        import traceback
        traceback.print_exc()

async def main():
    print("="*50)
    print("Windows BLE 连接测试 (WinRT后端)")
    print("="*50)
    print(f"BLEAK_BACKEND: {os.environ.get('BLEAK_BACKEND', 'default')}")
    print()
    
    await test_connect()

if __name__ == "__main__":
    asyncio.run(main())