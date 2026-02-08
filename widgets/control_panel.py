class GyroPanel(Widget):
    def _draw_hud(self):
        self.canvas.clear()
        with self.canvas:
            cx, cy = self.center
            w, h = self.size
            
            # 绘制背景装饰线
            Color(*COLORS["primary"][:3], 0.2)
            Line(points=[self.x, cy, self.right, cy], width=1)
            
            # 绘制动态 Pitch 指示器 (垂直刻度)
            Color(*COLORS["primary"][:3], 0.8)
            pitch_y = cy + (self.pitch * 2)
            Line(points=[cx-50, pitch_y, cx+50, pitch_y], width=2)
            
            # 绘制 Roll 旋转刻度
            with self.canvas.before:
                PushMatrix()
                Rotate(angle=-self.roll, origin=(cx, cy))
            Line(circle=(cx, cy, 40, 0, 180), width=1.5)
            PopMatrix()