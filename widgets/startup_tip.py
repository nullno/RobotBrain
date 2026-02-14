from kivy.utils import platform
from widgets.universal_tip import UniversalTip


class StartupTip:
    def __init__(self, msg=None, icon='', **kwargs):
        # 居中提示文字 - 根据平台显示不同内容
        if platform == 'android':
            default_msg = '请允许摄像头麦克风权限\n点击"允许"完成权限申请\n确保 USB OTG 转接板已牢固连接'
        else:
            default_msg = '应用已启动\n请确保 USB OTG 转接板已牢固连接'
        self._tip = UniversalTip(
            title='',
            message=msg or default_msg,
            icon=icon or '提示',
            ok_text='知道了',
            auto_dismiss=True,
            show_buttons=True,
            **kwargs,
        )
        self._popup = None

    def _on_ok(self, *args):
        try:
            if self._popup:
                self._popup.dismiss()
        except Exception:
            pass

    def open(self):
        self._tip.open()
        self._popup = getattr(self._tip, '_popup', None)
