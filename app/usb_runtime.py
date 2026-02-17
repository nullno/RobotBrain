import threading
import time

from kivy.clock import Clock
from kivy.utils import platform

from widgets.runtime_status import RuntimeStatusLogger
from services.servo_bus import ServoBus
from services.imu import IMUReader
from services.motion_controller import MotionController


def _get_android_servo_baud_candidates(app):
    """获取 Android 舵机串口候选波特率（按优先级去重）。"""
    values = []
    try:
        cur = int(getattr(app, "_usb_baud", 0) or 0)
        if cur > 0:
            values.append(cur)
    except Exception:
        pass

    try:
        extra = getattr(app, "_usb_baud_candidates", None)
        if isinstance(extra, (list, tuple)):
            for item in extra:
                try:
                    v = int(item)
                    if v > 0:
                        values.append(v)
                except Exception:
                    pass
    except Exception:
        pass

    values.extend([115200, 1000000])
    uniq = []
    seen = set()
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        uniq.append(v)
    return uniq


def _try_open_android_servo_bus(app, prefer_device_id=None):
    """按候选波特率尝试打开 Android USB 串口并创建 ServoBus。"""
    try:
        from services.android_serial import (
            open_first_usb_serial,
            get_last_usb_serial_status,
        )
    except Exception:
        return None, "fail: android_serial import error", None

    last_status = "fail: unknown"
    for baud in _get_android_servo_baud_candidates(app):
        try:
            usb_wrapper = open_first_usb_serial(
                baud=baud,
                prefer_device_id=prefer_device_id,
            )
            last_status = str(get_last_usb_serial_status())
            if not usb_wrapper:
                continue

            sb = ServoBus(port=usb_wrapper, baudrate=baud)
            if sb and not getattr(sb, "is_mock", True):
                try:
                    app._usb_baud = int(baud)
                except Exception:
                    pass
                return sb, last_status, baud

            try:
                usb_wrapper.close()
            except Exception:
                pass
        except Exception:
            try:
                last_status = str(get_last_usb_serial_status())
            except Exception:
                pass
            continue
    return None, last_status, None


def _retry_android_servo_scan_with_baud_fallback(app, source="连接"):
    """Android 在 0/25 时切换波特率重连并复扫一次。"""
    try:
        if platform != "android":
            return []
        if getattr(app, "_android_baud_recover_in_progress", False):
            return []
        app._android_baud_recover_in_progress = True

        old_sb = getattr(app, "servo_bus", None)
        sb, status, baud = _try_open_android_servo_bus(app)
        if not sb:
            return []

        try:
            if old_sb and old_sb is not sb and hasattr(old_sb, "close"):
                old_sb.close()
        except Exception:
            pass

        app.servo_bus = sb
        try:
            app._mark_usb_connected_after_permission(status)
        except Exception:
            pass
        init_motion_controller_after_connect(app)

        mgr = getattr(sb, "manager", None)
        if not mgr:
            return []

        scan_ids = list(range(1, 26))
        online_ids = []
        for idx in range(3):
            try:
                mgr.servo_scan(scan_ids)
            except Exception:
                pass

            try:
                online_ids = sorted(
                    sid
                    for sid, info in getattr(mgr, "servo_info_dict", {}).items()
                    if getattr(info, "is_online", False)
                )
            except Exception:
                online_ids = []

            if online_ids:
                break
            time.sleep(0.25 + 0.2 * idx)

        if online_ids:
            RuntimeStatusLogger.log_info(
                f"{source}后0/25，切换波特率重连成功（baud={baud}），在线 {len(online_ids)} 个"
            )
        else:
            RuntimeStatusLogger.log_info(
                f"{source}后0/25，已尝试波特率重连（baud={baud}）但仍未发现舵机"
            )
        return online_ids
    except Exception:
        return []
    finally:
        try:
            app._android_baud_recover_in_progress = False
        except Exception:
            pass


def is_duplicate_usb_attach_event(app, signature, interval_sec=4.0):
    """判断 USB attach 事件是否在短时间内重复。"""
    try:
        now = time.time()
        sig = str(signature or "unknown")
        last_sig = str(getattr(app, "_last_usb_attach_signature", "") or "")
        last_t = float(getattr(app, "_last_usb_attach_time", 0.0) or 0.0)
        is_dup = (sig == last_sig) and ((now - last_t) < float(interval_sec))
        app._last_usb_attach_signature = sig
        app._last_usb_attach_time = now
        return is_dup
    except Exception:
        return False


def ensure_android_usb_reconnect_watcher(app, reason=""):
    """Android USB 授权等待期间，定时重试连接；成功后自动停止。"""
    try:
        if platform != "android":
            return
        now = time.time()
        app._android_usb_reconnect_deadline = max(
            float(getattr(app, "_android_usb_reconnect_deadline", 0.0) or 0.0),
            now + 30.0,
        )
        if getattr(app, "_android_usb_reconnect_ev", None):
            return

        def _tick(dt):
            try:
                if (
                    getattr(app, "servo_bus", None)
                    and not getattr(app.servo_bus, "is_mock", True)
                ):
                    app._android_usb_reconnect_ev = None
                    return False

                if time.time() > float(getattr(app, "_android_usb_reconnect_deadline", 0.0) or 0.0):
                    app._android_usb_reconnect_ev = None
                    return False

                sb, status, baud = _try_open_android_servo_bus(app)
                if sb:
                    try:
                        if getattr(app, "servo_bus", None) and hasattr(app.servo_bus, "close"):
                            app.servo_bus.close()
                    except Exception:
                        pass
                    app.servo_bus = sb
                    app._mark_usb_connected_after_permission(status)
                    init_motion_controller_after_connect(app)
                    RuntimeStatusLogger.log_info(
                        f"Android USB 串口已连接（授权后自动重试成功，baud={baud}）"
                    )
                    schedule_servo_scan_after_connect(app, "USB授权")
                    Clock.schedule_once(app._safe_refresh_ui, 0)
                    app._android_usb_reconnect_ev = None
                    return False

                if status.startswith("wait:"):
                    if app._should_log_usb_status("usb_wait_reconnect", status, 3.0):
                        RuntimeStatusLogger.log_info("等待 USB 授权中: " + status)
                        app._last_usb_permission_status = status
                    app._update_usb_state(
                        detect="device",
                        auth="wait",
                        connect="down",
                        detail=status,
                    )
                else:
                    app._last_usb_permission_status = None
                    app._update_usb_state(
                        detect="nodevice",
                        auth="idle",
                        connect="down",
                        detail=status,
                    )
                return True
            except Exception:
                return True

        app._android_usb_reconnect_ev = Clock.schedule_interval(_tick, 1.0)
        if reason:
            RuntimeStatusLogger.log_info(f"已启动 Android USB 自动重试: {reason}")
    except Exception:
        pass


def handle_android_usb_attach_intent(app, source="resume"):
    """处理 Android USB attach intent，并做短时间去重。"""
    try:
        if platform != "android":
            return
        try:
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            intent = activity.getIntent()
            if not intent:
                return
            action = str(intent.getAction() or "")
            if action != "android.hardware.usb.action.USB_DEVICE_ATTACHED":
                return

            UsbManager = autoclass("android.hardware.usb.UsbManager")
            dev = intent.getParcelableExtra(UsbManager.EXTRA_DEVICE)
            dev_name = "unknown"
            vid = -1
            pid = -1
            try:
                if dev:
                    dev_name = str(dev.getDeviceName())
                    vid = int(dev.getVendorId())
                    pid = int(dev.getProductId())
            except Exception:
                pass

            sig = f"{action}|{dev_name}|{vid}:{pid}"
            if is_duplicate_usb_attach_event(app, sig, 4.0):
                app._update_usb_state(
                    detect="device",
                    detail=f"intent重复已忽略({source}): {dev_name} {vid}:{pid}",
                )
                RuntimeStatusLogger.log_info(
                    f"忽略重复 USB attach intent: {dev_name} {vid}:{pid}"
                )
                app._suppress_android_otg_added_until = time.time() + 2.5
                return

            app._update_usb_state(
                detect="device",
                auth="unknown",
                connect="down",
                detail=f"intent={dev_name} {vid}:{pid}",
            )
            RuntimeStatusLogger.log_info(
                f"收到 USB attach intent({source}): {dev_name} {vid}:{pid}"
            )
            ensure_android_usb_reconnect_watcher(app, "attach intent")
        except Exception:
            pass
    except Exception:
        pass


def init_motion_controller_after_connect(app):
    """连接成功后初始化 MotionController。"""
    try:
        imu = IMUReader(simulate=False)
        imu.start()
        app.motion_controller = MotionController(
            app.servo_bus.manager,
            balance_ctrl=app.balance_ctrl,
            imu_reader=imu,
            neutral_positions={},
        )
    except Exception:
        app.motion_controller = None


def schedule_servo_scan_after_connect(app, source="连接"):
    """连接成功后在后台重扫舵机，避免设备刚枚举完成时首轮扫描漏检。"""
    try:
        if getattr(app, "_servo_scan_in_progress", False):
            return
        app._servo_scan_in_progress = True

        def _worker():
            try:
                sb = getattr(app, "servo_bus", None)
                if not sb or getattr(sb, "is_mock", True):
                    return

                mgr = getattr(sb, "manager", None)
                if not mgr:
                    return

                if platform == "android":
                    try:
                        # 手机侧 USB 串口刚建立时总线可能尚未稳定，先短暂等待再扫
                        time.sleep(0.18)
                    except Exception:
                        pass

                scan_ids = list(range(1, 26))
                online_ids = []
                for idx in range(3):
                    try:
                        mgr.servo_scan(scan_ids)
                    except Exception:
                        pass

                    try:
                        online_ids = sorted(
                            sid
                            for sid, info in getattr(mgr, "servo_info_dict", {}).items()
                            if getattr(info, "is_online", False)
                        )
                    except Exception:
                        online_ids = []

                    if online_ids:
                        break

                    time.sleep(0.25 + 0.2 * idx)

                if online_ids:
                    app._update_usb_state(
                        connect="up",
                        scan=f"ok({len(online_ids)})",
                        detail=f"online={len(online_ids)}",
                    )
                    RuntimeStatusLogger.log_info(
                        f"{source}后舵机扫描完成，在线 {len(online_ids)} 个"
                    )
                else:
                    recovered_ids = []
                    if platform == "android":
                        recovered_ids = _retry_android_servo_scan_with_baud_fallback(app, source)

                    if recovered_ids:
                        app._update_usb_state(
                            connect="up",
                            scan=f"ok({len(recovered_ids)})",
                            detail=f"online={len(recovered_ids)}",
                        )
                        RuntimeStatusLogger.log_info(
                            f"{source}后初次扫描0/25，重连重扫恢复成功，在线 {len(recovered_ids)} 个"
                        )
                    else:
                        tried_bauds = _get_android_servo_baud_candidates(app) if platform == "android" else [115200]
                        app._update_usb_state(
                            connect="up",
                            scan="none(0)",
                            detail="online=0",
                        )
                        RuntimeStatusLogger.log_error(
                            f"{source}后串口已连接，但未扫描到舵机（0/25），请检查舵机供电/接线/ID/波特率；已尝试波特率={tried_bauds}，并已放宽通信超时/重试"
                        )

                try:
                    Clock.schedule_once(app._safe_refresh_ui, 0)
                except Exception:
                    pass
            finally:
                app._servo_scan_in_progress = False

        threading.Thread(target=_worker, daemon=True).start()
    except Exception:
        try:
            app._servo_scan_in_progress = False
        except Exception:
            pass


def try_auto_connect(app, candidate_ports=None, list_ports_module=None):
    """尝试通过候选端口列表自动连接 ServoBus。"""
    try:
        if platform == "android" and not candidate_ports:
            try:
                sb, status, baud = _try_open_android_servo_bus(app)
                if sb:
                    if getattr(app, "servo_bus", None) and hasattr(app.servo_bus, "close"):
                        try:
                            app.servo_bus.close()
                        except Exception:
                            pass

                    app.servo_bus = sb
                    app._mark_usb_connected_after_permission(status)
                    init_motion_controller_after_connect(app)
                    RuntimeStatusLogger.log_info(f"自动连接 Android USB 串口成功（baud={baud}）")
                    Clock.schedule_once(app._safe_refresh_ui, 0)
                    return True
                else:
                    try:
                        _s = str(status)
                        if _s.startswith("wait:"):
                            app._last_usb_permission_status = _s
                            app._update_usb_state(
                                detect="device",
                                auth="wait",
                                connect="down",
                                detail=_s,
                            )
                            RuntimeStatusLogger.log_info(
                                "自动连接检测到设备，等待 USB 授权: " + _s
                            )
                            app._ensure_android_usb_reconnect_watcher("自动连接等待授权")
                        else:
                            app._update_usb_state(
                                detect="nodevice",
                                auth="idle",
                                connect="down",
                                detail=_s,
                            )
                            RuntimeStatusLogger.log_info(
                                "自动连接 Android USB 串口未成功: " + _s
                            )
                    except Exception:
                        pass
            except Exception as e:
                print(f"Android auto-connect failed: {e}")

        candidates = []
        if candidate_ports:
            candidates = list(candidate_ports)
        else:
            if list_ports_module:
                try:
                    for p in list_ports_module.comports():
                        dev = p.device
                        desc = p.description or ""
                        if (
                            "ch340" in desc.lower()
                            or "usb-serial" in desc.lower()
                            or "usb serial" in desc.lower()
                        ):
                            candidates.insert(0, dev)
                        else:
                            candidates.append(dev)
                except Exception:
                    pass

            default = getattr(app, "_dev_port", None) or (
                "/dev/ttyUSB0" if platform == "android" else "COM8"
            )
            if default and default not in candidates:
                candidates.append(default)

        for cand in candidates:
            try:
                sb = ServoBus(port=cand)
                if sb and not getattr(sb, "is_mock", True):
                    try:
                        if getattr(app, "servo_bus", None) and hasattr(
                            app.servo_bus, "close"
                        ):
                            try:
                                app.servo_bus.close()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    app._dev_port = cand
                    app.servo_bus = sb
                    init_motion_controller_after_connect(app)
                    try:
                        RuntimeStatusLogger.log_info(f"自动连接串口成功: {cand}")
                    except Exception:
                        pass
                    try:
                        Clock.schedule_once(app._safe_refresh_ui, 0)
                    except Exception:
                        pass
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def handle_otg_event(app, event, device_id, list_ports_module=None):
    """处理 OTG 插拔事件：在设备插入时尝试重建 ServoBus 并刷新界面；拔出时清理状态。"""
    try:
        if event == "added":
            try:
                sig = f"otg-added|{device_id}"
                if app._is_duplicate_usb_attach_event(sig, 2.0):
                    if app._should_log_usb_status("otg_added_duplicate", sig, 1.5):
                        RuntimeStatusLogger.log_info(f"忽略重复 OTG added 事件: {device_id}")
                    return
            except Exception:
                pass

        def _handle():
            try:
                if event == "added":
                    try:
                        if platform == "android":
                            suppress_until = float(
                                getattr(app, "_suppress_android_otg_added_until", 0.0)
                                or 0.0
                            )
                            if time.time() < suppress_until:
                                return
                    except Exception:
                        pass

                    try:
                        if (
                            platform == "android"
                            and getattr(app, "servo_bus", None)
                            and not getattr(app.servo_bus, "is_mock", True)
                        ):
                            return
                    except Exception:
                        pass

                    try:
                        if platform == "android":
                            try:
                                sb, status, baud = _try_open_android_servo_bus(
                                    app,
                                    prefer_device_id=device_id,
                                )
                            except Exception:
                                sb, status, baud = None, "fail: unknown", None

                            if sb:
                                try:
                                    app._mark_usb_connected_after_permission(status)
                                except Exception:
                                    pass

                                try:
                                    if getattr(app, "servo_bus", None) and hasattr(
                                        app.servo_bus, "close"
                                    ):
                                        try:
                                            app.servo_bus.close()
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                                app.servo_bus = sb
                                try:
                                    RuntimeStatusLogger.log_info(
                                        f"OTG 串口连接成功（baud={baud}）"
                                    )
                                except Exception:
                                    pass
                                try:
                                    schedule_servo_scan_after_connect(app, "OTG")
                                except Exception:
                                    pass
                                try:
                                    Clock.schedule_once(app._safe_refresh_ui, 0)
                                except Exception:
                                    pass
                                return
                            else:
                                try:
                                    status = str(status)
                                    if status.startswith("wait:"):
                                        if app._should_log_usb_status("usb_permission", status, 3.0):
                                            RuntimeStatusLogger.log_info(
                                                "OTG 已检测到设备，正在等待 USB 授权: " + status
                                            )
                                            app._last_usb_permission_status = status
                                        app._update_usb_state(
                                            detect="device",
                                            auth="wait",
                                            connect="down",
                                            detail=status,
                                        )
                                        app._ensure_android_usb_reconnect_watcher("OTG插入等待授权")
                                    else:
                                        app._last_usb_permission_status = None
                                        app._update_usb_state(
                                            detect="device",
                                            auth="unknown",
                                            connect="down",
                                            detail=status,
                                        )
                                        if app._should_log_usb_status("usb_unconnected", status, 3.0):
                                            RuntimeStatusLogger.log_info(
                                                "OTG added 事件触发，但 Android USB Serial 未连接: " + status
                                            )
                                except Exception:
                                    pass
                    except Exception:
                        pass

                def _parse_port(dev_id):
                    try:
                        if not dev_id:
                            return None
                        if "::" in dev_id:
                            return dev_id.split("::", 1)[0]
                        import re

                        m = re.search(r"(COM\d+)", dev_id, re.I)
                        if m:
                            return m.group(1)
                        m = re.search(r"(/dev/tty[^,;\s]+)", dev_id)
                        if m:
                            return m.group(1)
                        return dev_id
                    except Exception:
                        return None

                port = (
                    _parse_port(device_id)
                    or getattr(app, "_dev_port", None)
                    or ("/dev/ttyUSB0" if platform == "android" else "COM8")
                )

                if not getattr(app, "servo_bus", None) or getattr(
                    app.servo_bus, "is_mock", True
                ):
                    try:
                        app._dev_port = port
                        tried = [port]
                        connected = False
                        try_ports = list(tried)

                        if list_ports_module:
                            try:
                                for p in list_ports_module.comports():
                                    dev = p.device
                                    desc = p.description or ""
                                    if dev not in try_ports:
                                        if (
                                            "ch340" in desc.lower()
                                            or "usb-serial" in desc.lower()
                                            or "usb serial" in desc.lower()
                                        ):
                                            try_ports.insert(0, dev)
                                        else:
                                            try_ports.append(dev)
                            except Exception:
                                pass

                        import time as _time

                        _time.sleep(0.2)
                        if list_ports_module:
                            try:
                                for p in list_ports_module.comports():
                                    dev = p.device
                                    if dev not in try_ports:
                                        try_ports.append(dev)
                            except Exception:
                                pass

                        for cand in try_ports:
                            try:
                                sb = ServoBus(port=cand)
                                if sb and not getattr(sb, "is_mock", True):
                                    try:
                                        if getattr(app, "servo_bus", None) and hasattr(
                                            app.servo_bus, "close"
                                        ):
                                            try:
                                                app.servo_bus.close()
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                    app.servo_bus = sb
                                    try:
                                        schedule_servo_scan_after_connect(app, "OTG")
                                    except Exception:
                                        pass
                                    connected = True
                                    try:
                                        imu = IMUReader(simulate=False)
                                        imu.start()
                                        app.motion_controller = MotionController(
                                            app.servo_bus.manager,
                                            balance_ctrl=app.balance_ctrl,
                                            imu_reader=imu,
                                            neutral_positions={},
                                        )
                                    except Exception:
                                        app.motion_controller = None
                                    try:
                                        RuntimeStatusLogger.log_info(
                                            f"检测到 OTG 设备，已连接串口: {cand}"
                                        )
                                    except Exception:
                                        pass
                                    break
                            except Exception:
                                pass

                        if connected:
                            try:
                                Clock.schedule_once(app._safe_refresh_ui, 0)
                            except Exception:
                                pass
                    except Exception:
                        pass
                elif event == "removed":
                    try:
                        if getattr(app, "servo_bus", None) and hasattr(
                            app.servo_bus, "close"
                        ):
                            try:
                                app.servo_bus.close()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        app.servo_bus = None
                    except Exception:
                        pass
                    try:
                        app.motion_controller = None
                    except Exception:
                        pass
                    try:
                        RuntimeStatusLogger.log_info(f"串口设备已拔出: {device_id}")
                        app._update_usb_state(
                            detect="nodevice",
                            auth="idle",
                            connect="down",
                            scan="idle",
                            detail=f"removed={device_id}",
                        )
                    except Exception:
                        pass
                    try:
                        Clock.schedule_once(app._safe_refresh_ui, 0)
                    except Exception:
                        pass
            except Exception:
                pass

        threading.Thread(target=_handle, daemon=True).start()
    except Exception:
        pass
