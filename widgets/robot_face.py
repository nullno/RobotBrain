import math
import random
from kivy.uix.widget import Widget
from kivy.clock import Clock
from kivy.graphics import (
    Color,
    RoundedRectangle,
    Line,
    Ellipse,
    Rectangle,
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
        self._prev_emotion = "normal"
        self._emotion_blend = 1.0
        self.camera_view = None
        self.eye_scale = 1.0

        # ===== 动画状态 =====
        self.eye_open = 1.0
        self.target_eye_open = 1.0
        self.mouth_open = 0.0
        self.target_mouth_open = 0.0
        self.look_x = 0.0  # -1 ~ 1
        self.look_y = 0.0  # -1 ~ 1
        self.target_look_x = 0.0
        self.target_look_y = 0.0
        self.breath = 0.0

        # 说话状态
        self.talking = False
        self._talk_event = None
        self._talk_pattern = [(0.34, 1), (0.48, 1), (0.82, 2)]  # 短-短-长
        self._talk_pattern_index = 0
        self._talk_hold_remaining = 0
        self._talk_current_level = 0.0
        self._draw_pending = False
        self._force_draw = True
        self._last_draw_snapshot = None
        self._speech_text_cached = None
        self._speech_texture_cached = None

        # 自动眨眼
        blink_interval = 3.6
        Clock.schedule_interval(self._auto_blink, blink_interval)

        anim_interval = 1.0 / 30.0

        # 呼吸灯动画
        Clock.schedule_interval(self._update_breath, anim_interval)

        # 眼球运动动画
        Clock.schedule_interval(self._update_eye_motion, anim_interval)

        # 情绪过渡
        Clock.schedule_interval(self._update_state, anim_interval)

        self.bind(pos=lambda *_: self.request_draw(force=True))
        self.bind(size=lambda *_: self.request_draw(force=True))

        # 说话字母显示缓冲
        self.speech_text = ""
        self._speech_clear_ev = None
        try:
            RuntimeStatusLogger.log_info("RobotFace 初始化完成")
        except Exception:
            pass
        self.request_draw(force=True)

    def _snapshot(self):
        tex_obj = None
        try:
            if self.camera_view is not None:
                tex_obj = getattr(self.camera_view, "texture", None)
        except Exception:
            tex_obj = None
        return (
            round(float(self.eye_open), 3),
            round(float(self.target_eye_open), 3),
            round(float(self.mouth_open), 3),
            round(float(self.look_x), 3),
            round(float(self.look_y), 3),
            round(float(self.breath), 3),
            str(self.target_emotion),
            str(self.speech_text or ""),
            int(self.width),
            int(self.height),
            int(self.x),
            int(self.y),
            id(tex_obj),
        )

    def request_draw(self, force=False):
        if force:
            self._force_draw = True
        if self._draw_pending:
            return
        self._draw_pending = True
        Clock.schedule_once(self._draw_if_needed, 0)

    def _draw_if_needed(self, dt=0):
        self._draw_pending = False
        try:
            snap = self._snapshot()
            if (not self._force_draw) and (snap == self._last_draw_snapshot):
                return
            self._force_draw = False
            self._last_draw_snapshot = snap
            self.draw()
        except Exception:
            try:
                self.draw()
            except Exception:
                pass

    def _get_speech_texture(self):
        text = str(self.speech_text or "")
        if not text:
            return None
        if text == self._speech_text_cached and self._speech_texture_cached is not None:
            return self._speech_texture_cached
        try:
            label = CoreLabel(text=text, font_size=16, font_name=FONT)
            label.refresh()
            self._speech_text_cached = text
            self._speech_texture_cached = label.texture
            return self._speech_texture_cached
        except Exception:
            return None

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
        self.request_draw(force=True)

    def _clear_speech_text(self, dt=None):
        self.speech_text = ""
        self._speech_text_cached = None
        self._speech_texture_cached = None
        self._speech_clear_ev = None
        self.request_draw(force=True)

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
        new_emo = str(emo or "normal")
        if new_emo == self.target_emotion:
            return
        self._prev_emotion = self.target_emotion
        self.target_emotion = new_emo
        self._emotion_blend = 0.0
        self.request_draw()
        # try:
        #     RuntimeStatusLogger.log_info(f"RobotFace 情绪设为: {emo}")
        # except Exception:
        #     pass

    def start_talking(self):
        if not self.talking:
            self.talking = True
            self._talk_pattern_index = 0
            self._talk_hold_remaining = 0
            self._talk_current_level = 0.25
            self.target_mouth_open = max(0.18, self.target_mouth_open)
            self._talk_event = Clock.schedule_interval(self._talk_step, 0.15)
            self.request_draw()

    def stop_talking(self):
        self.talking = False
        if self._talk_event:
            self._talk_event.cancel()
            self._talk_event = None
        self._talk_hold_remaining = 0
        self.target_mouth_open = 0.0
        self.request_draw()

    def look_at(self, x_norm, y_norm=0):
        self.target_look_x = max(-1, min(1, x_norm))
        self.target_look_y = max(-1, min(1, y_norm))
        self.request_draw()

    def naughty_look(self):
        self.target_look_x = random.uniform(-1, 1)
        self.target_look_y = random.uniform(-1, 1)

    # ================= 动画系统 =================
    def _auto_blink(self, dt):
        self.target_eye_open = 0.0
        Clock.schedule_once(lambda dt: setattr(self, "target_eye_open", 1.0), 0.15)

    def _talk_step(self, dt):
        if self._talk_hold_remaining > 0:
            self._talk_hold_remaining -= 1
            base_level = self._talk_current_level
        else:
            base_level, hold_steps = self._talk_pattern[self._talk_pattern_index]
            self._talk_pattern_index = (self._talk_pattern_index + 1) % len(self._talk_pattern)
            self._talk_hold_remaining = max(0, int(hold_steps) - 1)
            self._talk_current_level = float(base_level)

        # 不同情绪的口型力度缩放
        emo_scale = {
            "happy": 1.05,
            "sad": 0.88,
            "angry": 1.1,
            "surprised": 1.2,
            "sleepy": 0.72,
            "thinking": 0.86,
            "wink": 0.92,
        }.get(str(self.target_emotion), 1.0)

        # 语流中的短停顿：模拟自然断句
        if random.random() < 0.12:
            target = random.uniform(0.08, 0.2)
            self._talk_hold_remaining = 0
        else:
            jitter = random.uniform(-0.06, 0.06)
            target = (base_level + jitter) * emo_scale

        self.target_mouth_open = max(0.06, min(1.0, target))
        self.request_draw()

    def _update_breath(self, dt):
        self.breath += dt * 2
        if self.breath > math.pi * 2:
            self.breath = 0
        self.request_draw()

    def _update_eye_motion(self, dt):
        speed = 6 * dt
        prev_x = self.look_x
        prev_y = self.look_y
        self.look_x += (self.target_look_x - self.look_x) * speed
        self.look_y += (self.target_look_y - self.look_y) * speed
        if abs(self.look_x - prev_x) > 0.001 or abs(self.look_y - prev_y) > 0.001:
            self.request_draw()

        if not self.talking and random.random() < 0.01:
            self.naughty_look()

    def _update_state(self, dt):
        speed = 7 * dt
        prev_eye = self.eye_open
        self.eye_open += (self.target_eye_open - self.eye_open) * speed
        if abs(self.eye_open - prev_eye) > 0.001:
            self.request_draw()

        mouth_speed = 11 * dt
        prev_mouth = self.mouth_open
        self.mouth_open += (self.target_mouth_open - self.mouth_open) * mouth_speed
        if abs(self.mouth_open - prev_mouth) > 0.001:
            self.request_draw()

        if self._emotion_blend < 1.0:
            prev_blend = self._emotion_blend
            self._emotion_blend = min(1.0, self._emotion_blend + dt * 5.0)
            if abs(self._emotion_blend - prev_blend) > 0.0001:
                self.request_draw()

    # ================= 主绘制 =================
    def draw(self, *args):
        self.canvas.clear()
        prev_color = COLORS.get(self._prev_emotion, COLORS["primary"])
        target_color = COLORS.get(self.target_emotion, COLORS["primary"])
        blend = max(0.0, min(1.0, self._emotion_blend))
        base_color = (
            prev_color[0] + (target_color[0] - prev_color[0]) * blend,
            prev_color[1] + (target_color[1] - prev_color[1]) * blend,
            prev_color[2] + (target_color[2] - prev_color[2]) * blend,
            1.0,
        )
        w, h = self.size
        x, y = self.pos

        with self.canvas:
            self._draw_eyes(x, y, w, h, base_color)
            if self._prev_emotion != self.target_emotion and blend < 1.0:
                self._draw_eyebrows(
                    x,
                    y,
                    w,
                    h,
                    prev_color,
                    emo_override=self._prev_emotion,
                    alpha=(1.0 - blend),
                )
                self._draw_mouth(
                    x,
                    y,
                    w,
                    h,
                    prev_color,
                    emo_override=self._prev_emotion,
                    alpha=(1.0 - blend),
                )
            self._draw_eyebrows(
                x,
                y,
                w,
                h,
                target_color,
                emo_override=self.target_emotion,
                alpha=blend,
            )
            self._draw_mouth(
                x,
                y,
                w,
                h,
                target_color,
                emo_override=self.target_emotion,
                alpha=blend,
            )

    def _draw_eyebrows(self, x, y, w, h, color, emo_override=None, alpha=1.0):
        alpha = max(0.0, min(1.0, float(alpha)))
        if alpha <= 0.001:
            return

        eye_w, eye_h = w * 0.28, h * 0.5 * self.eye_scale
        eyes_x = [x + w * 0.15, x + w * 0.57]
        eye_y = y + h * 0.35

        r, g, b = color[0], color[1], color[2]
        emo = str(emo_override or self.target_emotion)
        glow_w, mid_w, core_w = 35, 18, 10

        for idx, ex in enumerate(eyes_x):
            x0 = ex + eye_w * 0.08
            x2 = ex + eye_w * 0.92
            x1 = (x0 + x2) * 0.5

            talk_raise = self.mouth_open * h * 0.012 if self.talking else 0.0
            eye_squeeze = (1.0 - max(0.0, min(1.0, self.eye_open))) * h * 0.004
            brow_base_y = eye_y + eye_h + h * 0.09 - self.look_y * eye_h * 0.06 + talk_raise - eye_squeeze
            breath_jitter = math.sin(self.breath + idx * 0.8) * h * 0.004
            gaze_tilt = self.look_x * h * 0.008

            outer_raise = 0.0
            inner_raise = 0.0
            arch_lift = h * 0.018

            if emo == "happy":
                outer_raise = h * 0.05
                inner_raise = h * 0.046
                arch_lift = h * 0.048
            elif emo == "sad":
                outer_raise = -h * 0.03
                inner_raise = h * 0.052
                arch_lift = h * 0.004
            elif emo == "angry":
                outer_raise = h * 0.036
                inner_raise = -h * 0.045
                arch_lift = h * 0.002
            elif emo == "surprised":
                outer_raise = h * 0.062
                inner_raise = h * 0.062
                arch_lift = h * 0.052
            elif emo == "sleepy":
                outer_raise = -h * 0.026
                inner_raise = -h * 0.02
                arch_lift = h * 0.002
            elif emo == "thinking":
                outer_raise = h * 0.008
                inner_raise = h * 0.01
                if idx == 1:
                    outer_raise += h * 0.034
                    inner_raise += h * 0.038
                    arch_lift = h * 0.026
                else:
                    arch_lift = h * 0.014
            elif emo == "wink":
                outer_raise = h * 0.006
                inner_raise = h * 0.006
                wink_side = 0 if self.look_x <= 0 else 1
                if idx == wink_side:
                    outer_raise += h * 0.032
                    inner_raise += h * 0.032
                arch_lift = h * 0.018
            else:
                outer_raise = h * 0.004
                inner_raise = h * 0.005
                arch_lift = h * 0.016

            if idx == 0:
                outer_raise -= gaze_tilt * 0.4
                inner_raise += gaze_tilt * 0.4
            else:
                outer_raise += gaze_tilt * 0.4
                inner_raise -= gaze_tilt * 0.4

            # 左眼：内侧在右；右眼：内侧在左
            if idx == 0:
                y0 = brow_base_y + outer_raise + breath_jitter
                y2 = brow_base_y + inner_raise + breath_jitter
            else:
                y0 = brow_base_y + inner_raise + breath_jitter
                y2 = brow_base_y + outer_raise + breath_jitter
            y1 = min(y0, y2) + arch_lift

            points = []
            steps = 18
            for i in range(steps + 1):
                t = i / steps
                px = (1 - t) * (1 - t) * x0 + 2 * (1 - t) * t * x1 + t * t * x2
                py = (1 - t) * (1 - t) * y0 + 2 * (1 - t) * t * y1 + t * t * y2
                points.extend([px, py])

            Color(r, g, b, 0.16 * alpha)
            Line(points=points, width=glow_w, cap="round", joint="round")
            Color(r, g, b, 0.38 * alpha)
            Line(points=points, width=mid_w, cap="round", joint="round")
            Color(r, g, b, 1.0 * alpha)
            Line(points=points, width=core_w, cap="round", joint="round")

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
                try:
                    cam = self.camera_view
                    if cam is not None and hasattr(cam, "get_effective_tex_coords"):
                        tex_coords = cam.get_effective_tex_coords(tex)
                    else:
                        u0, v0 = tex.uvpos
                        us, vs = tex.uvsize
                        tex_coords = [
                            u0,
                            v0,
                            u0 + us,
                            v0,
                            u0 + us,
                            v0 + vs,
                            u0,
                            v0 + vs,
                        ]
                except Exception:
                    tex_coords = None
                RoundedRectangle(
                    texture=tex,
                    pos=(ex - ox + shift_x, eye_y - oy + shift_y),
                    size=(draw_w, draw_h),
                    tex_coords=tex_coords,
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
                tex = self._get_speech_texture()
                if tex is None:
                    return
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
    def _draw_mouth(self, x, y, w, h, color, emo_override=None, alpha=1.0):
        alpha = max(0.0, min(1.0, float(alpha)))
        if alpha <= 0.001:
            return

        r, g, b = color[0], color[1], color[2]
        talk_boost = self.mouth_open * h * 0.012 if self.talking else 0.0
        breath_bob = math.sin(self.breath * 1.4) * h * 0.006
        mx = x + w * 0.4 + self.look_x * w * 0.01
        my = y + h * 0.05 + talk_boost + breath_bob
        mw = w * 0.2
        smile_bias = self.look_x * h * 0.015
        left_bias = -smile_bias
        right_bias = smile_bias

        G_W, M_W, C_W = 35, 18, 10

        emo = str(emo_override or self.target_emotion)
        open_amt = min(1.2, self.mouth_open + (0.08 if self.talking else 0.0))

        with self.canvas:
            pts = []
            steps = 40

            if emo == "happy":
                for i in range(steps + 1):
                    t = i / steps
                    px = mx + t * mw
                    side_offset = left_bias * (1 - t) + right_bias * t
                    py = my + 25 - 70 * (4 * (t - 0.5) ** 2) - open_amt * 18 + side_offset
                    pts.extend([px, py])

            elif emo == "sad":
                for i in range(steps + 1):
                    t = i / steps
                    px = mx + t * mw
                    side_offset = left_bias * (1 - t) + right_bias * t
                    py = my - 25 + 70 * (4 * (t - 0.5) ** 2) + open_amt * 15 + side_offset * 0.4
                    pts.extend([px, py])

            elif emo == "angry":
                pts = [
                    mx,
                    my + left_bias * 0.3,
                    mx + mw * 0.3,
                    my + 15 + open_amt * 4,
                    mx + mw * 0.6,
                    my - 15 - open_amt * 4,
                    mx + mw,
                    my + right_bias * 0.3,
                ]

            elif emo == "surprised":
                size = mw * (0.34 + open_amt * 0.45)
                Color(r, g, b, 0.15 * alpha)
                Ellipse(
                    pos=(mx + mw * 0.5 - size / 2, my - size / 2), size=(size, size)
                )
                Color(r, g, b, 0.5 * alpha)
                Ellipse(
                    pos=(mx + mw * 0.5 - size * 0.45, my - size * 0.45),
                    size=(size * 0.9, size * 0.9),
                )
                Color(r, g, b, 1.0 * alpha)
                Ellipse(
                    pos=(mx + mw * 0.5 - size * 0.35, my - size * 0.35),
                    size=(size * 0.7, size * 0.7),
                )
                return

            elif emo == "sleepy":
                pts = [mx, my - 4, mx + mw, my + right_bias * 0.2 - 4]

            elif emo == "thinking":
                for i in range(steps + 1):
                    t = i / steps
                    px = mx + t * mw
                    side_offset = left_bias * (1 - t) + right_bias * t
                    py = my + math.sin(t * 2.5 * math.pi * 2) * 12 + side_offset * 0.55
                    pts.extend([px, py])

            elif emo == "wink":
                pts = [
                    mx,
                    my + left_bias * 0.25,
                    mx + mw * 0.4,
                    my + 10 + open_amt * 4,
                    mx + mw * 0.8,
                    my + right_bias * 0.25,
                ]

            else:
                pts = [mx, my + left_bias * 0.2, mx + mw, my + right_bias * 0.2]

            Color(r, g, b, 0.15 * alpha)
            Line(points=pts, width=G_W, cap="round", joint="round")
            Color(r, g, b, 0.4 * alpha)
            Line(points=pts, width=M_W, cap="round", joint="round")
            Color(r, g, b, 1.0 * alpha)
            Line(points=pts, width=C_W, cap="round", joint="round")
