from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock

from widgets.other_settings_panel import OtherSettingsPanel


def build_other_settings_tab_content(tab_item, show_message, debug_panel, button_factory):
    sv = ScrollView(size_hint=(1, 1))
    sv.do_scroll_x = False
    sv.do_scroll_y = True

    panel = OtherSettingsPanel(
        show_message=show_message,
        debug_panel=debug_panel,
        button_factory=button_factory,
    )

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
    return panel
