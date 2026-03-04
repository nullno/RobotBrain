# RobotBrain

**人形机器人主控程序** — 运行在 PC / Android 上，通过 Wi-Fi 局域网控制 ESP32 + 25 路舵机。

## 系统架构

```
┌──────────────────────────────────────────────────┐
│            PC / Android  (Kivy GUI)              │
│                                                  │
│  app/              widgets/           services/   │
│  ├ app_root        ├ robot_face       ├ wifi_servo│
│  ├ bootstrap_rt    ├ debug_panel      ├ balance   │
│  ├ esp32_runtime   ├ esp32_setup      ├ motion    │
│  ├ balance_rt      ├ esp32_indicator  ├ imu       │
│  ├ ai_runtime      ├ gyro_panel       ├ ai_core   │
│  └ ...             └ camera_view      └ vision    │
│                                                  │
│  ① BLE 配网 (bleak)  ② UDP 5005 指令/遥测        │
└──────────────┬──────────────┬────────────────────┘
               │ BLE          │ Wi-Fi UDP
               ▼              ▼
         ┌─────────────────────────┐
         │        ESP32            │
         │  MicroPython 固件       │
         │  WiFi / BLE / I2C       │
         │  UDP ⇄ UART 桥接       │
         └──────┬──────────┬───────┘
                │ UART     │ I2C
                ▼          ▼
        CH340 舵机驱动板   IMU 传感器
              │            (姿态数据)
          25 路舵机
```

### 通信流程

1. **首次配网** — App 通过 BLE 将 Wi-Fi SSID/密码发送给 ESP32
2. **日常连接** — App 通过 UDP 广播发现 ESP32，建立局域网通信
3. **指令下发** — `wifi_servo` 模块封装 JSON 指令：舵机目标、扭矩、动作、状态查询
4. **遥测上报** — ESP32 返回舵机状态 + IMU 姿态 + Wi-Fi 信号

## 项目结构

```
RobotBrain/
├── main.py                 # 程序入口
├── app/                    # 运行时逻辑（启动、循环、ESP32 连接）
├── services/               # 核心服务（wifi_servo、平衡控制、AI）
├── widgets/                # Kivy UI 组件
├── kv/                     # Kivy 布局文件
├── assets/                 # 字体、图标资源
├── data/                   # 配置数据（AI 模型等）
├── logs/                   # 运行日志
│
├── a_DebugPanel/           # 🔧 独立项目：装机调试面板工具
├── a_Firmware/             # 🔧 独立项目：ESP32 固件烧录程序
│   ├── esp32/              #    MicroPython 固件源码
│   ├── imuLib/             #    IMU 库
│   └── servo-micropython-esp32-sdk/
│
├── requirements.txt
└── buildozer.spec          # Android 打包配置
```

> **注意**：`a_DebugPanel` 是装机调试工具，`a_Firmware` 是固件烧录程序，它们是**独立项目**，不参与主程序运行。

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

## 日志

运行日志输出到 `logs/robot_dashboard.log`。


1.初始化界面检测配网时 不加载主界面（表情 陀螺仪imu指示 连接状态 日志状态），待弹出esp32_setup.py流程走完再进入主界面
2.主界面日志面板（runtime_status.py）的内容调整成可复制；
3.主界面的连接状态需要单独抽离一个组件放到widgets，再加载渲染；整体业务逻辑做到模块清晰，还有什么优化可以一起抽离 或者精简代码（不要动额可以移除），现在app_root.py 代码太长了
4.重构陀螺仪指示（gyro_panel.py），在主界面左上角绘制一个迷你三维小人，来显示空间姿态；
5.在已连接设备的情况下: 调试面板中的 快捷动作 舵机连接状态 关节调试中的功能操作无法和esp32数据通信，固件程序a_Firmware/esp32 需要参考servo-micropython-esp32-sdk/example 的示例来编写指令程序（单独编写模块加载main.py中使用，源代码的引入uservo sdk也挪到这个模块，做到功能划分清晰可可扩展，后续还要追加imu，摄像头传感器等数据固件程序）；主控程序则需要编写对应的wifi_servo.py通信，来发送和接受数据，已便能正常的控制舵机和接受舵机状态数据渲染到舵机连接状态卡片，同时要做好两个程序日志输出，以便可以观察两个程序互相数据传输的状态日志，更好调试检查