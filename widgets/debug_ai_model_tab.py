from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock

from widgets.ai_model_panel import AIModelPanel


def build_ai_model_tab_content(tab_item):
    sv = ScrollView(size_hint=(1, 1))
    sv.do_scroll_x = False
    sv.do_scroll_y = True

    panel = AIModelPanel(size_hint=(1, None))

    def _sync_panel_height(_inst, _val):
        try:
            panel.height = max(panel.minimum_height, sv.height)
        except Exception:
            pass

    sv.bind(height=_sync_panel_height)
    panel.bind(minimum_height=lambda *_: _sync_panel_height(None, None))
    Clock.schedule_once(lambda dt: _sync_panel_height(None, None), 0)

    sv.add_widget(panel)
    try:
        tab_item.clear_widgets()
    except Exception:
        pass
    tab_item.add_widget(sv)
