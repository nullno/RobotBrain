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
```

## 日志

运行日志输出到 `logs/robot_dashboard.log`。


1.初始化界面检测配网时 不加载主界面（表情 陀螺仪imu指示 连接状态 日志状态），待弹出esp32_setup.py流程走完再进入主界面
2.主界面日志面板（runtime_status.py）的内容调整成可复制；
3.主界面的连接状态需要单独抽离一个组件放到widgets，再加载渲染；整体业务逻辑做到模块清晰，还有什么优化可以一起抽离 或者精简代码（不要动额可以移除），现在app_root.py 代码太长了
4.重构陀螺仪指示（gyro_panel.py），在主界面左上角绘制一个迷你三维小人，来显示空间姿态；
5.在已连接设备的情况下: 调试面板中的 快捷动作 舵机连接状态 关节调试中的功能操作无法和esp32数据通信，固件程序a_Firmware/esp32 需要参考servo-micropython-esp32-sdk/example 的示例来编写指令程序（单独编写模块加载main.py中使用，源代码的引入uservo sdk也挪到这个模块，做到功能划分清晰可可扩展，后续还要追加imu，摄像头传感器等数据固件程序）；主控程序则需要编写对应的wifi_servo.py通信，来发送和接受数据，已便能正常的控制舵机和接受舵机状态数据渲染到舵机连接状态卡片，同时要做好两个程序日志输出，以便可以观察两个程序互相数据传输的状态日志，更好调试检查


请完成下面任务：不要生成错误代码和乱码和异常编码文件，保证代码的稳健可靠：
1.主程序不要频繁的发送udp心跳；10秒钟检测一次，要有失败重试机制；
2.调试面板连接状态，要显示全部25个卡片，不要只显示已连接的；
3.现在wifi操作舵机基本已连通可以正常控制了；但还是有些问题，要优化细节：调试面板的关节调试归零、首次获取状态没有反应，旋钮操作舵机时动时不动，不丝滑不跟手，要优化算法;还要优化固件舵机控制程序（a_Firmware/esp32）要进行插值平滑算法，让机器人运动的更自然顺畅；
4.固件 a_Firmware/esp32/servo_controller.py ,参考usb串口控制的功能方案（UART_PythonSDK2025）为我们固件程序新增更全的功能方法，目前只能读取到角度，无法读取完整的舵机状态信息（温度电压等）；
5.建立连接后，主程序可以随时从esp32设备获取数据和发送数据即无顿挫感与舵机交互，比如打开调试面板的连接状态；马上就可以观察到 25个舵机的连接在线情况
6.移除主程序中的姿态管理代码（balance_runtime.py，balance_ctrl.py，imu.py 等）， imu姿态管理应该只存在于固件（a_Firmware/esp32）中计算，后续我会连接IMU 传感器，新建一个模块用于后续机器人姿态平衡计算；主程序只通过wifi通信实时获取姿态数据 渲染到gyro_panel.py 组件， 没有连接的情况下可以生成模拟数据；
7.基于imu和舵机执行指令，在固件a_Firmware/esp32里可以完善人性机器人动态平衡算法了,下面是我的舵机分布：
```
颈部2个【左右头部转动、上下抬头】
左/右手各5个【肩部旋转（前后摆臂）、 手臂抬起、 手大臂旋转、 臂腕弯曲、 手部抓取（正转拉经夹取反转释放）】
腰部1个 【左右旋转上肢身体】
左/右腿各6个 【跨部旋转（前后摆腿行走）、 大腿臂抬起、 腿大臂旋转、 膝盖弯曲、 脚腕左右摆动（控制身体平衡关键）、脚腕前后摆动（控制身体平衡关键）】
```
8.基于步骤7,帮我生成一份md装机文档，装机位置、编号、和合理设置装机角度等说明文档
