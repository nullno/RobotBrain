from kivy.utils import platform


def load_gyroscope_module():
    """按平台加载 gyroscope 模块（仅 Android）。"""
    try:
        if platform == "android":
            try:
                import importlib

                return importlib.import_module("plyer.gyroscope")
            except ModuleNotFoundError:
                return None
            except Exception:
                return None
        return None
    except Exception:
        return None


def get_run_on_ui_thread():
    """返回可用的 run_on_ui_thread 装饰器；非 Android 时返回 no-op。"""
    def _identity(func):
        return func

    if platform == "android":
        try:
            from android.runnable import run_on_ui_thread as _run_on_ui_thread
            return _run_on_ui_thread
        except ImportError:
            return _identity
        except Exception:
            return _identity

    return _identity
