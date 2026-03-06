# ESP32 固件烧录与部署

本目录提供 ESP32 烧录脚本与 MicroPython 运行代码。默认端口 UDP 5005，BLE 广播名 `ROBOT-ESP32-S3-BLE`。

## 目录结构
- `esp32/`：MicroPython 主程序 `main.py`、默认配置 `esp32_config.json`（可选）。
- `esp32/uservo.py`：舵机 SDK（已从官方示例复制）。
- `esp32/servo_controller.py`：高级舵机执行与查询适配层，供 `main.py` 调用。
- `flash.py`：基于 esptool 的烧录助手。
- `FLASHING.md`：本说明。

## 环境准备
- Python 3.8+
- 安装依赖（已在 requirements.txt 中列出）：
	```bash
	pip install -r requirements.txt
	```
	（包含 esptool、mpremote）

## 部署
- 首次刷固件快速部署执行install.bat，可按下面分步进行；后续修改程序后 执行`python cp.py`下载程序到板子

## 烧录 MicroPython 固件
1) 通过 USB 连接 ESP32，确认串口：Windows 查看设备管理器（如COM5），Linux/macOS 查看 `/dev/ttyUSB*`。
2) 下载对应板子的 MicroPython 固件（例如 `esp32-20240602-v1.23.0.bin` 放在 `esp32/`）。
3) 执行烧录（设备管理器查看串行设备端口；波特率 460800，S3 板请加 `--chip esp32s3 --offset 0x0`）
```bash
python -m esptool --chip esp32s3 --port COM5 erase_flash
python flash.py --chip esp32s3 --offset 0x0 --port COM5 --baud 460800 --bin esp32/ESP32_GENERIC_S3-20251209-v1.27.0.bin
```
4) 看到 “Hash of data verified” 即烧录完成。必要时可加 `--erase` 做全擦除。

## 部署项目脚本到板子
1) 复制主程序与配置（可选）：
```bash
mpremote connect COM5 repl #测试输入 `import os; os.listdir();`
python cp.py #复制esp32目录下的程序到板子
mpremote connect COM5 fs ls #查看板子系统文件

```
2) 复位开发板：
```bash
mpremote connect COM5 reset 
```
3) 固件启动后：
- 尝试使用存储的 Wi-Fi 配置连接；若无配置或失败，将启用 AP，SSID 为 `ROBOT-ESP32-S3`。
- 开启 BLE 广播 `ROBOT-ESP32-S3-BLE`（Service UUID `0000ffaa-0000-1000-8000-00805f9b34fb`，Char UUID `0000ffab-0000-1000-8000-00805f9b34fb`），支持 `ssid\npassword` 或 JSON `{ "ssid": "...", "password": "..." }` 写入配网。
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



## IMU 技术方案与操作指南

### 1. 硬件连接 (基于 YbImu I2C 模块)
IMU 模块负责为人形机器人提供高精度的姿态估计（Pitch/Roll/Yaw）。
我们采用内置硬件级卡尔曼/互补滤波解算的 YbImu 模块，直接通过 I2C 接口总线输出欧拉角（不再占用 ESP32 的算力资源）。

**ESP32 默认 I2C 接线定义:**
- SCL -> Pin 41
- SDA -> Pin 42
- VCC -> 3.3V
- GND -> GND
- 模块 I2C 通讯地址: `0x23`

### 2. 软件架构及模块划分
固件层对 IMU 的操作分为底层通信驱动、解算获取，以及上层控制策略三块：
1. **`imuI2cLib.py`:** 底层驱动。使用标准 MicroPython `machine.I2C` 对指定地址的寄存器进行读写操作，封装了版本读取、校准、参数获取等方法。
2. **`imu_controller.py`:** 控制器包装层。实现了 `IMUController` 类，内部持续通过 `imuI2cLib.py` API 拉取姿态数据、加速度、角速度等信息。提供给外围代码一个平滑的获取接口 `update()`。
3. **`balance_controller.py`:** 机器人平衡补偿层（高级算法）。当机器人站立或走路时，获取 `imu_controller` 发出的欧拉角（主要是 Pitch 和 Roll），动态计算这会对各个关节（主要为踝、膝关节）产生的偏差，进而生成微调的修正目标发给舵机底盘，维持动静平衡。提供 `invert_pitch` / `invert_roll` 用以快速兼容传感器的正反面安装差异。

### 3. 操作与调试方法

#### 3.1 本地 3D 姿态可视化 (Windows / Mac)
在把 IMU 装上机器人前，您可以在电脑上通过 USB 串口或者直接插入电脑独立测试这个传感器，并通过一个 3D 程序直观查看其姿态指向对不对。
1. 切换目录到 `docs/imuLib`，安装依赖：
   ```bash
   cd docs/imuLib
   pip install vpython pyserial
   ```
2. 运行 3D 人形机器人可视化程序，注意需要修改脚本里的串口号 (例如从 `COM8` 改为您的实际端口)：
   ```bash
   python imu_3d_vis.py
   ```
   *程序会自动打开浏览器并渲染 60 fps 的互动 3D 机器人姿态。*

#### 3.2 烧录到 ESP32 进行单元测试
将传感器连上 ESP32 的 I2C 引脚后进行联调。可以使用刚才编写的自动化测试脚本快速验证硬件：
1. 将 `a_Firmware/esp32/` 目录下所有相关脚本(`imuI2cLib.py` `imu_controller.py` `test_imu.py`) 烧录到板子上（使用上方的 `cp.py` 或 `mpremote fs cp`）。
2. 在电脑终端启动 REPL 并运行：
   ```bash
   mpremote connect COM5 repl
   ```
3. 在 MicroPython 交互界面中导入并执行：
   ```python
   import test_imu
   test_imu.test_imu()
   ```
4. 如果接线与通信正常，终端将以 10Hz 输出实时的 Pitch、Roll、Yaw 角度偏转和测试结果报表。这证明您可以放心地在主程序 `main.py` 中激活对应的平衡层。


## 舵机执行控制技术方案与操作指南

### 1. 硬件连接 (基于 UART 串口控制)
整个机器人采用高达 25 路的高压串口总线舵机。为了兼容 ESP32 与舵机的协议电平要求，方案采用内部 UART 进行半双工串行通讯。
- **ESP32 串口定义:** 通过指定 TX/RX 引脚发送和回读舵机响应 (根据当前硬件连线，默认使用 `UART_TX_PIN = 47, UART_RX_PIN = 48`)。
- **通信链路:** ESP32 <-> RX/TX 物理连线 <-> 舵机串口控制板 <-> 多路级联总线舵机。

### 2. 软件架构及模块划分
舵机控制链路由三个 Python 模块封装组成：
1. **`uservo.py`:** 最底层的串口驱动 SDK。封装了串口收发、协议组包与解析、校验位计算，实现所有底层的指令包格式支持。
2. **`servo_controller.py`:** 高级执行与查询适配层。封装了简单易用的 API 接口（如 `set_positions` 批量动作更新，`read_full_status` 查询角度、温度、电压状态等），剥离了应用层和繁琐驱动层的强耦合，实现了面向 `25` 个关节的一体化控制。
3. **`main.py / balance_controller.py`:** 核心控制流。来自网端 (如 UDP/Websocket) 的动作解析与 IMU 平衡数据融合后，将合成的目标 (各关节 ID 及其目标角度) 指派给 `servo_controller.py` 驱动硬件快速执行。

### 3. 舵机操作与测试方法

#### 3.1 终端独立联机调试
为验证串口及其到舵机的物理排线是否导通稳定，可以使用封装好的专门独立测试脚本来读写舵机各项内部寄存器数据：
1. 请先固定好 ESP32 TX=47 / RX=48 到舵机转接板的数据线，并为舵机接通独立供电。
2. 运行 REPL 单元测试指令：
   ```bash
   mpremote connect COM5 run test_unit/test_servo.py
   ```
3. 这个测试会自动初始化串口并测试指定舵机（默认 ID:1）的连通性。如果响应成功，会输出测试报表（如读取到的舵机当前位置、电压和温度）；若无法打印数据（只出现“无响应”），需要检查：
   - 物理线上的 `RX/TX` 针脚是否接反。
   - 波特率（目前默认为 `115200`）是否和舵机内部参数相符。


#### 3.2 关节组装注意项
机器人整体计算模型严格依赖设定的关节编号对应实际的身体部位。如 ID 15 必为左大腿弯曲，ID 17 必为左膝关节。
在拼装测试时：
- 对刚拆包的新舵机，默认 ID 为 0 或 1。必须用官方烧写器，或者开发专门设定的工具代码，把它单独插上后烧好设定的 ID 值 (如 ID 17)，再接进级联总线网络内。如果串联后再设置 ID，会导致总线上所有舵机被改成同一个号码而无法正常控制。


