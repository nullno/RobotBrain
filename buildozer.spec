[app]
title = RobotBrain
package.name = robotbrain
package.domain = com.nullno.robot

source.dir = .
source.include_exts = py,kv,png,jpg,atlas,ttf,ttc

version = 0.1

# 依赖包配置（按重要性排序）
# - kivy: UI框架
# - pyserial: 串口通信
# - pyjnius: Python-Java接口（Android权限和功能）
# - plyer: 跨平台设备功能API
# - requests: HTTP库
# - opencv, numpy: 视觉处理
requirements = python3,kivy==2.3.0,pyjnius,plyer,requests,pyserial,android

# 修复 Colab 上的 AIDL 错误
# android.skip_update = False

# UI配置
fullscreen = 1
orientation = landscape
icon.filename = %(source.dir)s/assets/logo.png

# 启动页
android.presplash_color = #171732
presplash.filename = %(source.dir)s/assets/setup.png
include_statusbar = False

# short_edges: 允许内容扩展到刘海/挖孔区域
android.window_layout_in_display_cutout_mode = short_edges

# 打包优化
# android.add_src = 

# 自动接受SDK许可
android.accept_sdk_license = True

# 权限配置
# CAMERA - 摄像头
# INTERNET - 网络连接
# ACCESS_NETWORK_STATE - 网络状态
# WRITE/READ_EXTERNAL_STORAGE - 文件访问
# (注意：USB_PERMISSION 是代码中的 Intent Action，不是 Manifest 权限，已移除)

android.permissions = INTERNET,ACCESS_NETWORK_STATE,CAMERA,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

# android.manifest.intent_filters = android/usb/intent_filter.xml
# android.extra_res_dirs = android/res

# 使用本地 aar 库（最稳妥的方式，避免 Maven 仓库连接问题）
android.add_libs = android/libs/usb-serial-for-android-3.5.1.aar
# android.gradle_dependencies = com.github.mik3y:usb-serial-for-android:3.5.1


android.enable_androidx = True
android.gradle_args = -Xmx4g

# Android版本配置
android.api = 33
android.minapi = 21
android.ndk = 25c

# 架构配置（增加 32位 支持以兼容旧设备）
android.archs = arm64-v8a

# 隐私政策（可选但推荐）
android.privacy_policy = 



[buildozer]
log_level = 2
warn_on_root = 0