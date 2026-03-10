from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, RoundedRectangle, Line

from widgets.bubble_level import BubbleLevel
from widgets.vision_settings_panel import VisionSettingsPanel

try:
    from widgets.runtime_status import RuntimeStatusLogger
except Exception:
    RuntimeStatusLogger = None


class OtherSettingsPanel(BoxLayout):
    """高级设置面板：整合性能、平衡与视觉设置。"""

    PRESETS = {
        "省电": {
            "sync_active_period": 0.16,
            "sync_idle_period": 0.32,
            "gyro_ui_period": 0.26,
            "sync_compute_pose_threshold": 0.26,
            "sync_compute_idle_period": 0.40,
            "sync_pose_threshold": 0.8,
            "sync_target_threshold": 6,
            "status_read_batch_size": 3,
            "status_slow_fields_interval": 4.0,
            "status_backoff_base_sec": 1.2,
            "status_backoff_max_sec": 6.0,
        },
        "平衡": {
            "sync_active_period": 0.12,
            "sync_idle_period": 0.22,
            "gyro_ui_period": 0.20,
            "sync_compute_pose_threshold": 0.22,
            "sync_compute_idle_period": 0.35,
            "sync_pose_threshold": 0.5,
            "sync_target_threshold": 3,
            "status_read_batch_size": 6,
            "status_slow_fields_interval": 3.0,
            "status_backoff_base_sec": 0.8,
            "status_backoff_max_sec": 5.0,
        },
        "高性能": {
            "sync_active_period": 0.09,
            "sync_idle_period": 0.16,
            "gyro_ui_period": 0.12,
            "sync_compute_pose_threshold": 0.16,
            "sync_compute_idle_period": 0.22,
            "sync_pose_threshold": 0.3,
            "sync_target_threshold": 2,
            "status_read_batch_size": 10,
            "status_slow_fields_interval": 2.0,
            "status_backoff_base_sec": 0.6,
            "status_backoff_max_sec": 4.0,
        },
    }

    def __init__(self, show_message=None, debug_panel=None, button_factory=None, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", dp(8))
        kwargs.setdefault("padding", (dp(10), dp(10), dp(10), dp(10)))
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.bind(minimum_height=self.setter("height"))

        self._show_message = show_message
        self._debug_panel = debug_panel
        self._button_factory = button_factory
        self._balance_level = None
        self._vision_panel = None
        self._level_loaded = False
        self._vision_loaded = False

        perf_box, perf_body = self._create_section_box("性能模式")

        preset_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._preset_spinner = Spinner(
            text="平衡",
            values=tuple(self.PRESETS.keys()),
            size_hint=(1, 1),
        )
        self._btn_apply = self._make_button("应用预设", width=dp(110))
        self._btn_refresh = self._make_button("读取当前", width=dp(110))
        preset_row.add_widget(self._preset_spinner)
        preset_row.add_widget(self._btn_apply)
        preset_row.add_widget(self._btn_refresh)
        perf_body.add_widget(preset_row)

        self._status = Label(
            text="状态：待读取",
            size_hint_y=None,
            height=dp(76),
            color=(0.84, 0.92, 1, 1),
            halign="left",
            valign="top",
        )
        self._status.bind(size=self._status.setter("text_size"))
        perf_body.add_widget(self._status)
        self.add_widget(perf_box)

        bal_box, bal_body = self._create_section_box("平衡参数")

        row_balance = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._gain_p_input = TextInput(
            text="5.50",
            multiline=False,
            input_filter="float",
            size_hint=(None, 1),
            width=dp(88),
        )
        self._gain_r_input = TextInput(
            text="4.20",
            multiline=False,
            input_filter="float",
            size_hint=(None, 1),
            width=dp(88),
        )
        self._btn_bal_apply = self._make_button("应用", width=dp(84))
        self._btn_bal_refresh = self._make_button("读取", width=dp(84))
        self._btn_bal_reset = self._make_button("默认", width=dp(84))
        row_balance.add_widget(Label(text="P", size_hint=(None, 1), width=dp(18), color=(0.75, 0.85, 0.95, 1)))
        row_balance.add_widget(self._gain_p_input)
        row_balance.add_widget(Label(text="R", size_hint=(None, 1), width=dp(18), color=(0.75, 0.85, 0.95, 1)))
        row_balance.add_widget(self._gain_r_input)
        row_balance.add_widget(self._btn_bal_apply)
        row_balance.add_widget(self._btn_bal_refresh)
        row_balance.add_widget(self._btn_bal_reset)
        bal_body.add_widget(row_balance)

        row_axis = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._btn_axis_auto = self._make_button("轴:Auto", width=dp(96))
        self._btn_axis_normal = self._make_button("Normal", width=dp(96))
        self._btn_axis_swapped = self._make_button("Swapped", width=dp(96))
        self._axis_status = Label(
            text="",
            size_hint_y=None,
            height=dp(24),
            color=(0.72, 0.82, 0.92, 1),
            halign="left",
            valign="middle",
        )
        self._axis_status.bind(size=self._axis_status.setter("text_size"))
        row_axis.add_widget(self._btn_axis_auto)
        row_axis.add_widget(self._btn_axis_normal)
        row_axis.add_widget(self._btn_axis_swapped)
        bal_body.add_widget(row_axis)
        bal_body.add_widget(self._axis_status)
        self.add_widget(bal_box)

        level_box, level_body = self._create_section_box("姿态指示")
        self._level_body = level_body
        self._level_loading = Label(
            text="姿态指示加载中...",
            size_hint_y=None,
            height=dp(36),
            color=(0.72, 0.82, 0.92, 1),
            halign="left",
            valign="middle",
        )
        self._level_loading.bind(size=self._level_loading.setter("text_size"))
        level_body.add_widget(self._level_loading)
        self.add_widget(level_box)

        vis_box, vis_body = self._create_section_box("视觉设置")
        self._vision_body = vis_body
        self._vision_loading = Label(
            text="视觉设置加载中...",
            size_hint_y=None,
            height=dp(36),
            color=(0.72, 0.82, 0.92, 1),
            halign="left",
            valign="middle",
        )
        self._vision_loading.bind(size=self._vision_loading.setter("text_size"))
        vis_body.add_widget(self._vision_loading)
        self.add_widget(vis_box)

        # 摄像头切换设置
        cam_box, cam_body = self._create_section_box("远程摄像头")
        self._cam_body = cam_body
        self._cam_status = Label(
            text="摄像头源: 本地",
            size_hint_y=None,
            height=dp(28),
            color=(0.8, 0.9, 1, 1),
            halign="left",
            valign="middle",
        )
        self._cam_status.bind(size=self._cam_status.setter("text_size"))
        cam_body.add_widget(self._cam_status)

        cam_hint = Label(
            text="切换表情眼睛画面源：本地摄像头或其他连接设备",
            size_hint_y=None,
            height=dp(24),
            color=(0.7, 0.8, 0.9, 1),
            halign="left",
            valign="middle",
        )
        cam_hint.bind(size=cam_hint.setter("text_size"))
        cam_body.add_widget(cam_hint)

        cam_row1 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._cam_source_spinner = Spinner(
            text="本地摄像头",
            values=["本地摄像头"],
            size_hint=(1, 1),
        )
        self._btn_cam_refresh = self._make_button("刷新列表", width=dp(100))
        cam_row1.add_widget(self._cam_source_spinner)
        cam_row1.add_widget(self._btn_cam_refresh)
        cam_body.add_widget(cam_row1)

        cam_row2 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self._btn_cam_switch = self._make_button("切换画面", width=dp(100))
        self._btn_cam_register = self._make_button("注册设备", width=dp(100))
        self._btn_cam_upload = self._make_button("开启共享", width=dp(100))
        cam_row2.add_widget(self._btn_cam_switch)
        cam_row2.add_widget(self._btn_cam_register)
        cam_row2.add_widget(self._btn_cam_upload)
        cam_body.add_widget(cam_row2)

        self._cam_upload_enabled = False
        self.add_widget(cam_box)

        self._btn_apply.bind(on_release=self._apply_preset)
        self._btn_refresh.bind(on_release=lambda *_: self.refresh_status())
        self._btn_bal_apply.bind(on_release=self._apply_balance)
        self._btn_bal_refresh.bind(on_release=lambda *_: self._refresh_balance())
        self._btn_bal_reset.bind(on_release=self._reset_balance)
        self._btn_axis_auto.bind(on_release=lambda *_: self._set_axis_mode("auto"))
        self._btn_axis_normal.bind(on_release=lambda *_: self._set_axis_mode("normal"))
        self._btn_axis_swapped.bind(on_release=lambda *_: self._set_axis_mode("swapped"))

        # 摄像头切换事件绑定
        self._btn_cam_refresh.bind(on_release=lambda *_: self._refresh_camera_sources())
        self._btn_cam_switch.bind(on_release=lambda *_: self._switch_camera_source())
        self._btn_cam_register.bind(on_release=lambda *_: self._register_camera())
        self._btn_cam_upload.bind(on_release=lambda *_: self._toggle_frame_upload())

        Clock.schedule_once(lambda _dt: self.refresh_status(), 0)
        Clock.schedule_once(lambda _dt: self._refresh_balance(), 0)
        Clock.schedule_once(lambda _dt: self._ensure_level_loaded(), 0)
        Clock.schedule_once(lambda _dt: self._ensure_vision_loaded(), 0.12)
        Clock.schedule_once(lambda _dt: self._refresh_camera_sources(), 0.5)

    def _ensure_level_loaded(self):
        if self._level_loaded:
            return
        try:
            self._level_body.remove_widget(self._level_loading)
        except Exception:
            pass
        bubble_anchor = AnchorLayout(
            anchor_x="center",
            anchor_y="center",
            size_hint_y=None,
            height=dp(170),
        )
        self._balance_level = BubbleLevel(size_hint=(None, None), size=(dp(140), dp(140)))
        bubble_anchor.add_widget(self._balance_level)
        self._level_body.add_widget(bubble_anchor)
        self._level_loaded = True
        self._start_balance_level()

    def _ensure_vision_loaded(self):
        if self._vision_loaded:
            return
        try:
            self._vision_body.remove_widget(self._vision_loading)
        except Exception:
            pass
        panel = VisionSettingsPanel(show_message=self._show_message)
        panel.size_hint_y = None
        panel.height = dp(150)
        self._vision_panel = panel
        self._vision_body.add_widget(panel)
        self._vision_loaded = True

    def _start_balance_level(self):
        try:
            if self._balance_level:
                self._balance_level.start_tracking()
        except Exception:
            pass

    def on_panel_closed(self):
        try:
            if self._balance_level:
                self._balance_level.stop_tracking()
        except Exception:
            pass

    def _section_title(self, text):
        lbl = Label(
            text=str(text),
            size_hint_y=None,
            height=dp(24),
            color=(0.3, 0.85, 1, 1),
            bold=True,
            halign="left",
            valign="middle",
        )
        lbl.bind(size=lbl.setter("text_size"))
        return lbl

    def _create_section_box(self, title):
        box = BoxLayout(
            orientation="vertical",
            spacing=dp(8),
            padding=(dp(8), dp(8), dp(8), dp(8)),
            size_hint_y=None,
        )
        box.bind(minimum_height=box.setter("height"))

        with box.canvas.before:
            box._bg = Color(0.12, 0.16, 0.2, 0.16)
            box._bg_rect = RoundedRectangle(radius=[8])
        with box.canvas.after:
            box._bd = Color(0.2, 0.7, 0.95, 0.2)
            box._bd_line = Line(rounded_rectangle=(0, 0, 100, 100, 8), width=1.0)

        def _upd(*_):
            box._bg_rect.pos = box.pos
            box._bg_rect.size = box.size
            box._bd_line.rounded_rectangle = (box.x, box.y, box.width, box.height, 8)

        box.bind(pos=_upd, size=_upd)
        box.add_widget(self._section_title(title))
        return box, box

    def _make_button(self, text, width=dp(100)):
        try:
            if callable(self._button_factory):
                return self._button_factory(text=text, size_hint=(None, 1), width=width)
        except Exception:
            pass
        return Button(text=text, size_hint=(None, 1), width=width)

    def _notify(self, text):
        msg = str(text)
        try:
            if callable(self._show_message):
                self._show_message(msg)
        except Exception:
            pass
        try:
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_info(msg)
        except Exception:
            pass

    def _apply_preset(self, *_args):
        app = App.get_running_app()
        if not app:
            self._notify("未找到 App 实例，无法应用预设")
            return

        name = str(self._preset_spinner.text or "平衡")
        cfg = dict(self.PRESETS.get(name, self.PRESETS["平衡"]))

        try:
            app._sync_active_period = float(cfg["sync_active_period"])
            app._sync_idle_period = float(cfg["sync_idle_period"])
            app._gyro_ui_period = float(cfg.get("gyro_ui_period", getattr(app, "_gyro_ui_period", 0.2)))
            app._sync_compute_pose_threshold_deg = float(
                cfg.get("sync_compute_pose_threshold", getattr(app, "_sync_compute_pose_threshold_deg", 0.2))
            )
            app._sync_compute_idle_period = float(
                cfg.get("sync_compute_idle_period", getattr(app, "_sync_compute_idle_period", app._sync_idle_period))
            )
            app._sync_pose_threshold_deg = float(cfg["sync_pose_threshold"])
            app._sync_target_threshold = int(cfg["sync_target_threshold"])
        except Exception:
            pass

        try:
            panel = self._debug_panel
            if panel is not None:
                panel._status_read_batch_size = int(cfg["status_read_batch_size"])
                panel._status_slow_fields_interval = float(cfg["status_slow_fields_interval"])
                panel._status_backoff_base_sec = float(cfg["status_backoff_base_sec"])
                panel._status_backoff_max_sec = float(cfg["status_backoff_max_sec"])
        except Exception:
            pass

        try:
            if hasattr(app, "save_balance_tuning"):
                app.save_balance_tuning()
        except Exception:
            pass

        self._notify(f"已应用性能预设：{name}")
        self.refresh_status()

    def _set_axis_mode(self, mode):
        app = App.get_running_app()
        if mode not in ("auto", "normal", "swapped"):
            return
        try:
            app._gyro_axis_mode = mode
            if mode == "auto":
                app._gyro_axis_samples = 0
            if hasattr(app, "save_balance_tuning"):
                app.save_balance_tuning()
            self._axis_status.text = f"轴映射: {mode}"
            self._notify(f"轴映射已设置: {mode}")
        except Exception:
            pass

    def _refresh_balance(self):
        app = App.get_running_app()
        bc = getattr(app, "balance_ctrl", None)
        if not bc:
            self._axis_status.text = "轴映射: -"
            return
        try:
            gp = float(getattr(bc, "gain_p", 5.5))
            gr = float(getattr(bc, "gain_r", 4.2))
            self._gain_p_input.text = f"{gp:.2f}"
            self._gain_r_input.text = f"{gr:.2f}"
            mode = str(getattr(app, "_gyro_axis_mode", "auto") or "auto")
            if mode not in ("auto", "normal", "swapped"):
                mode = "auto"
            self._axis_status.text = f"轴映射: {mode}"
        except Exception:
            self._axis_status.text = "轴映射: -"

    def _apply_balance(self, *_args):
        app = App.get_running_app()
        bc = getattr(app, "balance_ctrl", None)
        if not bc:
            self._notify("BalanceController 不存在")
            return
        try:
            gp = max(0.0, min(20.0, float(self._gain_p_input.text)))
            gr = max(0.0, min(20.0, float(self._gain_r_input.text)))
            bc.gain_p = gp
            bc.gain_r = gr
            if hasattr(app, "save_balance_tuning"):
                app.save_balance_tuning()
            self._gain_p_input.text = f"{gp:.2f}"
            self._gain_r_input.text = f"{gr:.2f}"
            self._notify(f"平衡参数已应用: P={gp:.2f}, R={gr:.2f}")
        except Exception:
            self._notify("平衡参数输入无效")

    def _reset_balance(self, *_args):
        app = App.get_running_app()
        bc = getattr(app, "balance_ctrl", None)
        if not bc:
            self._notify("BalanceController 不存在")
            return
        try:
            bc.gain_p = 5.5
            bc.gain_r = 4.2
            app._gyro_axis_mode = "auto"
            app._gyro_axis_samples = 0
            if hasattr(app, "save_balance_tuning"):
                app.save_balance_tuning()
            self._refresh_balance()
            self._notify("平衡参数已恢复默认")
        except Exception:
            pass

    def refresh_status(self):
        app = App.get_running_app()
        panel = self._debug_panel

        try:
            sync_active = float(getattr(app, "_sync_active_period", 0.12) or 0.12)
            sync_idle = float(getattr(app, "_sync_idle_period", 0.22) or 0.22)
            gyro_ui = float(getattr(app, "_gyro_ui_period", 0.2) or 0.2)
            compute_pose_th = float(getattr(app, "_sync_compute_pose_threshold_deg", 0.2) or 0.2)
            compute_idle = float(getattr(app, "_sync_compute_idle_period", sync_idle) or sync_idle)
            pose_th = float(getattr(app, "_sync_pose_threshold_deg", 0.5) or 0.5)
            target_th = int(getattr(app, "_sync_target_threshold", 3) or 3)

            if panel is not None:
                batch_size = int(getattr(panel, "_status_read_batch_size", 6) or 6)
                slow_interval = float(getattr(panel, "_status_slow_fields_interval", 3.0) or 3.0)
                backoff_base = float(getattr(panel, "_status_backoff_base_sec", 0.8) or 0.8)
                backoff_max = float(getattr(panel, "_status_backoff_max_sec", 5.0) or 5.0)
            else:
                batch_size = 6
                slow_interval = 3.0
                backoff_base = 0.8
                backoff_max = 5.0

            self._status.text = (
                "状态：已读取\n"
                f"主循环: active={sync_active:.2f}s idle={sync_idle:.2f}s threshold={pose_th:.2f}°/{target_th}\n"
                f"计算/UI: compute={compute_idle:.2f}s@{compute_pose_th:.2f}° ui={gyro_ui:.2f}s\n"
                f"状态读取: batch={batch_size} slow={slow_interval:.1f}s backoff={backoff_base:.1f}-{backoff_max:.1f}s"
            )
        except Exception:
            self._status.text = "状态：读取失败"

    # ==================== 远程摄像头切换 ====================

    def _get_camera_view(self):
        """获取CameraView实例。"""
        try:
            app = App.get_running_app()
            root = getattr(app, "root_widget", None)
            if root and getattr(root, "ids", None):
                cam = root.ids.get("camera_view")
                if cam is not None:
                    return cam

            from widgets.camera_view import CameraView

            def _walk(widget):
                if isinstance(widget, CameraView):
                    return widget
                for child in getattr(widget, "children", []):
                    found = _walk(child)
                    if found is not None:
                        return found
                return None

            if root is not None:
                return _walk(root)
        except Exception:
            pass
        return None

    def _refresh_camera_sources(self):
        """刷新可用摄像头源列表（包含P2P直连信息）。"""
        try:
            cam = self._get_camera_view()
            sources = [{"id": "local", "name": "本地摄像头"}]
            
            if cam and hasattr(cam, "get_available_sources"):
                sources = cam.get_available_sources()
            
            # 更新下拉框选项，保存完整设备信息用于P2P直连
            source_names = []
            self._camera_source_map = {}  # name -> id
            self._camera_source_info = {}  # name -> full device info
            for src in sources:
                name = src.get("name", src.get("id", "未知"))
                source_names.append(name)
                self._camera_source_map[name] = src.get("id", "local")
                self._camera_source_info[name] = src  # 保存完整信息包括ip/port
            
            if source_names:
                self._cam_source_spinner.values = tuple(source_names)
                # 设置当前选中项
                if cam:
                    current = cam.get_camera_source()
                    for name, sid in self._camera_source_map.items():
                        if sid == current or (current == "local" and sid == "local"):
                            self._cam_source_spinner.text = name
                            break
            
            # 更新状态
            current_source = "本地" if (not cam or cam.get_camera_source() == "local") else cam.current_source_name
            self._cam_status.text = f"摄像头源: {current_source}"
            
            self._notify(f"找到 {len(sources)} 个摄像头源")
        except Exception as e:
            self._notify(f"刷新摄像头源失败: {e}")

    def _switch_camera_source(self):
        """切换到选中的摄像头源（P2P直连）。"""
        try:
            cam = self._get_camera_view()
            if not cam or not hasattr(cam, "set_camera_source"):
                self._notify("未找到CameraView，无法切换")
                return
            
            selected_name = self._cam_source_spinner.text
            source_map = getattr(self, "_camera_source_map", {})
            source_info = getattr(self, "_camera_source_info", {})
            source_id = source_map.get(selected_name, "local")
            
            # 获取完整设备信息用于P2P直连
            if source_id == "local":
                target = "local"
            else:
                target = source_info.get(selected_name, {"id": source_id})
            
            if cam.set_camera_source(target):
                current = "本地" if source_id == "local" else selected_name
                self._cam_status.text = f"摄像头源: {current}"
                self._notify(f"已切换摄像头: {selected_name}")
            else:
                self._notify("切换摄像头失败")
        except Exception as e:
            self._notify(f"切换摄像头失败: {e}")

    def _register_camera(self):
        """向ESP32注册本设备（仅用于设备发现）。"""
        try:
            cam = self._get_camera_view()
            if not cam or not hasattr(cam, "register_with_esp32"):
                self._notify("未找到CameraView，无法注册")
                return
            
            if cam.register_with_esp32():
                self._notify("设备注册成功")
                Clock.schedule_once(lambda dt: self._refresh_camera_sources(), 0.5)
            else:
                self._notify("设备注册失败，请检查ESP32连接")
        except Exception as e:
            self._notify(f"注册失败: {e}")

    def _toggle_frame_upload(self):
        """切换P2P视频流共享（启动本地HTTP流服务器）。"""
        try:
            cam = self._get_camera_view()
            if not cam or not hasattr(cam, "enable_stream_sharing"):
                self._notify("未找到CameraView，无法共享")
                return
            
            self._cam_upload_enabled = not getattr(self, "_cam_upload_enabled", False)
            cam.enable_stream_sharing(self._cam_upload_enabled)
            
            if self._cam_upload_enabled:
                self._btn_cam_upload.text = "停止共享"
                self._notify("已开始P2P共享本地画面 (端口5010)")
            else:
                self._btn_cam_upload.text = "开启共享"
                self._notify("已停止共享本地画面")
        except Exception as e:
            self._notify(f"共享切换失败: {e}")
