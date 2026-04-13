"""
GyroPanel - 迷你三维小人姿态指示器 V2。

在主界面左上角绘制一个线框小人，根据 pitch/roll/yaw 实时旋转，
直观显示机器人空间姿态。

V2 优化：
- 更高刷新率（30fps → 更流畅的姿态跟踪）
- 更快的插值响应（alpha 0.25 → 0.45，减少滞后）
- 显示角速度指示箭头（显示运动趋势）
- 显示平衡状态（正常/警告/倾倒）
"""

import math
from kivy.uix.widget import Widget
from kivy.uix.behaviors import ButtonBehavior
from kivy.graphics import Color, Line, Ellipse, Rectangle as GRect
from kivy.core.text import Label as CoreLabel
from kivy.clock import Clock
from kivy.metrics import dp
from app.theme import COLORS, FONT

# -- 三维小人骨骼定义（归一化坐标，朝前站立） --
_BONES = {
    "head":       (0.0,  1.70, 0.0),
    "neck":       (0.0,  1.45, 0.0),
    "shoulder_l": (-0.35, 1.40, 0.0),
    "shoulder_r": ( 0.35, 1.40, 0.0),
    "elbow_l":    (-0.45, 1.05, 0.0),
    "elbow_r":    ( 0.45, 1.05, 0.0),
    "hand_l":     (-0.38, 0.72, 0.0),
    "hand_r":     ( 0.38, 0.72, 0.0),
    "hip_c":      (0.0,  0.85, 0.0),
    "hip_l":      (-0.18, 0.82, 0.0),
    "hip_r":      ( 0.18, 0.82, 0.0),
    "knee_l":     (-0.20, 0.42, 0.0),
    "knee_r":     ( 0.20, 0.42, 0.0),
    "foot_l":     (-0.18, 0.02, 0.0),
    "foot_r":     ( 0.18, 0.02, 0.0),
}

_LIMBS = [
    ("neck", "shoulder_l"), ("neck", "shoulder_r"),
    ("shoulder_l", "elbow_l"), ("shoulder_r", "elbow_r"),
    ("elbow_l", "hand_l"), ("elbow_r", "hand_r"),
    ("neck", "hip_c"),
    ("hip_c", "hip_l"), ("hip_c", "hip_r"),
    ("hip_l", "knee_l"), ("hip_r", "knee_r"),
    ("knee_l", "foot_l"), ("knee_r", "foot_r"),
]


def _rotate_xyz(x, y, z, pitch_deg, roll_deg, yaw_deg):
    """绕 XYZ 轴分别旋转，返回新的 (x, y, z)。"""
    p = math.radians(pitch_deg)
    r = math.radians(roll_deg)
    w = math.radians(yaw_deg)
    # Yaw (Y)
    x1 = x * math.cos(w) + z * math.sin(w)
    y1 = y
    z1 = -x * math.sin(w) + z * math.cos(w)
    # Pitch (X)
    x2 = x1
    y2 = y1 * math.cos(p) - z1 * math.sin(p)
    z2 = y1 * math.sin(p) + z1 * math.cos(p)
    # Roll (Z)
    x3 = x2 * math.cos(r) - y2 * math.sin(r)
    y3 = x2 * math.sin(r) + y2 * math.cos(r)
    return x3, y3, z2


def _project(x3, y3, z3, cx, cy, scale, persp=3.5):
    """简单透视投影。"""
    f = persp / (persp + z3) if (persp + z3) > 0.01 else 1.0
    return cx + x3 * scale * f, cy + y3 * scale * f


class GyroPanel(ButtonBehavior, Widget):
    """迷你三维小人姿态部件 V2。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pitch = 0.0
        self.roll = 0.0
        self.yaw = 0.0
        self._target_pitch = 0.0
        self._target_roll = 0.0
        self._target_yaw = 0.0
        self._text_cache = {}
        # 平衡状态指示
        self._balance_status = 'normal'  # 'normal', 'warning', 'fall'
        # V2 固件新增：角速度显示
        self._gyro_pitch_rate = 0.0
        self._gyro_roll_rate = 0.0
        self._gyro_yaw_rate = 0.0
        # 遥测数据新鲜度（ms）
        self._data_age_ms = 999.0
        self._signal_ok = True

        self.bind(pos=self._request_draw, size=self._request_draw)
        # V2: 提升到 30fps，更流畅
        Clock.schedule_interval(self._animate_smooth, 1.0 / 30.0)

    def update(self, pitch, roll, yaw=0):
        self._target_pitch = float(pitch)
        self._target_roll = float(roll)
        self._target_yaw = float(yaw)
        # 根据倾斜角度自动判断平衡状态
        max_tilt = max(abs(float(pitch)), abs(float(roll)))
        if max_tilt > 25:
            self._balance_status = 'fall'
        elif max_tilt > 10:
            self._balance_status = 'warning'
        else:
            self._balance_status = 'normal'

    def update_gyro_rates(self, gyro_pitch=0.0, gyro_roll=0.0, gyro_yaw=0.0):
        """V2: 接收固件上报的角速度（deg/s）。"""
        self._gyro_pitch_rate = float(gyro_pitch)
        self._gyro_roll_rate = float(gyro_roll)
        self._gyro_yaw_rate = float(gyro_yaw)

    def set_data_age(self, age_ms):
        """V2: 设置遥测数据的新鲜度（ms）。"""
        self._data_age_ms = float(age_ms)
        self._signal_ok = (age_ms < 2000)

    def _animate_smooth(self, dt):
        # V2: 更快的追踪系数（0.25 → 0.45），减少姿态滞后
        alpha = 0.45
        changed = False
        for attr in ('pitch', 'roll', 'yaw'):
            cur = getattr(self, attr)
            tgt = getattr(self, '_target_' + attr)
            if abs(cur - tgt) > 0.05:
                setattr(self, attr, cur + (tgt - cur) * alpha)
                changed = True
        if changed:
            self._draw()

    def _request_draw(self, *_):
        self._draw()

    def _draw(self):
        self.canvas.clear()
        w, h = self.width, self.height
        if w < 10 or h < 10:
            return

        cx = self.x + w * 0.5
        cy = self.y + h * 0.45
        scale = min(w, h) * 0.30

        projected = {}
        for name, (bx, by, bz) in _BONES.items():
            rx, ry, rz = _rotate_xyz(bx, by, bz, self.pitch, self.roll, self.yaw)
            px, py = _project(rx, ry, rz, cx, cy, scale)
            projected[name] = (px, py, rz)

        limb_data = []
        for a, b in _LIMBS:
            pa = projected[a]
            pb = projected[b]
            avg_z = (pa[2] + pb[2]) / 2.0
            limb_data.append((avg_z, a, b))
        limb_data.sort(key=lambda t: t[0])

        # V2: 根据平衡状态改变颜色
        if self._balance_status == 'fall':
            BODY_CLR = (1.0, 0.2, 0.2)    # 红色 = 倾倒
            HEAD_CLR = (1.0, 0.1, 0.1)
        elif self._balance_status == 'warning':
            BODY_CLR = (1.0, 0.8, 0.1)    # 黄色 = 警告
            HEAD_CLR = (1.0, 0.6, 0.1)
        else:
            BODY_CLR = (0.0, 0.9, 1.0)    # 青色 = 正常
            HEAD_CLR = (0.95, 0.35, 0.75)

        with self.canvas:
            # 地面参考
            Color(BODY_CLR[0], BODY_CLR[1], BODY_CLR[2], 0.12)
            ground_y = cy - scale * 0.55
            Ellipse(pos=(cx - scale * 0.4, ground_y - dp(2)), size=(scale * 0.8, dp(4)))

            # 肢体线段
            for avg_z, a, b in limb_data:
                pa = projected[a]
                pb = projected[b]
                depth_alpha = max(0.25, min(0.95, 0.6 + avg_z * 0.35))
                lw = 1.6 if avg_z > 0 else 1.2
                Color(BODY_CLR[0], BODY_CLR[1], BODY_CLR[2], depth_alpha)
                Line(points=[pa[0], pa[1], pb[0], pb[1]], width=lw)

            # 关节点
            for name in ('shoulder_l', 'shoulder_r', 'elbow_l', 'elbow_r',
                         'hip_l', 'hip_r', 'knee_l', 'knee_r',
                         'hand_l', 'hand_r', 'foot_l', 'foot_r'):
                px, py, pz = projected[name]
                da = max(0.2, min(0.8, 0.5 + pz * 0.3))
                rr = dp(1.8)
                Color(BODY_CLR[0], BODY_CLR[1], BODY_CLR[2], da)
                Ellipse(pos=(px - rr, py - rr), size=(rr * 2, rr * 2))

            # 头部
            hx, hy, hz = projected["head"]
            head_r = dp(5)
            Color(HEAD_CLR[0], HEAD_CLR[1], HEAD_CLR[2], 0.7)
            Ellipse(pos=(hx - head_r, hy - head_r), size=(head_r * 2, head_r * 2))

            # 数值显示（含状态 + 角速度）
            Color(BODY_CLR[0], BODY_CLR[1], BODY_CLR[2], 0.8)
            status_char = ""
            if self._balance_status == 'fall':
                status_char = "!"
            elif self._balance_status == 'warning':
                status_char = "~"
            lbl_text = "{}P{} R{}".format(status_char, int(self.pitch), int(self.roll))
            tex = self._get_text_tex(lbl_text)
            GRect(texture=tex, pos=(cx - tex.size[0] / 2, self.y + dp(-2)), size=tex.size)

            # V2: 角速度方向箭头（从重心处向运动趋势方向）
            gp_rate = self._gyro_pitch_rate
            gr_rate = self._gyro_roll_rate
            rate_mag = (gp_rate * gp_rate + gr_rate * gr_rate) ** 0.5
            if rate_mag > 5.0:  # 角速度 > 5 deg/s 时才显示箭头
                arrow_len = min(scale * 0.4, rate_mag * 0.3)
                hip_x, hip_y, _ = projected["hip_c"]
                # 角速度映射为屏幕方向
                dx = gr_rate / rate_mag * arrow_len
                dy = -gp_rate / rate_mag * arrow_len
                Color(1.0, 0.5, 0.0, 0.6)
                Line(points=[hip_x, hip_y, hip_x + dx, hip_y + dy], width=1.4)

            # V2: 信号新鲜度指示点
            if not self._signal_ok:
                Color(1.0, 0.2, 0.2, 0.7)
            else:
                Color(0.2, 1.0, 0.3, 0.5)
            dot_r = dp(2)
            Ellipse(pos=(self.x + w - dp(6), self.y + h - dp(6)), size=(dot_r * 2, dot_r * 2))

    def _get_text_tex(self, text):
        if text in self._text_cache:
            return self._text_cache[text]
        lbl = CoreLabel(text=text, font_size=9, font_name=FONT)
        lbl.refresh()
        tex = lbl.texture
        self._text_cache[text] = tex
        if len(self._text_cache) > 64:
            first = next(iter(self._text_cache))
            self._text_cache.pop(first, None)
        return tex

    def toggle_visible(self):
        pass

    def draw(self, *args):
        self._draw()