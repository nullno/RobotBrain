from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.popup import Popup
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.utils import platform
import os


class StartupTip(BoxLayout):
    def __init__(self, msg=None, icon='', **kwargs):
        super().__init__(orientation='vertical', spacing=8, padding=12, size_hint=(None, None), **kwargs)
        self.width = dp(400)  # 适合手机屏幕的宽度
        # 根据平台调整高度：Android需要权限提示文本
        self.height = dp(200) if platform == 'android' else dp(200)

        with self.canvas.before:
            # 外层荧光边框（略大于内层）
            Color(0.0, 0.9, 1.0, 0.9)
            self._border = RoundedRectangle(pos=(self.x - dp(2), self.y - dp(2)), size=(self.width + dp(4), self.height + dp(4)), radius=[12])
            # 内层半透明卡片
            Color(0, 0, 0, 0.6)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[10])
        self.bind(pos=lambda inst, val: setattr(self._rect, 'pos', self.pos))
        self.bind(size=lambda inst, val: setattr(self._rect, 'size', self.size))
        self.bind(pos=lambda inst, val: setattr(self._border, 'pos', (self.x - dp(2), self.y - dp(2))))
        self.bind(size=lambda inst, val: setattr(self._border, 'size', (self.width + dp(4), self.height + dp(4))))

        # 顶部图标（居顶），优先使用 assets/icon_tip.svg
        icon_widget = None
        icon_path = kwargs.pop('icon_path', 'assets/icon_tip.png')
        if os.path.exists(icon_path):
            try:
                icon_widget = Image(source=icon_path, size_hint=(None, None), size=(48, 48))
            except Exception:
                icon_widget = None

        if not icon_widget:
            icon_widget = Label(text=icon, font_size='32sp', size_hint=(None, None), size=(48, 48), halign='center', valign='middle')
            icon_widget.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))

        icon_container = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, None), height=56)
        icon_container.add_widget(icon_widget)
        # 居中提示文字 - 根据平台显示不同内容
        if platform == 'android':
            default_msg = '请允许摄像头麦克风权限\n点击"允许"完成权限申请\n确保 USB OTG 转接板已牢固连接'
        else:
            default_msg = '应用已启动\n按下面板按钮开始调试'
        
        lbl = Label(text=msg or default_msg, font_size='20sp', halign='center', valign='middle')
        lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))

        # 底部按钮：在 Android 上增大高度以便触控
        btn_height = dp(56) if platform == 'android' else dp(40)
        btn = Button(text='知道了', size_hint=(1, None), height=btn_height, background_normal='')
        btn.background_color = (1, 1, 1, 0.08)
        btn.color = (1, 1, 1, 1)
        btn.bind(on_release=self._on_ok)

        self.add_widget(icon_container)
        self.add_widget(lbl)
        self.add_widget(btn)

        self._popup = None

    def _on_ok(self, *args):
        if self._popup:
            self._popup.dismiss()

    def open(self):
        if not self._popup:
            self._popup = Popup(
                title='',
                content=self,
                size_hint=(None, None),
                # 在手机上适配为屏幕宽度的 90% 和更高的高度
                size=(self.width if platform != 'android' else self.width * 0.9, self.height if platform != 'android' else self.height * 1.1),
                auto_dismiss=False,
                background='',
                background_color=(0, 0, 0, 0),
                separator_height=0,
            )
        self._popup.open()
