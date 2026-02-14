from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, Ellipse
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.app import App


class BubbleLevel(Widget):
    """圆形水平仪：中心气泡根据 pitch/roll 位移。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pitch = 0.0
        self.roll = 0.0
        self._target_pitch = 0.0
        self._target_roll = 0.0
        self.max_angle = 20.0
        self._track_ev = None
        self._anim_ev = Clock.schedule_interval(self._tick, 1.0 / 60.0)
        self.bind(pos=self._redraw, size=self._redraw)

    def start_tracking(self):
        if self._track_ev is None:
            self._track_ev = Clock.schedule_interval(self._pull_from_app, 1.0 / 30.0)

    def stop_tracking(self):
        if self._track_ev is not None:
            self._track_ev.cancel()
            self._track_ev = None

    def update(self, pitch, roll):
        try:
            self._target_pitch = float(pitch)
            self._target_roll = float(roll)
        except Exception:
            pass

    def _pull_from_app(self, dt):
        try:
            app = App.get_running_app()
            p = float(getattr(app, "_latest_pitch", 0.0))
            r = float(getattr(app, "_latest_roll", 0.0))
            self.update(p, r)
        except Exception:
            pass

    def _tick(self, dt):
        alpha = 0.2
        self.pitch += (self._target_pitch - self.pitch) * alpha
        self.roll += (self._target_roll - self.roll) * alpha
        self._redraw()

    def _redraw(self, *args):
        self.canvas.clear()
        if self.width <= 0 or self.height <= 0:
            return

        cx, cy = self.center_x, self.center_y
        radius = max(dp(24), min(self.width, self.height) * 0.48)
        ring = radius - dp(2)

        with self.canvas:
            Color(0.08, 0.1, 0.13, 0.95)
            Ellipse(pos=(cx - radius, cy - radius), size=(radius * 2, radius * 2))

            Color(0.2, 0.7, 0.95, 0.8)
            Line(circle=(cx, cy, ring), width=1.5)
            Color(0.2, 0.7, 0.95, 0.28)
            Line(circle=(cx, cy, ring * 0.66), width=1.0)
            Line(circle=(cx, cy, ring * 0.33), width=1.0)

            Color(0.2, 0.7, 0.95, 0.45)
            Line(points=[cx - ring, cy, cx + ring, cy], width=1.0)
            Line(points=[cx, cy - ring, cx, cy + ring], width=1.0)

            travel = max(dp(6), ring - dp(14))
            n_roll = max(-1.0, min(1.0, self.roll / max(0.1, self.max_angle)))
            n_pitch = max(-1.0, min(1.0, self.pitch / max(0.1, self.max_angle)))
            bx = cx + n_roll * travel
            by = cy - n_pitch * travel

            bubble_r = dp(10)
            Color(0.0, 0.98, 0.7, 0.95)
            Ellipse(pos=(bx - bubble_r, by - bubble_r), size=(bubble_r * 2, bubble_r * 2))
            Color(1, 1, 1, 0.6)
            Ellipse(pos=(bx - bubble_r * 0.45, by + bubble_r * 0.05), size=(bubble_r * 0.8, bubble_r * 0.8))
