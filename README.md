你是一名经验丰富的嵌入式与 Python/Kivy 工程师。请生成完整的工业级代码（可直接运行，注释清晰，可扩展性强），要求包括 PC/手机端的 GUI、ESP32 通信逻辑、IMU 数据采集、舵机控制等所有模块。要求遵循高质量工业规范：

系统架构：
```
PC / 手机端 (同一局域网 WiFi)
        │
        │ HTTP / WebSocket / UDP
        ▼
      ESP32
        │
   ┌────┼───────────┐
   │    │           │
 WiFi  Bluetooth   I2C
         │           │
       配网        IMU传感器
                      │
                   姿态数据
        │
        │ UART
        ▼
CH340 舵机驱动板
        │
     25路舵机
```
要求：
1. **PC/手机端 GUI**：
   - 管理设置面板 实现蓝牙给esp32发送wifi配网数据
   - 管理设置面板 实时显示 25 路舵机状态和 IMU 姿态数据
   - 管理设置面板 加入快捷遥控器操作控制机器人运动
   - 支持通过 WebSocket/UDP 向 ESP32 发送控制指令
   - 具备基本安全检查（例如指令边界检查）
   - 可扩展多平台（Windows/Linux/Android/iOS）

2. **ESP32**：
   - 支持 WiFi、Bluetooth、I2C 通信
   - 通过 HTTP/WebSocket/UDP 接收 PC/手机端控制指令
   - 采集 IMU 数据（例如 MPU6050 或 BNO055）
   - 将 IMU 数据和舵机状态通过 UART 发给 CH340舵机板
   - 支持基础异常处理和重连机制

3. **IMU 传感器**：
   - 使用 I2C 总线读取
   - 提供角度/姿态数据（Pitch/Yaw/Roll）
   - 支持滤波（如互补滤波或卡尔曼滤波）
   
4. **CH340 舵机驱动板**：
   - 支持 25 路舵机控制
   - 接收 UART 指令并执行，反馈舵机状态
   - 提供安全边界检查（舵机角度范围限制）
   
5. **代码质量要求**：
   - 模块化、可扩展
   - 每个模块提供清晰注释和接口说明
   - 遵循 PEP8/Python 工业规范
   - 使用 asyncio 或多线程保证实时性
   - 提供基础调试和日志功能
   - 生成requirements.txt

7. **项目目录**：
   - 合理优化目录结构
   - 生成requirements.txt

6. **固件烧录**：
   - 在a_Firmware固件目录生成可用的烧录程序
   - 生成说明文档


请生成代码并保持每个模块独立，且能互通，附带注释和使用示例,旧代码用不到的可以删除，精简代码结构

**固件（ESP32）**
- 固件示例位于 `firmware/esp32`，包含 MicroPython 示例 `main.py` 与 `README.md`，用于接收主机 UDP 关键帧并通过 UART 输出舵机同步写帧。
- 常见刷写步骤（示例，先将设备进入刷写模式）：

```bash
# 使用 mpremote 将固件复制到设备并重启（推荐）：
mpremote connect serial:/dev/ttyUSB0 fs put firmware/esp32/* :/flash/
mpremote connect serial:/dev/ttyUSB0 exec "import machine; machine.reset()"

# 或使用 esptool 烧录 MicroPython 固件镜像（若需要重装固件）
# esptool.py --port COM3 write_flash -z 0x1000 esp32-micropython.bin
```

请根据你的操作系统调整串口设备名称（Windows 例 `COM3`，Linux 例 `/dev/ttyUSB0`）。固件 README 中有更多说明。

**调试面板架构文档**
- 调试面板拆分与调用关系见：`docs/debug_panel_architecture.md`

**关键功能定位（遇到问题去这些地方排查）**
- 摄像头无画面（Android）: 检查 `widgets/camera_view.py`、Android 权限（`app_root._check_android_permissions`）以及打包时是否声明摄像头权限。
- 摄像头无画面（PC）: 检查是否安装 `opencv-python`，在 `widgets/camera_view.py` 内对 `cv2` 的导入是否抛错。
- 陀螺仪无数据: 查 `app._setup_gyroscope` 与 `services/imu.py`；Android 使用 `plyer.gyroscope`，桌面为模拟数据。
- 网络/舵机通信异常: 查 `services/esp32_client.py`、`app/esp32_runtime.py`、固件 `firmware/esp32/main.py`、以及网络连通性（局域网内 UDP/ICMP 可达）。同时检查 ESP32 与 CH340 的 UART 物理连线与电压兼容性。
- 权限相关问题: `app_root._start_permission_watcher` 和 `widgets/startup_tip.py` 控制提示与重试逻辑。

**运行时日志与调试**
- 程序会在 `logs/robot_dashboard.log` 写入运行日志。UI 中 `runtime_status` 面板也会显示日志。
- 将 `logging.basicConfig(level=logging.DEBUG, ...)` 可临时打开更多日志（仅用于调试）。

**打包注意（Android）**
- 在 `buildozer.spec` 或打包脚本中确保声明摄像头、读写存储等权限。
- `plyer` 在 Android 上可提供陀螺仪与 TTS 接口；测试时先在真实设备上验证权限流程。

**语音合成（TTS）**
- 优先使用 `plyer.tts`（移动平台），回退到 `pyttsx3`（桌面）或 Windows `win32com`/PowerShell。相关逻辑在 `app/app_root.py:_ai_speak_final`。

**如何定位新功能/问题（快速步骤）**
1. 阅读 `app/app_root.py` 的启动流程，定位初始化失败处（日志/控制台输出）。
2. 复现问题并查看 `logs/robot_dashboard.log`。
3. 找到相关模块（`widgets/` 或 `services/`），在模块内添加更详细的日志并重试。

**开发建议与 TODO**
- 将硬件接口（`ServoBus`、`IMUReader`）抽象并提供 Mock 实现，方便无设备调试。
- 将 AI/语音/视觉功能拆成独立服务模块，添加配置开关（enable/disable）以便在不同平台控制初始化流程。
- 编写单元测试/集成测试（至少覆盖 `services` 层核心算法）。

**常用命令小结**
- 安装依赖：`pip install -r requirements.txt`
- 运行：`python main.py`
- 查看日志：`tail -f logs/robot_dashboard.log`（Linux/macOS）

**提示词**
```
优化和完善机器人主控程序：
1.这个是一个机器人主控程序,可以运行在pc/手机上；
2.局域网wifi内，pc/手机端运行这个程序通过wifi控制esp32下发动作指令给舵机，接线逻辑是[esp32+imu->CH340舵机驱动板->舵机（25个）]，
3.固件目录a_Firmware,a_Firmware/esp32是esp32开发板烧录程序;a_Firmware/imuLib 是 imu 开发板烧录程序;servo-micropython-esp32-sdk 这个文件是 esp32开发板 sdk,对应完成编写烧录程序
4.保留现在的表情和各功能面板模块，在此基础上完善项目；在主程序和esp32 处在wifi配对情况下；开始读取各种舵机数据和执行各种动作，陀螺仪指示 读取imu 开发板数据（也是）保持机器人姿态平衡，相关代码在balance_ctrl.py；



帮我编写可靠的人形机器人的运动，输出封装通用的运动api方法（比如 行走、小跑、坐、 站起 、挥手、抓取、叉腰 扭动等等 人体各种运动）：
下面是我的舵机分布，手机是安装在头部（上下抬头的部位，除正常平衡外，左右上下摇运动头部要保证我身体平衡不摔倒）
左/右手各5个【肩部旋转（前后摆臂）、 手臂抬起、 手大臂旋转、 臂腕弯曲、 手部抓取（正转拉经夹取反转释放）】

左/右腿各6个 【跨部旋转（前后摆腿行走）、 大腿臂抬起、 腿大臂旋转、 膝盖弯曲、 脚腕左右摆动（控制身体平衡关键）、脚腕前后摆动（控制身体平衡关键）】

腰部1个 【左右旋转上肢身体】

颈部2个【左右头部转动、上下抬头】
```

1.可以扫描到esp32的蓝牙，但是用蓝牙发送配网wifi配置时提示Provision failed: TimeoutError()，结合固件程序a_Firmware/esp32 帮我修复；期望成功给esp32配网；
2.完善这个单元测试程序，连接蓝牙后判断esp32设备是否已经联网，如果已经联网就提示用户，不用再发送wifi配置步骤了；有必要可以a_Firmware/esp32/main.py 程序里新增判断wifi连接逻辑