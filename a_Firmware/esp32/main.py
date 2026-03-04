"""
RobotBrain ESP32 MicroPython 固件
- Wi-Fi + BLE 配网（BLE 名称 ROBOT-ESP32-S3-BLE，UUID 与主控一致）
- UDP(5005) / HTTP(8080) / WebSocket(8765) 控制通道
- I2C IMU 采样（MPU6050/BNO055，可扩展），简单互补滤波占位
- 舵机控制通过 servo_controller 模块
"""

import uasyncio as asyncio
import ujson as json
import socket
import struct
import time
from machine import UART, Pin, I2C
import machine

#  模块化导入 
from servo_controller import ServoController
from imu_controller import IMUController
from balance_controller import BalanceController

try:
    import network
    import ubinascii
    import os
except Exception:
    network = None
    ubinascii = None
    os = None

try:
    import bluetooth
except Exception:
    bluetooth = None

try:
    import uwebsockets.server as ws_server
except Exception:
    ws_server = None

#  常量配置 
CONFIG_PATH = "esp32_config.json"
DEVICE_NAME = "ROBOT-ESP32-S3"
BLE_NAME = "ROBOT-ESP32-S3-BLE"
UDP_PORT = 5005
HTTP_PORT = 8080
WS_PORT = 8765
UART_ID = 1
UART_BAUD = 115200
UART_TX_PIN = 47
UART_RX_PIN = 48
I2C_SCL_PIN = 20
I2C_SDA_PIN = 21
IMU_ADDR = 0x68
SERVO_COUNT = 25
TELEMETRY_MS = 400
BLE_WIFI_STATUS_UUID = "0000ffac-0000-1000-8000-00805f9b34fb"

#  硬件初始化 
try:
    uart = UART(UART_ID, baudrate=UART_BAUD, tx=UART_TX_PIN, rx=UART_RX_PIN, timeout=0)
except Exception as e:
    uart = None
    print("uart init failed: {}".format(e))

try:
    i2c = I2C(0, scl=Pin(I2C_SCL_PIN), sda=Pin(I2C_SDA_PIN))
except Exception as e:
    i2c = None
    print("i2c init failed: {}".format(e))

# 舵机控制器（模块化）
servo = ServoController(uart, servo_count=SERVO_COUNT)

# IMU 控制器（互补滤波）
imu_ctrl = IMUController(i2c, addr=IMU_ADDR)
try:
    if i2c is not None:
        imu_ctrl.init()
        print("imu controller init ok")
except Exception as e:
    print("imu controller init failed: {}".format(e))

# 平衡控制器
balance_ctrl = BalanceController()

# 全局状态
state = {
    "imu": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0, "accel": (0, 0, 0), "gyro": (0, 0, 0)},
    "servos": {},
}

_last_wifi_state = {"wifi_ok": False, "ip": None, "ap_mode": False}
_ble_status_ctx = {"ble": None, "status_handle": None}
_ble_adv_ctx = {"adv_data": None, "resp_data": None, "interval_us": 100000, "name": None}


def log(msg):
    try:
        ts_ms = time.ticks_ms()
        print("[{:.3f}] {}".format(ts_ms / 1000.0, msg))
    except Exception:
        try:
            print(msg)
        except Exception:
            pass


#  配置管理 
def load_config():
    try:
        if os and CONFIG_PATH in os.listdir("/"):
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(cfg):
    try:
        if os:
            with open(CONFIG_PATH, "w") as f:
                f.write(json.dumps(cfg))
            return True
    except Exception:
        pass
    return False


#  BLE 相关 
def _adv_payload(name):
    try:
        name_b = name.encode()
    except Exception:
        name_b = b""
    adv = bytearray()
    adv.extend(b"\x02\x01\x06")
    if name_b:
        adv.extend(struct.pack("BB", len(name_b) + 1, 0x09))
        adv.extend(name_b)
    return bytes(adv)


def _restart_ble_advertising(reason="resume"):
    ble = _ble_status_ctx.get("ble")
    adv = _ble_adv_ctx.get("adv_data")
    resp = _ble_adv_ctx.get("resp_data")
    interval = _ble_adv_ctx.get("interval_us", 100000)
    name = _ble_adv_ctx.get("name") or "?"
    if not ble or adv is None:
        return
    try:
        ble.gap_advertise(interval, adv_data=adv, resp_data=resp)
        log("ble: adv restarted name={} reason={}".format(name, reason))
    except Exception as e:
        log("ble: adv restart failed {}".format(e))


def update_ble_wifi_status(info=None):
    global _last_wifi_state
    if info:
        _last_wifi_state.update(info)
    ble = _ble_status_ctx.get("ble")
    handle = _ble_status_ctx.get("status_handle")
    if not ble or handle is None:
        return
    try:
        payload = {
            "wifi_ok": bool(_last_wifi_state.get("wifi_ok")),
            "ip": _last_wifi_state.get("ip"),
            "ap_mode": bool(_last_wifi_state.get("ap_mode")),
        }
        raw = json.dumps(payload)[:200]
        ble.gatts_write(handle, raw.encode())
    except Exception:
        pass


#  IMU 读取 
def read_mpu6050():
    """使用 IMU 控制器更新姿态（互补滤波）。"""
    try:
        result = imu_ctrl.update()
        if result:
            state["imu"] = imu_ctrl.get_state_dict()
    except Exception:
        pass
    return state["imu"]


#  WiFi 连接 
async def wifi_connect():
    if network is None:
        log("wifi: no network module")
        update_ble_wifi_status({"wifi_ok": False, "ip": None, "ap_mode": False})
        return {"wifi_ok": False, "ip": None, "ap_mode": False}
    log("wifi: init STA")
    cfg = load_config()
    try:
        ap = network.WLAN(network.AP_IF)
        ap.active(False)
    except Exception:
        pass
    sta = network.WLAN(network.STA_IF)
    if not sta.active():
        sta.active(True)
    wifi_cfg = cfg.get("wifi") or {}
    if wifi_cfg.get("ssid"):
        log("wifi: connecting ssid={}".format(wifi_cfg.get("ssid")))
        try:
            sta.connect(wifi_cfg.get("ssid"), wifi_cfg.get("password"))
            for _ in range(40):
                if sta.isconnected():
                    break
                await asyncio.sleep_ms(250)
        except Exception as e:
            log("wifi: connect err={}".format(e))
    if not sta.isconnected():
        log("wifi: STA connect failed")
        result = {"wifi_ok": False, "ip": None, "ap_mode": False}
    else:
        try:
            ip = sta.ifconfig()[0]
        except Exception:
            ip = "<unknown>"
        try:
            mac = ubinascii.hexlify(sta.config("mac")).decode() if ubinascii else "n/a"
        except Exception:
            mac = "n/a"
        log("wifi: connected ip={} mac={}".format(ip, mac))
        result = {"wifi_ok": True, "ip": ip, "ap_mode": False}
    update_ble_wifi_status(result)
    return result


def wifi_status_snapshot():
    wifi_ip = None
    wifi_ok = False
    if network:
        try:
            sta = network.WLAN(network.STA_IF)
            wifi_ok = sta.isconnected()
            wifi_ip = sta.ifconfig()[0]
        except Exception:
            pass
    return {"wifi_ok": wifi_ok, "ip": wifi_ip, "ap_mode": False}


#  Telemetry 
def telemetry_payload():
    wifi_ip = None
    wifi_ok = False
    if network:
        try:
            sta = network.WLAN(network.STA_IF)
            wifi_ok = sta.isconnected()
            wifi_ip = sta.ifconfig()[0]
        except Exception:
            pass
    # 获取舵机缓存位置
    servo_data = {}
    cached = servo.get_cached_positions()
    for sid, pos in cached.items():
        servo_data[str(sid)] = {"position": int(pos)}

    return {
        "type": "telemetry",
        "imu": state.get("imu"),
        "servos": servo_data,
        "wifi": wifi_ip,
        "wifi_ok": wifi_ok,
        "uptime_ms": time.ticks_ms(),
    }


#  指令处理(核心) 
async def handle_command(msg, addr, sock=None):
    """处理来自主控的 UDP/WS/HTTP 指令。

    支持的指令类型:
    - discover       : 局域网发现
    - servo_targets  : 批量设置舵机位置
    - keyframe       : 同 servo_targets
    - torque         : 扭矩开关
    - motion         : 预设动作
    - status         : 请求状态遥测
    - ping           : Ping 单个舵机
    - read_position  : 读取舵机位置
    - motor_mode     : 切换电机/舵机模式
    - motor_speed    : 设置电机转速
    - scan           : 扫描在线舵机
    """
    mtype = msg.get("type") or msg.get("cmd") or "servo_targets"
    resp = None

    if mtype == "discover":
        resp = {"type": "discover_resp", "port": UDP_PORT, "device": DEVICE_NAME}
        if network:
            try:
                sta = network.WLAN(network.STA_IF)
                resp["ip"] = sta.ifconfig()[0]
                if ubinascii:
                    resp["mac"] = ubinascii.hexlify(sta.config("mac")).decode()
            except Exception:
                pass

    elif mtype in ("servo_targets", "keyframe"):
        targets = msg.get("targets") or {}
        duration = int(msg.get("duration", 300))
        servo.set_positions(targets, duration)
        log("cmd: set_positions count={} dur={}".format(len(targets), duration))

    elif mtype == "torque":
        enable = bool(msg.get("enable", True))
        if enable:
            servo.torque_on()
        else:
            servo.torque_off()
        log("cmd: torque={}".format(enable))

    elif mtype == "motion":
        name = str(msg.get("name", "")).lower().strip()
        log("cmd: motion={}".format(name))
        # TODO: 预设动作序列播放

    elif mtype == "status":
        resp = telemetry_payload()

    elif mtype == "ping":
        sid = int(msg.get("servo_id", 1))
        result = servo.ping(sid)
        resp = {"type": "ping_resp", "servo_id": sid, "online": result == 0}

    elif mtype == "read_position":
        sid = int(msg.get("servo_id", 1))
        pos = servo.read_position(sid)
        resp = {"type": "read_position_resp", "servo_id": sid, "position": pos}

    elif mtype == "motor_mode":
        sid = int(msg.get("servo_id", 1))
        mode = str(msg.get("mode", "motor"))
        if mode == "servo":
            servo.set_servo_mode(sid)
        else:
            servo.set_motor_mode(sid)
        resp = {"type": "motor_mode_resp", "servo_id": sid, "mode": mode, "ok": True}

    elif mtype == "motor_speed":
        sid = int(msg.get("servo_id", 1))
        speed = int(msg.get("speed", 0))
        direction = int(msg.get("direction", 1))
        servo.set_motor_direction(sid, direction)
        servo.set_motor_speed(sid, speed)
        resp = {"type": "motor_speed_resp", "ok": True}

    elif mtype == "scan":
        online = servo.scan()
        resp = {"type": "scan_resp", "online": online, "count": len(online)}

    elif mtype == "set_single":
        sid = int(msg.get("servo_id", 1))
        pos = int(msg.get("position", 2048))
        dur = int(msg.get("duration", 300))
        servo.set_single(sid, pos, dur)
        resp = {"type": "set_single_resp", "ok": True, "servo_id": sid}

    elif mtype == "read_full_status":
        sid = int(msg.get("servo_id", 1))
        st = servo.read_full_status(sid)
        resp = {"type": "read_full_status_resp", "servo_id": sid, "data": st or {}}

    elif mtype == "read_temperature":
        sid = int(msg.get("servo_id", 1))
        temp = servo.read_temperature(sid)
        resp = {"type": "read_temperature_resp", "servo_id": sid, "temperature": temp}

    elif mtype == "read_voltage":
        sid = int(msg.get("servo_id", 1))
        volt = servo.read_voltage(sid)
        resp = {"type": "read_voltage_resp", "servo_id": sid, "voltage": volt}

    elif mtype == "torque_single":
        sid = int(msg.get("servo_id", 1))
        enable = bool(msg.get("enable", True))
        if enable:
            servo.torque_on([sid])
        else:
            servo.torque_off([sid])
        resp = {"type": "torque_single_resp", "ok": True, "servo_id": sid}

    elif mtype == "set_servo_id":
        old_id = int(msg.get("old_id", 1))
        new_id = int(msg.get("new_id", 1))
        servo.set_servo_id(old_id, new_id)
        resp = {"type": "set_servo_id_resp", "ok": True}

    elif mtype == "balance_enable":
        enable = bool(msg.get("enable", True))
        balance_ctrl.enabled = enable
        resp = {"type": "balance_enable_resp", "enabled": balance_ctrl.enabled}

    elif mtype == "balance_set_gains":
        balance_ctrl.set_gains(
            gain_p=msg.get("gain_p"),
            gain_r=msg.get("gain_r"),
            gain_y=msg.get("gain_y"),
        )
        resp = {
            "type": "balance_set_gains_resp",
            "gain_p": balance_ctrl.gain_p,
            "gain_r": balance_ctrl.gain_r,
            "gain_y": balance_ctrl.gain_y,
        }

    else:
        log("cmd: unknown type={}".format(mtype))

    if resp and sock and addr:
        try:
            sock.sendto(json.dumps(resp).encode(), addr)
        except Exception as e:
            log("resp send err: {}".format(e))


#  UDP 服务器 
async def udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.setblocking(False)
    log("udp: listening on :{}".format(UDP_PORT))
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except Exception:
            data = None
        if data:
            try:
                msg = json.loads(data.decode())
                log("udp: recv type={} from={}".format(msg.get("type", "?"), addr[0]))
                await handle_command(msg, addr, sock)
            except Exception as e:
                log("udp: handle err={}".format(e))
        await asyncio.sleep_ms(10)


#  HTTP 服务器 
async def http_server():
    async def handle(reader, writer):
        try:
            req_line = await reader.readline()
            if not req_line:
                await writer.wait_closed()
                return
            content_length = 0
            while True:
                line = await reader.readline()
                if line == b"\r\n" or not line:
                    break
                if line.lower().startswith(b"content-length"):
                    try:
                        content_length = int(line.decode().split(":")[1].strip())
                    except Exception:
                        content_length = 0
            body = b""
            if content_length:
                body = await reader.readexactly(content_length)
            try:
                payload = json.loads(body.decode()) if body else {}
            except Exception:
                payload = {}
            path = req_line.decode().split(" ")[1]
            if path == "/provision":
                ssid = payload.get("ssid")
                password = payload.get("password")
                cfg = load_config()
                cfg["wifi"] = {"ssid": ssid, "password": password}
                ok = save_config(cfg)
                resp = {"ok": bool(ok)}
            elif path == "/status":
                resp = telemetry_payload()
            elif path == "/command":
                await handle_command(payload, None, None)
                resp = {"ok": True}
            else:
                resp = {"ok": True}
            raw = json.dumps(resp)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(raw)).encode() + b"\r\n\r\n" + raw.encode())
            await writer.drain()
        except Exception:
            pass
        try:
            await writer.wait_closed()
        except Exception:
            pass

    srv = await asyncio.start_server(handle, "0.0.0.0", HTTP_PORT)
    log("http: listening on :{}".format(HTTP_PORT))
    while True:
        await asyncio.sleep_ms(1000)


#  周期任务 
async def telemetry_task():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    while True:
        cfg = load_config()
        host = cfg.get("host") or cfg.get("pair")
        if host:
            try:
                sock.sendto(json.dumps(telemetry_payload()).encode(), (host.get("ip"), int(host.get("port", UDP_PORT))))
            except Exception:
                pass
        await asyncio.sleep_ms(TELEMETRY_MS)


async def ble_status_task():
    while True:
        update_ble_wifi_status(wifi_status_snapshot())
        await asyncio.sleep_ms(2000)


async def imu_task():
    """10ms IMU 采样 + 互补滤波更新。"""
    while True:
        read_mpu6050()
        await asyncio.sleep_ms(10)


async def balance_task():
    """平衡控制任务 —— 50ms 周期读取 IMU 姿态，计算补偿并驱动舵机。"""
    await asyncio.sleep_ms(5000)  # 等待系统初始化
    while True:
        if balance_ctrl.enabled:
            try:
                p = imu_ctrl.pitch
                r = imu_ctrl.roll
                y = imu_ctrl.yaw
                targets = balance_ctrl.compute(p, r, y)
                if targets:
                    servo.set_positions(
                        {str(sid): pos for sid, pos in targets.items()},
                        duration=80,
                    )
            except Exception:
                pass
        await asyncio.sleep_ms(50)


async def servo_poll_task():
    """后台轮询读取舵机完整状态（温度、电压、位置等）。"""
    await asyncio.sleep_ms(3000)
    poll_index = 0
    while True:
        if servo.available:
            try:
                online = servo.get_online_ids()
                if not online:
                    online = list(range(1, SERVO_COUNT + 1))
                # 每次读取一批（4个）的完整状态
                batch_size = 4
                start = poll_index % len(online)
                batch = online[start:start + batch_size]
                for sid in batch:
                    try:
                        servo.read_full_status(sid)
                    except Exception:
                        pass
                    await asyncio.sleep_ms(15)
                poll_index += batch_size
            except Exception:
                pass
        await asyncio.sleep_ms(400)


async def interpolation_task():
    """插值平滑输出任务 —— 20ms 周期驱动舵机平滑运动。"""
    while True:
        try:
            servo.interpolation_step()
        except Exception:
            pass
        await asyncio.sleep_ms(20)


async def ws_task():
    if ws_server is None:
        return
    async def handler(reader, writer):
        ws = await ws_server.serve(reader, writer)
        while True:
            try:
                msg = await ws.recv()
                if msg is None:
                    break
                try:
                    obj = json.loads(msg)
                    await handle_command(obj, None)
                except Exception:
                    pass
            except Exception:
                break
        await ws.close()

    await asyncio.start_server(handler, "0.0.0.0", WS_PORT)
    log("ws: listening on :{}".format(WS_PORT))
    while True:
        await asyncio.sleep_ms(1000)


#  BLE 配网 
def ble_setup():
    if bluetooth is None:
        log("ble: no bluetooth module")
        return None
    log("ble: init")
    try:
        ble = bluetooth.BLE()
        ble.active(True)
    except Exception as e:
        log("ble: init failed {}".format(e))
        return None

    cfg = load_config()

    SERVICE_UUID = bluetooth.UUID("0000ffaa-0000-1000-8000-00805f9b34fb")
    WIFI_CHAR_UUID = bluetooth.UUID("0000ffab-0000-1000-8000-00805f9b34fb")
    STATUS_CHAR_UUID = bluetooth.UUID(BLE_WIFI_STATUS_UUID)
    WIFI_CHAR = (WIFI_CHAR_UUID, bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE)
    STATUS_CHAR = (STATUS_CHAR_UUID, bluetooth.FLAG_READ)
    service = (SERVICE_UUID, (WIFI_CHAR, STATUS_CHAR))
    try:
        handles = ble.gatts_register_services((service,))
        if not handles:
            log("ble: register failed")
            return None
        svc = handles[0]
        if len(svc) < 2:
            log("ble: missing handles")
            return None
        wifi_handle, status_handle = svc[0], svc[1]
    except Exception as e:
        log("ble: register err {}".format(e))
        return None

    _ble_status_ctx["ble"] = ble
    _ble_status_ctx["status_handle"] = status_handle

    def on_write(attr_handle, _data):
        if attr_handle != wifi_handle:
            return
        try:
            txt = ble.gatts_read(wifi_handle).decode().strip()
            ssid = ""
            pwd = ""
            if "\n" in txt:
                parts = txt.split("\n", 1)
                ssid, pwd = parts[0], parts[1] if len(parts) > 1 else ""
            else:
                try:
                    payload = json.loads(txt)
                    ssid = payload.get("ssid") or ""
                    pwd = payload.get("password") or ""
                except Exception:
                    pass
            if ssid:
                cfg_now = load_config()
                cfg_now["wifi"] = {"ssid": ssid, "password": pwd}
                save_config(cfg_now)
                try:
                    asyncio.create_task(wifi_connect())
                except Exception:
                    pass
        except Exception:
            pass
    ble.gatts_set_buffer(wifi_handle, 256, True)

    IRQ_CENTRAL_CONNECT = getattr(bluetooth, "IRQ_CENTRAL_CONNECT", 1)
    IRQ_CENTRAL_DISCONNECT = getattr(bluetooth, "IRQ_CENTRAL_DISCONNECT", 2)
    IRQ_GATTS_WRITE = getattr(bluetooth, "IRQ_GATTS_WRITE", 3)

    def ble_irq(event, data):
        if event == IRQ_GATTS_WRITE:
            on_write(data[1], None)
        elif event == IRQ_CENTRAL_CONNECT:
            log("ble: connected")
        elif event == IRQ_CENTRAL_DISCONNECT:
            log("ble: disconnected")
            _restart_ble_advertising("disconnect")

    ble.irq(ble_irq)
    adv_name = cfg.get("ble_name") or BLE_NAME or DEVICE_NAME
    try:
        ble.config(gap_name=adv_name)
    except Exception:
        pass
    adv = _adv_payload(adv_name)
    resp = None
    try:
        resp = bluetooth.advertising_payload(name=None, services=[SERVICE_UUID]) if hasattr(bluetooth, "advertising_payload") else None
    except Exception:
        resp = None

    _ble_adv_ctx.update({"adv_data": adv, "resp_data": resp, "interval_us": 100000, "name": adv_name})
    _restart_ble_advertising("init")
    update_ble_wifi_status()
    return ble


#  主入口 
async def main():
    log("system: main loop starting")
    wifi_state = await wifi_connect()

    asyncio.create_task(udp_server())
    asyncio.create_task(telemetry_task())
    asyncio.create_task(imu_task())
    asyncio.create_task(balance_task())
    asyncio.create_task(servo_poll_task())
    asyncio.create_task(interpolation_task())
    asyncio.create_task(ws_task())
    asyncio.create_task(http_server())

    ble_setup()
    asyncio.create_task(ble_status_task())
    update_ble_wifi_status(wifi_state)

    log("system: all services started")
    while True:
        await asyncio.sleep_ms(1000)


try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()