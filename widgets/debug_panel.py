from kivy.uix.widget import Widget
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
import threading
import subprocess
import os
import sys
import time


# ===================== 科技风按钮 =====================
class TechButton(Button):
    border_color = (0.2, 0.7, 0.95, 1)
    fill_color = (0.2, 0.7, 0.95, 0.18)
    text_color = (0.9, 0.96, 1, 1)
    radius = 8

    def __init__(self, **kwargs):
        kwargs.setdefault('background_normal', '')
        kwargs.setdefault('background_down', '')
        kwargs.setdefault('background_color', (0, 0, 0, 0))
        kwargs.setdefault('color', self.text_color)
        kwargs.setdefault('size_hint_y', None)
        # 在 Android 上增大按钮高度以便触控
        default_height = dp(56) if Window.system_size and False else None
        try:
            from kivy.utils import platform
            if platform == 'android':
                kwargs.setdefault('height', dp(56))
            else:
                kwargs.setdefault('height', 40)
        except Exception:
            kwargs.setdefault('height', 40)
        super().__init__(**kwargs)

        with self.canvas.before:
            self._bg_color = Color(0, 0, 0, 0)
            self._bg_rect = RoundedRectangle(radius=[self.radius])
        with self.canvas.after:
            self._border_color = Color(*self.border_color)
            self._border_line = Line(rounded_rectangle=(0, 0, 100, 100, self.radius), width=1.4)

        self.bind(pos=self._update, size=self._update,
                  state=self._on_state)

    def _update(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._border_line.rounded_rectangle = (
            self.x, self.y, self.width, self.height, self.radius
        )

    def _on_state(self, *args):
        if self.state == 'down':
            self._bg_color.rgba = self.fill_color
            self._border_color.rgba = (0.35, 0.85, 1, 1)
        else:
            self._bg_color.rgba = (0, 0, 0, 0)
            self._border_color.rgba = self.border_color


# ===================== 红色实心紧急按钮 =====================
class DangerButton(Button):
    radius = 8

    def __init__(self, **kwargs):
        kwargs.setdefault('background_normal', '')
        kwargs.setdefault('background_down', '')
        kwargs.setdefault('background_color', (0, 0, 0, 0))
        kwargs.setdefault('color', (1, 1, 1, 1))
        kwargs.setdefault('size_hint_y', None)
        try:
            from kivy.utils import platform
            if platform == 'android':
                kwargs.setdefault('height', dp(58))
            else:
                kwargs.setdefault('height', 42)
        except Exception:
            kwargs.setdefault('height', 42)
        super().__init__(**kwargs)

        with self.canvas.before:
            self._bg_color = Color(0.92, 0.25, 0.25, 1)
            self._bg_rect = RoundedRectangle(radius=[self.radius])

        self.bind(pos=self._update, size=self._update,
                  state=self._on_state)

    def _update(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _on_state(self, *args):
        if self.state == 'down':
            self._bg_color.rgba = (1, 0.35, 0.35, 1)
        else:
            self._bg_color.rgba = (0.92, 0.25, 0.25, 1)


# ===================== 科技风状态卡片 =====================
class ServoStatusCard(BoxLayout):
    radius = 8

    def __init__(self, sid, data=None, online=True, **kwargs):
        super().__init__(orientation='vertical', padding=6,
                         spacing=3, size_hint_y=None, height=110, **kwargs)

        self.sid = sid

        with self.canvas.before:
            if online:
                self._bg_color = Color(0.12, 0.16, 0.2, 0.9)
                self._border_color = Color(0.2, 0.7, 0.95, 0.9)
            else:
                self._bg_color = Color(0.12, 0.12, 0.15, 0.7)
                self._border_color = Color(0.4, 0.4, 0.45, 0.6)
            self._bg_rect = RoundedRectangle(radius=[self.radius])
            self._border_line = Line(rounded_rectangle=(0, 0, 100, 100, self.radius), width=1.2)

        self.bind(pos=self._update, size=self._update)

        # Header
        header = BoxLayout(size_hint_y=None, height=22)
        header.add_widget(Label(text=f'ID {sid}',
                                 color=(0.3, 0.85, 1, 1),
                                 bold=True))
        self.add_widget(header)

        # 内容区域
        self.body = GridLayout(cols=2, row_default_height=20,
                               spacing=2, size_hint_y=None)
        self.body.bind(minimum_height=self.body.setter('height'))
        self.add_widget(self.body)

        if data:
            self.update_data(data)
        else:
            self.body.add_widget(Label(text='状态:', color=(0.7, 0.7, 0.75, 1)))
            self.body.add_widget(Label(text='未连接', color=(0.9, 0.9, 0.9, 1)))

    def _update(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._border_line.rounded_rectangle = (
            self.x, self.y, self.width, self.height, self.radius
        )

    def update_data(self, data):
        self.body.clear_widgets()
        fields = [
            ('角度', data.get('pos', '--')),
            ('温度', f"{data.get('temp', '--')}°C"),
            ('电压', f"{data.get('volt', '--')}V"),
            ('扭矩', 'ON' if data.get('torque') else 'OFF'),
        ]
        for k, v in fields:
            self.body.add_widget(Label(text=f'{k}:',
                                       color=(0.7, 0.8, 0.9, 1)))
            self.body.add_widget(Label(text=str(v),
                                       color=(0.9, 0.95, 1, 1)))


# ===================== 主调试面板 =====================
class DebugPanel(Widget):

    # ---------------- TAB 样式 ----------------
    def _style_tab(self, tab):
        tab.background_normal = ''
        tab.background_down = ''
        tab.background_color = (0, 0, 0, 0)

        with tab.canvas.before:
            tab._hl_color = Color(0.2, 0.7, 0.95, 0.0)
            tab._hl_rect = RoundedRectangle(radius=[8])

        def _upd(*_):
            tab._hl_rect.pos = tab.pos
            tab._hl_rect.size = tab.size

        tab.bind(pos=_upd, size=_upd)

    def _update_tab_highlight(self, tp, current):
        for tab in tp.tab_list:
            if tab == current:
                tab._hl_color.rgba = (0.2, 0.7, 0.95, 0.22)
            else:
                tab._hl_color.rgba = (0, 0, 0, 0)

    # -------------------------------------------------

    def open_debug(self):
        app = App.get_running_app()
        accent_blue = (0.2, 0.7, 0.95, 1.0)

        content = BoxLayout(orientation='vertical', spacing=8, padding=10)

        # 面板背景
        with content.canvas.before:
            Color(0.12, 0.15, 0.18, 0.95)
            self._bg_rect = RoundedRectangle(radius=[12])
        with content.canvas.after:
            Color(accent_blue[0], accent_blue[1], accent_blue[2], 0.08)
            self._glow_rect = RoundedRectangle(radius=[14])
            Color(0.2, 0.7, 0.95, 0.6)
            self._border_line = Line(rounded_rectangle=(0, 0, 100, 100, 12), width=2)

        def _update_rect(*_):
            self._bg_rect.pos = content.pos
            self._bg_rect.size = content.size
            self._glow_rect.pos = (content.x - 6, content.y - 6)
            self._glow_rect.size = (content.width + 12, content.height + 12)
            self._border_line.rounded_rectangle = (
                content.x, content.y, content.width, content.height, 12
            )

        content.bind(pos=_update_rect, size=_update_rect)

        info = Label(
            text='调试面板 — 谨慎操作舵机。确保周围无人。',
            size_hint_y=None,
            height=28,
            color=(0.85, 0.9, 0.98, 1),
        )
        content.add_widget(info)

        # ---------------- TabbedPanel ----------------
        tp = TabbedPanel(do_default_tab=False, tab_width=150, size_hint_y=0.78)
        try:
            from kivy.utils import platform
            tp.tab_height = dp(56) if platform == 'android' else 42
        except Exception:
            tp.tab_height = 42

        # ---------- 动作 Tab ----------
        t_actions = TabbedPanelItem(text='动作')
        self._style_tab(t_actions)

        sv_actions = ScrollView()
        grid = GridLayout(cols=2, spacing=10, size_hint_y=None, padding=6)
        grid.bind(minimum_height=grid.setter('height'))

        btn_run_demo = TechButton(text='运行示例动作')
        btn_stand = TechButton(text='站立')
        btn_sit = TechButton(text='坐下')
        btn_walk = TechButton(text='前行小步')
        btn_wave = TechButton(text='挥手(右)')
        btn_dance = TechButton(text='舞蹈')
        btn_jump = TechButton(text='跳跃')
        btn_turn = TechButton(text='原地转身')
        btn_squat = TechButton(text='下蹲')
        btn_kick = TechButton(text='踢腿')
        btn_zero_id = TechButton(text='归零/写ID')

        grid.add_widget(btn_run_demo)
        grid.add_widget(btn_zero_id)
        grid.add_widget(btn_stand)
        grid.add_widget(btn_sit)
        grid.add_widget(btn_walk)
        grid.add_widget(btn_wave)
        grid.add_widget(btn_dance)
        grid.add_widget(btn_jump)
        grid.add_widget(btn_turn)
        grid.add_widget(btn_squat)
        grid.add_widget(btn_kick)

        sv_actions.add_widget(grid)
        t_actions.add_widget(sv_actions)
        tp.add_widget(t_actions)

        # ---------- 舵机状态 Tab ----------
        t_status = TabbedPanelItem(text='舵机状态')
        self._style_tab(t_status)

        sv = ScrollView()
        self._status_grid = GridLayout(cols=3, spacing=10,
                                       size_hint_y=None, padding=8)
        self._status_grid.bind(minimum_height=self._status_grid.setter('height'))
        sv.add_widget(self._status_grid)
        t_status.add_widget(sv)
        tp.add_widget(t_status)
        # 添加单舵机独立调试 Tab（不参与主流程）
        try:
            self._build_single_servo_tab(tp)
        except Exception:
            pass

        tp.bind(current_tab=lambda inst, val: self._update_tab_highlight(inst, val))
        Clock.schedule_once(lambda dt: self._update_tab_highlight(tp, tp.current_tab), 0)

        content.add_widget(tp)

        # ---------------- 底部按钮 ----------------
        bottom = BoxLayout(size_hint_y=None, height=42, spacing=8)

        btn_emergency = DangerButton(text='紧急释放扭矩')
        btn_close = TechButton(text='关闭')
        btn_close.border_color = (0.6, 0.6, 0.7, 1)
        btn_close.fill_color = (0.5, 0.5, 0.6, 0.25)

        bottom.add_widget(btn_emergency)
        bottom.add_widget(btn_close)
        content.add_widget(bottom)

        popup = Popup(title='', content=content, size_hint=(None, None),
                      separator_height=0, background='', background_color=(0, 0, 0, 0))

        popup_width = min(1560, Window.width * 0.95)
        if Window.width > Window.height:
            popup_height = min(1000, Window.height * 0.85)
        else:
            popup_height = min(1120, Window.height * 0.95)
        popup.size = (popup_width, popup_height)

        # ---------------- 事件绑定 ----------------
        def _run_demo(_):
            popup.dismiss()
            self._start_demo_thread()

        def _zero_id(_):
            popup.dismiss()
            self._start_zero_id_thread()

        def _stand(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=('stand',), daemon=True).start()

        def _sit(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=('sit',), daemon=True).start()

        def _walk(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=('walk',), daemon=True).start()

        def _wave(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=('wave',), daemon=True).start()

        def _dance(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=('dance',), daemon=True).start()

        def _jump(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=('jump',), daemon=True).start()

        def _turn(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=('turn',), daemon=True).start()

        def _squat(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=('squat',), daemon=True).start()

        def _kick(_):
            popup.dismiss()
            threading.Thread(target=self._call_motion, args=('kick',), daemon=True).start()

        def _emergency(_):
            popup.dismiss()
            self._emergency_torque_release()

        btn_run_demo.bind(on_release=_run_demo)
        btn_stand.bind(on_release=_stand)
        btn_sit.bind(on_release=_sit)
        btn_walk.bind(on_release=_walk)
        btn_wave.bind(on_release=_wave)
        btn_dance.bind(on_release=_dance)
        btn_jump.bind(on_release=_jump)
        btn_turn.bind(on_release=_turn)
        btn_squat.bind(on_release=_squat)
        btn_kick.bind(on_release=_kick)
        btn_zero_id.bind(on_release=_zero_id)
        btn_emergency.bind(on_release=_emergency)
        btn_close.bind(on_release=lambda *a: popup.dismiss())

        def _on_tab_switch(instance, value):
            if value and getattr(value, 'text', '') == '舵机状态':
                threading.Thread(target=self.refresh_servo_status, daemon=True).start()

        tp.bind(current_tab=_on_tab_switch)

        popup.open()

    # ---------------- 原有功能代码 ----------------

    def _start_demo_thread(self):
        t = threading.Thread(target=self._run_demo_motion, daemon=True)
        t.start()

    def _run_demo_motion(self):
        app = App.get_running_app()

        def show_msg(txt):
            # _show_info_popup 已经内部处理了线程安全，这里可以直接调用
            # 为了保险起见，保持 schedule 也无妨，或者直接调用
            self._show_info_popup(txt)

        try:
            from widgets.runtime_status import RuntimeStatusLogger
        except:
            RuntimeStatusLogger = None

        if not hasattr(app, 'servo_bus') or not app.servo_bus or getattr(app.servo_bus, 'is_mock', True):
            show_msg('未连接舵机或为 MOCK 模式，无法运行 Demo')
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_error("Demo 启动失败：未连接舵机或为 MOCK 模式")
            return

        try:
            from services.motion_controller import MotionController
            from services.imu import IMUReader
        except Exception as e:
            show_msg(f'模块导入失败: {e}')
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_error(f"Demo 模块导入失败: {e}")
            return

        servo_mgr = app.servo_bus.manager
        neutral = {i: 2048 for i in servo_mgr.servo_info_dict.keys()} if hasattr(
            servo_mgr, 'servo_info_dict') else {i: 2048 for i in range(1, 26)}
        imu = IMUReader(simulate=True)
        imu.start()
        mc = MotionController(servo_mgr, balance_ctrl=app.balance_ctrl,
                              imu_reader=imu, neutral_positions=neutral)

        show_msg('开始 Demo: 站立')
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo 开始 - 站立")
        mc.stand()
        time.sleep(1.0)

        show_msg('Demo: 挥手')
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo - 挥手")
        mc.wave(side='right', times=3)
        time.sleep(0.6)

        show_msg('Demo: 前行小步')
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo - 前行小步")
        mc.walk(steps=2, step_length=120, step_height=120, time_per_step_ms=350)
        time.sleep(0.6)

        show_msg('Demo: 坐下')
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo - 坐下")
        mc.sit()
        time.sleep(1.2)

        show_msg('Demo: 站起并回中位')
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo - 站起并回中位")
        mc.stand()
        time.sleep(0.8)

        imu.stop()
        show_msg('Demo 完成')
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("Demo 完成")

    def _start_zero_id_thread(self):
        t = threading.Thread(target=self._run_zero_id_script, daemon=True)
        t.start()

    def _run_zero_id_script(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        script = os.path.join(root, 'tools', 'testbench', 'servo_zero_and_id.py')
        if not os.path.exists(script):
            script = os.path.join(os.path.abspath(os.path.join(root, '..')),
                                  'tools', 'testbench', 'servo_zero_and_id.py')
        if not os.path.exists(script):
            self._show_info_popup('未找到 servo_zero_and_id.py 脚本')
            return
        try:
            subprocess.Popen([sys.executable, script])
            self._show_info_popup('归零/写ID脚本已在独立进程启动')
        except Exception as e:
            self._show_info_popup(f'启动脚本失败: {e}')

    def _emergency_torque_release(self):
        app = App.get_running_app()

        try:
            from widgets.runtime_status import RuntimeStatusLogger
        except:
            RuntimeStatusLogger = None

        if not hasattr(app, 'servo_bus') or not app.servo_bus:
            self._show_info_popup('未找到 ServoBus')
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_error("未找到 ServoBus 无法释放扭矩")
            return
        try:
            app.servo_bus.set_torque(False)
            self._show_info_popup('已发送：紧急释放扭矩')
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_action("紧急释放扭矩")
        except Exception as e:
            self._show_info_popup(f'释放扭矩失败: {e}')
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_error(f"释放扭矩失败: {e}")

    # ===================== 舵机状态刷新（科技卡片版） =====================
    def refresh_servo_status(self):
        app = App.get_running_app()
        mgr = getattr(app, 'servo_bus', None)

        # 1. 在主线程清理现有组件
        def _clear():
            self._status_grid.clear_widgets()
        Clock.schedule_once(lambda dt: _clear(), 0)

        # 2. 如果没有连接或Mock模式
        if not mgr or getattr(mgr, 'is_mock', False):
            max_id = 25
            for sid in range(1, max_id + 1):
                # 修复：实例化 Widget 必须在主线程
                Clock.schedule_once(
                    lambda dt, s=sid: self._status_grid.add_widget(
                        ServoStatusCard(s, data=None, online=False)
                    ), 0
                )
            return

        # 3. 正常连接模式 - I/O 在后台，UI 创建在主线程
        mgr = app.servo_bus.manager
        known_ids = set(getattr(mgr, 'servo_info_dict', {}).keys())
        max_known = max(known_ids) if known_ids else 25
        max_id = max(max_known, getattr(mgr, 'max_id', 25))

        for sid in range(1, max_id + 1):
            data = None
            online = False
            
            # --- 耗时 IO 操作 (保留在后台线程) ---
            if sid in known_ids:
                try:
                    pos = mgr.read_data_by_name(sid, 'CURRENT_POSITION')
                    temp = mgr.read_data_by_name(sid, 'CURRENT_TEMPERATURE')
                    volt = mgr.read_data_by_name(sid, 'CURRENT_VOLTAGE')
                    torque_flag = mgr.read_data_by_name(sid, 'TORQUE_ENABLE')
                    online = mgr.servo_info_dict[sid].is_online

                    data = dict(pos=pos, temp=temp,
                                volt=volt, torque=torque_flag)
                except Exception:
                    data = None
                    online = False
            
            # --- UI 更新操作 (调度回主线程) ---
            Clock.schedule_once(
                lambda dt, s=sid, d=data, o=online: self._status_grid.add_widget(
                    ServoStatusCard(s, data=d, online=o)
                ), 0
            )

    # ------------------------------------------------------

    def _show_info_popup(self, text):
        # 修复：将整个弹窗创建逻辑包裹在 Clock.schedule_once 中
        # 这样无论从哪个线程调用，都会被调度到主线程执行
        def _create_popup_ui(dt):
            # 1. 创建内容容器
            content = BoxLayout(padding=(20, 10), orientation='vertical')
            
            # 2. 绘制背景和边框 (与主面板风格统一)
            with content.canvas.before:
                # 半透明黑色背景
                Color(0.1, 0.12, 0.15, 0.95)
                bg_rect = RoundedRectangle(radius=[10])
            with content.canvas.after:
                # 科技蓝边框
                Color(0.2, 0.7, 0.95, 0.8)
                border_line = Line(width=1.5)
            
            # 3. 动态更新背景尺寸
            def _update_bg(inst, val):
                bg_rect.pos = inst.pos
                bg_rect.size = inst.size
                border_line.rounded_rectangle = (inst.x, inst.y, inst.width, inst.height, 10)
                
            content.bind(pos=_update_bg, size=_update_bg)
            
            # 4. 添加文字标签
            lbl = Label(text=text, 
                        color=(0.9, 0.95, 1, 1), 
                        font_size='16sp', 
                        halign='center', 
                        valign='middle')
            lbl.bind(size=lbl.setter('text_size')) 
            content.add_widget(lbl)

            # 5. 创建 Popup
            popup = Popup(
                title='', 
                title_size=0,           # 隐藏标题栏占位
                separator_height=0,     # 隐藏分割线
                content=content,
                size_hint=(None, None),
                size=(400, 100),        # 紧凑的固定尺寸
                auto_dismiss=False,     # 禁止点击外部关闭
                background='',          # 去掉默认背景图
                background_color=(0,0,0,0), # 完全透明
                overlay_color=(0,0,0,0.3)   # 背景稍微变暗
            )
            
            popup.open()
            Clock.schedule_once(lambda dt: popup.dismiss(), 2.0)

        # 调度到主线程执行
        Clock.schedule_once(_create_popup_ui, 0)

    def _call_motion(self, action):
        app = App.get_running_app()
        mc = getattr(app, 'motion_controller', None)
        if not mc:
            self._show_info_popup('MotionController 未初始化或为 MOCK 模式')
            return

        # 在执行任何主流程动作前，确保扭矩已开启
        try:
            if hasattr(app, 'servo_bus') and app.servo_bus and not getattr(app.servo_bus, 'is_mock', True):
                try:
                    app.servo_bus.set_torque(True)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            from widgets.runtime_status import RuntimeStatusLogger
        except:
            RuntimeStatusLogger = None

        try:
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_action(action)

            if action == 'stand':
                mc.stand()
            elif action == 'sit':
                mc.sit()
            elif action == 'walk':
                mc.walk(steps=2, step_length=120,
                        step_height=120, time_per_step_ms=350)
            elif action == 'wave':
                mc.wave(side='right', times=3)
            elif action == 'dance':
                mc.dance() if hasattr(mc, 'dance') else None
            elif action == 'jump':
                mc.jump() if hasattr(mc, 'jump') else None
            elif action == 'turn':
                mc.turn(angle=360) if hasattr(mc, 'turn') else None
            elif action == 'squat':
                mc.squat() if hasattr(mc, 'squat') else None
            elif action == 'kick':
                mc.kick() if hasattr(mc, 'kick') else None

            self._show_info_popup(f'动作 {action} 已发送')
        except Exception as e:
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_error(f"动作 {action} 执行失败: {e}")
            self._show_info_popup(f'动作执行失败: {e}')

    # ================= 单舵机快捷调试 =================
    def _build_single_servo_tab(self, tp):
        app = App.get_running_app()
        t_single = TabbedPanelItem(text='单舵机')
        self._style_tab(t_single)

        box = BoxLayout(orientation='vertical', padding=8, spacing=8)

        # ID 控制行
        id_row = BoxLayout(size_hint_y=None, height=44, spacing=6)
        lbl = Label(text='ID:', size_hint_x=None, width=36, color=(0.8, 0.9, 1, 1))
        self._single_id_label = Label(text='1', size_hint_x=None, width=40)
        btn_dec = TechButton(text='-')
        btn_inc = TechButton(text='+')
        # id_row.add_widget(lbl)
        id_row.add_widget(btn_dec)
        id_row.add_widget(self._single_id_label)
        id_row.add_widget(btn_inc)
        box.add_widget(id_row)

        # 快捷操作行
        row = GridLayout(cols=2, spacing=8, size_hint_y=None, height=200)
        btn_zero = TechButton(text='归零/回中位')
        btn_60 = TechButton(text='转 60°')
        btn_360 = TechButton(text='转 360°')
        btn_read = TechButton(text='读取状态')
        btn_torque_on = TechButton(text='扭矩 ON')
        btn_torque_off = TechButton(text='扭矩 OFF')

        row.add_widget(btn_zero)
        row.add_widget(btn_read)
        row.add_widget(btn_60)
        row.add_widget(btn_360)
        row.add_widget(btn_torque_on)
        row.add_widget(btn_torque_off)

        box.add_widget(row)
        t_single.add_widget(box)
        tp.add_widget(t_single)

        # helpers
        def _get_sid():
            try:
                return int(self._single_id_label.text)
            except Exception:
                return 1

        def _set_sid(n):
            n = max(1, min(250, n))
            self._single_id_label.text = str(n)

        def _inc(_):
            _set_sid(_get_sid() + 1)

        def _dec(_):
            _set_sid(_get_sid() - 1)

        def _ensure_torque():
            app = App.get_running_app()
            try:
                if hasattr(app, 'servo_bus') and app.servo_bus and not getattr(app.servo_bus, 'is_mock', True):
                    app.servo_bus.set_torque(True)
                    return True
            except Exception:
                pass
            return False

        def _move_to_angle(angle_deg):
            app = App.get_running_app()
            sid = _get_sid()
            if not hasattr(app, 'servo_bus') or not app.servo_bus or getattr(app.servo_bus, 'is_mock', True):
                self._show_info_popup('未连接舵机或为 MOCK 模式')
                return
            def _do():
                try:
                    _ensure_torque()
                    mgr = app.servo_bus.manager
                    pos = int(angle_deg / 360.0 * 4095)
                    mgr.set_position_time(sid, pos, time_ms=400)
                    Clock.schedule_once(lambda dt: self._show_info_popup(f'ID {sid} 转到 {angle_deg}°'))
                except Exception as e:
                    msg = f'移动失败: {e}'
                    Clock.schedule_once(lambda dt, m=msg: self._show_info_popup(m))
            threading.Thread(target=_do, daemon=True).start()

        def _move_zero(_):
            _move_to_angle(0)

        def _move_60(_):
            _move_to_angle(60)

        def _move_360(_):
            _move_to_angle(360)

        def _read_status(_):
            app = App.get_running_app()
            sid = _get_sid()
            if not hasattr(app, 'servo_bus') or not app.servo_bus or getattr(app.servo_bus, 'is_mock', True):
                self._show_info_popup('未连接舵机或为 MOCK 模式')
                return
            def _do_read():
                try:
                    mgr = app.servo_bus.manager
                    pos = mgr.read_data_by_name(sid, 'CURRENT_POSITION')
                    temp = mgr.read_data_by_name(sid, 'CURRENT_TEMPERATURE')
                    volt = mgr.read_data_by_name(sid, 'CURRENT_VOLTAGE')
                    Clock.schedule_once(lambda dt: self._show_info_popup(f'ID {sid} -> pos:{pos} temp:{temp}C volt:{volt}V'))
                except Exception as e:
                    Clock.schedule_once(lambda dt: self._show_info_popup(f'读取失败: {e}'))
            threading.Thread(target=_do_read, daemon=True).start()

        def _torque_on(_):
            app = App.get_running_app()
            try:
                if hasattr(app, 'servo_bus') and app.servo_bus and not getattr(app.servo_bus, 'is_mock', True):
                    app.servo_bus.set_torque(True)
                    self._show_info_popup('已发送：扭矩 ON')
                else:
                    self._show_info_popup('ServoBus 未连接')
            except Exception as e:
                self._show_info_popup(f'扭矩操作失败: {e}')

        def _torque_off(_):
            app = App.get_running_app()
            try:
                if hasattr(app, 'servo_bus') and app.servo_bus and not getattr(app.servo_bus, 'is_mock', True):
                    app.servo_bus.set_torque(False)
                    self._show_info_popup('已发送：扭矩 OFF')
                else:
                    self._show_info_popup('ServoBus 未连接')
            except Exception as e:
                self._show_info_popup(f'扭矩操作失败: {e}')

        btn_inc.bind(on_release=_inc)
        btn_dec.bind(on_release=_dec)
        btn_zero.bind(on_release=_move_zero)
        btn_60.bind(on_release=_move_60)
        btn_360.bind(on_release=_move_360)
        btn_read.bind(on_release=_read_status)
        btn_torque_on.bind(on_release=_torque_on)
        btn_torque_off.bind(on_release=_torque_off)