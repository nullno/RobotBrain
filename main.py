import sys
import os

# 解析并移除自定义启动参数，防止 Kivy 报错 "option not recognized"
run_mode = None
argv_clean = []
i = 0
while i < len(sys.argv):
    if sys.argv[i] == "--mode" and i + 1 < len(sys.argv):
        run_mode = sys.argv[i+1]
        i += 2
    else:
        argv_clean.append(sys.argv[i])
        i += 1
sys.argv = argv_clean

from kivy.config import Config
from kivy.utils import platform
import argparse

Config.set('kivy', 'exit_on_escape', '1')

if platform in ("win", "linux", "macosx"):
    Config.set("graphics", "width", "900")
    Config.set("graphics", "height", "500")
    Config.set("graphics", "resizable", "0")  # 0=不可调整大小，1=可调整

from app.app_root import RobotDashboardApp

if __name__ == "__main__":
    if run_mode not in ["pc", "phone"]:
        run_mode = "pc" if platform in ("win", "linux", "macosx") else "phone"
    
    app = RobotDashboardApp()
    app.run_mode = run_mode
    app.run()
