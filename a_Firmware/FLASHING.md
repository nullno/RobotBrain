# ESP32 固件烧录与部署

本目录提供 ESP32 烧录脚本与 MicroPython 运行代码。默认端口 UDP 5005，BLE 广播名 `ESP32-PROV`。

## 目录结构
- `esp32/`：MicroPython 主程序 `main.py`、默认配置 `esp32_config.json`（可选）。
- `esp32/uservo.py`：舵机 SDK（已从官方示例复制）。
- `esp32/servo_sdk_adapter.py`：基于 SDK 的适配层，供 `main.py` 调用。
- `flash.py`：基于 esptool 的烧录助手。
- `FLASHING.md`：本说明。
- 其他子目录：`imuLib/`、`servo-micropython-esp32-sdk/` 为参考库与示例。

## 环境准备
- Python 3.8+
- 安装依赖（已在 requirements.txt 中列出）：
	```bash
	pip install -r a_Firmware/requirements.txt
	```
	（包含 esptool、mpremote）

## 烧录 MicroPython 固件
1) 通过 USB 连接 ESP32，确认串口：Windows 查看设备管理器（如 COM3），Linux/macOS 查看 `/dev/ttyUSB*`。
2) 下载 MicroPython 固件（例如 `esp32-20240602-v1.23.0.bin` 放在 `a_Firmware/esp32/`）。
3) 执行烧录（示例端口 COM3，波特率 460800）：
```bash
python a_Firmware/flash.py --port COM5 --baud 460800 --bin esp32/esp32-20240602-v1.23.0.bin
```
4) 看到 “Hash of data verified” 即烧录完成。必要时可加 `--erase` 做全擦除。

## 部署项目脚本到板子
1) 复制主程序与配置（可选）：
```bash
mpremote connect COM5 repl #测试端口
python cp.py #复制esp32目录下的程序到板子
mpremote connect COM5 fs ls #查看板子系统文件
```
2) 复位开发板：
```bash
mpremote connect COM5 repl
import machine; machine.reset()
```
3) 固件启动后：
- 尝试使用存储的 Wi-Fi 配置连接；若无配置或失败，将启用 AP，SSID 为 `robotbrain-esp32`。
- 开启 BLE 广播 `ESP32-PROV`（Service UUID `0000ffaa-0000-1000-8000-00805f9b34fb`，Char UUID `0000ffab-0000-1000-8000-00805f9b34fb`），支持 `ssid\npassword` 或 JSON `{ "ssid": "...", "password": "..." }` 写入配网。
- 开启 UDP(5005)/HTTP(8080)/WebSocket(8765) 控制，I2C 采集 IMU，UART 桥接 CH340 舵机板。

## 如何确认烧录/部署成功
- 烧录阶段：esptool 输出包含 `Hash of data verified` 说明固件写入并校验通过。
- 连接检测：`mpremote connect COM5 repl` 能进入交互即表示串口和固件正常；无法进入请检查占用/驱动/COM 号。
- 文件检查：在 REPL 执行 `import os; os.listdir()` 应能看到 `/main.py`（如果已上传）。
- 版本信息：在 REPL 执行 `import sys; print(sys.platform, sys.implementation)` 确认是 esp32/esp32s3 MicroPython。
- 程序启动：执行 `import machine; machine.reset()` 复位后，串口会打印启动日志，若网络/IMU/UART 正常会有对应提示；也可用 `mpremote connect COM5 exec "import machine; machine.reset()"` 触发复位。

## 协议速览
- UDP 端口 5005：
	- 发现：`{"type": "discover"}` → 返回 IP/MAC/port。
	- 关键帧：`{"type": "servo_targets", "targets": {"1":1500}, "duration":300}`。
	- 状态：`{"type": "status"}` → 返回 telemetry。
- WebSocket：`ws://<esp32_ip>:8765/ws`，与 UDP 相同 JSON 载荷。
- HTTP：`POST /provision {"ssid","password"}`；`POST /status` 返回 telemetry。
- BLE：写入上面的 UUID 特征，内容支持 `ssid\npassword` 或 JSON 配置。

## 常见问题
- 烧录失败：降低波特率到 115200，或先执行 `--erase`。
- 连接不上：按住 BOOT/EN 进入烧录或启动；确认 5V/3.3V 供电稳定。
- 舵机无响应：检查 UART TX/RX 引脚、电平匹配，以及 CH340 板供电是否独立。 