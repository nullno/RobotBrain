import os
import sys

# Ensure UART SDK src is importable
here = os.path.dirname(__file__)
sdk_src = os.path.join(here, "UART_PythonSDK", "src")
if sdk_src not in sys.path:
    sys.path.insert(0, sdk_src)

from panel import DebugPanelApp


if __name__ == '__main__':
    DebugPanelApp().run()
