from kivy.uix.widget import Widget
from kivy.graphics import Color, Line, PushMatrix, PopMatrix, Rotate, Rectangle
from kivy.core.text import Label as CoreLabel
from app.theme import COLORS, FONT
from widgets.runtime_status import RuntimeStatusLogger

_gyro_logged = False

class GyroPanel(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pitch = 0
        self.roll = 0
        self.yaw = 0
        # 增加平滑缓冲变量
        self._target_pitch = 0
        self._target_roll = 0
        self._target_yaw = 0
        
        self.bind(pos=self.draw, size=self.draw)
        try:
            RuntimeStatusLogger.log_info('GyroPanel 初始化')
        except Exception:
            pass
        
        # 启动动画循环用于平滑过渡
        from kivy.clock import Clock
        Clock.schedule_interval(self._animate_smooth, 1.0 / 60.0)

    def _animate_smooth(self, dt):
        # 简单的线性插值平滑处理 (Lerp)，平滑系数 0.15
        alpha = 0.15
        if abs(self.pitch - self._target_pitch) > 0.01:
            self.pitch += (self._target_pitch - self.pitch) * alpha
        if abs(self.roll - self._target_roll) > 0.01:
            self.roll += (self._target_roll - self.roll) * alpha
        if abs(self.yaw - self._target_yaw) > 0.01:
            self.yaw += (self._target_yaw - self.yaw) * alpha
            
        self.draw()

    def update(self, pitch, roll, yaw=0):
        # 仅更新目标值，实际绘制由 _animate_smooth 接管
        self._target_pitch = pitch
        self._target_roll = roll
        self._target_yaw = yaw
        
        global _gyro_logged
        if not _gyro_logged:
            try:
                RuntimeStatusLogger.log_info(f'陀螺仪第一次更新: pitch={pitch:.2f}, roll={roll:.2f}, yaw={yaw:.2f}')
            except Exception:
                pass
            _gyro_logged = True
        # self.draw() # 移出，由 Loop 统一绘制

    def _get_text_texture(self, text, color):
        """生成数字纹理"""
        label = CoreLabel(text=text, font_size=11, font_name=FONT)
        label.refresh()
        return label.texture

    def draw(self, *args):
        self.canvas.clear()

        # 新实现（小巧精致版）：去掉边框，绘制旋转的地平线以直观展示前后（pitch）和左右（roll）倾角
        from kivy.metrics import dp
        max_w = dp(1000)  # 扩大显示面积以提高（左右）灵敏度观察
        w = min(self.width * 0.62, max_w)
        h = dp(100)  # 也扩大高度
        x, y = self.center_x - w / 2, self.top - h - dp(6)
        cx, cy = x + w / 2, y + h / 2

        # 调整为赛博朋克配色：暗紫背景 + 霓虹青/粉作为指示色
        NEON_CYAN = (0.0, 0.9, 1.0)
        NEON_PINK = (0.95, 0.18, 0.82)
        SKY_COLOR = (0.18, 0.06, 0.28, 0.95)   # 暗紫调的天空
        GROUND_COLOR = (0.04, 0.02, 0.06, 0.95) # 更暗的地面
        r, g, b = NEON_CYAN

        # 由 pitch（前后）决定地平线的垂直偏移；roll 决定旋转角（缩放以便小面板也能明显可见）
        pitch_offset = (self.pitch / 25.0) * (h * 0.5)  # 降低灵敏度，使范围更合理
        pitch_offset = max(-h * 0.8, min(h * 0.8, pitch_offset))

        with self.canvas:
            # 背景
            Color(0, 0, 0, 0.08)
            Rectangle(pos=(x, y), size=(w, h))

            # --- 保存当前坐标系状态 ---
            PushMatrix()
            
            display_roll = self.roll * 1.5 
            Rotate(angle=display_roll, origin=(cx, cy)) # 注意：方向可能需要反转，视传感器而定

            # 绘制地平线 (加长线条保证旋转后能覆盖屏幕)
            # 使用相对中心的坐标绘制
            Color(NEON_CYAN[0], NEON_CYAN[1], NEON_CYAN[2], 0.95)
            # 线条更加长，确保旋转大角度时不会露馅
            Line(points=[cx - w * 1.5, cy + pitch_offset, cx + w * 1.5, cy + pitch_offset], width=1.5)

            # 刻度
            Color(r, g, b, 0.8)
            # 将刻度也通过偏移绘制，使其跟随地平线移动
            for off in [-2, -1, 1, 2]: # 简化刻度
                ly = cy + pitch_offset + off * dp(20)
                # 刻度线长度随距离缩减，制造透视感
                scale_w = dp(40) - abs(off) * dp(5)
                Line(points=[cx - scale_w - dp(10), ly, cx - dp(10), ly], width=1.2)
                Line(points=[cx + dp(10), ly, cx + scale_w + dp(10), ly], width=1.2)
                
            # --- 恢复坐标系 ---
            PopMatrix()

            # 中心十字准星（不随旋转），更精致
            Color(NEON_PINK[0], NEON_PINK[1], NEON_PINK[2], 1)
            Line(points=[cx - 8, cy, cx - 3, cy], width=1.6)
            Line(points=[cx + 3, cy, cx + 8, cy], width=1.6)
            Line(points=[cx, cy - 8, cx, cy - 3], width=1.6)
            Line(points=[cx, cy + 3, cx, cy + 8], width=1.6)

            # 数值显示：Pitch（上）和 Roll（下）
            pitch_tex = self._get_text_texture(f"P {int(self.pitch)}°", (NEON_CYAN[0], NEON_CYAN[1], NEON_CYAN[2], 1))
            roll_tex = self._get_text_texture(f"R {int(self.roll)}°", (NEON_CYAN[0], NEON_CYAN[1], NEON_CYAN[2], 1))
            Color(NEON_CYAN[0], NEON_CYAN[1], NEON_CYAN[2], 1)
            Rectangle(texture=pitch_tex, pos=(cx - pitch_tex.size[0] / 2, cy + dp(26)), size=pitch_tex.size)
            Rectangle(texture=roll_tex, pos=(cx - roll_tex.size[0] / 2, cy - dp(34)), size=roll_tex.size)

            # 左右指向箭头（提示倾斜方向）
            arrow_alpha = min(1.0, abs(self.roll) / 30.0 + 0.1)  # 降低roll阈值，提高灵敏度
            Color(NEON_CYAN[0], NEON_CYAN[1], NEON_CYAN[2], arrow_alpha)
            if self.roll > 2:
                Line(points=[cx + dp(30), cy, cx + dp(50), cy, cx + dp(46), cy + dp(4)], width=1.6)
            elif self.roll < -2:
                Line(points=[cx - dp(30), cy, cx - dp(50), cy, cx - dp(46), cy + dp(4)], width=1.6)

            # 前后提示箭头（基于 pitch）
            p_alpha = min(1.0, abs(self.pitch) / 30.0 + 0.1)  # 降低pitch阈值
            Color(NEON_CYAN[0], NEON_CYAN[1], NEON_CYAN[2], p_alpha)
            if self.pitch > 3:
                Line(points=[cx, cy - dp(30), cx, cy - dp(50), cx + dp(4), cy - dp(46)], width=1.6)
            elif self.pitch < -3:
                Line(points=[cx, cy + dp(30), cx, cy + dp(50), cx + dp(4), cy + dp(46)], width=1.6)