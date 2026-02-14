from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.popup import Popup
from kivy.graphics import Color, RoundedRectangle
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.utils import platform
import os


def _pick_emoji_font():
    candidates = [
        'assets/fonts/NotoColorEmoji.ttf',
        'assets/fonts/NotoEmoji-Regular.ttf',
        'assets/fonts/simhei.ttf',
        r'C:\\Windows\\Fonts\\seguiemj.ttf',
        '/system/fonts/NotoColorEmoji.ttf',
        '/system/fonts/NotoColorEmoji-Regular.ttf',
        '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf',
        '/System/Library/Fonts/Apple Color Emoji.ttc',
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                return p
        except Exception:
            pass
    return None


class UniversalTip(BoxLayout):
    """通用提示弹窗组件（样式对齐 StartupTip，可配置单/双按钮）。"""

    def __init__(
        self,
        message,
        title="",
        icon="💡",
        icon_path="assets/icon_tip.png",
        ok_text="知道了",
        cancel_text=None,
        on_ok=None,
        on_cancel=None,
        auto_dismiss=True,
        auto_close_seconds=0,
        show_buttons=True,
        **kwargs,
    ):
        super().__init__(
            orientation="vertical",
            spacing=dp(8),
            padding=dp(12),
            size_hint=(None, None),
            **kwargs,
        )
        self._base_width = dp(400)
        self.width = self._base_width
        self.height = dp(160)
        self._popup = None

        self._title = title
        self._message = message
        self._ok_text = ok_text
        self._cancel_text = cancel_text
        self._on_ok = on_ok
        self._on_cancel = on_cancel
        self._auto_dismiss = auto_dismiss
        self._auto_close_seconds = float(auto_close_seconds or 0)
        self._show_buttons = bool(show_buttons)
        self._auto_close_ev = None
        self._title_lbl = None
        self._msg_lbl = None
        self._icon_box = None
        self._btn_row = None
        self._emoji_font = _pick_emoji_font()
        try:
            self._message = str(self._message).replace("\ufe0f", "")
            self._title = str(self._title).replace("\ufe0f", "")
            icon = str(icon).replace("\ufe0f", "")
        except Exception:
            pass

        with self.canvas.before:
            Color(0.0, 0.9, 1.0, 0.9)
            self._border = RoundedRectangle(
                pos=(self.x - dp(2), self.y - dp(2)),
                size=(self.width + dp(4), self.height + dp(4)),
                radius=[12],
            )
            Color(0, 0, 0, 0.65)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[10])

        self.bind(pos=self._update_rects, size=self._update_rects)

        icon_widget = None
        if icon_path and os.path.exists(icon_path):
            try:
                icon_widget = Image(
                    source=icon_path,
                    size_hint=(None, None),
                    size=(dp(48), dp(48)),
                )
            except Exception:
                icon_widget = None

        if not icon_widget:
            icon_kwargs = {}
            if self._emoji_font:
                icon_kwargs['font_name'] = self._emoji_font
            icon_widget = Label(
                text=icon,
                font_size="30sp",
                size_hint=(None, None),
                size=(dp(48), dp(48)),
                halign="center",
                valign="middle",
                **icon_kwargs,
            )
            icon_widget.bind(size=lambda inst, val: setattr(inst, "text_size", val))

        icon_box = AnchorLayout(
            anchor_x="center", anchor_y="center", size_hint=(1, None), height=dp(56)
        )
        icon_box.add_widget(icon_widget)
        self._icon_box = icon_box

        if self._title:
            title_kwargs = {}
            if self._emoji_font:
                title_kwargs['font_name'] = self._emoji_font
            title_lbl = Label(
                text=self._title,
                size_hint=(1, None),
                height=dp(24),
                color=(0.85, 0.95, 1, 1),
                font_size="16sp",
                bold=True,
                halign="center",
                valign="middle",
                **title_kwargs,
            )
            title_lbl.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
            self.add_widget(title_lbl)
            self._title_lbl = title_lbl

        msg_kwargs = {}
        if self._emoji_font:
            msg_kwargs['font_name'] = self._emoji_font
        msg_lbl = Label(
            text=self._message,
            size_hint=(1, None),
            height=dp(28),
            font_size="16sp",
            halign="center",
            valign="middle",
            color=(1, 1, 1, 1),
            **msg_kwargs,
        )
        msg_lbl.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
        self._msg_lbl = msg_lbl

        self.add_widget(icon_box)
        self.add_widget(msg_lbl)
        if self._show_buttons:
            btn_row = BoxLayout(size_hint=(1, None), height=dp(42), spacing=dp(8))
            if self._cancel_text:
                btn_cancel = Button(text=self._cancel_text, background_normal="")
                btn_cancel.background_color = (1, 1, 1, 0.06)
                btn_cancel.color = (0.9, 0.95, 1, 1)
                btn_cancel.bind(on_release=self._handle_cancel)
                btn_row.add_widget(btn_cancel)

            btn_ok = Button(text=self._ok_text, background_normal="")
            btn_ok.background_color = (0.0, 0.9, 1.0, 0.2)
            btn_ok.color = (1, 1, 1, 1)
            btn_ok.bind(on_release=self._handle_ok)
            btn_row.add_widget(btn_ok)
            self.add_widget(btn_row)
            self._btn_row = btn_row

        self.bind(width=lambda *_: self._refresh_content_height())
        Clock.schedule_once(lambda dt: self._refresh_content_height(), 0)

    def _update_rects(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size
        self._border.pos = (self.x - dp(2), self.y - dp(2))
        self._border.size = (self.width + dp(4), self.height + dp(4))

    def _refresh_content_height(self):
        try:
            pad = self.padding
            if isinstance(pad, (int, float)):
                pad_l = pad_r = pad_t = pad_b = float(pad)
            elif len(pad) >= 4:
                pad_l, pad_t, pad_r, pad_b = [float(x) for x in pad[:4]]
            elif len(pad) == 2:
                pad_l = pad_r = float(pad[0])
                pad_t = pad_b = float(pad[1])
            else:
                pad_l = pad_r = pad_t = pad_b = dp(12)

            content_w = max(dp(120), self.width - pad_l - pad_r)

            title_h = 0
            if self._title_lbl is not None:
                self._title_lbl.text_size = (content_w, None)
                self._title_lbl.texture_update()
                title_h = max(dp(24), self._title_lbl.texture_size[1] + dp(4))
                self._title_lbl.height = title_h

            msg_h = dp(28)
            if self._msg_lbl is not None:
                self._msg_lbl.text_size = (content_w, None)
                self._msg_lbl.texture_update()
                msg_h = max(dp(28), self._msg_lbl.texture_size[1] + dp(6))
                self._msg_lbl.height = msg_h

            icon_h = self._icon_box.height if self._icon_box is not None else 0
            btn_h = self._btn_row.height if self._btn_row is not None else 0

            visible_count = 2 + (1 if title_h > 0 else 0) + (1 if btn_h > 0 else 0)
            spacing_total = self.spacing * max(0, visible_count - 1)

            min_h = dp(120) if btn_h <= 0 else dp(140)
            target_h = pad_t + pad_b + icon_h + title_h + msg_h + btn_h + spacing_total
            self.height = max(min_h, target_h)

            if self._popup:
                self._popup.size = (self.width, self.height)
        except Exception:
            pass

    def _handle_ok(self, *args):
        try:
            if callable(self._on_ok):
                self._on_ok()
        except Exception:
            pass
        if self._auto_dismiss and self._popup:
            self._popup.dismiss()

    def _handle_cancel(self, *args):
        try:
            if callable(self._on_cancel):
                self._on_cancel()
        except Exception:
            pass
        if self._auto_dismiss and self._popup:
            self._popup.dismiss()

    def open(self):
        w = self._base_width if platform != "android" else self._base_width * 0.9
        self.width = w
        self._refresh_content_height()
        if not self._popup:
            self._popup = Popup(
                title="",
                content=self,
                size_hint=(None, None),
                size=(self.width, self.height),
                auto_dismiss=False,
                background="",
                background_color=(0, 0, 0, 0),
                separator_height=0,
            )
        else:
            self._popup.size = (self.width, self.height)
        self._popup.open()
        if self._auto_close_seconds > 0:
            try:
                if self._auto_close_ev is not None:
                    self._auto_close_ev.cancel()
            except Exception:
                pass

            def _dismiss(_dt):
                try:
                    if self._popup:
                        self._popup.dismiss()
                except Exception:
                    pass

            self._auto_close_ev = Clock.schedule_once(_dismiss, self._auto_close_seconds)
