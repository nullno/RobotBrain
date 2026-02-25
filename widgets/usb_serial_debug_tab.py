from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.app import App
import threading
import time

from widgets.debug_ui_components import TechButton
from widgets.runtime_status import RuntimeStatusLogger


def _hex_to_bytes(s: str):
    try:
        # 支持 00 11 AA 或 0x00,0x11 或 连续无间隔的 hex
        s = s.strip()
        if not s:
            return b''
        parts = s.replace(',', ' ').replace('\t', ' ').split()
        # if parts look like single long string without spaces, split every two chars
        if len(parts) == 1 and all(c in '0123456789abcdefABCDEF' for c in parts[0]):
            p = parts[0]
            if len(p) % 2 == 1:
                p = '0' + p
            parts = [p[i:i+2] for i in range(0, len(p), 2)]

        out = bytearray()
        for token in parts:
            token = token.strip()
            if token.startswith('0x') or token.startswith('0X'):
                token = token[2:]
            if token == '':
                continue
            if len(token) == 1:
                token = '0' + token
            out.append(int(token, 16) & 0xFF)
        return bytes(out)
    except Exception:
        return None


def _bytes_to_hex(b: bytes):
    try:
        return ' '.join(f"{x:02X}" for x in b)
    except Exception:
        return ''


def build_usb_serial_tab_content(tp, tab_item=None):
    tab = tab_item if tab_item is not None else None
    if tab is None:
        from kivy.uix.tabbedpanel import TabbedPanelItem

        tab = TabbedPanelItem(text='串口调试', font_size='15sp')

    root = BoxLayout(orientation='vertical', spacing=8, padding=8)

    # 返回显示区域（放顶部，扩展填充），状态放在右侧不覆盖显示区
    top_box = BoxLayout(orientation='horizontal', size_hint=(1, 1), spacing=8)

    scroll = ScrollView(size_hint=(1, 1))
    # 使用合法的 markup color 标签，避免未知标签造成显示问题
    rx_label = Label(text='[color=888888]等待数据...[/color]', markup=True, size_hint_y=None, halign='left', valign='top')
    rx_label.bind(texture_size=rx_label.setter('size'))
    scroll.add_widget(rx_label)

    

    # 状态栏放在右侧，给出固定宽度并包含控制按钮
    status_width = dp(180)
    status_lbl = Label(
        text='状态: 未连接',
        size_hint=(1, None),
        height=dp(22),
        padding=(dp(6), dp(6)),
        color=(0.9, 0.95, 1, 1),
        font_size='11sp',
        shorten=True,
        shorten_from='right',
        halign='left',
        valign='middle',
    )
    # 限制宽度并允许缩略显示，保持单行不换行
    status_lbl.text_size = (status_width - dp(20), None)

    # 创建控制按钮（将放在右侧连接状态区域）
    refresh_btn = TechButton(text='刷新')
    clear_btn = TechButton(text='清空')

    # 右侧面板带背景框，竖向排布，更紧凑美观，顶部保留额外间距
    from kivy.graphics import Color, RoundedRectangle
    frame = BoxLayout(orientation='vertical', size_hint=(None, 1), width=status_width, spacing=8, padding=(6,12,6,6))
    with frame.canvas.before:
        Color(0, 0, 0, 0.10)
        _rect = RoundedRectangle(radius=[8], pos=frame.pos, size=frame.size)

    def _update_frame_rect(*_):
        try:
            inset = dp(4)
            _rect.pos = (frame.x + inset, frame.y + inset)
            _rect.size = (max(0, frame.width - inset * 2), max(0, frame.height - inset * 2))
        except Exception:
            pass

    frame.bind(pos=_update_frame_rect, size=_update_frame_rect)

    # 按钮列：竖直排列，包含状态和按钮，填满剩余高度，确保都在背景框内
    btns_col = BoxLayout(orientation='vertical', size_hint=(1, 1), spacing=6)
    # 把状态标签放到按钮列顶部（保持固定高度）
    status_lbl.size_hint_y = None
    status_lbl.height = dp(22)
    btns_col.add_widget(status_lbl)
    refresh_btn.size_hint_y = None
    refresh_btn.height = dp(36)
    clear_btn.size_hint_y = None
    clear_btn.height = dp(36)
    btns_col.add_widget(refresh_btn)
    btns_col.add_widget(clear_btn)

    from kivy.uix.widget import Widget
    btns_col.add_widget(Widget(size_hint_y=None, height=dp(6)))
    frame.add_widget(btns_col)

    top_box.add_widget(scroll)
    top_box.add_widget(frame)
    root.add_widget(top_box)

    # 保证文本宽度与滚动区域匹配（考虑右侧状态宽度），避免换行或不可见
    def _update_rx_text_size(*_):
        try:
            w = max(dp(40), float(scroll.width) - dp(16))
            rx_label.text_size = (w, None)
        except Exception:
            pass

    scroll.bind(width=_update_rx_text_size)
    Clock.schedule_once(lambda dt: _update_rx_text_size(), 0)

    # hex 输入行（放底部）
    inp_box = BoxLayout(size_hint_y=None, height=dp(40), spacing=8)
    # 使用 ASCII hint 避免部分设备上 hint 显示乱码
    hex_input = TextInput(multiline=False, hint_text='HEX e.g. 01 02 FF or 0x01,0x02,0xFF or 0102FF', font_size='14sp')
    inp_box.add_widget(hex_input)

    send_btn = TechButton(text='发送', size_hint_x=None, width=dp(90))
    inp_box.add_widget(send_btn)
    root.add_widget(inp_box)

    app = App.get_running_app()

    def _get_conn_status():
        try:
            sb = getattr(app, 'servo_bus', None)
            if not sb or getattr(sb, 'is_mock', True):
                return False, '未连接'
            uart = getattr(sb, 'uart', None)
            # 优先尝试常见属性
            port = None
            baud = None
            try:
                port = getattr(uart, 'port', None)
            except Exception:
                port = None
            if not port:
                try:
                    port = getattr(app, '_dev_port', None)
                except Exception:
                    port = None
            try:
                baud = getattr(app, '_usb_baud', None) or getattr(uart, 'baudrate', None)
            except Exception:
                baud = None
            descr = f"已连接: {port or 'USB'}"
            if baud:
                descr += f" @ {baud}"
            return True, descr
        except Exception:
            return False, '未知'

    def _refresh_status(dt):
        ok, txt = _get_conn_status()
        try:
            if ok:
                status_lbl.color = (0.6, 1.0, 0.6, 1)
            else:
                status_lbl.color = (0.95, 0.6, 0.6, 1)
            status_lbl.text = f"状态: {txt}"
        except Exception:
            pass

    # 仅在标签被激活时周期刷新（降低默认频率以节省资源）
    status_ev = {"ev": None}
    refresh_interval = 1.5

    def _on_tab_switch(inst, val):
        try:
            if val == tab:
                # 启动周期刷新
                if status_ev["ev"] is None:
                    status_ev["ev"] = Clock.schedule_interval(_refresh_status, refresh_interval)
                    _refresh_status(0)
            else:
                # 停止周期刷新
                if status_ev["ev"] is not None:
                    try:
                        status_ev["ev"].cancel()
                    except Exception:
                        pass
                    status_ev["ev"] = None
        except Exception:
            pass

    try:
        # 绑定父 TabbedPanel 的切换事件以控制刷新
        if hasattr(tp, 'bind'):
            tp.bind(current_tab=_on_tab_switch)
    except Exception:
        pass

    def _append_rx(text):
        try:
            now = time.strftime('%H:%M:%S')
            prev = rx_label.text or ''
            lines = prev.split('\n') if prev else []
            lines.append(f"[color=00ff88]{now}[/color] {text}")
            # 仅保留最近 200 行
            if len(lines) > 200:
                lines = lines[-200:]
            rx_label.text = '\n'.join(lines)
        except Exception:
            pass

    def _do_send():
        try:
            data = _hex_to_bytes(hex_input.text)
            if data is None:
                _append_rx('[color=ff5555]解析 HEX 失败[/color]')
                return
            sb = getattr(app, 'servo_bus', None)
            if not sb or getattr(sb, 'is_mock', True):
                _append_rx('[color=ff5555]未连接串口或为 MOCK 模式[/color]')
                return
            uart = getattr(sb, 'uart', None)
            if not uart or not hasattr(uart, 'write'):
                _append_rx('[color=ff5555]串口对象不可用[/color]')
                return
            def _w_and_wait():
                try:
                    # write 可能会阻塞，放后台执行
                    uart.write(data)
                    _append_rx(f"[color=00e6ff]TX[/color] {_bytes_to_hex(data)}")
                except Exception as e:
                    _append_rx(f"[color=ff5555]发送异常: {e}[/color]")
                    return

                # 发送后短时等待回包，若在 timeout 内无回包则提示无回传
                try:
                    timeout = 0.5  # seconds
                    poll_interval = 0.06
                    waited = 0.0
                    found = False
                    while waited < timeout:
                        try:
                            buf = None
                            if hasattr(uart, 'readall'):
                                buf = uart.readall()
                            elif hasattr(uart, 'read'):
                                buf = uart.read(256)
                            if buf:
                                b = bytes(buf)
                                _append_rx(f"[color=ffdd00]RX[/color] {_bytes_to_hex(b)}")
                                found = True
                                break
                        except Exception:
                            pass
                        time.sleep(poll_interval)
                        waited += poll_interval
                    if not found:
                        _append_rx('[color=ffdd00]RX: 无回传[/color]')
                except Exception:
                    pass

            threading.Thread(target=_w_and_wait, daemon=True).start()
        except Exception as e:
            _append_rx(f"[color=ff5555]发送失败: {e}[/color]")

    def _do_read():
        try:
            sb = getattr(app, 'servo_bus', None)
            if not sb or getattr(sb, 'is_mock', True):
                _append_rx('[color=ff5555]未连接串口或为 MOCK 模式[/color]')
                return
            uart = getattr(sb, 'uart', None)
            if not uart or not hasattr(uart, 'readall'):
                _append_rx('[color=ff5555]串口对象不可用[/color]')
                return

            def _r():
                try:
                    # 非阻塞读一次
                    buf = uart.readall()
                    if not buf:
                        _append_rx('[color=888888]无可读数据[/color]')
                        return
                    b = bytes(buf)
                    _append_rx(f"[color=ffdd00]RX[/color] {_bytes_to_hex(b)}")
                except Exception as e:
                    _append_rx(f"[color=ff5555]读取异常: {e}[/color]")

            threading.Thread(target=_r, daemon=True).start()
        except Exception as e:
            _append_rx(f"[color=ff5555]读取失败: {e}[/color]")

    def _do_clear():
        try:
            rx_label.text = ''
        except Exception:
            pass

    send_btn.bind(on_release=lambda *_: _do_send())
    refresh_btn.bind(on_release=lambda *_: Clock.schedule_once(lambda dt: _refresh_status(dt), 0))
    clear_btn.bind(on_release=lambda *_: _do_clear())

    if tab_item is None:
        tab.add_widget(root)
        return tab
    else:
        tab.add_widget(root)
        return tab
