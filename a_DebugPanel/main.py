import os
import sys
from kivy.config import Config
from kivy.utils import platform

Config.set('kivy', 'exit_on_escape', '1')

if platform in ("win", "linux", "macosx"):
    Config.set("graphics", "width", "800")
    Config.set("graphics", "height", "600")
    Config.set("graphics", "resizable", "0")  # 0=不可调整大小，1=可调整

# Ensure UART SDK src is importable
here = os.path.dirname(__file__)
sdk_src = os.path.join(here, "UART_PythonSDK", "src")
if sdk_src not in sys.path:
    sys.path.insert(0, sdk_src)

from panel import DebugPanelApp


if __name__ == '__main__':
    DebugPanelApp().run()
