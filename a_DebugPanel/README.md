# 舵机调试面板（串口调试）

概述
- 使用 Kivy 实现的舵机串口调试面板（科技浅蓝风格）。
- 支持通过 CH340 类型 USB 转串口与舵机驱动板通信，支持热插拔检测。
- 集成已存在的 UART SDK（位于 `UART_PythonSDK/src`）。

快速开始
1. 安装依赖：
```
pip install -r requirements.txt
```
2. 运行应用：
```
python main.py
```

目录说明
- `main.py`：应用入口。
- `panel.py`：Kivy App 与 UI 逻辑。
- `debug_panel.kv`：界面布局与样式。
- `serial_manager.py`：串口检测与包装（支持热插拔）。
- `knob.py`：简单的拟物旋钮控件实现。
- `UART_PythonSDK/src`：已有的 SDK（无需复制）。

注意
- 本项目假设 `UART_PythonSDK/src` 下的模块可直接导入；`main.py` 已将其加入 `sys.path`。
- 若需打包到可执行文件，请根据目标平台调整 Kivy 的打包配置。
# 关节调试面板
