import json
import pathlib

from widgets.runtime_status import RuntimeStatusLogger


def balance_tuning_file(app):
    try:
        return pathlib.Path(app.user_data_dir) / "balance_tuning.json"
    except Exception:
        return pathlib.Path("data") / "balance_tuning.json"


def save_balance_tuning(app):
    """持久化当前平衡参数（gain_p/gain_r）与陀螺仪轴映射模式。"""
    try:
        bc = getattr(app, "balance_ctrl", None)
        if not bc:
            return False
        fp = balance_tuning_file(app)
        fp.parent.mkdir(parents=True, exist_ok=True)
        axis_mode = str(getattr(app, "_gyro_axis_mode", "normal"))
        if axis_mode not in ("auto", "normal", "swapped"):
            axis_mode = "normal"
        data = {
            "gain_p": float(getattr(bc, "gain_p", 5.5)),
            "gain_r": float(getattr(bc, "gain_r", 4.2)),
            "gyro_axis_mode": axis_mode,
        }
        with open(fp, "w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_balance_tuning(app):
    """加载并应用持久化的平衡参数与陀螺仪轴映射。"""
    try:
        bc = getattr(app, "balance_ctrl", None)
        if not bc:
            return False
        fp = balance_tuning_file(app)
        if not fp.exists():
            return False
        with open(fp, "r", encoding="utf8") as f:
            obj = json.load(f)

        gp = float(obj.get("gain_p", getattr(bc, "gain_p", 5.5)))
        gr = float(obj.get("gain_r", getattr(bc, "gain_r", 4.2)))
        axis_mode = str(obj.get("gyro_axis_mode", getattr(app, "_gyro_axis_mode", "normal")))
        if axis_mode not in ("auto", "normal", "swapped"):
            axis_mode = "normal"
        gp = max(0.0, min(20.0, gp))
        gr = max(0.0, min(20.0, gr))
        bc.gain_p = gp
        bc.gain_r = gr
        app._gyro_axis_mode = axis_mode
        app._gyro_axis_mode_logged = axis_mode
        if axis_mode == "auto":
            app._gyro_axis_samples = 0
        try:
            RuntimeStatusLogger.log_info(
                f"已加载平衡参数: gain_p={gp:.2f}, gain_r={gr:.2f}, axis={axis_mode}"
            )
        except Exception:
            pass
        return True
    except Exception:
        return False
