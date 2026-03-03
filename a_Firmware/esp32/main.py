"""
RobotBrain ESP32 MicroPython 固件
- Wi-Fi + BLE 配网（BLE 名称 ROBOT-ESP32-S3-BLE，UUID 与主控一致）
- UDP(5005) / HTTP(8080) / WebSocket(8765) 控制通道
- I2C IMU 采样（MPU6050/BNO055，可扩展），简单互补滤波占位
- UART 桥接 CH340 舵机板（25 路，同步写）
"""

import uasyncio as asyncio
import ujson as json
import socket
import struct
import time
from machine import UART, Pin, I2C
import machine
from servo_sdk_adapter import ServoSDKBridge

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

CONFIG_PATH = "esp32_config.json"
DEVICE_NAME = "ROBOT-ESP32-S3"
BLE_NAME = "ROBOT-ESP32-S3-BLE"  # 可在 esp32_config.json 中用 ble_name 覆盖
UDP_PORT = 5005
HTTP_PORT = 8080
WS_PORT = 8765
UART_ID = 1
UART_BAUD = 115200
UART_TX_PIN = 17
UART_RX_PIN = 16
I2C_SCL_PIN = 20
I2C_SDA_PIN = 21
IMU_ADDR = 0x68
SERVO_MIN = 0
SERVO_MAX = 1000
TELEMETRY_MS = 400
BLE_WIFI_STATUS_UUID = "0000ffac-0000-1000-8000-00805f9b34fb"

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

servo = ServoSDKBridge(uart, servo_count=25) if uart else None

state = {
    "imu": {"pitch": 0.0, "roll": 0.0, "yaw": 0.0, "accel": (0, 0, 0), "gyro": (0, 0, 0)},
    "servos": {},
}

_last_wifi_state = {"wifi_ok": False, "ip": None, "ap_mode": False}
_ble_status_ctx = {"ble": None, "status_handle": None}
_ble_adv_ctx = {"adv_data": None, "resp_data": None, "interval_us": 100000, "name": None}


def log(msg):
    """轻量串口日志，附带毫秒时间戳。"""
    try:
        ts_ms = time.ticks_ms()
        print("[{:.3f}] {}".format(ts_ms / 1000.0, msg))
    except Exception:
        try:
            print(msg)
        except Exception:
            pass


# ---------------------------------------------------------------------------
def _adv_payload(name: str, services=None):
    """构建包含 Flags + 完整本地名 + 可选服务 UUID 的广播包"""
    try:
        name_b = name.encode()
    except Exception:
        name_b = b""

    adv = bytearray()
    # Flags: LE General Discoverable + BR/EDR not supported
    adv.extend(b"\x02\x01\x06")
    if name_b:
        adv.extend(struct.pack("BB", len(name_b) + 1, 0x09))
        adv.extend(name_b)

    if services:
        try:
            # 128-bit UUIDs in scan response preferred，放在 resp_data
            pass
        except Exception:
            pass
    return bytes(adv)


def _restart_ble_advertising(reason="resume"):
    """Restart BLE advertising; useful after disconnect because MicroPython stops advertising on connect."""
    ble = _ble_status_ctx.get("ble")
    adv = _ble_adv_ctx.get("adv_data")
    resp = _ble_adv_ctx.get("resp_data")
    interval = _ble_adv_ctx.get("interval_us", 100000)
    name = _ble_adv_ctx.get("name") or "?"
    if not ble or adv is None:
        return
    try:
        ble.gap_advertise(interval, adv_data=adv, resp_data=resp)
        log("ble: 广播已重启 name={} reason={}".format(name, reason))
    except Exception as e:
        log("ble: 广播重启失败 {}".format(e))


def load_config():
    try:
        if os and CONFIG_PATH in os.listdir("/"):
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(cfg) -> bool:
    try:
        if os:
            with open(CONFIG_PATH, "w") as f:
                f.write(json.dumps(cfg))
            return True
    except Exception:
        pass
    return False


def clamp(val, lo, hi):
    if val < lo:
        return lo
    if val > hi:
        return hi
    return val


def update_ble_wifi_status(info=None):
    """将最新 Wi-Fi 状态写入 BLE 特征，便于手机侧读取。"""
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


def checksum(servo_id, data_size, cmd_type, param_bytes):
    buf = struct.pack("<BBB", servo_id, data_size, cmd_type) + param_bytes
    s = 0
    for b in buf:
        s += b if isinstance(b, int) else ord(b)
    return (0xFF - (s & 0xFF)) & 0xFF


def pack_frame(servo_id, cmd_type, param_bytes=b""):
    data_size = len(param_bytes) + 2
    cs = checksum(servo_id, data_size, cmd_type, param_bytes)
    return b"\xff\xff" + struct.pack("<BBB", servo_id, data_size, cmd_type) + param_bytes + struct.pack("<B", cs)


def build_sync_param(pairs):
    out = bytearray()
    out.extend(b"\x2A\x04")
    for sid, pos, runtime in pairs:
        out.extend(struct.pack(">BHH", int(sid) & 0xFF, int(pos) & 0xFFFF, int(runtime) & 0xFFFF))
    return bytes(out)


def send_servo_targets(targets, duration_ms):
    safe_targets = {}
    for sid, val in targets.items():
        try:
            sid_i = int(sid)
            pos_i = clamp(int(val), SERVO_MIN, SERVO_MAX)
            safe_targets[sid_i] = pos_i
            state["servos"][sid_i] = pos_i
        except Exception:
            pass
    if not safe_targets:
        return
    if servo:
        servo.set_positions(safe_targets, duration_ms)
    else:
        log("servo: uart 未初始化，无法下发位置")


def read_mpu6050():
    if i2c is None:
        log("imu: I2C 未初始化，跳过读取")
        return None
    try:
        i2c.writeto_mem(IMU_ADDR, 0x6B, b"\x00")
        data = i2c.readfrom_mem(IMU_ADDR, 0x3B, 14)

        def to_i16(h, l):
            v = (h << 8) | l
            return v - 65536 if v & 0x8000 else v

        ax = to_i16(data[0], data[1])
        ay = to_i16(data[2], data[3])
        az = to_i16(data[4], data[5])
        gx = to_i16(data[8], data[9])
        gy = to_i16(data[10], data[11])
        gz = to_i16(data[12], data[13])
        state["imu"].update({"accel": (ax, ay, az), "gyro": (gx, gy, gz)})
    except Exception:
        return None
    return state["imu"]


# ---------------------------------------------------------------------------
async def wifi_connect():
    if network is None:
        log("wifi: 无法加载 network 模块")
        update_ble_wifi_status({"wifi_ok": False, "ip": None, "ap_mode": False})
        return {"wifi_ok": False, "ip": None, "ap_mode": False}
    log("wifi: 初始化 STA 模式")
    cfg = load_config()
    try:
        # 禁用 AP，避免影响路由器连接
        ap = network.WLAN(network.AP_IF)
        ap.active(False)
    except Exception:
        pass
    sta = network.WLAN(network.STA_IF)
    if not sta.active():
        sta.active(True)
    wifi_cfg = cfg.get("wifi") or {}
    if wifi_cfg.get("ssid"):
        log("wifi: 正在连接 ssid={}".format(wifi_cfg.get("ssid")))
        try:
            sta.connect(wifi_cfg.get("ssid"), wifi_cfg.get("password"))
            for _ in range(40):
                if sta.isconnected():
                    break
                await asyncio.sleep_ms(250)
        except Exception as e:
            log("wifi: 连接异常 err={}".format(e))
    if not sta.isconnected():
        log("wifi: STA 连接失败，不开启 AP")
        state = {"wifi_ok": False, "ip": None, "ap_mode": False}
    else:
        try:
            ip = sta.ifconfig()[0]
        except Exception:
            ip = "<unknown>"
        try:
            mac = ubinascii.hexlify(sta.config("mac")).decode() if ubinascii else "n/a"
        except Exception:
            mac = "n/a"
        log("wifi: STA 已连接 ip={} mac={}".format(ip, mac))
        state = {"wifi_ok": True, "ip": ip, "ap_mode": False}
    update_ble_wifi_status(state)
    return state


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
    while True:
        await asyncio.sleep_ms(1000)


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
    return {
        "type": "telemetry",
        "imu": state.get("imu"),
        "servos": state.get("servos"),
        "wifi": wifi_ip,
        "wifi_ok": wifi_ok,
        "uptime_ms": time.ticks_ms(),
    }


def wifi_status_snapshot():
    """Read current Wi-Fi state for BLE status updates."""
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


async def udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.setblocking(False)
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except Exception:
            data = None
        if data:
            try:
                msg = json.loads(data.decode())
                await handle_command(msg, addr, sock)
            except Exception:
                pass
        await asyncio.sleep_ms(10)


async def handle_command(msg, addr, sock=None):
    mtype = msg.get("type") or msg.get("cmd") or "servo_targets"
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
        if sock:
            sock.sendto(json.dumps(resp).encode(), addr)
    elif mtype in ("servo_targets", "keyframe"):
        targets = msg.get("targets") or {}
        duration = int(msg.get("duration", 300))
        send_servo_targets(targets, duration)
    elif mtype == "torque":
        enable = bool(msg.get("enable", True))
        if servo:
            servo.torque(enable=enable)
        else:
            log("servo: uart 未初始化，无法控制力矩")
    elif mtype == "motion":
        # 占位：根据需要映射动作到关键帧
        pass
    elif mtype == "status":
        if sock:
            sock.sendto(json.dumps(telemetry_payload()).encode(), addr)


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
    """Periodic BLE status refresh to keep wifi_ok accurate."""
    while True:
        update_ble_wifi_status(wifi_status_snapshot())
        await asyncio.sleep_ms(2000)


async def imu_task():
    while True:
        read_mpu6050()
        await asyncio.sleep_ms(50)


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
    while True:
        await asyncio.sleep_ms(1000)


def ble_setup():
    if bluetooth is None:
        log("ble: 无法加载 bluetooth 模块")
        return None
    log("ble: 启用 BLE 控制器")
    try:
        ble = bluetooth.BLE()
        ble.active(True)
    except Exception as e:
        log("ble: 控制器初始化失败 {}".format(e))
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
            log("ble: 注册服务失败（返回为空）")
            return None
        svc = handles[0]
        # MicroPython 返回的 svc 为特征句柄列表，与定义顺序一致
        if len(svc) < 2:
            log("ble: 特征句柄缺失")
            return None
        wifi_handle, status_handle = svc[0], svc[1]
    except Exception as e:
        log("ble: 注册服务异常 {}".format(e))
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
                cfg = load_config()
                cfg["wifi"] = {"ssid": ssid, "password": pwd}
                save_config(cfg)
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
            try:
                addr = data[2] if len(data) > 2 else None
                addr_txt = ubinascii.hexlify(addr).decode() if ubinascii and addr else "n/a"
                log("ble: central connected handle={} addr={}".format(data[0], addr_txt))
            except Exception:
                log("ble: central connected")
        elif event == IRQ_CENTRAL_DISCONNECT:
            log("ble: central disconnected handle={}".format(data[0] if data else "?"))
            _restart_ble_advertising("central disconnect")

    ble.irq(ble_irq)
    adv_name = cfg.get("ble_name") or BLE_NAME or DEVICE_NAME
    try:
        ble.config(gap_name=adv_name)
    except Exception:
        pass
    adv = _adv_payload(adv_name)
    resp = None
    try:
        # 将 128-bit 服务放到 scan response，便于部分手机显示服务信息
        resp = bluetooth.advertising_payload(name=None, services=[SERVICE_UUID]) if hasattr(bluetooth, "advertising_payload") else None
    except Exception:
        resp = None

    _ble_adv_ctx.update({"adv_data": adv, "resp_data": resp, "interval_us": 100000, "name": adv_name})
    _restart_ble_advertising("init")

    update_ble_wifi_status()
    return ble


async def main():
    log("system: 主循环启动")
    wifi_state = await wifi_connect()
    asyncio.create_task(udp_server())
    asyncio.create_task(telemetry_task())
    asyncio.create_task(imu_task())
    asyncio.create_task(ws_task())
    asyncio.create_task(http_server())
    ble_setup()
    asyncio.create_task(ble_status_task())
    update_ble_wifi_status(wifi_state)
    log("system: 核心服务已启动")
    while True:
        await asyncio.sleep_ms(1000)


try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()
