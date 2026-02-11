[app]
title = RobotBrain
package.name = robotbrain
package.domain = com.nullno.robot

source.dir = .
source.include_exts = py,kv,png,jpg,atlas,ttf,ttc

version = 0.3

# 依赖包配置（按重要性排序）
# - kivy: UI框架
# - pyserial: 串口通信
# - pyjnius: Python-Java接口（Android权限和功能）
# - plyer: 跨平台设备功能API
# - requests: HTTP库
requirements = python3,kivy==2.3.0,pyjnius,plyer,requests,pyserial,android

# UI配置
orientation = landscape
fullscreen = 1
icon.filename = %(source.dir)s/assets/logo.png

# 启动页
android.presplash_color = #171732
presplash.filename = %(source.dir)s/assets/setup.png
include_statusbar = False

# short_edges: 允许内容扩展到刘海/挖孔区域
android.window_layout_in_display_cutout_mode = short_edges

# 打包优化
android.gradle_dependencies = 
android.add_src = 

# 权限配置
# CAMERA - 摄像头
# INTERNET - 网络连接
# ACCESS_NETWORK_STATE - 网络状态
# WRITE/READ_EXTERNAL_STORAGE - 文件访问
android.permissions = INTERNET,ACCESS_NETWORK_STATE,CAMERA,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

# Android版本配置
android.api = 31
android.minapi = 21
android.ndk = 25b

# 架构配置（仅支持64位）
android.archs = arm64-v8a

# 隐私政策（可选但推荐）
android.privacy_policy = 

[buildozer]
log_level = 2
warn_on_root = 0