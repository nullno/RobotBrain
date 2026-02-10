from kivy.config import Config
from kivy.utils import platform


if platform in ("win", "linux", "macosx"):
    Config.set("graphics", "width", "1000")
    Config.set("graphics", "height", "500")
    Config.set("graphics", "resizable", "1")  # 0=不可调整大小，1=可调整

from app.app_root import RobotDashboardApp

if __name__ == "__main__":
    RobotDashboardApp().run()
