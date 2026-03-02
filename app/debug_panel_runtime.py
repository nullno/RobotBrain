import os
import subprocess
import sys
import threading
import time

from kivy.app import App
from kivy.clock import Clock

from widgets.universal_tip import UniversalTip
from widgets.debug_ui_components import ServoStatusCard


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

    if (
        not hasattr(app, "servo_bus")
        or not app.servo_bus
        or getattr(app.servo_bus, "is_mock", True)
    ):
        show_msg("未连接舵机或为 MOCK 模式，无法运行 Demo")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_error("Demo 启动失败：未连接舵机或为 MOCK 模式")
        return

    try:
        from services.motion_controller import MotionController
        from services.imu import IMUReader
    except Exception as e:
        show_msg(f"模块导入失败: {e}")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_error(f"Demo 模块导入失败: {e}")
        return

    servo_mgr = app.servo_bus.manager
    neutral = (
        {i: 2048 for i in servo_mgr.servo_info_dict.keys()}
        if hasattr(servo_mgr, "servo_info_dict")
        else {i: 2048 for i in range(1, 26)}
    )
    imu = IMUReader(simulate=True)
    imu.start()
    mc = MotionController(
        servo_mgr,
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

    show_msg("Demo: 前行小步")
    if RuntimeStatusLogger:
        RuntimeStatusLogger.log_action("Demo - 前行小步")
    mc.walk(steps=2, step_length=120, step_height=120, time_per_step_ms=350)
    time.sleep(0.6)

    show_msg("Demo: 坐下")
    if RuntimeStatusLogger:
        RuntimeStatusLogger.log_action("Demo - 坐下")
    mc.sit()
    time.sleep(1.2)

    show_msg("Demo: 站起并回中位")
    if RuntimeStatusLogger:
        RuntimeStatusLogger.log_action("Demo - 站起并回中位")
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
        owner._show_info_popup("归零/写ID脚本已在独立进程启动")
    except Exception as e:
        owner._show_info_popup(f"启动脚本失败: {e}")


def emergency_torque_release(owner):
    app = App.get_running_app()

    try:
        from widgets.runtime_status import RuntimeStatusLogger
    except Exception:
        RuntimeStatusLogger = None

    if not hasattr(app, "servo_bus") or not app.servo_bus:
        owner._show_info_popup("未找到 ServoBus")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_error("未找到 ServoBus 无法释放扭矩")
        return
    try:
        app.servo_bus.set_torque(False)
        owner._show_info_popup("已发送：紧急释放扭矩")
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action("紧急释放扭矩")
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

    # 先渲染占位卡，避免首次刷新期间（尤其手机端串口探测慢）出现空白页
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

    try:
        bridge = getattr(app, "control_bridge", None)
        if bridge:
            cards = list(bridge.get_servo_cards() or [])
            if cards:
                owner._status_cards_cache = cards
                owner._status_cards_cache_time = time.time()
                Clock.schedule_once(lambda dt, c=cards: render_status_cards(owner, c), 0)
                if time.time() < suspend_until:
                    return
    except Exception:
        pass
    if time.time() < suspend_until:
        # 轮询暂停期间若有缓存则继续显示缓存，避免看起来“没有内容”
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

    app = App.get_running_app()
    mgr = getattr(app, "servo_bus", None)
    writable_ids = set(getattr(owner, "_writable_servo_ids", set()) or set())

    cards = []
    if not mgr or getattr(mgr, "is_mock", False):
        max_id = 25
        for sid in range(1, max_id + 1):
            cards.append((sid, None, False))
    else:
        mgr = app.servo_bus.manager
        known_ids = set(getattr(mgr, "servo_info_dict", {}).keys())

        if not known_ids:
            try:
                runtime_profile = str(getattr(app, "_runtime_profile", "") or "").lower()
                if runtime_profile == "mobile":
                    last_probe = float(getattr(owner, "_status_unknown_probe_ts", 0.0) or 0.0)
                    if (now - last_probe) >= 2.0:
                        preferred_ids = list(getattr(app, "_last_online_servo_ids", []) or [])
                        probe_ids = sorted(writable_ids) if writable_ids else preferred_ids
                        if (not probe_ids) and app and getattr(app, "servo_bus", None):
                            if getattr(app, "_latest_probe_sid", None):
                                probe_ids = [int(getattr(app, "_latest_probe_sid"))]
                        probe_ids = [int(x) for x in probe_ids[:3]]
                        for sid in probe_ids:
                            try:
                                if mgr.ping(int(sid)):
                                    known_ids.add(int(sid))
                            except Exception:
                                pass
                        owner._status_unknown_probe_ts = now
                else:
                    preferred_ids = list(getattr(app, "_last_online_servo_ids", []) or [])
                    probe_ids = sorted(writable_ids) if writable_ids else preferred_ids
                    if (not probe_ids) and app and getattr(app, "servo_bus", None):
                        if getattr(app, "_latest_probe_sid", None):
                            probe_ids = [int(getattr(app, "_latest_probe_sid"))]
                    for sid in probe_ids:
                        try:
                            if mgr.ping(int(sid)):
                                known_ids.add(int(sid))
                        except Exception:
                            pass
            except Exception:
                pass

        max_known = max(known_ids) if known_ids else 25
        max_id = max(max_known, getattr(mgr, "max_id", 25))

        known_sorted = sorted(int(sid) for sid in known_ids if int(sid) > 0)
        batch_size = int(max(1, getattr(owner, "_status_read_batch_size", 6) or 6))
        ids_to_probe = set()
        if known_sorted:
            rr = int(getattr(owner, "_status_rr_index", 0) or 0)
            rr = rr % len(known_sorted)
            end = rr + min(batch_size, len(known_sorted))
            if end <= len(known_sorted):
                probe_list = known_sorted[rr:end]
            else:
                probe_list = known_sorted[rr:] + known_sorted[: (end % len(known_sorted))]
            ids_to_probe = set(probe_list)
            owner._status_rr_index = end % len(known_sorted)

        for sid in range(1, max_id + 1):
            cache_data = dict(owner._status_data_cache.get(sid, {}) or {})
            data = cache_data.get("data")
            online = bool(cache_data.get("online", False))

            if sid in known_ids:
                if sid in ids_to_probe:
                    backoff = dict(owner._status_read_backoff.get(sid, {}) or {})
                    next_allowed_ts = float(backoff.get("next_ts", 0.0) or 0.0)
                    if now < next_allowed_ts:
                        owner._status_data_cache[sid] = {
                            "data": data,
                            "online": bool(online),
                            "ts": now,
                        }
                        cards.append((sid, data, online))
                        continue
                    try:
                        pos = mgr.read_data_by_name(sid, "CURRENT_POSITION")
                        if pos is not None:
                            cache = owner._status_slow_fields_cache.get(sid, {})
                            last_ts = float(cache.get("_ts", 0.0) or 0.0)
                            if (now - last_ts) >= float(getattr(owner, "_status_slow_fields_interval", 3.0) or 3.0):
                                temp = mgr.read_data_by_name(sid, "CURRENT_TEMPERATURE")
                                volt = mgr.read_data_by_name(sid, "CURRENT_VOLTAGE")
                                torque_flag = mgr.read_data_by_name(sid, "TORQUE_ENABLE")
                                cache = {
                                    "temp": temp,
                                    "volt": volt,
                                    "torque": torque_flag,
                                    "_ts": now,
                                }
                                owner._status_slow_fields_cache[sid] = cache
                            temp = cache.get("temp")
                            volt = cache.get("volt")
                            torque_flag = cache.get("torque")
                            online = bool(getattr(mgr.servo_info_dict.get(sid, None), "is_online", True))
                            data = dict(pos=pos, temp=temp, volt=volt, torque=torque_flag)
                            owner._status_read_backoff[sid] = {"fail_count": 0, "next_ts": 0.0}
                        else:
                            online = False
                            data = None
                            fail_count = int(backoff.get("fail_count", 0) or 0) + 1
                            base_sec = float(getattr(owner, "_status_backoff_base_sec", 0.8) or 0.8)
                            max_sec = float(getattr(owner, "_status_backoff_max_sec", 5.0) or 5.0)
                            wait_sec = min(max_sec, base_sec * (2 ** max(0, fail_count - 1)))
                            owner._status_read_backoff[sid] = {
                                "fail_count": fail_count,
                                "next_ts": now + wait_sec,
                            }
                    except Exception:
                        data = None
                        online = False
                        fail_count = int(backoff.get("fail_count", 0) or 0) + 1
                        base_sec = float(getattr(owner, "_status_backoff_base_sec", 0.8) or 0.8)
                        max_sec = float(getattr(owner, "_status_backoff_max_sec", 5.0) or 5.0)
                        wait_sec = min(max_sec, base_sec * (2 ** max(0, fail_count - 1)))
                        owner._status_read_backoff[sid] = {
                            "fail_count": fail_count,
                            "next_ts": now + wait_sec,
                        }
            elif sid in writable_ids:
                # 仅用于后续探测优先级，不作为在线判据，避免“未连接却显示已连接”
                online = False
                if data is None:
                    data = dict(pos="?", temp="?", volt="?", torque=None)

            owner._status_data_cache[sid] = {
                "data": data,
                "online": bool(online),
                "ts": now,
            }
            cards.append((sid, data, online))

    owner._status_cards_cache = list(cards)
    owner._status_cards_cache_time = now

    def _render(dt=0):
        render_status_cards(owner, cards)

    Clock.schedule_once(_render, 0)


def show_info_popup(owner, text):
    def _show(dt):
        try:
            UniversalTip(
                message=str(text),
                icon="ℹ",
                auto_dismiss=True,
                auto_close_seconds=2.0,
                show_buttons=False,
            ).open()
        except Exception:
            pass

    Clock.schedule_once(_show, 0)


def call_motion(owner, action):
    app = App.get_running_app()
    mc = getattr(app, "motion_controller", None)
    if not mc:
        owner._show_info_popup("MotionController 未初始化或为 MOCK 模式")
        return

    try:
        if (
            hasattr(app, "servo_bus")
            and app.servo_bus
            and not getattr(app.servo_bus, "is_mock", True)
        ):
            try:
                app.servo_bus.set_torque(True)
            except Exception:
                pass
    except Exception:
        pass

    try:
        from widgets.runtime_status import RuntimeStatusLogger
    except Exception:
        RuntimeStatusLogger = None

    try:
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_action(action)

        if action == "stand":
            mc.stand()
        elif action == "sit":
            mc.sit()
        elif action == "walk":
            mc.walk(steps=2, step_length=120, step_height=120, time_per_step_ms=350)
        elif action == "wave":
            mc.wave(side="right", times=3)
        elif action == "dance":
            mc.dance() if hasattr(mc, "dance") else None
        elif action == "jump":
            mc.jump() if hasattr(mc, "jump") else None
        elif action == "turn":
            mc.turn(angle=360) if hasattr(mc, "turn") else None
        elif action == "squat":
            mc.squat() if hasattr(mc, "squat") else None
        elif action == "kick":
            mc.kick() if hasattr(mc, "kick") else None

        owner._show_info_popup(f"动作 {action} 已发送")
    except Exception as e:
        if RuntimeStatusLogger:
            RuntimeStatusLogger.log_error(f"动作 {action} 执行失败: {e}")
        owner._show_info_popup(f"动作执行失败: {e}")
