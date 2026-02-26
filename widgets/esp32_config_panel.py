from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.app import App
from kivy.uix.scrollview import ScrollView
from kivy.metrics import dp
import threading
import socket
import json

from services import esp32_discovery
from services import esp32_client


class ESP32ConfigPanel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=8, padding=8, **kwargs)

        # 内部容器，便于在外部 ScrollView 中自适应高度
        self.container = BoxLayout(orientation='vertical', size_hint_y=None, spacing=6, padding=0)
        self.container.bind(minimum_height=self.container.setter('height'))

        top = BoxLayout(size_hint_y=None, height=dp(36), spacing=6, padding=(0,0))
        self.refresh_btn = Button(text='扫描设备', size_hint_x=None, width=dp(110))
        self.set_host_btn = Button(text='设置为主控', size_hint_x=None, width=dp(110), disabled=True)
        top.add_widget(self.refresh_btn)
        top.add_widget(self.set_host_btn)
        self.container.add_widget(top)

        self.list_scroll = ScrollView(size_hint_y=None, height=dp(140))
        self.list_box = BoxLayout(orientation='vertical', size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter('height'))
        self.list_scroll.add_widget(self.list_box)
        self.container.add_widget(self.list_scroll)

        form = BoxLayout(size_hint_y=None, height=dp(120), orientation='vertical', spacing=6, padding=(0,0))
        self.ssid_inp = TextInput(hint_text='WiFi SSID', multiline=False)
        # 密码在未连接设备前禁用，避免误输入
        self.pwd_inp = TextInput(hint_text='WiFi Password', multiline=False, password=True, disabled=True)
        self.provision_btn = Button(text='配对到选中设备', size_hint_y=None, height=dp(40), disabled=True)
        form.add_widget(self.ssid_inp)
        form.add_widget(self.pwd_inp)
        form.add_widget(self.provision_btn)
        self.container.add_widget(form)

        # Control buttons
        ctrl = BoxLayout(size_hint_y=None, height=dp(40), spacing=6)
        self.ping_btn = Button(text='Ping', size_hint_x=None, width=dp(80))
        self.status_btn = Button(text='状态', size_hint_x=None, width=dp(80))
        self.stop_btn = Button(text='停止', size_hint_x=None, width=dp(80))
        self.reboot_btn = Button(text='重启', size_hint_x=None, width=dp(80))
        self.reset_btn = Button(text='恢复出厂', size_hint_x=None, width=dp(100))
        ctrl.add_widget(self.ping_btn)
        ctrl.add_widget(self.status_btn)
        ctrl.add_widget(self.stop_btn)
        ctrl.add_widget(self.reboot_btn)
        ctrl.add_widget(self.reset_btn)
        self.container.add_widget(ctrl)

        # Sample send and telemetry listener
        extra = BoxLayout(size_hint_y=None, height=dp(40), spacing=6)
        self.send_sample_btn = Button(text='发送示例关键帧', size_hint_x=None, width=dp(140))
        self.listen_btn = Button(text='开始监听 telemetry', size_hint_x=None, width=dp(160))
        extra.add_widget(self.send_sample_btn)
        extra.add_widget(self.listen_btn)
        self.container.add_widget(extra)

        self.status_lbl = Label(text='状态: 空', size_hint_y=None, height=dp(24))
        self.container.add_widget(self.status_lbl)

        self._devices = []  # list of (ip, info)
        self._selected = None

        self.refresh_btn.bind(on_release=lambda *_: threading.Thread(target=self._do_discover, daemon=True).start())
        self.provision_btn.bind(on_release=lambda *_: threading.Thread(target=self._do_provision, daemon=True).start())
        self.set_host_btn.bind(on_release=lambda *_: self._do_set_host())
        self.ping_btn.bind(on_release=lambda *_: threading.Thread(target=self._do_ping, daemon=True).start())
        self.status_btn.bind(on_release=lambda *_: threading.Thread(target=self._do_status, daemon=True).start())
        self.stop_btn.bind(on_release=lambda *_: threading.Thread(target=self._do_stop, daemon=True).start())
        self.reboot_btn.bind(on_release=lambda *_: threading.Thread(target=self._do_reboot, daemon=True).start())
        self.reset_btn.bind(on_release=lambda *_: threading.Thread(target=self._do_factory_reset, daemon=True).start())
        self.send_sample_btn.bind(on_release=lambda *_: threading.Thread(target=self._do_send_sample, daemon=True).start())
        self.listen_btn.bind(on_release=lambda *_: threading.Thread(target=self._do_listen_toggle, daemon=True).start())

        # 监听 SSID 文本变化，用于启用/禁用配对按钮
        try:
            self.ssid_inp.bind(text=lambda inst, val: self._update_provision_state())
        except Exception:
            pass

        # 将内部容器高度绑定回自身高度，便于外部 ScrollView 使用
        try:
            self.size_hint_y = None
            def _sync_height(inst, val):
                try:
                    self.height = val
                except Exception:
                    pass

            self.container.bind(height=_sync_height)
        except Exception:
            pass

        # 最后把内部容器作为顶层子控件加入（如果外部不是 ScrollView，也能展示）
        self.add_widget(self.container)

    def _update_list(self):
        self.list_box.clear_widgets()
        for ip, info in self._devices:
            btn = Button(text=f"{ip}  {info}", size_hint_y=None, height=dp(36), size_hint_x=1)
            def _on(b, ip=ip, info=info):
                self._selected = (ip, info)
                self.status_lbl.text = f'选中: {ip}'
                # 选中设备后允许设置为主控
                try:
                    self.set_host_btn.disabled = False
                except Exception:
                    pass
            btn.bind(on_release=_on)
            self.list_box.add_widget(btn)

    def _do_discover(self):
        try:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '扫描中...'), 0)
            devices = esp32_discovery.discover()
            self._devices = devices
            Clock.schedule_once(lambda dt: self._update_list(), 0)
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'扫描完成: {len(devices)} 个设备'), 0)
        except Exception as e:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'扫描失败: {e}'), 0)

    def _do_send_sample(self):
        if not self._selected:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '请先选中设备'), 0)
            return
        ip, info = self._selected
        esp32_client.set_host(ip)
        # 示例关键帧：几个舵机回到中位（示例 id/pos）
        sample = {1:1500, 2:1500, 3:1500}
        Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'发送示例到 {ip}...'), 0)
        ok = esp32_client.send_keyframe(sample, duration_ms=500)
        Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'示例发送: {ok}'), 0)

    def _telemetry_listener(self, port=5005):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('', port))
            s.settimeout(1.0)
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'已开始监听 {port}')), 0
            while getattr(self, '_listening', False):
                try:
                    data, addr = s.recvfrom(4096)
                    try:
                        obj = json.loads(data.decode('utf-8'))
                    except Exception:
                        obj = {'raw': data.decode('utf-8', errors='ignore')}
                    Clock.schedule_once(lambda dt, o=obj, a=addr: setattr(self.status_lbl, 'text', f'Telemetry from {a}: {o}'), 0)
                except socket.timeout:
                    continue
        except Exception as e:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'监听错误: {e}'), 0)
        finally:
            try:
                s.close()
            except Exception:
                pass
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '监听已停止'), 0)

    def _do_listen_toggle(self):
        if getattr(self, '_listening', False):
            # stop
            self._listening = False
            Clock.schedule_once(lambda dt: setattr(self.listen_btn, 'text', '开始监听 telemetry'), 0)
            return
        # start
        self._listening = True
        Clock.schedule_once(lambda dt: setattr(self.listen_btn, 'text', '停止监听 telemetry'), 0)
        threading.Thread(target=self._telemetry_listener, daemon=True).start()

    def _do_ping(self):
        if not self._selected:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '请先选中设备'), 0)
            return
        ip, info = self._selected
        Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'Ping {ip}...'), 0)
        ok = esp32_client.send_command('ping') or True
        Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'Ping 发送: {ok}'), 0)

    def _do_status(self):
        if not self._selected:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '请先选中设备'), 0)
            return
        ip, info = self._selected
        esp32_client.set_host(ip)
        res = esp32_client.status()
        Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'状态: {res}'), 0)

    def _do_stop(self):
        if not self._selected:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '请先选中设备'), 0)
            return
        ip, info = self._selected
        esp32_client.set_host(ip)
        res = esp32_client.stop()
        Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'停止: {res}'), 0)

    def _do_reboot(self):
        if not self._selected:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '请先选中设备'), 0)
            return
        ip, info = self._selected
        esp32_client.set_host(ip)
        res = esp32_client.reboot()
        Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'重启命令发送: {res}'), 0)

    def _do_factory_reset(self):
        if not self._selected:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '请先选中设备'), 0)
            return
        ip, info = self._selected
        esp32_client.set_host(ip)
        res = esp32_client.factory_reset()
        Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'恢复出厂命令发送: {res}'), 0)

    def _do_provision(self):
        if not self._selected:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '请先选中设备'), 0)
            return
        ip, info = self._selected
        ssid = self.ssid_inp.text.strip()
        pwd = self.pwd_inp.text
        if not ssid:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '请输入 SSID'), 0)
            return
        Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'正在配对 {ip}...'), 0)
        ok = esp32_discovery.provision_device(ip, ssid, pwd)
        if ok:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'配对命令已发送到 {ip}'), 0)
        else:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'配对发送失败 {ip}'), 0)

    def _do_set_host(self):
        if not self._selected:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', '请先选中设备'), 0)
            return
        ip, info = self._selected
        try:
            esp32_client.set_host(ip)
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'已设置 {ip} 为主控设备'), 0)
            # 连接设备后启用密码输入与配对按钮
            try:
                self._enable_password_entry()
            except Exception:
                pass
        except Exception as e:
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', f'设置失败: {e}'), 0)

    def _enable_password_entry(self):
        try:
            self.pwd_inp.disabled = False
            # 将焦点移到密码输入框（主线程）
            Clock.schedule_once(lambda dt: setattr(self.pwd_inp, 'focus', True), 0)
            self._update_provision_state()
        except Exception:
            pass

    def _update_provision_state(self):
        try:
            ok = bool(getattr(self, '_selected', None)) and (not self.pwd_inp.disabled) and bool(self.ssid_inp.text.strip())
            self.provision_btn.disabled = not ok
        except Exception:
            pass
