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
├── docs/                   # 资料文档 舵机调试工具
├── a_DebugPanel/           # 🔧 独立项目：装机调试面板工具
├── a_Firmware/             # 🔧 独立项目：ESP32 固件烧录程序
│   ├── esp32/              #    MicroPython 固件源码
│
├── requirements.txt
└── buildozer.spec          # Android 打包配置
```

> **注意**：`a_DebugPanel` 是装机调试工具，`a_Firmware` 是固件烧录程序，它们是**独立项目**，不参与主程序运行。

## 快速开始

```bash
pip install -r requirements.txt
python main.py 
python main.py --mode phone #手机应用调试
```

## 日志

运行日志输出到 `logs/robot_dashboard.log`。


