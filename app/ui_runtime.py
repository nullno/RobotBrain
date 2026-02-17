import time

from widgets.runtime_status import RuntimeStatusLogger


def should_log_usb_status(app, key, status, interval_sec=3.0):
    """同类 USB 状态日志节流：状态变化立即记，重复状态按间隔记。"""
    try:
        now = time.time()
        last_status = getattr(app, f"_last_{key}_status", None)
        last_time = float(getattr(app, f"_last_{key}_time", 0.0) or 0.0)
        if status != last_status or (now - last_time) >= float(interval_sec):
            setattr(app, f"_last_{key}_status", status)
            setattr(app, f"_last_{key}_time", now)
            return True
        return False
    except Exception:
        return True


def log_usb_state_summary(app):
    """输出单行 USB 状态机摘要，便于现场排障。"""
    try:
        st = getattr(app, "_usb_state", None) or {}
        line = (
            "USB状态机: "
            f"detect={st.get('detect', 'idle')} | "
            f"auth={st.get('auth', 'idle')} | "
            f"connect={st.get('connect', 'idle')} | "
            f"scan={st.get('scan', 'idle')}"
        )
        detail = str(st.get("detail", "") or "").strip()
        if detail:
            line += f" | {detail}"
        if should_log_usb_status(app, "usb_state_summary", line, 1.5):
            RuntimeStatusLogger.log_info(line)
    except Exception:
        pass


def update_usb_state(app, **kwargs):
    """更新 USB 连接状态机并输出单行摘要日志。"""
    try:
        st = getattr(app, "_usb_state", None)
        if not isinstance(st, dict):
            st = {
                "detect": "idle",
                "auth": "idle",
                "connect": "idle",
                "scan": "idle",
                "detail": "",
            }
        st.update(kwargs)
        app._usb_state = st
        log_usb_state_summary(app)
    except Exception:
        pass


def safe_refresh_ui(app, dt=0):
    """在主线程安全刷新调试面板与运行面板。"""
    try:
        try:
            dp = None
            if hasattr(app, "root_widget") and getattr(app.root_widget, "ids", None):
                dp = app.root_widget.ids.get("debug_panel")
            if dp and hasattr(dp, "refresh_servo_status"):
                dp.refresh_servo_status()
        except Exception:
            pass
        try:
            rs = None
            if hasattr(app, "root_widget") and getattr(app.root_widget, "ids", None):
                rs = app.root_widget.ids.get("runtime_status")
            if rs and hasattr(rs, "refresh"):
                rs.refresh()
        except Exception:
            pass
    except Exception:
        pass
