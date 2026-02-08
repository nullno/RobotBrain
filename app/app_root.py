from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.utils import platform
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from widgets.startup_tip import StartupTip
import random
import math
import os
import sys
import subprocess
import json

from widgets.camera_view import CameraView
from widgets.robot_face import RobotFace
from widgets.gyro_panel import GyroPanel
from widgets.debug_panel import DebugPanel
from widgets.servo_status import ServoStatus
from widgets.runtime_status import RuntimeStatusPanel, RuntimeStatusLogger
from services.servo_bus import ServoBus
from services.balance_ctrl import BalanceController
from services.motion_controller import MotionController
from services.imu import IMUReader
from services.neutral import load_neutral
from services import usb_otg
# AICore 暂时禁用，注释掉导入
# from services.ai_core import AICore
import logging
import pathlib

try:
    from plyer import gyroscope
except ImportError:
    gyroscope = None


class RobotDashboardApp(App):
    def build(self):
        # Android权限申请
        if platform == "android":
            from android.permissions import request_permissions, Permission, check_permission
            
            # 检查并请求权限
            required_perms = [
                Permission.CAMERA,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
            ]
            
            # 检查缺失的权限
            missing_perms = []
            for perm in required_perms:
                try:
                    if not check_permission(perm):
                        missing_perms.append(perm)
                except Exception:
                    missing_perms.append(perm)
            
            if missing_perms:
                def _perm_callback(permissions, results):
                    if all(results):
                        print("✅ 所有权限申请成功")
                    else:
                        missing = [p for p, r in zip(permissions, results) if not r]
                        print(f"⚠️ 未授予权限: {missing}，部分功能可能受限")
                
                request_permissions(missing_perms, _perm_callback)
            else:
                print("✅ 所有权限已获得")

        Builder.load_file("kv/style.kv")
        self.root_widget = Builder.load_file("kv/root.kv")

        # ---------- 硬件 ----------
        try:
            dev_port = "/dev/ttyUSB0" if platform == "android" else "COM6"
            self._dev_port = dev_port
            self.servo_bus = ServoBus(port=dev_port)
        except Exception as e:
            print(f"❌ 串口初始化失败: {e}")
            self.servo_bus = None

        # 初始化日志
        try:
            log_dir = pathlib.Path('logs')
            log_dir.mkdir(exist_ok=True)
            logging.basicConfig(level=logging.INFO, filename=str(log_dir / 'robot_dashboard.log'), filemode='a', format='%(asctime)s %(levelname)s: %(message)s')
            logging.info('App starting')
            # 将 Python logging 同步到 RuntimeStatusLogger，便于在界面查看日志
            try:
                class _ForwardHandler(logging.Handler):
                    def emit(self, record):
                        try:
                            msg = self.format(record)
                            if RuntimeStatusLogger:
                                if record.levelno >= logging.ERROR:
                                    RuntimeStatusLogger.log_error(msg)
                                else:
                                    RuntimeStatusLogger.log_info(msg)
                        except Exception:
                            pass

                fh = _ForwardHandler()
                fh.setLevel(logging.INFO)
                logging.getLogger().addHandler(fh)
            except Exception:
                pass
            # 将 stdout/stderr 重定向到 logging，以便 print() 也能显示在 runtime_status 中
            try:
                import sys

                class _StdForward:
                    def __init__(self, level='info'):
                        self._level = level
                    def write(self, s):
                        try:
                            s = s.strip()
                            if not s:
                                return
                            if self._level == 'error':
                                logging.getLogger().error(s)
                            else:
                                logging.getLogger().info(s)
                        except Exception:
                            pass
                    def flush(self):
                        pass

                sys.stdout = _StdForward('info')
                sys.stderr = _StdForward('error')
            except Exception:
                pass
        except Exception:
            pass

        # 加载中位配置（若存在）
        neutral_raw = load_neutral() or {}
        # normalize keys to ints
        try:
            neutral = {int(k): int(v) for k, v in neutral_raw.items()}
        except Exception:
            neutral = {i: 2048 for i in range(1, 26)}

        self.balance_ctrl = BalanceController(neutral, is_landscape=True)
        self._setup_gyroscope()

        # AI 核心暂时禁用（不初始化 AICore）
        self.ai_core = None
        self._ai_speech_buf = ''
        self._ai_speech_clear_ev = None

        # MotionController 集成（若有 ServoBus）
        try:
            if self.servo_bus and not getattr(self.servo_bus, 'is_mock', True):
                imu = IMUReader(simulate=False)
                imu.start()
                self.motion_controller = MotionController(self.servo_bus.manager, balance_ctrl=self.balance_ctrl, imu_reader=imu, neutral_positions=neutral)
            else:
                self.motion_controller = None
        except Exception as e:
            logging.exception('MotionController init failed')
            self.motion_controller = None

        # ---------- Demo 动画 ----------
        self._demo_step = 0
        Clock.schedule_interval(self._update_loop, 0.1)
        Clock.schedule_interval(self._demo_emotion_loop, 4.0)
        Clock.schedule_interval(self._demo_eye_move, 0.05)

        # 初始化运行状态日志记录器
        try:
            runtime_status_panel = self.root_widget.ids.runtime_status
            RuntimeStatusLogger.set_panel(runtime_status_panel)
            RuntimeStatusLogger.log_info("应用启动成功")
        except Exception as e:
            print(f"⚠️ 运行状态面板初始化失败: {e}")

        # 启动时展示权限和连接提示（会在未授权时持续提示并监听授权变化）
        Clock.schedule_once(lambda dt: self._start_permission_watcher(), 0.6)

        # 启动 OTG / 串口监测（跨平台：Android / PC / macOS / Linux）
        try:
            usb_otg.start_monitor()
            RuntimeStatusLogger.log_info('串口/OTG 监测已启动')
            try:
                # 注册 OTG 设备事件回调，热插拔时尝试重建 ServoBus 并刷新 UI
                usb_otg.register_device_callback(self._on_otg_event)
            except Exception:
                pass
        except Exception as e:
            try:
                RuntimeStatusLogger.log_error(f"OTG 监测启动失败: {e}")
            except Exception:
                print(f"OTG 监测启动失败: {e}")

        return self.root_widget

    def _on_otg_event(self, event, device_id):
        """处理 OTG 插拔事件：在设备插入时尝试重建 ServoBus 并刷新界面；拔出时清理状态。"""
        try:
            # 在后台执行 I/O/初始化以避免阻塞主线程
            def _handle():
                try:
                    if event == 'added':
                        # 解析 device_id 中的实际串口端口名（如 COM6 或 /dev/ttyUSB0）
                        def _parse_port(dev_id):
                            try:
                                if not dev_id:
                                    return None
                                if '::' in dev_id:
                                    return dev_id.split('::', 1)[0]
                                import re
                                m = re.search(r'(COM\d+)', dev_id, re.I)
                                if m:
                                    return m.group(1)
                                m = re.search(r'(/dev/tty[^,;\s]+)', dev_id)
                                if m:
                                    return m.group(1)
                                return dev_id
                            except Exception:
                                return None

                        port = _parse_port(device_id) or getattr(self, '_dev_port', None) or ("/dev/ttyUSB0" if platform == "android" else "COM6")
                        # 仅在当前没有可用硬件时尝试重建
                        if not getattr(self, 'servo_bus', None) or getattr(self.servo_bus, 'is_mock', True):
                            try:
                                # 先保存端口以便下次使用
                                self._dev_port = port
                                sb = ServoBus(port=port)
                                # 如果成功连接硬件（非 mock），替换并初始化 motion_controller
                                if sb and not getattr(sb, 'is_mock', True):
                                    # 关闭旧实例
                                    try:
                                        if getattr(self, 'servo_bus', None) and hasattr(self.servo_bus, 'close'):
                                            try:
                                                self.servo_bus.close()
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                    self.servo_bus = sb
                                    try:
                                        imu = IMUReader(simulate=False)
                                        imu.start()
                                        self.motion_controller = MotionController(self.servo_bus.manager, balance_ctrl=self.balance_ctrl, imu_reader=imu, neutral_positions={})
                                    except Exception:
                                        self.motion_controller = None
                                    try:
                                        RuntimeStatusLogger.log_info(f'检测到 OTG 设备，已连接串口: {port}')
                                    except Exception:
                                        pass
                                    # 刷新调试面板和状态卡片
                                    try:
                                        Clock.schedule_once(lambda dt: self.root_widget.ids.debug_panel.refresh_servo_status(), 0)
                                        Clock.schedule_once(lambda dt: self.root_widget.ids.runtime_status.refresh() if hasattr(self.root_widget.ids.runtime_status, 'refresh') else None, 0)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                    elif event == 'removed':
                        # 简单清理：优雅关闭 servo_bus 与 motion_controller，并刷新 UI
                        try:
                            if getattr(self, 'servo_bus', None) and hasattr(self.servo_bus, 'close'):
                                try:
                                    self.servo_bus.close()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        try:
                            self.servo_bus = None
                        except Exception:
                            pass
                        try:
                            self.motion_controller = None
                        except Exception:
                            pass
                        try:
                            RuntimeStatusLogger.log_info(f'串口设备已拔出: {device_id}')
                        except Exception:
                            pass
                        try:
                            Clock.schedule_once(lambda dt: self.root_widget.ids.debug_panel.refresh_servo_status(), 0)
                        except Exception:
                            pass
                except Exception:
                    pass

            threading.Thread(target=_handle, daemon=True).start()
        except Exception:
            pass

    # ================== 硬件 ==================
    def _setup_gyroscope(self):
        if platform == "android" and gyroscope:
            try:
                gyroscope.enable()
                try:
                    RuntimeStatusLogger.log_info('Android 陀螺仪已激活')
                except Exception:
                    pass
                print("✅ Android 陀螺仪已激活")
            except Exception as e:
                try:
                    RuntimeStatusLogger.log_error(f'无法激活陀螺仪: {e}')
                except Exception:
                    pass
                print(f"❌ 无法激活陀螺仪: {e}")

    def _check_android_permissions(self):
        """返回缺失的权限列表（Android）"""
        if platform != 'android':
            return []
        try:
            from android.permissions import check_permission, Permission
            required_perms = [
                Permission.CAMERA,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
            ]
            missing = []
            for p in required_perms:
                try:
                    if not check_permission(p):
                        missing.append(p)
                except Exception:
                    missing.append(p)
            return missing
        except Exception:
            return []

    def _start_permission_watcher(self):
        """在启动时（以及授权未完成时）持续提醒用户并在授权完成后触发重试初始化。"""
        missing = self._check_android_permissions()
        # 如果有权限缺失，展示 StartupTip 并每秒重试检查
        if missing:
            RuntimeStatusLogger.log_info("检测到缺失权限，等待用户授权")
            # 打开提示（如果用户延迟授权，可多次打开）
            try:
                self._startup_tip = StartupTip()
                self._startup_tip.open()
            except Exception:
                pass

            def _watch(dt):
                missing_now = self._check_android_permissions()
                if not missing_now:
                    # 权限已授予，关闭提示并重新初始化必要组件
                    try:
                        if hasattr(self, '_startup_tip') and self._startup_tip._popup:
                            self._startup_tip._popup.dismiss()
                    except Exception:
                        pass
                    RuntimeStatusLogger.log_info('权限已授予，正在重新初始化授权依赖模块')
                    # 触发 CameraView 重试（如果存在）
                    try:
                        cam = self.root_widget.ids.get('camera_view')
                        if cam and hasattr(cam, '_start_android'):
                            cam._start_android()
                    except Exception:
                        pass
                    return False
                return True

            Clock.schedule_interval(_watch, 1.0)
        else:
            # 没有缺失权限，仍记录日志
            RuntimeStatusLogger.log_info('权限检查通过')

    

    def _get_gyro_data(self):
        p, r, y = 0, 0, 0
        if platform == "android" and gyroscope:
            try:
                val = gyroscope.rotation
                if val[0] is not None:
                    p, r, y = val[0], val[1], val[2]
            except:
                pass
        else:
            p = random.uniform(-5, 5)
            r = random.uniform(-5, 5)
            y = random.uniform(0, 360)
        return p, r, y

    # ================== 主循环 ==================
    def _update_loop(self, dt):
        try:
            p, r, y = self._get_gyro_data()

            if "gyro_panel" in self.root_widget.ids:
                self.root_widget.ids.gyro_panel.update(p, r, y)

            # 硬件同步
            if self.servo_bus and not getattr(self.servo_bus, "is_mock", True):
                targets = self.balance_ctrl.compute(p, r, y)
                self.servo_bus.move_sync(targets, time_ms=100)
        except Exception as e:
            print(f"Loop Error: {e}")

    # ================== 表情 Demo ==================
    def _demo_emotion_loop(self, dt):
        faces = ["normal", "happy", "sad", "angry", "surprised", "sleepy", "thinking", "wink"]
        emo = faces[self._demo_step % len(faces)]
        self._demo_step += 1

        self.set_emotion(emo)

        face = self.root_widget.ids.get("face")
        if face:
            if emo in ("happy", "angry", "surprised"):
                face.start_talking()
            else:
                face.stop_talking()

    def _demo_eye_move(self, dt):
        face = self.root_widget.ids.get("face")
        if not face:
            return
        t = Clock.get_time()
        face.look_at(math.sin(t), math.cos(t * 0.7) * 0.5)

    # ============== AI 事件处理 ==============
    def _on_ai_action(self, instance, action, emotion):
        # 更新表情并处理动作指令（动作交给上层或硬件）
        if "face" in self.root_widget.ids:
            try:
                self.root_widget.ids.face.set_emotion(emotion)
            except Exception:
                pass
        # 简单打印或延后处理动作
        print(f"AI action received: {action}, emotion: {emotion}")

    def _on_ai_speech(self, instance, text):
        # 接收逐块/逐字的 speech 输出，传递给 RobotFace 做显示
        face = self.root_widget.ids.get('face')
        if face:
            try:
                face.show_speaking_text(text)
            except Exception:
                pass
        # 聚合分片，短时间无新分片则触发 TTS 播放完整句子
        try:
            self._ai_speech_buf += str(text)
            if self._ai_speech_clear_ev:
                self._ai_speech_clear_ev.cancel()
            self._ai_speech_clear_ev = Clock.schedule_once(self._ai_speak_final, 0.6)
        except Exception:
            pass

    def _ai_speak_final(self, dt):
        txt = self._ai_speech_buf.strip()
        self._ai_speech_buf = ''
        self._ai_speech_clear_ev = None
        if not txt:
            return
        # 尝试使用 plyer tts（优先，支持 Android/iOS），失败则回退到桌面 TTS（pyttsx3）
        try:
            from plyer import tts
            try:
                tts.speak(txt)
                return
            except Exception as e:
                print(f"TTS (plyer) play failed: {e}")
        except Exception as e:
            print(f"plyer.tts not available: {e}")

        # 回退到 pyttsx3（桌面环境），若不可用则打印文本
        try:
            # 确保 comtypes 有一个可写的缓存目录，避免权限错误
            try:
                cache_dir = os.environ.get('COMTYPES_CACHE_DIR') or os.path.join(os.path.expanduser('~'), '.comtypes_cache')
                os.makedirs(cache_dir, exist_ok=True)
                os.environ['COMTYPES_CACHE_DIR'] = cache_dir
            except Exception as _e:
                print(f"Warning: cannot create comtypes cache dir: {_e}")

            import pyttsx3
            try:
                engine = pyttsx3.init()
                # 调整语速与音量为适中
                try:
                    engine.setProperty('rate', 150)
                except Exception:
                    pass
                engine.say(txt)
                engine.runAndWait()
                return
            except Exception as e:
                print(f"TTS (pyttsx3) play failed: {e}")
                # Windows 特殊回退到 SAPI（win32com）尝试
                try:
                    import platform as _plat
                    if _plat.system().lower().startswith('win'):
                        try:
                            import win32com.client
                            sapi = win32com.client.Dispatch("SAPI.SpVoice")
                            sapi.Speak(txt)
                            return
                        except Exception as e2:
                            print(f"TTS (win32com SAPI) play failed: {e2}")
                            # PowerShell SAPI 直接调用回退（避开 comtypes 生成），可在多数 Windows 上工作
                            try:
                                if sys.platform.startswith('win'):
                                    ps_cmd = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak({json.dumps(txt)})"
                                    subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True)
                                    return
                            except Exception as e3:
                                print(f"TTS (PowerShell) play failed: {e3}")
                except Exception:
                    pass
        except Exception as e:
            print(f"pyttsx3 not available: {e}")

        # 最后的回退：在控制台输出文本
        print(f"AI says: {txt}")

    # ================== 外部接口 ==================
    def set_emotion(self, emo):
        if "face" in self.root_widget.ids:
            self.root_widget.ids.face.set_emotion(emo)
