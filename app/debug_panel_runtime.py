import logging
import os
import subprocess
import sys
import threading
import time

from kivy.app import App
from kivy.clock import Clock

from widgets.universal_tip import UniversalTip
from widgets.debug_ui_components import ServoStatusCard
from services.wifi_servo import get_controller as get_wifi_servo

logger = logging.getLogger(__name__)


def show_info_popup(owner, text, title="提示"):
    """使用通用提示气泡弹窗展示消息。"""
    try:
        UniversalTip(message=str(text), title=title).open()
    except Exception:
        try:
            # 兜底：直接调用 owner 的 popup 接口（若存在）
            if hasattr(owner, "_debug_popup") and getattr(owner, "_debug_popup"):
                owner._debug_popup.dismiss()
            popup = UniversalTip(message=str(text), title=title)
            popup.open()
        except Exception:
            pass


def call_motion(owner, action_name):
    """调用 ESP32 预设动作（通过 wifi_servo.send_motion）。"""
    app = App.get_running_app()
    ctrl = getattr(app, "wifi_servo", None) or get_wifi_servo()
    if not ctrl or not ctrl.is_connected:
        show_info_popup(owner, "未连接 ESP32，无法下发动作")
        return False
    try:
        ok = ctrl.send_motion(action_name)
        if ok:
            show_info_popup(owner, f"已下发动作：{action_name}")
        else:
            show_info_popup(owner, f"下发动作失败：{action_name}")
        return bool(ok)
    except Exception as e:
        show_info_popup(owner, f"动作发送异常: {e}")
        return False


def start_demo_thread(owner):
    t = threading.Thread(target=lambda: run_demo_motion(owner), daemon=True)
    t.start()


def run_demo_motion(owner):
    app = App.get_running_app()

    def show_msg(txt):
        owner._show_info_popup(txt)

    try:
        from widgets.runtime_status import RuntimeStatusLogger
    except Exception:
        RuntimeStatusLogger = None

    ctrl = getattr(app, "wifi_servo", None) or get_wifi_servo()
    if not ctrl or not ctrl.is_connected:
        show_msg("未连接 ESP32，无法运行 Demo")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_error("Demo 启动失败：未连接 ESP32")
        return

    try:
        from services.motion_controller import MotionController
        from services.imu import IMUReader
    except Exception as e:
        show_msg(f"模块导入失败: {e}")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_error(f"Demo 模块导入失败: {e}")
        return

    neutral = {i: 2048 for i in range(1, 26)}
    imu = IMUReader(simulate=True)
    imu.start()
    mc = MotionController(
        servo_manager=None,
        balance_ctrl=app.balance_ctrl,
        imu_reader=imu,
        neutral_positions=neutral,
    )

    show_msg("开始 Demo: 站立")
    if RuntimeStatusLogger:
        RuntimeStatusLogger.log_action("Demo 开始 - 站立")
    mc.stand()
    time.sleep(1.0)

    show_msg("Demo: 挥手")
    if RuntimeStatusLogger:
        RuntimeStatusLogger.log_action("Demo - 挥手")
    mc.wave(side="right", times=3)
    time.sleep(0.6)

    show_msg("Demo: 向前小步")
    if RuntimeStatusLogger:
        RuntimeStatusLogger.log_action("Demo - 向前小步")
    mc.walk(steps=2, step_length=120, step_height=120, time_per_step_ms=350)
    time.sleep(0.6)

    show_msg("Demo: 坐下")
    if RuntimeStatusLogger:
        RuntimeStatusLogger.log_action("Demo - 坐下")
    mc.sit()
    time.sleep(1.2)

    show_msg("Demo: 起立并回中位")
    if RuntimeStatusLogger:
        RuntimeStatusLogger.log_action("Demo - 起立并回中位")
    mc.stand()
    time.sleep(0.8)

    imu.stop()
    show_msg("Demo 完成")
    if RuntimeStatusLogger:
        RuntimeStatusLogger.log_action("Demo 完成")


def start_zero_id_thread(owner):
    t = threading.Thread(target=lambda: run_zero_id_script(owner), daemon=True)
    t.start()


def run_zero_id_script(owner):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    script = os.path.join(root, "tools", "testbench", "servo_zero_and_id.py")
    if not os.path.exists(script):
        script = os.path.join(
            os.path.abspath(os.path.join(root, "..")),
            "tools",
            "testbench",
            "servo_zero_and_id.py",
        )
    if not os.path.exists(script):
        owner._show_info_popup("未找到 servo_zero_and_id.py 脚本")
        return
    try:
        subprocess.Popen([sys.executable, script])
        owner._show_info_popup("归零/写ID脚本已在后台启动")
    except Exception as e:
        owner._show_info_popup(f"启动脚本失败: {e}")


def emergency_torque_release(owner):
    app = App.get_running_app()

    try:
        from widgets.runtime_status import RuntimeStatusLogger
    except Exception:
        RuntimeStatusLogger = None

    ctrl = getattr(app, "wifi_servo", None) or get_wifi_servo()
    if not ctrl or not ctrl.is_connected:
        owner._show_info_popup("未连接 ESP32")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_error("未连接 ESP32 无法释放扭矩")
        return

    try:
        if ctrl.set_torque(False):
            owner._show_info_popup("已发送：扭矩释放广播")
            if RuntimeStatusLogger:
                RuntimeStatusLogger.log_action("扭矩释放广播已发送")
        else:
            owner._show_info_popup("释放扭矩失败")
    except Exception as e:
        owner._show_info_popup(f"释放扭矩失败: {e}")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_error(f"释放扭矩失败: {e}")

def render_status_cards(owner, cards):
    grid = getattr(owner, "_status_grid", None)
    if grid is None:
        return
    try:
        on_card_click = getattr(owner, "_on_status_card_click", None)
        card_map = getattr(owner, "_status_card_widgets", None)
        if not isinstance(card_map, dict):
            card_map = {}
            owner._status_card_widgets = card_map

        sid_set = set(int(sid) for sid, _data, _online in cards)
        old_sids = set(card_map.keys())
        for sid in sorted(old_sids - sid_set):
            try:
                widget = card_map.pop(sid, None)
                if widget is not None:
                    grid.remove_widget(widget)
            except Exception:
                pass

        wanted_order = []
        for sid, data, online in cards:
            sid = int(sid)
            wanted_order.append(sid)
            widget = card_map.get(sid)
            if widget is None:
                widget = ServoStatusCard(sid, data=data, online=online, on_click=on_card_click)
                card_map[sid] = widget
                try:
                    grid.add_widget(widget)
                except Exception:
                    pass
            else:
                try:
                    widget.on_click = on_card_click
                    widget.update_data(data)
                    widget.set_online(bool(online))
                except Exception:
                    pass

        current_widgets = list(getattr(grid, "children", []))
        current_sids = []
        for w in current_widgets:
            try:
                current_sids.append(int(getattr(w, "sid", -1)))
            except Exception:
                current_sids.append(-1)
        expected_sids = list(reversed(wanted_order))

        if current_sids != expected_sids:
            try:
                grid.clear_widgets()
                for sid in wanted_order:
                    widget = card_map.get(sid)
                    if widget is not None:
                        grid.add_widget(widget)
            except Exception:
                pass
    except Exception:
        pass


def refresh_servo_status(owner):
    status_grid = getattr(owner, "_status_grid", None)
    if status_grid is None:
        return

    # 首次刷新先填充占位卡，避免出现空白页（尤其是移动端首帧）
    try:
        has_widgets = bool(getattr(status_grid, "children", None))
        has_cache = bool(getattr(owner, "_status_cards_cache", None))
        if (not has_widgets) and (not has_cache):
            placeholder_cards = [(sid, None, False) for sid in range(1, 26)]
            Clock.schedule_once(lambda dt, cards=placeholder_cards: render_status_cards(owner, cards), 0)
    except Exception:
        pass

    try:
        suspend_until = float(getattr(owner, "_status_poll_suspended_until", 0.0) or 0.0)
    except Exception:
        suspend_until = 0.0

    app = App.get_running_app()

    # 优先通过 wifi_servo 获取状态
    try:
        ctrl = getattr(app, "wifi_servo", None) or get_wifi_servo()
        if ctrl and ctrl.is_connected:
            st = ctrl.request_status(timeout=0.8)
            if st and "servos" in st:
                cards = []
                for sid_s, sdata in st["servos"].items():
                    sid = int(sid_s)
                    data = {
                        "pos": sdata.get("position"),
                        "temp": sdata.get("temperature"),
                        "volt": sdata.get("voltage"),
                        "torque": sdata.get("torque"),
                    }
                    cards.append((sid, data, True))
                if cards:
                    owner._status_cards_cache = cards
                    owner._status_cards_cache_time = time.time()
                    Clock.schedule_once(lambda dt, c=cards: render_status_cards(owner, c), 0)
                    return
    except Exception:
        pass
    if time.time() < suspend_until:
        # 轮询暂停期间若有缓存则继续展示，避免用户看到空白
        try:
            cards = list(getattr(owner, "_status_cards_cache", None) or [])
            if cards:
                Clock.schedule_once(lambda dt, c=cards: render_status_cards(owner, c), 0)
        except Exception:
            pass
        return

    now = time.time()
    try:
        runtime_profile = str(getattr(app, "_runtime_profile", "") or "").lower()
        if runtime_profile == "mobile":
            owner._status_cache_ttl = float(max(1.8, getattr(owner, "_status_cache_ttl", 1.2) or 1.2))
    except Exception:
        pass

    if (
        owner._status_cards_cache is not None
        and (now - float(getattr(owner, "_status_cards_cache_time", 0.0) or 0.0))
        < float(getattr(owner, "_status_cache_ttl", 1.2) or 1.2)
    ):
        cards = list(owner._status_cards_cache)

        def _render_cached(dt=0):
            render_status_cards(owner, cards)

        Clock.schedule_once(_render_cached, 0)
        return

    # wifi_servo 未返回数据，显示占位卡
    cards = [(sid, None, False) for sid in range(1, 26)]

    owner._status_cards_cache = list(cards)
    owner._status_cards_cache_time = time.time()
