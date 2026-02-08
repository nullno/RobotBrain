测试目录说明

本目录提供若干用于现场调试与装配的脚本（仅供工程调试使用，不随产品打包）：

脚本列表：
- `test_motion.py`：示例运动流程（站立、挥手、行走、坐起），可用于功能验证。
- `servo_zero_and_id.py`：舵机归零/示教并可写入舵机 ID，便于组装与安装调试。
- `test_servo_basic.py`：基础舵机读写示例（读取当前位置、温度、电压、扭矩开/关）。

使用注意：
- 运行脚本前请确保串口连接和电源正确，周围无危险物体。
- 运行前务必确认安全（人员远离、舵机固定），在不确定时输入 n 退出。
- 这些脚本会尝试调用项目内 `services` 下的模块；运行脚本时会自动把项目根路径加入 `sys.path`。

命令示例：

Windows:
```powershell
python tools\testbench\test_motion.py
python tools\testbench\servo_zero_and_id.py
```

Linux/macOS:
```bash
python3 tools/testbench/test_motion.py
python3 tools/testbench/servo_zero_and_id.py
```
