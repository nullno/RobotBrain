[app]
title = RobotBrain
package.name = robotbrain
package.domain = com.nullno.robot

source.dir = .
source.include_exts = py,kv,png,jpg,atlas,ttf,ttc,xml,aar

version = 0.1

# 依赖包配置（按重要性排序）
# - kivy: UI框架
# - pyserial: 串口通信
# - pyjnius: Python-Java接口（Android权限和功能）
# - plyer: 跨平台设备功能API
# - requests: HTTP库
# - opencv, numpy: 视觉处理
requirements = python3,kivy==2.3.0,pyjnius,plyer,requests,pyserial,edge-tts,pygame

# UI配置
fullscreen = 1
orientation = landscape
# 强制由传感器控制横屏方向（左右横屏可自动翻转）
# android.manifest.orientation = sensorLandscape
icon.filename = %(source.dir)s/assets/logo.png

# 启动页
android.presplash_color = #000000
presplash.filename = %(source.dir)s/assets/setup.png
include_statusbar = False

# short_edges: 允许内容扩展到刘海/挖孔区域
android.window_layout_in_display_cutout_mode = short_edges
# 屏幕是否常亮
android.wakelock = True

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

android.permissions = INTERNET,ACCESS_NETWORK_STATE,CAMERA,RECORD_AUDIO,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.res_xml = android/xml/device_filter.xml
# USB 插入可唤醒应用
android.manifest.intent_filters = android/usb/intent_filter.xml
# 避免应用已在运行时因 USB 事件重复创建 Activity 实例
android.manifest.launch_mode = singleTask

# USB Serial 依赖（使用 p4a 的 add_gradle_repositories 注入 JitPack）
android.add_gradle_repositories = maven { url 'https://jitpack.io' }
android.gradle_dependencies = com.github.mik3y:usb-serial-for-android:3.5.1


# Android版本配置
android.api = 31
android.minapi = 21
android.ndk = 25c

# 架构配置
android.archs = arm64-v8a

# 隐私政策（可选但推荐）
android.privacy_policy = 



[buildozer]
log_level = 2
warn_on_root = 0