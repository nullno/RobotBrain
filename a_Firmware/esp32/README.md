ESP32 固件（MicroPython）
=========================

功能概述
- 在局域网通过 UDP 接收主控发送的关键帧（targets + duration），对关键帧做插值并通过 UART（连接 CH340 -> 舵机驱动板）发送 JOHO sync_write 帧。
- 支持局域网发现（discover）、配网（provision）、配对（pair/set_host）、心跳/状态查询（ping/status）、远程停止（stop）、重启与恢复出厂（reboot/factory_reset）。
- 支持读取 MPU6050（I2C）作为 IMU 并周期性把 telemetry 发送到已配对主机。

默认位置
- 固件主脚本：`firmware/esp32/main.py`
- 默认配置文件：`firmware/esp32/esp32_config.json`

启动与配网流程
1. 启动时固件会读取 `esp32_config.json`。
2. 若其中包含 `wifi` 信息，会尝试以 STA 模式连接该 Wi‑Fi；若连接失败或无 Wi‑Fi 配置，会启动 AP（SSID 默认为 `device_name` 字段），以便手机/PC 连接并发送 `provision` 消息。
3. 主控通过 UDP 向设备发送以下消息以配网与配对。

UDP 消息格式（JSON）
- discover: 广播发现设备
  {"type": "discover"}

- provision: 在设备处于 AP 或可达网络时发送 Wi‑Fi 凭据
  {"type": "provision", "ssid": "MySSID", "password": "MyPass"}

- pair / set_host: 将主控 IP:port 持久化到设备，用于 telemetry 发送
  {"type": "pair", "host": "192.168.1.100", "port": 5005}

- ping: 测试连通性
  {"type": "ping"}

- status: 请求设备状态
  {"type": "status"}

- stop: 紧急停止当前动作（可中断关键帧插值）
  {"type": "stop"}

- reboot: 远程重启设备
  {"type": "reboot"}

- factory_reset: 删除 `esp32_config.json` 后重启
  {"type": "factory_reset"}

- keyframe（默认类型）: 发送关键帧控制舵机
  {"targets": {"1": 1500, "2": 1500}, "duration": 500}

固件响应示例
- discover_resp: {"type": "discover_resp", "device": "esp32", "port": 5005, "ip": "192.168.1.50", "mac": "..."}
- provision_resp: {"type": "provision_resp", "ok": true, "ip": "192.168.1.50"}
- pair_resp / stop_resp / reboot_resp / factory_reset_resp: 各自包含字段 `ok` 表示结果
- status_resp: 包含 `wifi_connected`, `ip`, `last_positions`, `imu`, `uptime_ms` 等

Telemetry
- 若设备已配对主控（通过 `pair` 保存 host），固件会按 `telemetry_interval_ms` 将 IMU 与 uptime 发送到主控：
  {"type":"telemetry","uptime_ms":12345,"imu":{...}}

刷写与调试
- 将文件拷贝到设备（示例使用 `mpremote`）：
  mpremote connect serial:/dev/ttyUSB0 fs put firmware/esp32/* :/flash/
  mpremote connect serial:/dev/ttyUSB0 exec "import machine; machine.reset()"

注意事项
- 请确认 UART 与 CH340/舵机驱动板的电压兼容，避免直接将 5V TTL 接入 3.3V MCU TX。
- 若使用不同型号 IMU，请修改 `init_imu` 与 `read_imu` 实现。

调试建议
- 使用 `tools/esp32_test.py` 进行 discover / provision / ping / send 测试。
ESP32 MicroPython 固件示例

说明：
- 监听 UDP 端口 5005，接收 JSON 格式关键帧：
  {
    "targets": {"1": 1500, "2": 1500},
    "duration": 300
  }
- 对关键帧进行线性插值（STEP_MS = 20ms），并通过 UART 以 JOHO 协议发送 sync_write 指令到舵机驱动板。

注意事项：
- 需要将 UART TX/RX 连接到 CH340.TTL 侧并确认电压兼容性（通常为 3.3V）。
- 当前固件未实现局域网发现（discovery）与配网（provisioning），建议添加对广播 discovery 的应答及配网消息的处理。
- 修改 `UART_TX_PIN` 等常量以匹配硬件引脚。

示例：
- 从主机发送：
  `{"targets": {"1": 1024, "2": 2048}, "duration": 500}`

作者：由 Copilot 自动生成示例固件，需在真实硬件上测试并根据需求改进。
