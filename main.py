# from kivy.config import Config

# # 在创建 App 之前设置
# Config.set('graphics', 'width', '900')
# Config.set('graphics', 'height', '400')
# Config.set('graphics', 'resizable', '0')  # 0=不可调整大小，1=可调整

from app.app_root import RobotDashboardApp

if __name__ == "__main__":
    RobotDashboardApp().run()
