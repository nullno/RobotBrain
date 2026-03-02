# 固件目录总览

本目录包含 ESP32 MicroPython 固件、烧录脚本及参考库。

结构：
- `esp32/`：主固件 `main.py`、默认配置 `esp32_config.json`（可选）。
- `flash.py`：基于 esptool 的烧录助手。
- `FLASHING.md`：中文烧录与部署指南（推荐先读）。
- `imuLib/`：IMU 相关示例/库（供参考）。
- `servo-micropython-esp32-sdk/`：舵机通信示例与 SDK（供参考）。

安装依赖：`pip install -r requirements.txt`

快速烧录(设备管理器查看串行设备端口；S3 板请加 `--chip esp32s3 --offset 0x0`)
```bash
python -m esptool --chip esp32s3 --port COM5 erase_flash
python flash.py --chip esp32s3 --offset 0x0 --port COM5 --baud 460800 --bin esp32/ESP32_GENERIC_S3-20251209-v1.27.0.bin
python cp.py #复制esp32目录下的程序到板子
mpremote connect COM5 reset
mpremote connect COM5 repl #测试是板子是否正常 端口是否可用 "import machine; machine.reset()"

```


详细步骤、协议说明见 [FLASHING.md](FLASHING.md)。