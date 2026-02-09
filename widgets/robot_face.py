import math
import random
from kivy.uix.widget import Widget
from kivy.clock import Clock
from kivy.graphics import (
    Color,
    RoundedRectangle,
    Line,
    Ellipse,
    StencilPush,
    StencilUse,
    StencilPop,
    StencilUnUse,
)
from app.theme import COLORS, FONT
from kivy.core.text import Label as CoreLabel
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.app import App
from widgets.runtime_status import RuntimeStatusLogger


class RobotFace(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.emotion = "normal"
        self.target_emotion = "normal"
        self.camera_view = None
        self.eye_scale = 1.0

        # ===== 动画状态 =====
        self.eye_open = 1.0
        self.target_eye_open = 1.0
        self.mouth_open = 0.0
        self.look_x = 0.0  # -1 ~ 1
        self.look_y = 0.0  # -1 ~ 1
        self.target_look_x = 0.0
        self.target_look_y = 0.0
        self.breath = 0.0

        # 说话状态
        self.talking = False
        self._talk_event = None

        # 自动眨眼
        Clock.schedule_interval(self._auto_blink, 3.2)

        # 呼吸灯动画
        Clock.schedule_interval(self._update_breath, 1 / 60)

        # 眼球运动动画
        Clock.schedule_interval(self._update_eye_motion, 1 / 60)

        # 情绪过渡
        Clock.schedule_interval(self._update_state, 1 / 60)

        self.bind(pos=self.draw, size=self.draw)

        # 说话字母显示缓冲
        self.speech_text = ""
        self._speech_clear_ev = None
        try:
            RuntimeStatusLogger.log_info("RobotFace 初始化完成")
        except Exception:
            pass

    def show_speaking_text(self, text, timeout=0.6):
        # 设置要显示的实时说话字母（短片段）
        try:
            self.speech_text = str(text)
        except Exception:
            self.speech_text = ""
        # 重置清除计时
        if self._speech_clear_ev:
            self._speech_clear_ev.cancel()
        self._speech_clear_ev = Clock.schedule_once(self._clear_speech_text, timeout)
        self.draw()

    def _clear_speech_text(self, dt=None):
        self.speech_text = ""
        self._speech_clear_ev = None
        self.draw()

    # def on_touch_down(self, touch):
    #     # 点击脸部弹出一个简易对话输入框，用于测试 AI 对话
    #     if self.collide_point(*touch.pos):
    #         self._open_ai_input()
    #         return True
    #     return super().on_touch_down(touch)

    def _open_ai_input(self):
        layout = BoxLayout(orientation="vertical", spacing=8, padding=8)
        ti = TextInput(
            hint_text="对机器人说些什么...",
            size_hint=(1, None),
            height=120,
            multiline=True,
            font_name=FONT,
        )
        btn_bar = BoxLayout(size_hint=(1, None), height=40)
        send = Button(text="发送")
        cancel = Button(text="取消")
        btn_bar.add_widget(cancel)
        btn_bar.add_widget(send)
        layout.add_widget(ti)
        layout.add_widget(btn_bar)

        popup = Popup(
            title="与机器人对话",
            content=layout,
            size_hint=(0.9, None),
            height=240,
            background="",
            background_color=(0, 0, 0, 0),
        )

        def _send(*args):
            txt = ti.text.strip()
            if txt:
                try:
                    app = App.get_running_app()
                    if hasattr(app, "ai_core") and app.ai_core:
                        app.ai_core.process_input(user_text=txt)
                except Exception:
                    pass
            popup.dismiss()

        send.bind(on_release=_send)
        cancel.bind(on_release=lambda *a: popup.dismiss())
        popup.open()

    # ================= 外部接口 =================
    def set_emotion(self, emo):
        self.target_emotion = emo
        try:
            RuntimeStatusLogger.log_info(f"RobotFace 情绪设为: {emo}")
        except Exception:
            pass

    def start_talking(self):
        if not self.talking:
            self.talking = True
            self._talk_event = Clock.schedule_interval(self._talk_step, 0.15)

    def stop_talking(self):
        self.talking = False
        if self._talk_event:
            self._talk_event.cancel()
            self._talk_event = None
        self.mouth_open = 0.0

    def look_at(self, x_norm, y_norm=0):
        self.target_look_x = max(-1, min(1, x_norm))
        self.target_look_y = max(-1, min(1, y_norm))

    def naughty_look(self):
        self.target_look_x = random.uniform(-1, 1)
        self.target_look_y = random.uniform(-1, 1)

    # ================= 动画系统 =================
    def _auto_blink(self, dt):
        self.target_eye_open = 0.0
        Clock.schedule_once(lambda dt: setattr(self, "target_eye_open", 1.0), 0.15)

    def _talk_step(self, dt):
        self.mouth_open = random.uniform(0.2, 1.0)

    def _update_breath(self, dt):
        self.breath += dt * 2
        if self.breath > math.pi * 2:
            self.breath = 0

    def _update_eye_motion(self, dt):
        speed = 6 * dt
        self.look_x += (self.target_look_x - self.look_x) * speed
        self.look_y += (self.target_look_y - self.look_y) * speed

        if not self.talking and random.random() < 0.01:
            self.naughty_look()

    def _update_state(self, dt):
        speed = 7 * dt
        self.eye_open += (self.target_eye_open - self.eye_open) * speed
        self.draw()

    # ================= 主绘制 =================
    def draw(self, *args):
        self.canvas.clear()
        base_color = COLORS.get(self.target_emotion, COLORS["primary"])
        w, h = self.size
        x, y = self.pos

        with self.canvas:
            self._draw_eyes(x, y, w, h, base_color)
            self._draw_mouth(x, y, w, h, base_color)

    # ================= 眼睛系统 =================
    def _draw_eyes(self, x, y, w, h, base_color):
        eye_w, eye_h = w * 0.28, h * 0.5 * self.eye_scale
        eyes_x = [x + w * 0.15, x + w * 0.57]
        eye_y = y + h * 0.35

        tex = None
        if self.camera_view and self.camera_view.texture:
            tex = self.camera_view.texture

        for idx, ex in enumerate(eyes_x):
            StencilPush()
            RoundedRectangle(pos=(ex, eye_y), size=(eye_w, eye_h), radius=[40])
            StencilUse()

            # ---------- 画视频或机器人眼底 ----------
            if tex:
                tw, th = tex.size
                scale = max(eye_w / tw, eye_h / th)
                draw_w = tw * scale * 1.5
                draw_h = th * scale * 1.5
                ox = (draw_w - eye_w) / 2
                oy = (draw_h - eye_h) / 2

                shift_x = self.look_x * eye_w * 0.12
                shift_y = self.look_y * eye_h * 0.1

                # 先绘制与嘴巴相同的背景色，避免纹理缩放时露出黑色边缘
                Color(base_color[0], base_color[1], base_color[2], 1.0)
                RoundedRectangle(pos=(ex, eye_y), size=(eye_w, eye_h), radius=[40])

                # 再绘制摄像头纹理（白色调保证颜色不变形）
                Color(1, 1, 1, 1)
                RoundedRectangle(
                    texture=tex,
                    pos=(ex - ox + shift_x, eye_y - oy + shift_y),
                    size=(draw_w, draw_h),
                )
            else:
                self._draw_robot_eye_base(ex, eye_y, eye_w, eye_h, base_color)

            # ---------- 眼皮（视频也会被遮） ----------
            self._draw_eyelids(ex, eye_y, eye_w, eye_h, self.eye_open)

            # ---------- 呼吸光效 ----------
            glow = 0.15 + 0.1 * math.sin(self.breath)
            Color(base_color[0], base_color[1], base_color[2], glow)
            RoundedRectangle(pos=(ex, eye_y), size=(eye_w, eye_h), radius=[40])

            StencilUnUse()
            StencilPop()

            # 眼睛轮廓与嘴巴使用同一色值，增加分层光晕（外层->中层->实线）
            r_col, g_col, b_col = base_color[0], base_color[1], base_color[2]
            # 外层柔和光（更大宽度、低透明度）
            Color(r_col, g_col, b_col, 0.18)
            Line(
                rounded_rectangle=(ex - 6, eye_y - 6, eye_w + 12, eye_h + 12, 44),
                width=20,
            )
            # 中层光晕
            Color(r_col, g_col, b_col, 0.34)
            Line(
                rounded_rectangle=(ex - 4, eye_y - 4, eye_w + 8, eye_h + 8, 42),
                width=10,
            )
            # 核心轮廓线（更粗）
            Color(r_col, g_col, b_col, 1.0)
            Line(
                rounded_rectangle=(ex - 3, eye_y - 3, eye_w + 6, eye_h + 6, 40),
                width=3.5,
            )

        # 如果有说话字母，显示在嘴部上方靠中间位置
        if self.speech_text:
            try:
                label = CoreLabel(text=self.speech_text, font_size=16, font_name=FONT)
                label.refresh()
                tex = label.texture
                tx = x + w * 0.5 - tex.size[0] / 2
                ty = y + h * 0.35
                Color(1, 1, 1, 0.95)
                Rectangle(texture=tex, pos=(tx, ty), size=tex.size)
            except Exception:
                pass

    # ---------- 无摄像头眼睛底图 ----------
    def _draw_robot_eye_base(self, ex, ey, ew, eh, color):
        r, g, b = color[:3]
        emo = self.target_emotion

        base_open = {
            "happy": 0.5,
            "sad": 0.7,
            "angry": 0.6,
            "surprised": 1.25,
            "sleepy": 0.3,
            "thinking": 0.9,
            "wink": 0.0,
        }.get(emo, 1.0)

        open_ratio = max(0.05, min(1.3, base_open))

        # 眼底
        Color(r, g, b, 0.25)
        RoundedRectangle(pos=(ex, ey), size=(ew, eh), radius=[40])

        # 瞳孔随眼球动
        pw = ew * 0.35
        ph = eh * 0.35 * open_ratio
        px = ex + ew * 0.5 - pw / 2 + self.look_x * ew * 0.18
        py = ey + eh * 0.5 - ph / 2 + self.look_y * eh * 0.15

        Color(1, 1, 1, 0.35)
        RoundedRectangle(pos=(px, py), size=(pw, ph), radius=[20])

    # ---------- 眼皮遮罩 ----------
    def _draw_eyelids(self, ex, ey, ew, eh, open_ratio):
        open_ratio = max(0.0, min(1.0, open_ratio))
        cover = eh * (1 - open_ratio)

        if cover <= 0:
            return

        # 眼皮改为不透明以遮挡视频或底图（眨眼时不透明）
        Color(0, 0, 0, 1.0)
        RoundedRectangle(pos=(ex, ey + eh - cover), size=(ew, cover), radius=[90])
        Color(0, 0, 0, 1.0)
        RoundedRectangle(pos=(ex, ey), size=(ew, cover * 0.35), radius=[50])

    # ================= 嘴巴系统 =================
    def _draw_mouth(self, x, y, w, h, color):
        r, g, b = color[0], color[1], color[2]
        mx, my = x + w * 0.4, y + h * 0.05
        mw = w * 0.2

        G_W, M_W, C_W = 35, 18, 10

        emo = self.target_emotion
        open_amt = self.mouth_open

        with self.canvas:
            pts = []
            steps = 40

            if emo == "happy":
                for i in range(steps + 1):
                    t = i / steps
                    px = mx + t * mw
                    py = my + 25 - 70 * (4 * (t - 0.5) ** 2) - open_amt * 15
                    pts.extend([px, py])

            elif emo == "sad":
                for i in range(steps + 1):
                    t = i / steps
                    px = mx + t * mw
                    py = my - 25 + 70 * (4 * (t - 0.5) ** 2) + open_amt * 15
                    pts.extend([px, py])

            elif emo == "angry":
                pts = [
                    mx,
                    my,
                    mx + mw * 0.3,
                    my + 15,
                    mx + mw * 0.6,
                    my - 15,
                    mx + mw,
                    my,
                ]

            elif emo == "surprised":
                size = mw * (0.3 + open_amt * 0.4)
                Color(r, g, b, 0.15)
                Ellipse(
                    pos=(mx + mw * 0.5 - size / 2, my - size / 2), size=(size, size)
                )
                Color(r, g, b, 0.5)
                Ellipse(
                    pos=(mx + mw * 0.5 - size * 0.45, my - size * 0.45),
                    size=(size * 0.9, size * 0.9),
                )
                Color(r, g, b, 1.0)
                Ellipse(
                    pos=(mx + mw * 0.5 - size * 0.35, my - size * 0.35),
                    size=(size * 0.7, size * 0.7),
                )
                return

            elif emo == "sleepy":
                pts = [mx, my, mx + mw, my]

            elif emo == "thinking":
                for i in range(steps + 1):
                    t = i / steps
                    px = mx + t * mw
                    py = my + math.sin(t * 2.5 * math.pi * 2) * 15
                    pts.extend([px, py])

            elif emo == "wink":
                pts = [mx, my, mx + mw * 0.4, my + 8, mx + mw * 0.8, my]

            else:
                pts = [mx, my, mx + mw, my]

            Color(r, g, b, 0.15)
            Line(points=pts, width=G_W, cap="round", joint="round")
            Color(r, g, b, 0.4)
            Line(points=pts, width=M_W, cap="round", joint="round")
            Color(r, g, b, 1.0)
            Line(points=pts, width=C_W, cap="round", joint="round")
