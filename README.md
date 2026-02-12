# Robot Dashboard — 开发者指南

**概述**
- 本仓库是一个基于 `Kivy` 的跨平台（PC / Android）机器人控制面板：摄像头、陀螺仪、舵机（通过 USB/OTG）与表情/语音交互。

**快速开始（开发环境）**
1. 克隆仓库并进入项目根目录。
2. 建议创建虚拟环境：
   - Windows: `python -m venv .venv` 然后 `.\.venv\Scripts\activate`
   - macOS / Linux: `python3 -m venv .venv` 然后 `source .venv/bin/activate`
3. 安装依赖：
   - `pip install -r requirements.txt`
4. 运行程序（桌面调试）：
   - `python main.py`

**主要文件与说明**
- `main.py`: 应用入口。
- `app/app_root.py`: 应用主类 `RobotDashboardApp`，负责初始化界面、日志、硬件（串口/陀螺 / 摄像头）并启动定时循环。
- `kv/`: 存放 Kivy 布局文件（`.kv`）。
- `widgets/`: UI 组件，如摄像头视图、表情、仪表盘、启动提示等。
  - `widgets/camera_view.py`: 摄像头封装，桌面使用 OpenCV（`cv2`），Android 使用系统摄像头接口。
  - `widgets/startup_tip.py`: 启动权限/连接提示弹窗，`app_root` 在权限缺失时会弹出。
  - `widgets/runtime_status.py`: 运行日志面板（`RuntimeStatusLogger`），界面日志转发实现位置。
- `services/`: 设备/硬件层封装与控制逻辑。
  - `services/servo_bus.py`, `uart_servo.py`: 舵机总线/串口驱动（使用 `pyserial`）。
  - `services/motion_controller.py`: 运动控制器，与 `BalanceController` 集成实现动作序列与平衡调整。
  - `services/imu.py`: IMU/陀螺读取封装（桌面可模拟）。
  - `services/vision.py`: 视觉处理（若有，通常依赖 OpenCV / numpy）。
- `requirements.txt`: 项目依赖（第三方库列表）。

**关键功能定位（遇到问题去这些地方排查）**
- 摄像头无画面（Android）: 检查 `widgets/camera_view.py`、Android 权限（`app_root._check_android_permissions`）以及打包时是否声明摄像头权限。
- 摄像头无画面（PC）: 检查是否安装 `opencv-python`，在 `widgets/camera_view.py` 内对 `cv2` 的导入是否抛错。
- 陀螺仪无数据: 查 `app._setup_gyroscope` 与 `services/imu.py`；Android 使用 `plyer.gyroscope`，桌面为模拟数据。
- 串口/舵机通信异常: 查 `services/servo_bus.py`、日志文件 `logs/robot_dashboard.log`、以及是否正确选择串口（Windows COMx / Linux /dev/ttyUSBx）。
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
我这是一个 ptthon kivy 项目，项目兼容PC 和手机(打包采用google colab)，部分功能pc 只需模拟（陀螺仪），目标是做一个人形机器人控制大脑，并带有灵动的表情交互，
1.通过USB OTG 连接转接板->舵机；
2.pc 上模拟陀螺仪，手机上读取陀螺仪数据；
3.使用前置摄像头
4.使用ucv姿态平衡算法；
5.需要接入ai接口 通过ai分析摄像头画面听懂语音 实现自动行走交互 做表情 说话，（代码里没有这部分帮我实现）
6.我的舵机分布：

帮我编写可靠的人形机器人的运动，输出封装通用的运动api方法（比如 行走、小跑、坐、 站起 、挥手、抓取、叉腰 扭动等等 人体各种运动）：
下面是我的舵机分布，手机是安装在头部（上下抬头的部位，除正常平衡外，左右上下摇运动头部要保证我身体平衡不摔倒）
左/右手各5个【肩部旋转（前后摆臂）、 手臂抬起、 手大臂旋转、 臂腕弯曲、 手部抓取（正转拉经夹取反转释放）】

左/右腿各6个 【跨部旋转（前后摆腿行走）、 大腿臂抬起、 腿大臂旋转、 膝盖弯曲、 脚腕左右摆动（控制身体平衡关键）、脚腕前后摆动（控制身体平衡关键）】

腰部1个 【左右旋转上肢身体】

颈部2个【左右头部转动、上下抬头】

```