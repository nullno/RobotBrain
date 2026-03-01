from math import atan2, cos, radians, sin

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
import os


def _pick_chinese_font():
    base = os.path.dirname(__file__)
    path = os.path.join(base, 'assets', 'fonts', 'simhei.ttf')
    if os.path.exists(path):
        return path
    return None


class Knob(FloatLayout):
    angle = NumericProperty(0.0)
    display_angle = NumericProperty(0.0)
    max_angle = NumericProperty(360.0)

    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.setdefault('size', (dp(220), dp(220)))
        super().__init__(**kwargs)

        self._radius = 0.0
        self._ring_width = dp(10)
        self._inner_margin = dp(20)
        self._shadow_offset = dp(2)
        self._drag_last_raw = None
        self._anim_ev = None

        with self.canvas.before:
            self._c_shadow = Color(0, 0, 0, 0.25)
            self._e_shadow = Ellipse()

            self._c_outer = Color(0.13, 0.16, 0.2, 1)
            self._e_outer = Ellipse()

            self._c_outer_stroke = Color(0.26, 0.32, 0.38, 0.8)
            self._l_outer_stroke = Line(circle=(0, 0, 1), width=1.2)

            self._c_inner = Color(0.1, 0.12, 0.15, 1)
            self._e_inner = Ellipse()

            self._c_track = Color(0.25, 0.31, 0.39, 0.55)
            self._l_track = Line(circle=(0, 0, 1), width=self._ring_width)

            self._c_progress = Color(0.2, 0.7, 0.95, 0.9)
            self._l_progress = Line(points=[], width=self._ring_width)

            self._c_pointer = Color(0.75, 0.9, 1, 1)
            self._e_pointer = Ellipse()

        font = _pick_chinese_font()
        label_kwargs = {}
        if font:
            label_kwargs['font_name'] = font

        self._value_label = Label(
            text='0°',
            color=(0.9, 0.96, 1, 1),
            bold=True,
            font_size='30sp',
            halign='center',
            valign='middle',
            size_hint=(None, None),
            **label_kwargs,
        )
        self.add_widget(self._value_label)

        self.bind(pos=self._update_canvas, size=self._update_canvas, display_angle=self._update_canvas)
        self.bind(angle=self._on_angle_changed)
        Clock.schedule_once(lambda dt: self._update_canvas(), 0)

    def _on_angle_changed(self, *args):
        if self._anim_ev is None:
            self._anim_ev = Clock.schedule_interval(self._tick_anim, 1.0 / 60.0)

    def _tick_anim(self, dt):
        target = float(self.angle)
        current = float(self.display_angle)
        delta = target - current
        if abs(delta) < 0.05:
            self.display_angle = target
            if self._anim_ev is not None:
                self._anim_ev.cancel()
                self._anim_ev = None
            return False

        alpha = min(1.0, max(0.0, dt * 20.0))
        self.display_angle = current + delta * alpha
        return True

    def _angle_to_canvas(self, deg):
        return 90.0 - float(deg)

    def _update_canvas(self, *args):
        cx, cy = self.center
        side = min(self.width, self.height)
        self._radius = side * 0.48

        outer_pos = (cx - self._radius, cy - self._radius)
        outer_size = (self._radius * 2, self._radius * 2)

        shadow_pos = (outer_pos[0] + self._shadow_offset, outer_pos[1] - self._shadow_offset)
        self._e_shadow.pos = shadow_pos
        self._e_shadow.size = outer_size

        self._e_outer.pos = outer_pos
        self._e_outer.size = outer_size
        self._l_outer_stroke.circle = (cx, cy, self._radius)

        inner_r = max(dp(12), self._radius - self._inner_margin)
        self._e_inner.pos = (cx - inner_r, cy - inner_r)
        self._e_inner.size = (inner_r * 2, inner_r * 2)

        ring_r = self._radius - self._ring_width * 0.6
        self._l_track.circle = (cx, cy, ring_r)

        progress_pts = []
        val = max(0.0, min(float(self.max_angle), float(self.display_angle)))
        # map current range to full circle for drawing
        mapped_val = val / float(self.max_angle or 1.0) * 360.0
        if val <= 0.0:
            a = radians(self._angle_to_canvas(0.0))
            progress_pts = [cx + cos(a) * ring_r, cy + sin(a) * ring_r]
        else:
            step = 1.0
            cur = 0.0
            while cur < mapped_val:
                a = radians(self._angle_to_canvas(cur))
                progress_pts.extend([cx + cos(a) * ring_r, cy + sin(a) * ring_r])
                cur += step
            a = radians(self._angle_to_canvas(mapped_val))
            progress_pts.extend([cx + cos(a) * ring_r, cy + sin(a) * ring_r])
        self._l_progress.points = progress_pts

        canvas_deg = self._angle_to_canvas(mapped_val)

        pointer_r = ring_r
        pa = radians(canvas_deg)
        px = cx + cos(pa) * pointer_r
        py = cy + sin(pa) * pointer_r
        pointer_size = dp(20)
        self._e_pointer.pos = (px - pointer_size / 2, py - pointer_size / 2)
        self._e_pointer.size = (pointer_size, pointer_size)

        self._value_label.text = f"{int(round(self.display_angle))}°"
        label_w = max(dp(110), inner_r * 1.45)
        label_h = max(dp(52), inner_r * 0.72)
        self._value_label.size = (label_w, label_h)
        self._value_label.text_size = self._value_label.size
        self._value_label.center = (cx + dp(10), cy)

    def set_angle(self, angle):
        try:
            angle = float(angle)
        except Exception:
            angle = 0.0
        cap = float(self.max_angle) if float(self.max_angle) > 0 else 360.0
        self.angle = max(0.0, min(cap, angle))

    def _update_from_touch(self, touch, dragging=False):
        cx, cy = self.center
        dx = float(touch.x - cx)
        dy = float(touch.y - cy)
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return

        dist_sq = dx * dx + dy * dy
        max_r = self._radius + dp(60)
        min_r = max(dp(8), self._radius * 0.2)
        if not dragging:
            if dist_sq < (min_r * min_r) or dist_sq > (max_r * max_r):
                return

        raw = (90.0 - (atan2(dy, dx) * 180.0 / 3.1415926)) % 360.0

        if self._drag_last_raw is None:
            self._drag_last_raw = raw
            return

        delta = raw - self._drag_last_raw
        if delta > 180:
            delta -= 360
        elif delta < -180:
            delta += 360

        self.set_angle(float(self.angle) + float(delta))
        self._drag_last_raw = raw

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        touch.grab(self)
        self._drag_last_raw = None
        self._update_from_touch(touch, dragging=False)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_move(touch)
        self._update_from_touch(touch, dragging=True)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._drag_last_raw = None
            return True
        return super().on_touch_up(touch)
