from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.metrics import dp
from kivy.clock import Clock


def build_actions_tab_content(tab_item, button_cls, on_demo, on_action):
    sv_actions = ScrollView(size_hint=(1, 1))
    sv_actions.do_scroll_x = False
    sv_actions.do_scroll_y = True

    grid = GridLayout(
        cols=5,
        padding=[dp(10), dp(15), dp(5), dp(5)],
        spacing=dp(10),
        size_hint=(None, None),
    )
    grid.bind(minimum_height=grid.setter("height"))

    actions_anchor = AnchorLayout(anchor_x="center", anchor_y="top", size_hint=(1, None))

    btn_run_demo = button_cls(text="运行示例\nDemo")
    btn_stand = button_cls(text="站立")
    btn_sit = button_cls(text="坐下")
    btn_walk = button_cls(text="前行小步")
    btn_wave = button_cls(text="挥手(右)")
    btn_dance = button_cls(text="舞蹈")
    btn_jump = button_cls(text="跳跃")
    btn_turn = button_cls(text="原地转身")
    btn_squat = button_cls(text="下蹲")
    btn_kick = button_cls(text="踢腿")

    buttons = [
        btn_run_demo, btn_stand, btn_sit, btn_walk, btn_wave,
        btn_dance, btn_jump, btn_turn, btn_squat, btn_kick,
    ]
    for btn in buttons:
        grid.add_widget(btn)

    actions_anchor.add_widget(grid)
    sv_actions.add_widget(actions_anchor)

    def _reflow_actions(instance, width):
        cols = max(1, grid.cols)
        spacing = grid.spacing[0] if isinstance(grid.spacing, (list, tuple)) else grid.spacing
        pad = grid.padding[0] * 2 if isinstance(grid.padding, (list, tuple)) else grid.padding * 2

        avail = max(dp(200), sv_actions.width - pad)
        item_w = max(dp(80), (avail - spacing * (cols - 1)) / cols)
        item_h = dp(90)

        grid.width = avail
        grid.size_hint_x = None
        grid.size_hint_y = None

        rows = (len(grid.children) + cols - 1) // cols
        grid.height = rows * item_h + max(0, rows - 1) * spacing
        actions_anchor.height = grid.height

        for c in grid.children:
            c.size_hint = (None, None)
            c.width = item_w * 0.96
            c.height = item_h

    sv_actions.bind(width=_reflow_actions)
    Clock.schedule_once(lambda dt: _reflow_actions(None, sv_actions.width), 0)

    btn_run_demo.bind(on_release=lambda *_: on_demo())
    btn_stand.bind(on_release=lambda *_: on_action("stand"))
    btn_sit.bind(on_release=lambda *_: on_action("sit"))
    btn_walk.bind(on_release=lambda *_: on_action("walk"))
    btn_wave.bind(on_release=lambda *_: on_action("wave"))
    btn_dance.bind(on_release=lambda *_: on_action("dance"))
    btn_jump.bind(on_release=lambda *_: on_action("jump"))
    btn_turn.bind(on_release=lambda *_: on_action("turn"))
    btn_squat.bind(on_release=lambda *_: on_action("squat"))
    btn_kick.bind(on_release=lambda *_: on_action("kick"))

    try:
        tab_item.clear_widgets()
    except Exception:
        pass
    tab_item.add_widget(sv_actions)
