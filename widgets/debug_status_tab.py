from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.metrics import dp


def build_status_tab_content(tab_item):
    sv = ScrollView(size_hint=(1, 1))
    sv.do_scroll_x = False
    sv.do_scroll_y = True

    status_grid = GridLayout(
        spacing=dp(12),
        padding=dp(15),
        size_hint=(1, None),
        cols=5,
    )
    status_grid.bind(minimum_height=status_grid.setter("height"))
    sv.add_widget(status_grid)

    try:
        tab_item.clear_widgets()
    except Exception:
        pass
    tab_item.add_widget(sv)
    return status_grid
