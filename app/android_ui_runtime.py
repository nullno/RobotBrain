def update_android_flags(app):
    """更新 Android 全屏/沉浸式/刘海屏显示参数。"""
    try:
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        View = autoclass("android.view.View")
        window = activity.getWindow()
        decor_view = window.getDecorView()

        flags = (
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
            | View.SYSTEM_UI_FLAG_FULLSCREEN
            | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        )
        decor_view.setSystemUiVisibility(flags)

        VERSION = autoclass("android.os.Build$VERSION")
        if VERSION.SDK_INT >= 28:
            LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
            try:
                layout_mode = LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            except Exception:
                layout_mode = 1

            params = window.getAttributes()
            params.layoutInDisplayCutoutMode = layout_mode
            window.setAttributes(params)
    except Exception as e:
        print(f"⚠ Android UI Flags 设置失败: {e}")
